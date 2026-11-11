#!/usr/bin/env python3
"""Copy only validated, recent v0.8.0 status into existing HA UI JSON paths.

Runs as admin through user systemd; cannot control EVCC, KOSTAL, or root guard.
If v0.8.0 is inactive or its data are stale, it does not publish.
"""
from datetime import datetime,timezone
from pathlib import Path
import json,os,subprocess,tempfile

SRC=Path("/run/battery-control-guard")
DST=Path(os.environ.get("BCG_HA_PUBLIC_DIR", "/nonexistent/bcg-ha-public-dir"))
SOURCES={
    "status-intelligent.json":("guard-v070-status.json",1),
    "forecast.json":("guard-recovery-v072.json",3),
}
CONTROLLER_KEYS=frozenset((
 "schema","version","generatedAt","validUntil","permissionActive",
 "permissionSource","controllerPhase","reasonCode","detail",
 "wouldGrantIfPlanned","potentialBudgetKwh","actualGrantedKwh",
 "spentKwh","remainingKwh","originalAllocationKwh","authorizedNowKwh",
 "sessionReason","batterySocPct","haReservePct","vehicleMode",
 "planActive","planConfigured","planTime","planTargetSoc",
 "predictedTroughSocPct","recoveryAt","forecastAgeSeconds",
 "forecastTargetDate","dataCoherent","note"
))

def parse_time(value):
    dt=datetime.fromisoformat(value)
    if dt.tzinfo is None:raise ValueError("timestamp lacks timezone")
    return dt.timestamp()

def validated(name,schema,now):
    path=SRC/name
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing/symlink public "+name)
    with path.open(encoding="utf-8") as f:obj=json.load(f)
    if obj.get("schema")!=schema or obj.get("version")!="0.8.0-beta":
        raise ValueError("schema/version mismatch "+name)
    if schema==1:
        stamp=parse_time(obj["generatedAt"])
        valid_until=parse_time(obj["validUntil"])
        if not (now-60<=stamp<=now+5 and now<valid_until<=now+70):
            raise ValueError("controller status stale")
        if type(obj.get("permissionActive")) is not bool:
            raise ValueError("permission type invalid")
        # Public UI projection explicitly excludes any future secret fields.
        return {k:obj[k] for k in CONTROLLER_KEYS if k in obj}
    stamp=parse_time(obj["asOf"])
    if not (now-20*60<=stamp<=now+5):
        raise ValueError("forecast stale")
    if obj.get("mode")!="observe_only" or obj.get("eligibleForControl") is not False:
        raise ValueError("unsafe forecast report")
    # Forecast has the established observational report schema.
    return obj

def publish(dest,obj):
    if not DST.is_dir() or DST.is_symlink():
        raise RuntimeError("HA destination invalid")
    path=DST/dest
    if path.is_symlink():
        raise RuntimeError("HA output symlink denied")
    fd,temp=tempfile.mkstemp(prefix="."+dest+".",suffix=".tmp",dir=DST)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(obj,f,ensure_ascii=False,allow_nan=False,separators=(",",":"))
            f.write("\n");f.flush();os.fsync(f.fileno())
        os.chmod(temp,0o644)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def main():
    p=subprocess.run(["/usr/bin/systemctl","is-active","--quiet",
                      "battery-control-guard.service"],timeout=5,check=False)
    if p.returncode!=0:
        print("SKIP: new guard not active",flush=True)
        return
    now=datetime.now(timezone.utc).timestamp()
    count=0
    for src,(dst,schema) in SOURCES.items():
        try:
            data=validated(src,schema,now)
            publish(dst,data)
            count+=1
        except (ValueError,OSError,KeyError,TypeError,RuntimeError) as e:
            print("SKIP",src,type(e).__name__,str(e)[:100],flush=True)
    print("HA v0.8.0 exports",count,flush=True)

if __name__=="__main__":main()
