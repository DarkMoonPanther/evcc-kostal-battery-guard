#!/usr/bin/env python3
"""Battery Control Guard v0.8.0-beta: optional intelligent energy management.

No Modbus access and NO EVCC write commands. Only already-active EVCC
charging may receive a bounded, short-lived storage discharge budget.
"""
from __future__ import annotations
import json,math,os,signal,threading,time,urllib.request,urllib.error
from datetime import datetime,timezone,timedelta
from . import recovery, decision, public
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(os.environ["BCG_STATE_DIR"])
STATE=ROOT/"intelligent-session.json"
LOG=ROOT/"intelligent-log.jsonl"
FORECAST=ROOT/"forecast.json"
STATUS_OUTPUT=ROOT/"status-intelligent.json"
LEDGER_DIR=ROOT/"night-ledgers"
STATUS_INTERVAL_S=15
API=os.environ["BCG_EVCC_API_URL"].rstrip("/")
TZ=ZoneInfo(os.environ.get("BCG_TIMEZONE","Europe/Berlin"))
# Additional discharge budget is bounded by the computed energy reserve; no fixed 0.6-kWh cap.
MIN_START_BUDGET_KWH=0.55
UNCERTAINTY_BUFFER_KWH=0.3      # leave this much beyond the model's 3kWh error buffer
MAX_FORECAST_AGE_S=20*60
# Configured reserve, optionally overridable by a fresh HA slider.
HA_RESERVE_ENTITY=os.getenv("BCG_HA_RESERVE_ENTITY","")
HA_AUTH_FILE=Path(os.getenv("BCG_HA_AUTH_FILE","/nonexistent/bcg-token"))
FLOOR_DEFAULT=10.0
POLL_S=5
HA_API_URL=os.getenv("BCG_HA_API_URL","").rstrip("/")
ARMED=os.getenv("INTELLIGENT_ARMED","false").lower()=="true"
status={"schema":1,"phase":"idle","permitted":False,"updatedAt":0,"expiresAt":0,"totalFloorPct":None,"source":None,"planId":None,"planTime":None}
lock=threading.Lock()
stop=False
def log(event,**v):
    rec={"at":datetime.now(TZ).isoformat(timespec="seconds"),"event":event,**v}
    LOG.parent.mkdir(parents=True,exist_ok=True)
    with LOG.open("a") as fp:fp.write(json.dumps(rec,ensure_ascii=False)+"\n")
    print(json.dumps(rec,ensure_ascii=False),flush=True)
def setstatus(phase,permit,**more):
    with lock:
        # Prevent stale budget values leaking into later idle HTTP statuses.
        status.clear()
        status.update({"schema":1,"phase":phase,"permitted":bool(permit),"reason":None,
          "updatedAt":time.time(),"expiresAt":time.time()+9,
          "source":None,"planId":None,"planTime":None,**more})
        decision.publish(status)
def get_state():
    with urllib.request.urlopen(API+"/state",timeout=4) as r:obj=json.load(r)
    return obj.get("result",obj)
def post(path):
    """A deliberate tripwire: this controller MUST NEVER control EVCC charging."""
    raise RuntimeError("EVCC commands forbidden: the controller manages storage only")

def write_state(data):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    temp=STATE.with_suffix(".tmp")
    with temp.open("w") as fp:
        json.dump(data,fp,indent=2);fp.flush();os.fsync(fp.fileno())
    os.replace(temp,STATE)
def read_floor():
    if not HA_RESERVE_ENTITY:
        # Deliberately configured value, never a guessed failover.
        return num(float(os.environ["BCG_FIXED_RESERVE_SOC_PCT"]),8,30)
    # Home Assistant's persistent helper is the single source of truth for the slider.
    # Never use a guessed fallback if HA, token, or numeric state is unavailable.
    hdr=HA_AUTH_FILE.read_text().strip()
    if not hdr.lower().startswith("bearer "):
        raise ValueError("invalid HA authorization")
    req=urllib.request.Request(HA_API_URL+"/api/states/"+HA_RESERVE_ENTITY,
                               headers={"Authorization":hdr})
    with urllib.request.urlopen(req,timeout=3) as r:state=json.load(r)
    return num(float(state["state"]),8,30)

