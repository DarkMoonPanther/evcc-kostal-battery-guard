"""One local operational status document. Read-only; no protocol access."""
from datetime import datetime,timezone
from pathlib import Path
import json,os,time
from . import __version__, decision

def _json_write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    with tmp.open("w",encoding="utf-8") as f:
        json.dump(value,f,ensure_ascii=False,indent=2)
        f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def snapshot(mode,guard,controller_alive=False,forecast_alive=False):
    permission=decision.snapshot()
    state_dir=Path(os.environ["BCG_STATE_DIR"])
    forecast_path=state_dir/"forecast.json"
    forecast_stamp=None
    if forecast_path.exists():
        try:
            with forecast_path.open() as f: forecast_stamp=json.load(f).get("asOf")
        except (OSError,ValueError):pass
    # Guard has only one writer. These status fields do not trigger a write.
    try: min_soc=decision.get_kostal_min_soc()
    except RuntimeError: min_soc=None
    return {"schema":1,"version":__version__,"generatedAt":datetime.now(timezone.utc).isoformat(),
            "mode":mode,"execution":"active",
            "protection":{"ready":guard.ready_event.is_set(),
                          "active":guard.baseline is not None,
                          "baseline1040W":guard.baseline,
                          "lastWritten1040W":guard.last_target,
                          "lastReason":getattr(guard,"last_reason",None),
                          "physicalMinSocPct":min_soc},
            "intelligent":{"workerAlive":bool(controller_alive),
                           "forecastWorkerAlive":bool(forecast_alive),
                           "permissionActive":bool(permission and permission["permitted"]),
                           "permissionSource":permission["source"] if permission else None,
                           "reportAsOf":forecast_stamp},
            "note":"Status is observational. Actual KOSTAL readback is in the guard journal."}

def monitor(config,guard,stop,workers):
    path=Path(config["application"]["state_dir"])/"status.json"
    while not stop.is_set():
        try:
            _json_write(path,snapshot(
                config["application"]["mode"],guard,
                controller_alive=bool(workers.get("intelligent") and workers["intelligent"].is_alive()),
                forecast_alive=bool(workers.get("forecast") and workers["forecast"].is_alive())))
        except Exception as exc:
            print("STATUS_WRITE_ERROR",type(exc).__name__,str(exc),flush=True)
        stop.wait(15)
    # Final status must not accidentally look like an active grant.
    _json_write(path,{"schema":1,"version":__version__,
                      "generatedAt":datetime.now(timezone.utc).isoformat(),
                      "execution":"stopped","protection":{"active":False},
                      "intelligent":{"permissionActive":False}})
