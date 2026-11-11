#!/usr/bin/env python3
"""Battery Control Guard v0.8.0-beta recovery forecast (EVCC GET only).

Safety: forecasts do not grant permission; only the intelligent controller can
request the existing guard's bounded battery permission. No Modbus or EVCC POST.
"""
from __future__ import annotations
import json
import math
import os
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from . import history as history_api, public

TZ = ZoneInfo(os.environ.get("BCG_TIMEZONE","Europe/Berlin"))
OUT = Path(os.environ["BCG_STATE_DIR"])/"forecast.json"
SLOT = 900
MAX_AGE_S = 1200
MAX_PV_W = 25000.0
MAX_HOME_W = 30000.0
MAX_CHARGE_W = 3000.0  # conservative provisional storage charging cap
CHARGE_EFF = 0.85
DISCHARGE_EFF = 0.90
RECOVERY_MARGIN_W = 200.0
RECOVERY_SLOTS = 4
RECOVERY_MIN_KWH = 0.2
FLOOR_REFERENCE_PCT = 15.0
MIN_NIGHTS = 4


def finite(v, lo, hi, label):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f"{label} invalid: {v!r}")
    return float(v)


def anchor_date(now: datetime) -> date:
    local = now.astimezone(TZ)
    # 16:00-20:00: show prospective upcoming night, using *current* SoC as an
    # explicitly hypothetical starting SoC (not predicted evening storage).
    return local.date() if local.hour >= 16 else local.date() - timedelta(days=1)


def night_bounds(anchor: date):
    a = datetime.combine(anchor, datetime.min.time(), TZ).replace(hour=20)
    b = datetime.combine(anchor + timedelta(days=2), datetime.min.time(), TZ)
    return a, b


def profile_from_history(home: dict[int, float], now: datetime, anchor: date):
    selected = []
    for lookback in range(1, 15):
        aday = anchor - timedelta(days=lookback)
        begin, end = night_bounds(aday)
        stamps = list(range(int(begin.timestamp()), int(end.timestamp()), SLOT))
        if stamps[-1] + SLOT > now.timestamp():
            continue
        valid = [(ts, home[ts]) for ts in stamps if ts in home]
        if len(valid) / len(stamps) < 0.98:
            continue
        byclock = {}
        for ts, energy in valid:
            dt = datetime.fromtimestamp(ts, TZ)
            key = dt.hour * 4 + dt.minute // 15
            byclock.setdefault(key, []).append(finite(energy, 0, 7.5, "house kWh") * 4000)
        selected.append((aday.isoformat(), byclock, round(sum(v for _, v in valid), 3)))
        if len(selected) >= 5:
            break
    if len(selected) < MIN_NIGHTS:
        raise ValueError(f"insufficient complete 20:00-18:00 nights ({len(selected)})")
    keys = list(range(80, 96)) + list(range(0, 96))
    profile = {}
    for k in keys:
        observations = [statistics.median(x[1][k]) for x in selected if k in x[1]]
        if len(observations) < MIN_NIGHTS:
            raise ValueError(f"missing household profile slot {k}")
        profile[k] = finite(statistics.median(observations), 0, MAX_HOME_W, "house power")
    return profile, selected


def pv_series_from_state(state: dict, target_day: date, now: datetime):
    solar = ((state.get("forecast") or {}).get("solar") or {})
    # The target date is explicit; the EVCC 'today' and 'tomorrow' keys move
    # at midnight, but this stored target date must not change.
    state_today = now.astimezone(TZ).date()
    difference = (target_day - state_today).days
    key = {0: "today", 1: "tomorrow", 2: "dayAfterTomorrow"}.get(difference)
    if key is None or not (solar.get(key) or {}).get("complete"):
        raise ValueError(f"complete PV forecast missing for {target_day}")
    values = solar.get("timeseries") or []
    if len(values) < 40:
        raise ValueError("PV forecast timeseries too short")
    out = {}
    prev = 0
    for row in values:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("unexpected PV timeseries format")
        ts = int(finite(row[0], 1500000000, 2200000000, "PV timestamp"))
        pw = finite(row[1], 0, MAX_PV_W, "PV power")
        if ts <= prev:
            raise ValueError("PV forecast unsorted/duplicate")
        prev = ts
        out[ts] = pw
    return out, solar, key


