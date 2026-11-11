"""Single executable for Battery Control Guard 0.8.0-beta.

Default is offline/read-only. No start or write unless BOTH config armed=true
and explicit --run AND old writer stopped. The service itself is not installed.
"""
from __future__ import annotations
import argparse, contextlib, fcntl, json, os, signal, subprocess, sys, threading, time, tomllib
from pathlib import Path
from datetime import datetime, timezone

from . import __version__, decision

class ConfigurationError(ValueError): pass

def load_config(path):
    with Path(path).open("rb") as f: c=tomllib.load(f)
    allowed={"application","evcc","kostal","protection","intelligent","home_assistant"}
    if set(c)-allowed:raise ConfigurationError("Unknown config sections: "+repr(set(c)-allowed))
    app=c.get("application",{})
    if app.get("mode","protection") not in ("protection","intelligent"):
        raise ConfigurationError("mode must be protection or intelligent")
    if app.get("execution","observe") not in ("observe","active"):
        raise ConfigurationError("execution must be observe or active")
    if not isinstance(app.get("armed",False),bool):
        raise ConfigurationError("armed must be bool")
    if "state_dir" not in app or not Path(app["state_dir"]).is_absolute():
        raise ConfigurationError("application.state_dir must be an absolute path")
    evcc=c.get("evcc",{})
    if not isinstance(evcc.get("state_url"),str) or not evcc["state_url"].endswith("/api/state"):
        raise ConfigurationError("evcc.state_url must end with /api/state")
    if not evcc["state_url"].startswith(("http://","https://")):
        raise ConfigurationError("evcc URL must be http(s)")
    if app.get("mode","protection")=="intelligent":
        ic=c.get("intelligent",{})
        if not isinstance(ic.get("vehicle_name"),str) or not ic.get("vehicle_name"):
            raise ConfigurationError("intelligent.vehicle_name is required")
        if ic.get("loadpoint_id",1)!=1:
            raise ConfigurationError("beta supports exactly one EVCC loadpoint, index 1")
        if not 8<=float(ic.get("fixed_reserve_soc_pct",-1))<=30:
            raise ConfigurationError("explicit reserve 8..30%% is required")
        ha=c.get("home_assistant",{})
        if ha.get("reserve_entity"):
            if not ha.get("api_url") or not ha.get("token_file"):
                raise ConfigurationError("HA reserve entity needs api_url and token_file")
            if not Path(ha["token_file"]).is_absolute():
                raise ConfigurationError("HA token_file must be absolute")
    k=c.get("kostal",{})
    if app.get("execution")=="active" and not k.get("host"):
        raise ConfigurationError("kostal.host is required for active mode")
    for key,minv,maxv in (("port",1,65535),("unit",0,255)):
        if key in k and not minv<=int(k[key])<=maxv:raise ConfigurationError("kostal "+key+" out of range")
    return c

def _set_env(c):
    """Single configuration source; legacy modules use these env names."""
    a=c["application"]; e=c["evcc"]; k=c.get("kostal",{})
    p=c.get("protection",{}); i=c.get("intelligent",{}); ha=c.get("home_assistant",{})
    mapping={
      "BCG_STATE_DIR":a["state_dir"],
      "BCG_TIMEZONE":a.get("timezone","Europe/Berlin"),
      "BCG_EVCC_API_URL":e["state_url"].removesuffix("/state"),
      "EVCC_STATE_URL":e["state_url"],
      "KOSTAL_HOST":k.get("host",""),
      "KOSTAL_PORT":k.get("port",1502),
      "KOSTAL_UNIT":k.get("unit",71),
      "POLL_INTERVAL_S":p.get("poll_interval_s",15),
      "REFRESH_INTERVAL_S":p.get("refresh_interval_s",30),
      "MIN_CHANGE_W":p.get("min_change_w",100),
      "GRID_MARGIN_W":p.get("grid_margin_w",100),
      "MIN_CHARGE_POWER_W":p.get("min_charge_power_w",500),
      "MIN_SOC_HYSTERESIS_PCT":p.get("min_soc_hysteresis_pct",0.5),
      "STATE_COHERENCE_W":p.get("state_coherence_w",500),
      "READBACK_TOLERANCE_W":p.get("readback_tolerance_w",50),
      "MAX_REASONABLE_POWER_W":p.get("max_reasonable_power_w",30000),
      "HTTP_TIMEOUT_S":p.get("http_timeout_s",3),
      "MODBUS_TIMEOUT_S":p.get("modbus_timeout_s",3),
      "STATE_DIR":a["state_dir"],
      "BCG_FIXED_RESERVE_SOC_PCT":i.get("fixed_reserve_soc_pct",15),
      "BCG_HA_API_URL":ha.get("api_url",""),
      "BCG_HA_AUTH_FILE":ha.get("token_file","/nonexistent/bcg-token"),
      "BCG_HA_RESERVE_ENTITY":ha.get("reserve_entity",""),
      "BCG_VEHICLE_NAME":i.get("vehicle_name",""),
      "BCG_LOADPOINT_ID":i.get("loadpoint_id",1),
      "INTELLIGENT_ARMED":"true" if a["mode"]=="intelligent" else "false",
      "ARMED":"true" if a["execution"]=="active" and a["armed"] else "false",
    }
    for key,val in mapping.items():os.environ[key]=str(val)