def read_effective_floor(state):
    """Reserve = max(configured/HA floor, EVCC minimum, real KOSTAL 1042).

    A fresh 1042 observation is published by the only Modbus driver.
    The controller never creates a KOSTAL/Modbus connection.
    """
    requested=read_floor()
    devices=(state.get("battery") or {}).get("devices") or []
    if len(devices)!=1:
        raise ValueError("ambiguous battery reserve")
    evcc_min=num(devices[0].get("minSoc"),0,100)
    kostal_min=decision.get_kostal_min_soc()
    return max(requested,evcc_min,kostal_min)


def num(x,lo,hi):
    if type(x) not in (float,int) or not math.isfinite(x) or not lo<=x<=hi:
        raise ValueError("invalid numeric metric "+repr(x))
    return float(x)
def quality(state):
    if state.get("batteryDischargeControl") is not False:raise ValueError("evcc owner")
    if str(state.get("batteryMode","unknown")).lower() not in ("unknown","normal","none",""):
        raise ValueError("conflicting battery mode")
    if state.get("batteryGridChargeActive") or state.get("batteryGridDischargeActive"):
        raise ValueError("grid battery mode")
    if state.get("bufferSoc")!=0 or state.get("bufferStartSoc")!=0:
        raise ValueError("user EVCC buffer mode in use")
    lp=state.get("loadpoints")
    if not isinstance(lp,list) or len(lp)!=1:raise ValueError("not one EVCC loadpoint")
    lp=lp[0]
    soc=num(state["battery"]["soc"],0,100)
    capacity=num(state["battery"]["capacity"],1,100)
    house=num(state["homePower"],-2000,30000)
    battery=num(state["battery"]["power"],-20000,20000)
    raw_car=lp.get("chargePower",0)
    # EVCC/go-e can report a slight negative idle offset before charging.
    # Never hide negative values while the charger actually charges.
    if (lp.get("charging") is not True and type(raw_car) in (int,float)
            and math.isfinite(raw_car) and -100<=raw_car<0):
        car=0.0
    else:
        car=num(raw_car,0,30000)
    grid=num(state["grid"]["power"],-20000,20000)
    pv=sum(num(v["power"],0,30000) for v in state["pv"])
    if abs(grid+pv+battery-car-house)>500:raise ValueError("EVCC meter imbalance")
    devices=state["battery"].get("devices") or []
    if len(devices)!=1:raise ValueError("battery ambiguity")
    if num(devices[0].get("minSoc"),0,100)>30:raise ValueError("EVCC minSoC too high for 8..30 slider")
    return lp,soc,capacity,house,battery,car,pv,grid