def stable_plan_identity(state: dict):
    """Only EVCC goal inputs identify the plan, never recomputed planner slots."""
    lps=state.get("loadpoints") or []
    if len(lps)!=1 or not isinstance(lps[0],dict):
        raise ValueError("ambiguous EVCC charging point")
    lp=lps[0]
    pid=lp.get("effectivePlanId")
    if pid in (0,None):
        return None
    if type(pid) is not int or pid<1:
        raise ValueError("invalid plan ID")
    goal=lp.get("effectivePlanSoc")
    if type(goal) not in (int,float) or not math.isfinite(goal) or not 1<=goal<=100:
        raise ValueError("invalid plan target SoC")
    raw=lp.get("effectivePlanTime")
    if not isinstance(raw,str) or not raw:
        raise ValueError("missing plan deadline")
    moment=datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        raise ValueError("plan deadline not timezone-aware")
    return {"vehicle":lp.get("vehicleName"),"planId":pid,
            "planTimeUtc":moment.astimezone(timezone.utc).isoformat(),
            "planSoc":float(goal)}

def vehicle_pv_competition_until(state: dict):
    """Conservative, *stable* PV exclusion for EVCC planning.

    EVCC recomputes plan-slot ends frequently. A 30-minute overrun allowance
    prevents slot jitter being mistaken for a user plan change. If an actual
    slot projects still later, exclude PV for longer. Any undercoverage is
    detected by the controller before authorizing extra battery discharge.
    """
    lps=state.get("loadpoints") or []
    if len(lps)!=1 or not isinstance(lps[0],dict):
        raise ValueError("ambiguous EVCC charging point")
    lp=lps[0]
    identity=stable_plan_identity(state)
    plan=lp.get("plan")
    if plan is not None and not isinstance(plan,list):
        raise ValueError("EVCC plan is not a list")
    ends=[]
    for slot in plan or []:
        if not isinstance(slot,dict):
            raise ValueError("EVCC plan slot is not an object")
        raw=slot.get("end")
        if raw is None: continue
        if not isinstance(raw,str): raise ValueError("invalid EVCC slot end")
        parsed=datetime.fromisoformat(raw)
        if parsed.tzinfo is None: raise ValueError("timezone missing in slot end")
        ends.append(parsed.timestamp())
    if identity is None:
        if lp.get("planActive") is True:
            raise ValueError("active EVCC plan without stable identity")
        # Slot list may transiently exist without an effective plan: reserve
        # PV for those slots nonetheless, never claim it twice.
        return math.ceil(max(ends)/SLOT)*SLOT if ends else 0.0
    end=datetime.fromisoformat(identity["planTimeUtc"]).timestamp()+1800
    if ends:end=max(end,max(ends))
    return math.ceil(end/SLOT)*SLOT