def _legacy_active():
    """Additional belt: refuse dual 1040 writers and legacy controller."""
    # Check BOTH legacy names: the previous public v0.4.0 installer used
    # evcc-battery-guard.service, while the private development name differed.
    for legacy_service in ("evcc-battery-guard.service", "mokka-battery-guard.service"):
        r=subprocess.run(["systemctl","is-active","--quiet",legacy_service],
                         check=False,capture_output=True)
        if r.returncode==0:
            return "legacy Modbus writer is active: "+legacy_service
        r=subprocess.run(["systemctl","is-enabled",legacy_service],
                         capture_output=True,text=True,check=False)
        if r.stdout.strip() in ("enabled","enabled-runtime","linked-runtime"):
            return "legacy writer remains enabled: "+legacy_service
    # The old controller can still start EVCC once-charging and emit 5099 grants.
    r=subprocess.run(["pgrep","-f","[m]okka-intelligent-controller-"],
                     capture_output=True,check=False)
    if r.returncode==0:return "legacy intelligent controller is active"
    return None

def _write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    with tmp.open("w",encoding="utf-8") as f:
        json.dump(obj,f,ensure_ascii=False,indent=2)
        f.flush();os.fsync(f.fileno())
    tmp.replace(path)

def _observe(c, state=None):
    """Read-only protection analysis. Never constructs ModbusTCP/Kostal/Guard."""
    from . import protection
    if state is None:state=protection.fetch_evcc_state(protection.Config.from_env())
    m=protection.metrics(state,protection.Config.from_env())
    limit,reason=decision.compute_target(
        m,state,protection.Config.from_env(),
        kostal_min=0,baseline=None,permission=None)
    if not m["guard_requested"]:
        limit=None;reason="no protected charging"
    elif not m["coherent"]:
        limit=0.0;reason="EVCC state incoherent: hypothetical failsafe"
    return {"version":__version__,"mode":c["application"]["mode"],
            "execution":"observe","generatedAt":datetime.now(timezone.utc).isoformat(),
            "modbusWrites":0,"evccPosts":0,
            "guardRequested":m["guard_requested"],"measurementsCoherent":m["coherent"],
            "coherenceErrorW":m["coherence_error"],"protectedTargetW":limit,
            "reason":reason,"batterySocPct":m["battery_soc"],
            "comment":"Hypothetical home-only limit, not a physical inverter command"}

def observe_live(c):
    report=_observe(c)
    _write_json(Path(c["application"]["state_dir"])/"status.json",report)
    print(json.dumps(report,indent=2,ensure_ascii=False))

def replay(c,path):
    """State snapshots: optional old expected values; no network or Modbus."""
    payload=json.loads(Path(path).read_text())
    rows=payload if isinstance(payload,list) else [payload]
    result=[]
    for j,row in enumerate(rows):
        try:
            output=_observe(c,row["evcc"])
            r={"index":j,"computed":output,"status":"OK"}
            if "expectHomeTargetW" in row:
                r["expected"]=row["expectHomeTargetW"]
                r["matches"]=abs(output["protectedTargetW"]-row["expectHomeTargetW"])<0.001
            result.append(r)
        except Exception as e: result.append({"index":j,"status":"ERROR","error":str(e)})
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return 0 if all(r.get("status")=="OK" and r.get("matches",True) for r in result) else 1