def forecast(state,capacity,floor):
    report=json.loads(FORECAST.read_text())
    at=datetime.fromisoformat(report["asOf"])
    age=(datetime.now(timezone.utc)-at.astimezone(timezone.utc)).total_seconds()
    if age<0 or age>MAX_FORECAST_AGE_S:raise ValueError("FORECAST_STALE")
    if report.get("schema")!=3 or report.get("version")!="0.8.0-beta":
        raise ValueError("FORECAST_SCHEMA_MISMATCH")
    if report.get("mode")!="observe_only" or report.get("eligibleForControl") is not False:
        raise ValueError("FORECAST_OWNERSHIP_INVALID")
    current_target=(datetime.now(TZ).date()+timedelta(days=1)
                    if datetime.now(TZ).hour>=16 else datetime.now(TZ).date())
    if report.get("targetDate")!=current_target.isoformat():
        raise ValueError("FORECAST_TARGET_DATE_MISMATCH")
    if abs(num(report["capacityKwh"],1,100)-capacity)>0.1:
        raise ValueError("FORECAST_BATTERY_CAPACITY_CHANGED")
    model_soc=num(report["batterySocPct"],0,100)
    live_soc=num(state["battery"]["soc"],0,100)
    if abs(model_soc-live_soc)>4:raise ValueError("FORECAST_BATTERY_SOC_STALE")
    f=report["forecast"]
    # Stable user plan identity, not constantly recomputed EVCC slot ends.

    identity=recovery.stable_plan_identity(state)
    if f.get("planFingerprint")!=identity:
        raise ValueError("FORECAST_PLAN_CHANGED")
    required_end=recovery.vehicle_pv_competition_until(state)
    saved_end=f.get("planPvCompetitionThrough")
    if required_end>0:
        if not isinstance(saved_end,str):
            raise ValueError("FORECAST_PV_COMPETITION_NOT_COVERED")
        observed_end=datetime.fromisoformat(saved_end)
        if observed_end.tzinfo is None or observed_end.timestamp()+1<required_end:
            raise ValueError("FORECAST_PV_COMPETITION_NOT_COVERED")
    elif saved_end:
        raise ValueError("FORECAST_PV_COMPETITION_NOT_COVERED")
    if f.get("recoveryFound") is not True or not f.get("recoveryAt"):
        raise ValueError("NO_SUSTAINABLE_PV_RECOVERY")
    recovery_at=datetime.fromisoformat(f["recoveryAt"])
    if recovery_at.tzinfo is None or recovery_at.date().isoformat()!=report["targetDate"]:
        raise ValueError("FORECAST_RECOVERY_DATE_INVALID")
    if recovery_at.timestamp() <= time.time():
        raise ValueError("PV_RECOVERY_ALREADY_STARTED")
    # The live configured SoC reserve is the ONLY user-selected security
    # allowance. The PV/house-demand forecast still controls the budget.
    # Refuse mixed/legacy forecast schemas: never silently reintroduce 3.3 kWh.
    if f.get("budgetPolicy")!="forecast_trough_minus_live_soc_floor_no_extra_kwh_margin":
        raise ValueError("FORECAST_BUDGET_POLICY_MISMATCH")
    if num(f["uncertaintyAllowanceKwh"],0,100)!=0:
        raise ValueError("FORECAST_EXTRA_KWH_MARGIN_NOT_ZERO")
    predicted=num(f["projectedTroughSocPct"],0,100)
    # Charge/discharge efficiencies were already modeled by the predictor.
    budget=max(0,(predicted-floor)/100*capacity)
    return budget,predicted,age

def eligible(state,floor):
    """PASSIVE Smart+minimum-once budget; never initiate a charging session.

    EVCC (or the person operating it) must ALREADY be charging. An attached
    but idle car, a pending plan or ordinary PV Smart mode cannot qualify.
    """
    now=datetime.now(TZ)
    if not (now.hour>=20 or now.hour<2):return None
    lp,soc,cap,home,battery,car,pv,grid=quality(state)
    if not (lp.get("mode")=="smart"
            and lp.get("alwaysCharge")=="once"
            and lp.get("connected") is True
            and lp.get("charging") is True
            and lp.get("vehicleName")==os.environ.get("BCG_VEHICLE_NAME")
            and car>=500
            and not lp.get("planActive")
            and lp.get("effectivePlanId",0) in (0,None)
            and lp.get("effectivePlanTime") is None
            and not lp.get("vehicleClimaterActive")
            and not lp.get("minSocNotReached")
            and not lp.get("smartCostActive")
            and not lp.get("batteryBoost")):
        return None
    if lp.get("effectiveLimitSoc") is None or lp.get("vehicleSoc") is None:return None
    if num(lp["vehicleSoc"],0,100)>=num(lp["effectiveLimitSoc"],0,100)-2:return None
    if soc<floor+20 or battery<0 or abs(grid)>1000:return None
    budget,predicted,age=forecast(state,cap,floor)
    if budget<MIN_START_BUDGET_KWH:return None
    rec=datetime.fromisoformat(json.loads(FORECAST.read_text())["forecast"]["recoveryAt"]).timestamp()
    return {"began":time.time(),"phase":"battery","budgetKwh":round(budget,4),
      "spentKwh":0.0,"lastSample":time.time(),"lastSoc":soc,
      "startVehicleSoc":lp["vehicleSoc"],"endVehicleSoc":lp["effectiveLimitSoc"],
      "forecastAgeS":round(age),"predictedTrough":predicted,
      "originMode":"smart","originAlwaysCharge":"once","floorPct":floor,
      "source":"once","stopBy":min(time.time()+12*3600,rec)}

