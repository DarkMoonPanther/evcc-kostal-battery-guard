#!/usr/bin/env python3
"""Read-only predictive observer for the existing Mokka Battery Guard.

No Modbus access, no EVCC mutations, no Home Assistant mutations.
Snapshots are immutable and always timestamped at time of forecast retrieval.
Prediction is explicitly theoretical and never authorizes discharge.
"""
from __future__ import annotations
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
MAX_PV_W = 25000
MAX_HOUSE_W = 30000
INTERVAL_S = 900
ARCHIVE_INTERVAL_S = 3600
OBSERVE_ONLY = True

def finite(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("missing/non-numeric value")
    x = float(value)
    if not math.isfinite(x) or not low <= x <= high:
        raise ValueError("out-of-range value")
    return x

def get_history(url, start, end, group, aggregate="15m", timeout=4):
    params = urllib.parse.urlencode({
        "from": start.isoformat(), "to": end.isoformat(),
        "aggregate": aggregate, "group": group
    })
    with urllib.request.urlopen(url + "history/energy?" + params, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, list):
        raise ValueError("EVCC history not a list")
    matching = [g for g in result if g.get("group") == group]
    if len(matching) != 1 or not isinstance(matching[0].get("data"), list):
        raise ValueError("EVCC history group missing")
    return matching[0]["data"]

def read_timeseries(state, now):
    solar = (state.get("forecast") or {}).get("solar") or {}
    raw = solar.get("timeseries")
    if not isinstance(raw, list) or len(raw) < 4:
        raise ValueError("PV-Forecast fehlt")
    series = []
    prior = None
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("PV-Datenformat fehlerhaft")
        ts = int(finite(item[0], 1500000000, 2200000000))
        power = finite(item[1], 0, MAX_PV_W)
        if prior is not None and ts <= prior:
            raise ValueError("PV-Zeitreihe nicht sortiert")
        prior = ts
        if ts >= int(now.timestamp()) - INTERVAL_S:
            series.append((ts, power))
    if not series or series[-1][0] < now.timestamp() + 18*3600:
        raise ValueError("PV-Vorschauhorizont unter 18 Stunden")
    return series, finite(solar.get("scale", 1), 0.01, 10)

def house_profile(rows, now):
    """Median of complete 15-minute historic slots; no interpolated fiction."""
    slots = defaultdict(list)
    days = defaultdict(set)
    for item in rows:
        try:
            dt = datetime.fromisoformat(item["start"]).astimezone(TZ)
            if dt.date() >= now.astimezone(TZ).date() or dt.date() < (now.astimezone(TZ).date()-timedelta(days=21)):
                continue
            energy = finite(item["energy"], 0, 7.5)
            key = dt.hour*4 + dt.minute//15
            if dt.minute % 15 != 0:
                continue
            slots[key].append(energy*4000)
            days[dt.date()].add(key)
        except (KeyError, ValueError, TypeError):
            continue
    full_days = {d for d, keys in days.items() if len(keys) >= 90}
    if len(full_days) < 7:
        raise ValueError(f"nur {len(full_days)} vollständige Verbrauchstage")
    # The source period is the latest 21 days. Require >= 7 observations per slot.
    if min((len(slots.get(k, [])) for k in range(96)), default=0) < 7:
        raise ValueError("Lücken im 15-Minuten-Verbrauchsprofil")
    profile = [statistics.median(slots[k]) for k in range(96)]
    if any(not 0 <= w <= MAX_HOUSE_W for w in profile):
        raise ValueError("Haushaltsprofil fehlerhaft")
    return profile, len(full_days)

def step_forecast(series, profile, now, capacity_kwh, soc_pct, min_soc_pct):
    """Energy budget until sustained PV covers expected house load.

    Deliberately not an authorization, leaves all losses unmodelled.
    """
    timeline = []
    for ts, pv_w in series:
        dt = datetime.fromtimestamp(ts, TZ)
        slot = dt.hour*4 + dt.minute//15
        home_w = profile[slot]
        timeline.append({"timestamp": ts, "pvW": round(pv_w), "expectedHomeW": round(home_w)})
    coverage = None
    # four consecutive 15min slots with >= 100W headroom
    for i in range(len(timeline)-3):
        if timeline[i]["timestamp"] < now.timestamp():
            continue
        if all(x["pvW"] >= x["expectedHomeW"] + 100 for x in timeline[i:i+4]):
            coverage = i
            break
    reserve = min(100, min_soc_pct + 5)
    if coverage is None:
        return {"available": False, "reason": "Keine sichere 60-Minuten-PV-Deckung in der Prognose",
                "reserveSocPct": round(reserve, 1), "estimatedPvCoverageAt": None,
                "theoreticalBudgetKwh": None}
    target = timeline[coverage]["timestamp"]
    # Discrete snapshot model: not an efficiency-corrected SOC trajectory.
    house_kwh = sum(max(0, r["expectedHomeW"]-r["pvW"])*.25/1000
                    for r in timeline[:coverage] if r["timestamp"] >= now.timestamp())
    capacity = finite(capacity_kwh, 1, 100)
    soc = finite(soc_pct, 0, 100)
    min_soc = finite(min_soc_pct, 0, 100)
    theoretical = max(0, (soc-reserve)/100*capacity-house_kwh)
    return {
        "available": True, "reason": "Theoretisches Budget; keine Entladefreigabe",
        "reserveSocPct": round(reserve, 1),
        "estimatedPvCoverageAt": datetime.fromtimestamp(target, TZ).isoformat(),
        "houseEnergyUntilPvKwh": round(house_kwh, 3),
        "theoreticalBudgetKwh": round(theoretical, 3),
        "lossesIncluded": False
    }

def evaluate(state, home_rows, now=None):
    now = now or datetime.now(timezone.utc)
    series, scale = read_timeseries(state, now)
    profile, days = house_profile(home_rows, now)
    battery = state.get("battery") or {}
    devices = battery.get("devices") or []
    if len(devices) != 1 or not isinstance(devices[0], dict):
        raise ValueError("mehrdeutige Hausbatterie")
    dev = devices[0]
    min_soc = finite(dev.get("minSoc"), 0, 100)
    soc = finite(battery.get("soc"), 0, 100)
    capacity = finite(battery.get("capacity"), 1, 100)
    budget = step_forecast(series, profile, now, capacity, soc, min_soc)
    lp = state.get("loadpoints") or []
    plans = []
    for p in lp:
        if not isinstance(p,dict):
            continue
        plans.append({"planActive": bool(p.get("planActive")),
                      "planProjectedStart": p.get("planProjectedStart"),
                      "planProjectedEnd": p.get("planProjectedEnd"),
                      "effectivePlanTime": p.get("effectivePlanTime"),
                      "planEnergy": p.get("planEnergy"),
                      "vehicleSoc": p.get("vehicleSoc"),
                      "mode": p.get("mode")})
    has_plan = any(p["planActive"] or p["effectivePlanTime"] for p in plans)
    return {
        "schema": 1, "mode": "observe_only", "eligibleForControl": False,
        "calculatedAt": now.isoformat(), "forecastScaleAlreadyApplied": scale,
        "houseHistoryDays": days, "planAvailable": has_plan,
        "plans": plans, "batterySocPct": soc,
        "minimumSocPctFromEvcc": min_soc, "capacityKwh": capacity,
        "budget": budget,
        "warnings": [
            "Keine automatisierte Freigabe; Mindest-SoC aus EVCC ist kein direkter Register-1042-Nachweis",
            "Wandlungs-/Batterieverluste sind nicht kalibriert",
            "Historische EVCC-Prognosewerte sind keine fixierten Vortagesprognosen"
        ]
    }, series

def atomic_json(path, value):
    temp = path.with_suffix(path.suffix+".tmp")
    try:
        with temp.open("w", encoding="utf-8") as fp:
            json.dump(value, fp, separators=(",", ":"), ensure_ascii=False)
            fp.write("\n")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()

class PredictiveObserver:
    def __init__(self, state_dir, evcc_state_url):
        self.root = Path(state_dir)/"predictive"
        self.evcc_api = evcc_state_url.split("/api/")[0].rstrip("/")+"/api/"
        self.last_attempt_mono = 0.0
        self.last_plan_signature = None

    def tick(self, state):
        now_mono = time.monotonic()
        signature = tuple((bool(p.get("planActive")),str(p.get("effectivePlanTime")))
                          for p in state.get("loadpoints",[]) if isinstance(p,dict))
        if self.last_attempt_mono and signature == self.last_plan_signature and now_mono-self.last_attempt_mono < ARCHIVE_INTERVAL_S:
            return
        self.last_attempt_mono = now_mono
        self.last_plan_signature = signature
        now = datetime.now(timezone.utc)
        solar, factor = read_timeseries(state, now)
        snapshot = {
            "schema": 1, "observedAt": now.isoformat(),
            "solarForecastW": solar, "solarCorrectionFactor": factor,
            "tomorrowComplete": bool((state.get("forecast") or {}).get("solar",{}).get("tomorrow",{}).get("complete")),
            "pvForecastSource": "evcc state forecast solar timeseries",
        }
        self.root.mkdir(parents=True, exist_ok=True)
        dayfile = self.root / (now.astimezone(TZ).date().isoformat()+".jsonl")
        with dayfile.open("a",encoding="utf-8") as fp:
            fp.write(json.dumps(snapshot, separators=(",", ":"))+"\n")
        # Only read history hourly; failures never affect controller and remain visible in status.
        status = {"archive": "ok", "snapshotAt": now.isoformat(), "mode": "observe_only",
                  "eligibleForControl": False}
        try:
            start = (now.astimezone(TZ)-timedelta(days=21)).replace(hour=0,minute=0,second=0,microsecond=0)
            rows = get_history(self.evcc_api,start,now.astimezone(TZ),"home")
            result,_ = evaluate(state, rows, now)
            status["simulation"] = result
        except Exception as exc:
            status["simulation"] = {"available":False,"reason":str(exc)[:160]}
        atomic_json(self.root/"latest.json", status)
        # Bounded retention; run once per observation with no network.
        threshold = (now - timedelta(days=400)).date().isoformat()
        for p in self.root.glob("????-??-??.jsonl"):
            if p.name[:10] < threshold:
                p.unlink()
        return status

if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(description="Battery Guard prognosis, strictly read-only")
    parser.add_argument("--preview", action="store_true")
    args=parser.parse_args()
    if not args.preview:
        parser.error("--preview is required")
    api="http://127.0.0.1:7070/api/"
    with urllib.request.urlopen(api+"state",timeout=5) as resp:
        state=json.load(resp)
    state=state.get("result",state)
    now=datetime.now(timezone.utc)
    start=(now.astimezone(TZ)-timedelta(days=21)).replace(hour=0,minute=0,second=0,microsecond=0)
    history=get_history(api,start,now.astimezone(TZ),"home")
    prediction,_=evaluate(state,history,now)
    print(json.dumps(prediction,indent=2,ensure_ascii=False))
