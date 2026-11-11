"""Independent shadow comparison against the exact installed v0.6.2 source.

ONLY uses GET /api/state and optional GET of local legacy permission.
NEVER constructs a KOSTAL client, never invokes EVCC POST, and does not
run protection.Guard. Output is private local JSONL/summary files.
"""
from __future__ import annotations
import argparse, ast, hashlib, importlib.util, json, os, sys, time, textwrap
from datetime import datetime,timezone
from pathlib import Path
from importlib.machinery import SourceFileLoader
from . import __version__
from . import protection,decision
from .app import load_config,_set_env

def load_reference(path,expected_sha256_prefix):
    path=Path(path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if not digest.startswith(expected_sha256_prefix):
        raise RuntimeError("Legacy source hash mismatch: refusing non-comparable reference")
    # Legacy module import executes only definitions; it is never instantiated
    # as a Guard and never run as its __main__.
    sys.path.insert(0,str(path.parent))
    loader=SourceFileLoader("bcg_v062_readonly_reference",str(path))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    loader.exec_module(module)

    # Compile only the original 1040 policy assignments/try-block, not the
    # original guard main loop, driver or any state-changing method.
    source=path.read_text()
    start=source.index('                desired = max(0.0, m["home"] - m["pv"] - self.cfg.grid_margin_w)')
    stop=source.index('                if self.should_refresh(desired):',start)
    policy=textwrap.dedent(source[start:stop])
    parsed=ast.parse(policy)
    allowed=(ast.Assign,ast.Try,ast.If,ast.Expr,ast.AugAssign)
    if not all(isinstance(x,allowed) for x in parsed.body):
        raise RuntimeError("Unexpected reference policy statements")
    body="def reference(self,m,state,permission):\n"
    body+="    def intelligent_permission(): return permission\n"
    body+=textwrap.indent(policy,"    ")
    body+="    return desired,origin\n"
    namespace={"intelligent_floor":module.intelligent_floor,
               "loadpoints":module.loadpoints,
               "max":max,"min":min}
    exec(compile(body,"<verified reference v0.6.2 policy>","exec"),namespace)
    return module,namespace["reference"],digest

def classify(state,m):
    if state.get("batteryDischargeControl") is not False:
        return "evcc_owns_battery"
    if state.get("batteryGridChargeActive") is True or state.get("batteryGridDischargeActive") is True or m["battery_boost"]:
        return "conflict"
    if str(state.get("batteryMode","unknown")).lower() not in {"unknown","normal","none",""}:
        return "conflict"
    if not (m["guard_requested"] or m["intelligent_once"]):
        return "not_guarded"
    if not m["coherent"]:
        return "incoherent"
    return "protected"

def sample(config,reference,reference_policy,state):
    oldm=reference.metrics(state,reference.Config.from_env())
    newm=protection.metrics(state,protection.Config.from_env())
    mode_old=classify(state,oldm)
    mode_new=classify(state,newm)
    differences={}
    for key in ("home","pv","grid","battery","battery_soc","charge",
                "coherence_error","coherent","guard_requested",
                "smart_minimum_charge","smart_continuous_charge","intelligent_once",
                "intelligent_plan","battery_boost"):
        if newm[key]!=oldm[key]:
            differences[key]={"old":oldm[key],"new":newm[key]}
    if mode_old!=mode_new: differences["guard_state"]={"old":mode_old,"new":mode_new}
    decision_old=None
    decision_new=None
    # With a real permit, the KOSTAL minimum 1042 has to be read from a
    # known trustworthy source. This shadow deliberately DOES NOT guess it.
    if mode_old=="protected":
        dummy=type("ReadonlyReference",(object,),{"cfg":reference.Config.from_env(),"baseline":None})()
        decision_old,origin_old=reference_policy(dummy,oldm,state,None)
        decision_new,origin_new=decision.compute_target(newm,state,protection.Config.from_env(),0.0,None,None)
        if abs(decision_new-decision_old)>1e-6:
            differences["home_only_limit_w"]={"old":decision_old,"new":decision_new}
    # Extra read-only fields for full charging/climater audits. No secrets,
    # vehicle identifiers, VIN, tokens or raw EVCC state are persisted.
    lp = state.get("loadpoints", [{}])[0] if state.get("loadpoints") else {}
    battery_obj = state.get("battery") or {}
    devices = battery_obj.get("devices") or []
    min_soc_evcc = devices[0].get("minSoc") if len(devices)==1 else None
    return {
      "schema":1,"version":__version__,
      "observedAt":datetime.now(timezone.utc).isoformat(),
      "execution":"shadow_read_only","modbusWrites":0,"evccPosts":0,
      "legacyState":mode_old,"betaState":mode_new,
      "chargeMode":str(state.get("loadpoints",[{}])[0].get("mode","unknown")) if state.get("loadpoints") else None,
      "planActive":bool(state.get("loadpoints",[{}])[0].get("planActive")) if state.get("loadpoints") else False,
      "intelligentPlanCandidate":bool(newm["intelligent_plan"]),
      "intelligentOnceCandidate":bool(newm["intelligent_once"]),
      "homeW":round(newm["home"],1),"pvW":round(newm["pv"],1),
      "gridW":round(newm["grid"],1),"batteryPowerW":round(newm["battery"],1),
      "carW":round(newm["charge"],1),"batterySocPct":round(newm["battery_soc"],1),
      "evccMinSocPct":min_soc_evcc,
      "vehicleSocPct":lp.get("vehicleSoc"),
      "vehicleClimaterActive":lp.get("vehicleClimaterActive"),
      "connected":lp.get("connected"),"charging":lp.get("charging"),
      "planTargetSocPct":lp.get("effectivePlanSoc"),
      "planDueAt":lp.get("effectivePlanTime"),
      "chargerTotalImportKwh":lp.get("chargeTotalImport"),
      "sessionEnergyWh":lp.get("sessionEnergy"),
      "sessionSolarPercentage":lp.get("sessionSolarPercentage"),
      "coherent":newm["coherent"],"homeOnlyLegacyW":decision_old,
      "homeOnlyBetaW":decision_new,
      "independentDifferences":differences,
      "comparisonScope":"Original guard v0.6.2, same EVCC state, no active permission; KOSTAL 1042/baseline/BMS not assumed"}

def _atomic(path,record):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    with tmp.open("w",encoding="utf-8") as out:
        json.dump(record,out,ensure_ascii=False,indent=2)
        out.flush();os.fsync(out.fileno())
    tmp.replace(path)

def run(config,source,prefix,once=False,interval=15):
    if config["application"].get("execution")!="observe" or config["application"].get("armed") is not False:
        raise RuntimeError("SHADOW START BLOCKED: execution=observe and armed=false are both required")
    if interval<5:raise ValueError("minimum polling interval 5 seconds")
    # Shadow is not a generic remote client. The production EVCC instance
    # must be accessed via the local read-only GET endpoint only.
    state_url=config["evcc"]["state_url"]
    if state_url != "http://127.0.0.1:7070/api/state":
        raise RuntimeError("Shadow network lockout: only local EVCC GET endpoint allowed")
    _set_env(config)
    original,policy,sha=load_reference(source,prefix)
    state_dir=Path(config["application"]["state_dir"])
    os.umask(0o077)
    state_dir.mkdir(parents=True,exist_ok=True)
    state_dir.chmod(0o700)
    report_file=state_dir/"shadow-latest.json"
    totals={"samples":0,"divergent":0,"errors":0,"protected":0,"other":0}
    counters=state_dir/"shadow-counters.json"
    if counters.is_file():
        try:
            old=json.loads(counters.read_text())
            if old.get("sourceSha256Prefix")==sha[:18] and old.get("version")==__version__:
                totals={k:int(old[k]) for k in totals}
        except (OSError,ValueError,TypeError,KeyError):
            pass
    while True:
        begin=time.monotonic()
        try:
            state=protection.fetch_evcc_state(protection.Config.from_env())
            rec=sample(config,original,policy,state)
            totals["samples"]+=1
            if rec["independentDifferences"]:totals["divergent"]+=1
            if rec["legacyState"]=="protected":totals["protected"]+=1
            else:totals["other"]+=1
        except Exception as exc:
            totals["errors"]+=1
            rec={"schema":1,"version":__version__,"observedAt":datetime.now(timezone.utc).isoformat(),
                 "execution":"shadow_read_only","error":f"{type(exc).__name__}: {exc}",
                 "modbusWrites":0,"evccPosts":0}
        _atomic(report_file,rec)
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with (state_dir/f"shadow-{date}.jsonl").open("a",encoding="utf-8") as out:
            out.write(json.dumps(rec,separators=(",",":"),ensure_ascii=False)+"\n")
        _atomic(counters,{"schema":1,"version":__version__,"sourceSha256Prefix":sha[:18],
                                                  "samplePeriodSeconds":interval,
                                                  "updatedAt":rec["observedAt"],**totals})
        if once:
            print(json.dumps(rec,ensure_ascii=False,indent=2))
            break
        time.sleep(max(0.2,interval-(time.monotonic()-begin)))

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--config",required=True)
    p.add_argument("--legacy-source",required=True)
    p.add_argument("--sha-prefix",required=True)
    p.add_argument("--once",action="store_true")
    p.add_argument("--interval",type=int,default=15)
    a=p.parse_args(argv)
    c=load_config(a.config)
    run(c,a.legacy_source,a.sha_prefix,once=a.once,interval=a.interval)

if __name__=="__main__":main()