def eligible_plan(state,floor):
    # NEVER start/stop or modify a planned EVCC charging session.
    lp,soc,cap,home,battery,car,pv,grid=quality(state)
    now=datetime.now(TZ)
    if not (lp.get("planActive") is True
            and lp.get("charging") is True
            and lp.get("connected") is True
            and lp.get("mode")=="smart"
            and lp.get("alwaysCharge")=="off"
            and lp.get("vehicleName")==os.environ.get("BCG_VEHICLE_NAME")
            and type(lp.get("effectivePlanId")) is int and lp["effectivePlanId"]>0
            and isinstance(lp.get("effectivePlanTime"),str)
            and lp.get("effectivePlanTime")
            and num(lp.get("chargePower",0),0,30000)>=500
            and not lp.get("vehicleClimaterActive")
            and not lp.get("minSocNotReached")
            and not lp.get("smartCostActive")
            and not lp.get("batteryBoost")):
        return None
    when=datetime.fromisoformat(lp["effectivePlanTime"]).astimezone(TZ)
    if when.tzinfo is None or (when-now).total_seconds() > 12*3600:
        return None
    if now>when+__import__("datetime").timedelta(minutes=30):
        return None
    if soc <=floor+5 or abs(grid)>16000:return None
    budget,predicted,age=forecast(state,cap,floor)
    if budget<MIN_START_BUDGET_KWH:return None
    return {"source":"plan","planId":lp["effectivePlanId"],
       "planTime":lp["effectivePlanTime"],"planSoc":lp.get("effectivePlanSoc"),
       "began":time.time(),"phase":"battery",
       "budgetKwh":round(budget,4),"spentKwh":0.0,
       "lastSample":time.time(),"lastSoc":soc,"floorPct":floor,
      "forecastAgeS":round(age),"predictedTrough":predicted,
      "planKey":recovery.stable_plan_identity(state),
      "allowedTotalKwh":round(budget,4),
      "stopBy":when.timestamp()+1800}

def plan_step(session,lp,soc,cap,home,battery,car,pv,grid,floor):
    """Fail-closed lease with monotonic budget cap and resumable forecast pause."""

    now=time.time()
    live_key=recovery.stable_plan_identity({"loadpoints":[lp]})
    if (live_key != session.get("planKey")
            or lp.get("connected") is not True
            or now>session["stopBy"]):
        restore(session,"PLAN_CHANGED_OR_ENDED")
        return None
    goal=session.get("planSoc")
    vehicle_soc=lp.get("vehicleSoc")
    if (type(goal) in (int,float) and type(vehicle_soc) in (int,float)
            and math.isfinite(vehicle_soc) and vehicle_soc>=goal):
        restore(session,"VEHICLE_TARGET_REACHED")
        return None
    dt=max(0,min(now-session["lastSample"],10))
    active=(lp.get("connected") is True and lp.get("planActive") is True
            and lp.get("charging") is True and lp.get("mode")=="smart"
            and lp.get("alwaysCharge")=="off" and lp.get("vehicleName")==os.environ.get("BCG_VEHICLE_NAME")
            and not lp.get("vehicleClimaterActive") and not lp.get("minSocNotReached")
            and not lp.get("smartCostActive") and not lp.get("batteryBoost")
            and car>=500)
    if active:
        # Charge conservative usage even during a temporary permission gap:
        # overcounting is preferable to budget re-issuance.
        contribution=max(0,min(car,battery-max(0,home-pv)))
        session["spentKwh"]+=contribution*dt/3600000
    session["lastSample"]=now
    session.setdefault("allowedTotalKwh",session["budgetKwh"])
    phase=session.get("phase")
    def event(new,reason):
        if session.get("phase")!=new:
            log("PLAN_TRANSITION",old=session.get("phase"),new=new,
                reason=reason,spentKwh=round(session["spentKwh"],4),
                allowedTotalKwh=round(session["allowedTotalKwh"],4))
        session["phase"]=new
        session["reason"]=reason
    def pause(new,reason):
        if session.get("phase")!=new:
            session["pausedAt"]=now
        session.pop("validSince",None)
        event(new,reason)
    if phase not in ("locked","exhausted"):
        if floor!=session["floorPct"] or soc<=floor+2:
            event("locked","FLOOR_OR_SOC")
        elif session["spentKwh"]>=session["allowedTotalKwh"]-1e-6:
            event("exhausted","BUDGET_SPENT")
        elif not active or battery<0:
            pause("paused_priority","EVCC_PRIORITY_OR_IDLE")
        else:
            try:
                left,predicted,age=forecast(get_state(),cap,floor)
                # left is *future* safe energy starting at current SoC;
                # prior spending is already reflected in current battery SoC.
                prior=session["allowedTotalKwh"]
                session["allowedTotalKwh"]=max(session["spentKwh"],min(
                    prior,session["spentKwh"]+left,session["budgetKwh"]))
                remaining=session["allowedTotalKwh"]-session["spentKwh"]
                if session["allowedTotalKwh"]<prior-0.01:
                    log("PLAN_BUDGET_REDUCED",wasKwh=round(prior,4),
                        nowKwh=round(session["allowedTotalKwh"],4),
                        forecastRemainingKwh=round(left,4))
                if remaining<0.15:
                    event("exhausted","FORECAST_SAFE_BUDGET_TOO_SMALL")
                elif phase in ("paused_forecast","paused_priority"):
                    # A forecast pause may resume only after a NEW model.
                    # Any 30s unstable segment resets the debounce timer.
                    updated=now-age
                    if (phase=="paused_forecast"
                            and updated<=session.get("pausedAt",now)):
                        session.pop("validSince",None)
                        event("paused_forecast","WAITING_NEW_FORECAST")
                    else:
                        since=session.setdefault("validSince",now)
                        if now-since>=30:
                            session.pop("validSince",None)
                            session.pop("pausedAt",None)
                            event("battery","VALID_FORECAST_STABLE_30S")
                else:
                    event("battery","VALID_FORECAST")
            except (OSError,ValueError,KeyError,TypeError,IndexError) as e:
                pause("paused_forecast",str(e)[:180])
    write_state(session)
    allow=active and session["phase"]=="battery"
    setstatus(session["phase"],allow,totalFloorPct=floor,
              reason=session.get("reason"),source="plan",
              planId=session["planId"],planTime=session["planTime"],
              remainingKwh=round(max(0,session["allowedTotalKwh"]-session["spentKwh"]),3),
              spentKwh=round(session["spentKwh"],4),batterySoc=soc)
    return session


