#!/usr/bin/env python3
"""Adaptive night-to-PV trough forecast for Mokka Battery Guard.

Read-only: GET evcc state and historical energy, optional HA reading.
NEVER opens Modbus, updates evcc or authorizes discharge.
The latest 5 complete comparable nights 20:00–09:00 calibrate the household
profile. No actual values from the night to be predicted are used for training.
Output is safe for the Home Assistant dashboard.
"""
from __future__ import annotations
import argparse,json,math,os,statistics,sys,urllib.parse,urllib.request
from datetime import date,datetime,time,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ=ZoneInfo(os.environ.get("BCG_TIMEZONE","Europe/Berlin"))
API=os.environ["BCG_EVCC_API_URL"].rstrip("/")+"/"
OUTPUT=Path(os.environ["BCG_STATE_DIR"])/"history-status.json"
SLOT=900
NIGHTS=5
MIN_NIGHTS=4
LOOKBACK_NIGHTS=12
REQUIRE_COMPLETENESS=.98
DEFAULT_TOTAL_FLOOR_PCT=15
# Retrospective household-only test on 19 stable/non-EV nights found a 2.418kWh
# worst underprediction for this five-night median model. 3.0kWh includes 0.582
# provisional additional allowance, NOT a statistically proven safety bound.
# Nights with unexpected high house loads can exceed this significantly.
REFERENCE_UNCERTAINTY_KWH=3.0

def jget(path,timeout=8):
    with urllib.request.urlopen(path,timeout=timeout) as r:
        return json.load(r)

def finite(x,lo,hi,label):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not lo<=x<=hi:
        raise ValueError(f"{label} invalid")
    return float(x)

def historical(group,begin,end):
    """15min EVCC energy, in kWh; batch to avoid history API limits."""
    result={}
    b=begin
    while b<end:
        e=min(end,b+timedelta(days=5))
        params=urllib.parse.urlencode({"from":datetime.combine(b,time.min,TZ).isoformat(),
                                       "to":datetime.combine(e,time.min,TZ).isoformat(),
                                       "aggregate":"15m","group":group})
        rows=jget(API+"history/energy?"+params,timeout=13)
        matching=[r for r in rows if r.get("group")==group]
        if len(matching)!=1 or not isinstance(matching[0].get("data"),list):
            raise ValueError(f"historical {group} is missing")
        for row in matching[0]["data"]:
            at=int(datetime.fromisoformat(row["start"]).timestamp())
            energy=finite(row["energy"],0,7.5,f"{group}.energy")
            result[at]=energy
        b=e
    return result

def night_anchor(now):
    local=now.astimezone(TZ)
    if local.hour>=20:
        return local.date()
    if local.hour<9:
        return local.date()-timedelta(days=1)
    raise ValueError("Planning only from 20:00 to next 09:00; daylight forecast window")

def forecast_window_open(now):
    """Return False if no complete 15-minute slot remains before 09:00.

    This read-only helper does not require an EV, or anyone to be home.
    The final useful forecast starts at 08:30; 08:45 is a no-op.
    """
    local=now.astimezone(TZ)
    return (local.hour >= 20 or local.hour < 8
            or (local.hour == 8 and local.minute < 45))


def night_range(day):
    a=datetime.combine(day,time(20),TZ)
    b=datetime.combine(day+timedelta(days=1),time(9),TZ)
    return list(range(int(a.timestamp()),int(b.timestamp()),SLOT))

def make_profile(home,now):
    today=night_anchor(now)
    selected=[]
    for offset in range(1,LOOKBACK_NIGHTS+1):
        d=today-timedelta(days=offset)
        stamps=night_range(d)
        available=[(t,home[t]) for t in stamps if t in home]
        if len(available)/len(stamps)<REQUIRE_COMPLETENESS:
            continue
        # Do not accept the partly ongoing / future night.
        if stamps[-1]+SLOT>now.timestamp():
            continue
        byclock={}
        for t,kwh in available:
            instant=datetime.fromtimestamp(t,TZ)
            key=instant.hour*4+instant.minute//15
            byclock.setdefault(key,[]).append(kwh*4000)
        selected.append({"day":d.isoformat(),"totalHouseKwh":round(sum(x for _,x in available),3),
                         "sampleSlots":len(available),"expectedSlots":len(stamps),
                         "byclock":byclock})
        if len(selected)==NIGHTS:break
    if len(selected)<MIN_NIGHTS:
        raise ValueError(f"only {len(selected)} complete recent nights, need >= {MIN_NIGHTS}")
    profile={}
    for key in list(range(80,96))+list(range(0,36)):
        values=[statistics.median(r["byclock"][key]) for r in selected if key in r["byclock"]]
        if len(values)<MIN_NIGHTS:
            raise ValueError(f"too few observations at clock slot {key}")
        profile[key]=statistics.median(values)
    return profile,selected

