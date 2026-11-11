"""Single-process decisions. Pure limit policy + expiring authorization bus.

Only protection.Guard may call the KOSTAL driver. This module has no I/O.
The policy is a line-for-line logical extraction of v0.6.2 lines 692-721.
"""
import math
import os
import threading
import time

_lock = threading.Lock()
_grant = {}
_kostal_soc = None
_kostal_soc_at = 0.0

def publish_kostal_min_soc(value, now=None):
    """Publish 1042 only after a verified read by the single KOSTAL driver."""
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("invalid physical minimum SoC from KOSTAL 1042")
    now = time.monotonic() if now is None else now
    global _kostal_soc, _kostal_soc_at
    with _lock:
        _kostal_soc = float(value)
        _kostal_soc_at = float(now)

def get_kostal_min_soc(now=None, maximum_age_s=35.0):
    """Refuse absent/stale physical minimum. No fallback to guessed HA values."""
    now = time.monotonic() if now is None else now
    with _lock:
        value, updated = _kostal_soc, _kostal_soc_at
    if value is None or not (0 <= now-updated <= maximum_age_s):
        raise RuntimeError("KOSTAL 1042 missing or stale")
    return value

def invalidate_kostal_min_soc():
    global _kostal_soc, _kostal_soc_at
    with _lock:
        _kostal_soc, _kostal_soc_at = None, 0.0

def publish(status):
    """Store a fresh lease; no modification of physical charge limits."""
    with _lock:
        _grant.clear()
        _grant.update(dict(status))

def clear():
    with _lock:
        _grant.clear()

def snapshot(now=None):
    """Validated short-lived intelligent grant, wholly in-process."""
    with _lock:
        v = dict(_grant)
    now = time.time() if now is None else now
    floor = v.get("totalFloorPct")
    valid = (v.get("schema")==1
             and type(v.get("updatedAt")) in (int,float)
             and 0<=now-v["updatedAt"]<=12
             and type(v.get("expiresAt")) in (int,float)
             and now<v["expiresAt"]<=now+20
             and type(floor) in (int,float)
             and math.isfinite(floor) and 8<=floor<=30)
    if not valid: return None
    source=v.get("source")
    if source not in ("once","plan"):return None
    if source=="plan" and (type(v.get("planId")) is not int
                          or v["planId"]<1
                          or not isinstance(v.get("planTime"),str)
                          or not v["planTime"]): return None
    return {"floor":float(floor),"source":source,"planId":v.get("planId"),
            "planTime":v.get("planTime"),
            "permitted":v.get("phase")=="battery" and v.get("permitted") is True}

def floor_with_limits(kostal_min, state, slider_floor):
    devices=(state.get("battery") or {}).get("devices") or []
    if len(devices)!=1:raise RuntimeError("ambiguous battery")
    raw=devices[0].get("minSoc")
    if isinstance(raw,bool) or not isinstance(raw,(float,int)) or not math.isfinite(raw) or not 0<=raw<=100:
        raise RuntimeError("invalid EVCC battery minSoc")
    if not 8<=slider_floor<=30:raise RuntimeError("invalid total reserve")
    return max(kostal_min,float(raw),slider_floor)

def compute_target(metrics,state,cfg,kostal_min,baseline,permission=None):
    """The sole policy used by the 1040 writer after all classic guard checks.

    Return (target W, reason); caller still applies baseline, BMS cap,
    minSoC hysteresis, rounding and write-readback verification.
    """
    m=metrics
    desired=max(0.0,m["home"]-m["pv"]-cfg.grid_margin_w)
    origin="classic"
    # Unchanged v0.6.2 rule: conventional fast/plan/HVAC protection wins.
    if m["intelligent_once"] or m["intelligent_plan"]:
        applicable=False
        if permission is not None:
            lps=[x for x in state.get("loadpoints",[]) if isinstance(x,dict)]
            if m["intelligent_once"] and not m["guard_requested"]:
                applicable=(permission["source"]=="once"
                            and len(lps)==1
                            and lps[0].get("vehicleName")==os.environ.get("BCG_VEHICLE_NAME"))
            elif m["intelligent_plan"]:
                applicable=(permission["source"]=="plan"
                            and len(lps)==1
                            and permission["planId"]==lps[0].get("effectivePlanId")
                            and permission["planTime"]==lps[0].get("effectivePlanTime"))
        if not applicable:
            origin="missing/stale/other session permission: home only"
        else:
            floor=floor_with_limits(kostal_min,state,permission["floor"])
            if m["battery_soc"]<=floor+0.5:
                desired=0.0
                origin=f"dynamic hard floor {floor:.1f}%"
            elif m["battery_soc"]>floor+1.5 and permission["permitted"]:
                desired=max(0.0,m["home"]-m["pv"]-cfg.grid_margin_w+m["charge"])
                origin=f"{permission['source']} budget authorized floor={floor:.1f}%"
            else:
                origin=f"{permission['source']} budget exhausted: home only floor={floor:.1f}%"
    desired=min(desired,baseline if baseline is not None else desired)
    return desired,origin