def restore(session,why):
    """Withdraw storage permission ONLY; EVCC retains charge and stop authority."""
    setstatus("grid",False,reason=why)
    # Never re-issue an already reserved nightly allocation, even on restart.
    if why in ("SHUTDOWN","CONTROL_ERROR","DISARMED_RECOVERY"):
        session["phase"]="locked"
        session["reason"]=why
        session["lastSample"]=time.time()
        write_state(session)
        log("BUDGET_LEDGER_RETAINED",source=session.get("source"),
            reason=why,spentKwh=session.get("spentKwh"))
    else:
        STATE.unlink(missing_ok=True)
        log("STORAGE_PERMISSION_ENDED",source=session.get("source"),
            reason=why,spentKwh=session.get("spentKwh"))
    # Deliberately NO POST to EVCC: never stop, start, or reset its charging.

def coherent_state():
    last=None
    for attempt in range(3):
        state=get_state()
        try:
            return state,quality(state)
        except ValueError as e:
            last=e
            if "EVCC meter imbalance" not in str(e) or attempt==2:
                raise
            time.sleep(0.55)
    raise last


def nightly_key():
    now=datetime.now(TZ)
    return (now.date() if now.hour>=16 else now.date()-timedelta(days=1)).isoformat()


def allocate_night_budget(proposal):
    """Issue one dynamically calculated budget per night; never reissue it.

    Recording the full allocation up front intentionally forfeits any
    unused budget after crash, restart or changed EVCC plan (fail-closed).
    """
    key=nightly_key()
    LEDGER_DIR.mkdir(parents=True,exist_ok=True)
    path=LEDGER_DIR/(key+".json")
    if path.exists():
        row=json.loads(path.read_text())
        if row.get("date")!=key:
            raise ValueError("NIGHT_LEDGER_DATE_INVALID")
        # A ledger record is immutable, including migrated 0 kWh entries.
        # Rewriting it would violate the migration SHA256 manifest and make
        # the next startup fail; no second night allocation is issued.
        num(row["allocatedKwh"],0,100)
        return None
    granted=num(proposal["budgetKwh"],0,100)
    if granted<MIN_START_BUDGET_KWH:
        return None
    proposal=dict(proposal)
    proposal["budgetKwh"]=round(granted,4)
    proposal["nightKey"]=key
    row={"date":key,"allocatedKwh":round(granted,4),
         "lastSource":proposal["source"],
         "lastGrantedAt":datetime.now(TZ).isoformat(),
         "policy":"dynamic_forecast_once_per_night"}
    temp=path.with_suffix(".tmp")
    with temp.open("w") as f:
        json.dump(row,f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp,path)
    return proposal