def evaluate(state: dict, home: dict[int, float], now: datetime | None = None, *, anchor: date | None = None):
    now = now or datetime.now(timezone.utc)
    anchor = anchor or anchor_date(now)
    start_dt, end_dt = night_bounds(anchor)
    start = max((int(now.timestamp()) // SLOT + 1) * SLOT, int(start_dt.timestamp()))
    end = int(end_dt.timestamp())
    if start >= end:
        raise ValueError("no remaining forecast horizon")
    target = anchor + timedelta(days=1)
    pv, solar, key = pv_series_from_state(state, target, now)
    profile, nights = profile_from_history(home, now, anchor)
    battery = state.get("battery") or {}
    devices = battery.get("devices") or []
    if len(devices) != 1:
        raise ValueError("ambiguous storage")
    soc = finite(battery.get("soc"), 0, 100, "battery SoC")
    capacity = finite(battery.get("capacity"), 1, 100, "storage capacity")
    min_evcc = finite(devices[0].get("minSoc"), 0, 100, "EVCC battery minSoC")
    plan_end = vehicle_pv_competition_until(state)
    stamps = list(range(start, end, SLOT))
    if any(ts not in pv for ts in stamps):
        raise ValueError("incomplete 15-minute PV samples for horizon")
    records = []
    for ts in stamps:
        local = datetime.fromtimestamp(ts, TZ)
        home_w = profile[local.hour * 4 + local.minute // 15]
        pv_w = pv[ts]
        # If a planned charge overlaps the possible PV recovery, assume the
        # car consumes all predicted PV until the plan is completed.
        for_car = pv_w if (plan_end is None or (plan_end > ts and plan_end > now.timestamp())) else 0.
        surplus = max(0.0, pv_w - home_w - for_car)
        balance = pv_w - home_w - for_car
        records.append((ts, home_w, pv_w, for_car, balance, surplus))
    recovery_at = None
    for i in range(len(records) - RECOVERY_SLOTS + 1):
        section = records[i:i+RECOVERY_SLOTS]
        if all(item[4] >= RECOVERY_MARGIN_W for item in section) and sum(x[5] for x in section) * SLOT / 3600000 >= RECOVERY_MIN_KWH:
            recovery_at = section[0][0]
            break
    # Full-horizon energy trajectory: do not trust only a short PV peak.
    wh = capacity * 1000 * soc / 100.0
    low_wh = wh
    trough_at = start
    home_deficit_to_recovery = 0.0
    pv_to_recovery = 0.0
    house_to_recovery = 0.0
    for ts, home_w, pv_w, for_car, balance, surplus in records:
        if balance < 0:
            wh += balance * SLOT / 3600 / DISCHARGE_EFF
        else:
            wh += min(MAX_CHARGE_W, balance) * SLOT / 3600 * CHARGE_EFF
        wh = min(wh, capacity * 1000)
        if wh < low_wh:
            low_wh = wh
            trough_at = ts + SLOT
        if recovery_at is None or ts < recovery_at:
            house_to_recovery += home_w * SLOT / 3600000
            pv_to_recovery += pv_w * SLOT / 3600000
            home_deficit_to_recovery += max(0, home_w - pv_w) * SLOT / 3600000
    trough_pct = max(0.0, min(100.0, low_wh / (capacity * 1000) * 100))
    reference_extra = max(0.0, (trough_pct - FLOOR_REFERENCE_PCT) / 100 * capacity)
    eligible = recovery_at is not None and reference_extra >= 0.55
    return {
        "schema": 3, "version": "0.8.0-beta", "mode": "observe_only", "eligibleForControl": False,
        "asOf": now.isoformat(), "targetDate": target.isoformat(), "nightAnchor": anchor.isoformat(),
        "forecastStart": datetime.fromtimestamp(start, TZ).isoformat(), "horizonEnd": end_dt.isoformat(),
        "basis": "EVCC solar timeseries + median of 5 complete 20:00-24:00+1day home windows",
        "homeTrainingNights": [x[0] for x in nights],
        "homeTrainingEnergyKwh": [x[2] for x in nights],
        "batterySocPct": round(soc, 2), "evccMinSocPct": min_evcc,
        "capacityKwh": capacity, "referenceFloorPct": FLOOR_REFERENCE_PCT,
        "pvForecastDayKey": key, "pvForecastTargetEnergyKwh": round((solar.get(key) or {}).get("energy", 0)/1000, 3),
        "forecast": {
            "recoveryAt": datetime.fromtimestamp(recovery_at, TZ).isoformat() if recovery_at else None,
            "recoveryFound": recovery_at is not None,
            "projectedTroughSocPct": round(trough_pct, 2),
            "projectedTroughAt": datetime.fromtimestamp(trough_at, TZ).isoformat(),
            "houseNeedUntilRecoveryKwh": round(home_deficit_to_recovery, 3),
            "houseTotalUntilRecoveryKwh": round(house_to_recovery, 3),
            "pvTotalUntilRecoveryKwh": round(pv_to_recovery, 3),
            "uncertaintyAllowanceKwh": 0.0,
            "budgetPolicy": "forecast_trough_minus_live_soc_floor_no_extra_kwh_margin",
            "candidateExtraDischargeKwhAt15Pct": round(reference_extra, 3),
            "lossesModeled": True,
            "planPvCompetitionThrough": datetime.fromtimestamp(plan_end, TZ).isoformat() if plan_end and plan_end > 0 else None,
            "planFingerprint": stable_plan_identity(state), "slotOverrunAllowanceMinutes": 30
        },
        "decision": {"simulationOnly": True, "canRelease": False, "physicalWriteW": 0,
                     "reason": "Model computes potential; real controller checks plan and safety gates",
                     "hypotheticalAt15Pct": bool(eligible)},
        "warnings": ["Current stored SoC used as starting SoC (before 20:00 hypothetical).",
                     "Forecast can be wrong; no additional kWh safety discount. Live SoC/KOSTAL guard remains authoritative.",
                     "No direct KOSTAL write; controller authorization remains separate."]
    }


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".new")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def main():
    import urllib.request
    with urllib.request.urlopen(os.environ["BCG_EVCC_API_URL"].rstrip("/")+"/state", timeout=6) as r:
        state = json.load(r)
    now = datetime.now(timezone.utc)
    anchor = anchor_date(now)
    begin = anchor - timedelta(days=15)
    home = history_api.historical("home", begin, anchor + timedelta(days=2))
    result = evaluate(state, home, now, anchor=anchor)
    atomic_json(OUT, result)
    try:
        public.publish("forecast.json",result)
    except (OSError,RuntimeError,ValueError) as e:
        print("HA_FORECAST_EXPORT_WARNING",str(e)[:180],flush=True)
    archive = Path(os.environ["BCG_STATE_DIR"])/"recovery-archive"
    archive.mkdir(parents=True, exist_ok=True)
    with (archive / (anchor.isoformat() + ".jsonl")).open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    print("Recovery v0.8.0-beta READ ONLY:", result["asOf"], "recovery", result["forecast"]["recoveryAt"],
          "troughSoC", result["forecast"]["projectedTroughSocPct"], flush=True)


if __name__ == "__main__":
    main()