@contextlib.contextmanager
def exclusive_writer_lock(state_dir):
    """One OS-enforced controller instance for the whole Modbus lifetime."""
    path=Path(state_dir)
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    lockpath=path/"instance.lock"
    fd=os.open(lockpath,os.O_RDWR|os.O_CREAT|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RuntimeError("WRITE LOCKOUT: another v0.8.0 instance holds instance.lock") from e
        os.ftruncate(fd,0)
        os.write(fd,str(os.getpid()).encode())
        os.fsync(fd)
        yield
    finally:
        os.close(fd)

def active(c):
    a=c["application"]
    if a["execution"]!="active" or not a["armed"]:
        raise ConfigurationError("Refusing to arm: execution=active and armed=true both required")
    conflict=_legacy_active()
    if conflict:raise RuntimeError("WRITE LOCKOUT: "+conflict)
    with exclusive_writer_lock(a["state_dir"]):
        return _active_locked(c)

def _active_locked(c):
    a=c["application"]
    conflict=_legacy_active()
    if conflict:raise RuntimeError("WRITE LOCKOUT: "+conflict)
    if a["mode"]=="intelligent":
        from .migrate import validate_marker
        validate_marker(a["state_dir"])
    # The only Modbus writer lives in protection.Guard.
    from . import protection
    stop=threading.Event()
    guard=protection.Guard(protection.Config.from_env())
    threads=[]
    workers={}
    intelligent=None
    def halt(*_):
        stop.set();guard.stop_requested=True;decision.clear();decision.invalidate_kostal_min_soc()
        if intelligent is not None:intelligent.set_stop()
    signal.signal(signal.SIGTERM,halt)
    signal.signal(signal.SIGINT,halt)
    if a["mode"]=="intelligent":
        from . import recovery, intelligent as controller
        intelligent=controller
        def forecast_worker():
            while not stop.is_set():
                try:
                    recovery.main()
                except Exception as exc:
                    decision.clear()
                    (Path(a["state_dir"])/"forecast.json").unlink(missing_ok=True)
                    print("FORECAST_DISABLED",type(exc).__name__,str(exc),flush=True)
                stop.wait(900)
        def controller_worker():
            # Mandatory preflight barrier. No intelligent budget without
            # a live coherent EVCC snapshot and a verified KOSTAL 1042.
            while not stop.is_set() and not guard.ready_event.wait(timeout=0.5):
                pass
            if stop.is_set():return
            try:controller.run_once()
            except Exception as exc:
                print("INTELLIGENCE_DISABLED",type(exc).__name__,str(exc),flush=True)
            finally:decision.clear()
        t=threading.Thread(target=forecast_worker,name="forecast",daemon=True);t.start();threads.append(t);workers["forecast"]=t
        t=threading.Thread(target=controller_worker,name="intelligent",daemon=True);t.start();threads.append(t);workers["intelligent"]=t
    from . import status
    status_thread=threading.Thread(target=status.monitor,args=(c,guard,stop,workers),name="status",daemon=True)
    status_thread.start()
    try:
        return guard.run()
    finally:
        halt()
        if guard.baseline is not None:guard.relinquish("single-process shutdown")
        for t in threads:t.join(timeout=3)
        status_thread.join(timeout=3)

def main(argv=None):
    p=argparse.ArgumentParser(description="EVCC KOSTAL Battery Control Guard "+__version__)
    p.add_argument("--config",required=False,default="config.toml")
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--observe",action="store_true")
    group.add_argument("--replay",metavar="FILE")
    group.add_argument("--run",action="store_true")
    group.add_argument("--check-config",action="store_true")
    group.add_argument("--version",action="store_true")
    args=p.parse_args(argv)
    if args.version:print(__version__);return 0
    c=load_config(args.config);_set_env(c)
    if args.check_config:
        print("Config valid:",c["application"]["mode"],c["application"]["execution"])
        return 0
    if args.replay:return replay(c,args.replay)
    if args.observe:observe_live(c);return 0
    return active(c)

if __name__=="__main__":
    try:sys.exit(main())
    except (ConfigurationError,RuntimeError,ValueError) as exc:
        print("GUARD REFUSED:",str(exc),file=sys.stderr);sys.exit(2)