_last_status_write=0.0
_last_status_signature=None
_last_status_audit=0.0
def publish_status(state,floor,session,problem=None):
    global _last_status_write,_last_status_signature,_last_status_audit
    now=time.time()
    with lock:
        actual=dict(status)
    permitted=(actual.get("permitted") is True and actual.get("phase")=="battery"
               and isinstance(actual.get("expiresAt"),(int,float))
               and actual["expiresAt"]>now)
    soc=None
    mode=None
    plan=False
    preview=0.0
    reason="NO_CURRENT_EVCC_STATE"
    rec=None
    trough=None
    report_age=None
    target_date=None
    last_model_error=None
    if state:
        try:
            soc=num(state["battery"]["soc"],0,100)
            lp=state["loadpoints"][0]
            mode=lp.get("mode")
            plan=lp.get("planActive") is True
            if floor is not None:
                available,predicted,age=forecast(state,state["battery"]["capacity"],floor)
                trough=round(predicted,2)
                preview=round(max(0,available),3)
                if preview<MIN_START_BUDGET_KWH:preview=0.0
                if soc<=floor+5:preview=0.0
                if state.get("optimizerAutomatic") not in (False,"off",None):
                    preview=0.0
                    reason="EVCC_OPTIMIZER_CONFLICT"
                elif problem:
                    preview=0.0
                    reason="MEASUREMENT_INVALID"
                elif preview==0:
                    reason="BUDGET_INSUFFICIENT"
                elif mode=="now":
                    reason="FAST_MODE_NO_RELEASE"
                elif not plan and lp.get("effectivePlanId") and lp.get("effectivePlanTime"):
                    reason="PLAN_SCHEDULED_WAITING"
                elif not (lp.get("charging") is True and
                          (plan or lp.get("alwaysCharge")=="once")):
                    reason="WAITING_FOR_EVCC_CHARGING"
                else:
                    reason="ELIGIBLE_IF_GATES_PASS"
                rep=json.loads(FORECAST.read_text())
                rec=rep["forecast"].get("recoveryAt")
                target_date=rep.get("targetDate")
                report_age=round(age)
            else:
                reason="HA_RESERVE_UNAVAILABLE"
        except (OSError,ValueError,KeyError,TypeError,IndexError) as e:
            last_model_error=str(e)[:180]
            reason="FORECAST_OR_DATA_INVALID"
    if problem:
        reason="MEASUREMENT_INVALID"
        last_model_error=str(problem)[:180]
        preview=0.0
    if permitted:
        reason="ACTUAL_PERMISSION_ACTIVE"
    elif session is not None and session.get("source")=="plan":
        reason={
            "paused_forecast":"FORECAST_PAUSED",
            "paused_priority":"PRIORITY_PAUSED",
            "locked":"SESSION_LOCKED",
            "exhausted":"BUDGET_EXHAUSTED"
        }.get(session.get("phase"),reason)
    if actual.get("reason") and not permitted:
        last_model_error=last_model_error or str(actual.get("reason"))[:180]
    record={
      "schema":1,"version":"0.8.0-beta","generatedAt":datetime.now(TZ).isoformat(),
      "validUntil":datetime.fromtimestamp(now+40,TZ).isoformat(),
      "permissionActive":permitted,
      "permissionSource":actual.get("source") if permitted else None,
      "controllerPhase":actual.get("phase"),"reasonCode":reason,"detail":last_model_error,
      "wouldGrantIfPlanned":preview>=MIN_START_BUDGET_KWH and not problem,
      "potentialBudgetKwh":preview,
      "actualGrantedKwh":round(float(session.get("budgetKwh",0)),3) if session and permitted else 0.0,
      "spentKwh":round(float(session.get("spentKwh",0)),3) if session else 0.0,
      "remainingKwh":round(max(0,float(session.get("allowedTotalKwh",session.get("budgetKwh",0)))-float(session.get("spentKwh",0))),3) if session else 0.0,
      "originalAllocationKwh":round(float(session.get("budgetKwh",0)),3) if session else 0.0,
      "authorizedNowKwh":round(max(0,float(session.get("allowedTotalKwh",session.get("budgetKwh",0)))-float(session.get("spentKwh",0))),3) if session and permitted else 0.0,
      "sessionReason":session.get("reason") if session else None,
      "batterySocPct":soc,"haReservePct":floor,"vehicleMode":mode,"planActive":plan,
      "planConfigured":bool(state and state.get("loadpoints") and state["loadpoints"][0].get("effectivePlanId")),
      "planTime":state["loadpoints"][0].get("effectivePlanTime") if state and state.get("loadpoints") else None,
      "planTargetSoc":state["loadpoints"][0].get("effectivePlanSoc") if state and state.get("loadpoints") else None,
      "predictedTroughSocPct":trough,"recoveryAt":rec,"forecastAgeSeconds":report_age,
      "forecastTargetDate":target_date,
      "dataCoherent":problem is None,
      "note":"Hypothetical preview is NOT an authorization. Only permissionActive is real."
    }
    signature=(permitted,reason,round(preview,2),floor,mode,plan,rec,round(float(session.get("spentKwh",0)),2) if session else 0)
    if now-_last_status_write < STATUS_INTERVAL_S and signature==_last_status_signature:
        return

    recovery.atomic_json(STATUS_OUTPUT,record)
    try:
        public.publish("status-intelligent.json",record)
    except (OSError,RuntimeError,ValueError) as e:
        log("HA_STATUS_EXPORT_WARNING",error=str(e)[:180])
    changed=signature!=_last_status_signature
    if changed or now-_last_status_audit>=900:
        audit=ROOT/"decision-audit"/("decisions-"+datetime.now(TZ).date().isoformat()+".jsonl")
        audit.parent.mkdir(parents=True,exist_ok=True)
        with audit.open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(record,ensure_ascii=False,separators=(",",":"))+"\n")
        _last_status_audit=now
    _last_status_write=now
    _last_status_signature=signature