def solar_series(state,now):
    forecast=((state.get("forecast") or {}).get("solar") or {})
    values=forecast.get("timeseries")
    if not isinstance(values,list) or len(values)<40:
        raise ValueError("incomplete EVCC solar forecast")
    result={}
    last=0
    for v in values:
        if not isinstance(v,list) or len(v)!=2:raise ValueError("unexpected EVCC PV sample")
        stamp=int(finite(v[0],1500000000,2200000000,"timestamp"))
        watt=finite(v[1],0,25000,"pvPower")
        if stamp<=last:raise ValueError("PV forecast not strictly sorted")
        result[stamp]=watt;last=stamp
    relevant="tomorrow" if now.astimezone(TZ).hour>=20 else "today"
    if not forecast.get(relevant,{}).get("complete"):
        raise ValueError(f"EVCC forecast for {relevant} is incomplete")
    return result,forecast

def predict_trough(state,home,now=None,extra_reserve=None,
                   pv_override=None):
    now=now or datetime.now(timezone.utc)
    b=state.get("battery") or {}
    devices=b.get("devices") or []
    if len(devices)!=1:raise ValueError("ambiguous home battery")
    soc=finite(b.get("soc"),0,100,"battery SoC")
    capacity=finite(b.get("capacity"),1,100,"battery capacity")
    evcc_min=finite(devices[0].get("minSoc"),0,100,"EVCC min SoC")
    # Default is an ABSOLUTE 15% floor, not an additive number of percentage points.
    # Respect any higher externally configured EVCC battery minimum.
    if extra_reserve is None:extra_reserve=max(0,DEFAULT_TOTAL_FLOOR_PCT-evcc_min)
    if not 0<=extra_reserve<=30:raise ValueError("reserve outside 0..30")
    profile,nights=make_profile(home,now)
    if pv_override is None:
        pv,forecast=solar_series(state,now)
    else:
        pv= pv_override
        forecast={"tomorrow":{"complete":True,"energy":None},"scale":None}
    start=(int(now.timestamp())//SLOT+1)*SLOT
    # Stop latest 09:00 tomorrow; the intended lowest point must occur overnight.
    target_day=night_anchor(now)+timedelta(days=1)
    end=int(datetime.combine(target_day,time(9),TZ).timestamp())
    if start>=end:raise ValueError("night window has passed")
    # complete quarter-hours required from now to 09:00
    stamps=list(range(start,end,SLOT))
    if any(t not in pv for t in stamps):
        raise ValueError("PV timeline has missing quarter-hour samples")
    loss_per_kwh=.0  # NOT modeled. Zero optimism described in warnings.
    current=soc;lowest=soc;lowest_time=start
    consumption=0;solar=0;net_discharge=0;raw_min_pct=soc
    # earliest 60-minute sustained PV coverage with >=100W margin.
    cover=None
    for i in range(len(stamps)-3):
        if all(pv[stamp]>=profile[datetime.fromtimestamp(stamp,TZ).hour*4+
                                   datetime.fromtimestamp(stamp,TZ).minute//15]+100
               for stamp in stamps[i:i+4]):
            cover=stamps[i];break
    # If no sustained PV before 09, present full 09:00 horizon with status.
    stop=cover if cover is not None else end
    for stamp in stamps:
        if stamp>=stop:break
        local=datetime.fromtimestamp(stamp,TZ)
        key=local.hour*4+local.minute//15
        expected=profile[key]
        solar_w=pv[stamp]
        deficit=(expected-solar_w)*.25/1000
        # Charging allowed by model if solar covers house. Conversion losses UNKNOWN.
        current=min(100,current-deficit/capacity*100)
        if current<lowest:
            lowest=current;lowest_time=stamp+SLOT
        consumption+=expected*.25/1000
        solar+=solar_w*.25/1000
        net_discharge+=deficit
    # The modeled trough can be below EVCC's configured reserve. That is not
    # usable energy and must be displayed as "reserve violation", not 8%.
    floor=evcc_min+extra_reserve
    nominal_above=max(0,(lowest-floor)/100*capacity)
    # Historical stable-subset error allowance. This is a SHADOW SIMULATION,
    # not a control authorization or a bound for abnormal nights.
    uncertainty=max(REFERENCE_UNCERTAINTY_KWH,abs(net_discharge)*.15)
    candidate=max(0,nominal_above-uncertainty)
    enough=lowest>floor
    return {"schema":2,"mode":"observe_only","eligibleForControl":False,
        "asOf":now.isoformat(),"source":("Measured historical PV oracle + prior house nights" if pv_override is not None else "EVCC live forecast + recent measured home load"),
        "batterySocPct":soc,"capacityKwh":capacity,"evccMinSocPct":evcc_min,
        "extraReservePctAssumed":extra_reserve,"floorPct":floor,
        "houseHistory":{"method":"5 newest complete 20:00-09:00 nights",
            "dates":[n["day"] for n in nights],
            "nightKwh":[n["totalHouseKwh"] for n in nights],
            "nightMedianKwh":round(statistics.median(n["totalHouseKwh"] for n in nights),3)},
        "forecast":{"pvTomorrowKwh":round(float(forecast.get("tomorrow",{}).get("energy") or 0)/1000,3) if pv_override is None else None,
            "scaleAlreadyApplied":forecast.get("scale"),
            "coverageAt":datetime.fromtimestamp(cover,TZ).isoformat() if cover else None,
            "coverageFoundBefore0900":cover is not None,
            "horizonEnd":datetime.fromtimestamp(stop,TZ).isoformat(),
            "projectedTroughAt":datetime.fromtimestamp(lowest_time,TZ).isoformat(),
            "projectedTroughSocPct":round(lowest,1),
            "totalHomeDemandToCoverageKwh":round(consumption,3),
            "totalPvToCoverageKwh":round(solar,3),
            "netBatteryDeficitKwh":round(net_discharge,3),
            "uncertaintyAllowanceKwh":round(uncertainty,3),
            "candidateExtraDischargeKwh":round(candidate,3),
            "lossesCalibrated":False},
        "decision":{"simulationOnly":True,"canRelease":False,"physicalWriteW":0,
            "reason":"Nur Berechnung. Freigabe hängt von realem Vortages-Prognosefehler, Batterieverlusten, aktivem Ladeplan und Testfreigabe ab.",
            "aboveReserveBeforeErrorKwh":round(nominal_above,3),
            "aboveReserveAfterErrorKwh":round(candidate,3),
            "reserveThresholdMetInModel":enough},
        "warnings":["Vorabendprognose noch nicht gegen den Folgetag validiert.",
            "PV-Zeitreihe ist aktuell, frühere Wetterprognose nicht bekannt.",
            "Batterie-/Wandlungsverluste nicht kalibriert.",
            "Vorlaeufig 3.0 kWh Fehlerpolster: in 19 ruhigen Ruecktest-Naechten betrug die groesste Last-Unterprognose 2.418 kWh; schwere Lastanomalien koennen das weit ueberschreiten, KEINE Sicherheitsgarantie.",
            "Keine automatische Entladefreigabe."]}

def atomic_write(target,obj):
    target.parent.mkdir(parents=True,exist_ok=True)
    tempfile=target.with_name(target.name+".new")
    with tempfile.open('w',encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2)
        f.write("\n");f.flush();os.fsync(f.fileno())
    os.replace(tempfile,target)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=OUTPUT)
    parser.add_argument("--reserve",type=int,default=None,help="optional percentage points ABOVE the EVCC minimum; default: 15 percent TOTAL")
    args=parser.parse_args()
    now=datetime.now(timezone.utc)
    if not forecast_window_open(now):
        print("SKIPPED adaptive night forecast: no complete 15-minute slot remains"
              " before 09:00 or daylight; no file modified",flush=True)
        return
    state=jget(API+"state",timeout=8);state=state.get("result",state)
    anchor=night_anchor(now)
    begin=anchor-timedelta(days=LOOKBACK_NIGHTS+1)
    end=anchor+timedelta(days=2)
    home=historical("home",begin,end)
    report=predict_trough(state,home,now=now,extra_reserve=args.reserve)
    atomic_write(args.output,report)
    archive=Path(os.environ["BCG_STATE_DIR"])/"adaptive-archive"
    archive.mkdir(parents=True,exist_ok=True)
    dayfile=archive/(night_anchor(now).isoformat()+".jsonl")
    with dayfile.open("a",encoding="utf-8") as fp:
        fp.write(json.dumps(report,ensure_ascii=False,separators=(",",":"))+chr(10))
        fp.flush()
        os.fsync(fp.fileno())
    print("READ ONLY adaptive snapshot",args.output,"archived",dayfile)
    print(json.dumps({"asOf":report["asOf"],"soc":report["batterySocPct"],
        "nights":report["houseHistory"],"projection":report["forecast"],
        "decision":report["decision"]},ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