def run_once():
    if not ARMED:
        setstatus("idle",False,why="armed=false")
        if STATE.exists():
            try:restore(json.loads(STATE.read_text()),"DISARMED_RECOVERY")
            except Exception as e:log("DISARMED_RECOVERY_ERROR",reason=str(e))
        return
    session=None
    if STATE.exists():
        # On restart never resume BATTERY permission from a persisted snapshot.
        session=json.loads(STATE.read_text())
        session["phase"]="locked"
        session["reason"]="RESTART_REQUIRES_NEW_SESSION"
        session["lastSample"]=time.time()
        write_state(session)
        log("RECOVERED_AFTER_RESTART_GRID_ONLY")
    tlastlog=0.0
    while not stop:
        start=time.time()
        s=None
        floor=None
        problem=None
        try:
            s,readings=coherent_state()
            lp,soc,cap,home,battery,car,pv,grid=readings
            floor=read_effective_floor(s)
            if s.get("optimizerAutomatic") not in (False,"off",None):
                raise ValueError("EVCC automatic optimizer conflicts with our battery owner")
            if session is None:
                try:
                    proposal=eligible_plan(s,floor)
                    if proposal is None:proposal=eligible(s,floor)
                except (OSError,ValueError,KeyError,TypeError) as e:
                    if start-tlastlog>180:log("START_NOT_ELIGIBLE",error=str(e));tlastlog=start
                    proposal=None
                if proposal is not None:
                    proposal=allocate_night_budget(proposal)
                if proposal is not None:
                    session=proposal
                    write_state(session)
                    setstatus("battery",True,totalFloorPct=floor,
                              source=session["source"],
                              planId=session.get("planId"),planTime=session.get("planTime"),
                              remainingKwh=session["budgetKwh"])
                    if session["source"]=="plan":
                        log("PLAN_BUDGET_STARTED",planId=session["planId"],
                            budgetKwh=session["budgetKwh"],soc=soc)
                    else:
                        log("PASSIVE_BUDGET_STARTED",budgetKwh=session["budgetKwh"],
                            batterySoc=soc,vehicleSoc=lp["vehicleSoc"])
                else:setstatus("idle",False,totalFloorPct=floor)
            elif session.get("source")=="plan":
                session=plan_step(session,lp,soc,cap,home,battery,car,pv,grid,floor)
            else:
                # EVCC exclusively owns minimum charging; the controller
                # observes it and grants/revokes ONLY KOSTAL energy.
                if lp.get("connected") is not True:
                    restore(session,"DISCONNECTED");session=None
                elif (lp.get("alwaysCharge")!="once" or lp.get("mode")!="smart"
                      or lp.get("charging") is not True or car<500):
                    restore(session,"EVCC_CHARGE_NOT_ACTIVE");session=None
                elif (lp.get("vehicleName")!=os.environ.get("BCG_VEHICLE_NAME")
                      or lp.get("vehicleClimaterActive") or lp.get("planActive")
                      or lp.get("effectivePlanId",0) not in (0,None)
                      or lp.get("effectivePlanTime") is not None
                      or lp.get("minSocNotReached") or lp.get("smartCostActive")
                      or lp.get("batteryBoost")):
                    restore(session,"OTHER_EVCC_PRIORITY");session=None
                elif lp.get("vehicleSoc") is not None and float(lp["vehicleSoc"])>=float(session["endVehicleSoc"]):
                    restore(session,"VEHICLE_TARGET_REACHED");session=None
                elif time.time()>session["stopBy"]:
                    restore(session,"RECOVERY_OR_MAX_TIME");session=None
                else:
                    dt=max(0,min(start-session["lastSample"],10))
                    ev_from_battery=max(0,min(car,battery-max(0,home-pv)))
                    session["spentKwh"]+=ev_from_battery*dt/3600000
                    session["lastSample"]=start
                    if session["phase"]=="battery":
                        if (soc <=floor+2 or floor!=session.get("floorPct")
                            or session["spentKwh"]>=session["budgetKwh"] or battery<0):
                            session["phase"]="grid"
                            log("HANDOFF_TO_GRID",reason="BUDGET_OR_SOC",spentKwh=round(session["spentKwh"],3),soc=soc)
                        else:
                            try:
                                current_budget,predicted,age=forecast(s,cap,floor)
                                if current_budget<0.15 or session["spentKwh"]+current_budget<session["budgetKwh"]-0.1:
                                    session["phase"]="grid"
                                    log("HANDOFF_TO_GRID",reason="FORECAST_DETERIORATED",soc=soc,modelBudgetKwh=current_budget)
                            except (OSError,ValueError,KeyError,TypeError) as e:
                                session["phase"]="grid"
                                log("HANDOFF_TO_GRID",reason="FORECAST_INVALID",detail=str(e))
                    write_state(session)
                    allow=session["phase"]=="battery"
                    setstatus("battery" if allow else "grid",allow,totalFloorPct=floor,source="once",
                        remainingKwh=round(max(0,session["budgetKwh"]-session["spentKwh"]),3),
                        spentKwh=round(session["spentKwh"],3),batterySoc=soc,carW=car)
                    if start-tlastlog>60:
                        log("SAMPLE",phase=session["phase"],soc=soc,carW=round(car),batW=round(battery),
                            homeW=round(home),gridW=round(grid),vehicleKwh=round(session["spentKwh"],3))
                        tlastlog=start
        except Exception as e:
            problem=e
            log("CONTROL_ERROR",reason=str(e))
            setstatus("grid",False,reason=str(e))
            if session:
                session["phase"]="locked"
                session["reason"]="CONTROL_ERROR"
                try:
                    write_state(session)
                    restore(session,"CONTROL_ERROR")
                    session=None
                except Exception:
                    # Keep the marker for retry/recovery; permission stays FALSE.
                    pass
        try:publish_status(s,floor,session,problem)
        except Exception as report_error:
            if start-tlastlog>180:
                log("UI_STATUS_ERROR",reason=str(report_error));tlastlog=start
        time.sleep(max(.1,POLL_S-(time.time()-start)))
    if session:
        restore(session,"SHUTDOWN")

def set_stop():
    global stop
    stop=True
