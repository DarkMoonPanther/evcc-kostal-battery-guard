"""Operator-controlled migration. Never modifies or removes old state."""
import argparse, json, os, shutil, sys, tempfile
from pathlib import Path
from datetime import datetime, timezone
from . import __version__

LEGACY_LEDGER="phase3-results/night-ledgers-v070"
LEGACY_SESSION="phase3-results/intelligent-session.json"
LEDGER="night-ledgers"
SESSION="intelligent-session.json"
MARKER="migration.json"

import hashlib,math,re
def _manifest(path):
    values={}
    for entry in sorted(path.glob("*.json")):
        if entry.is_symlink() or not entry.is_file():
            raise RuntimeError("Migration cannot follow symbolic links")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json",entry.name):
            raise RuntimeError("Unexpected legacy night-ledger filename")
        data=json.loads(entry.read_text())
        if data.get("date")!=entry.stem:
            raise RuntimeError("Night-ledger date mismatch: "+entry.name)
        x=data.get("allocatedKwh")
        if type(x) not in (int,float) or not math.isfinite(x) or x<0 or x>100:
            raise RuntimeError("Invalid persisted night allocation")
        values[entry.name]=hashlib.sha256(entry.read_bytes()).hexdigest()
    return values

def validate_marker(state_dir):
    path=Path(state_dir)/MARKER
    try:v=json.loads(path.read_text())
    except (OSError,ValueError):raise RuntimeError("Migration acknowledgement missing")
    if v.get("schema")!=1 or v.get("version")!=__version__:
        raise RuntimeError("Migration acknowledgement incompatible")
    if v.get("strategy") not in ("fresh","migrated"):
        raise RuntimeError("Migration strategy is invalid")
    if v.get("strategy")=="migrated":
        folder=Path(state_dir)/LEDGER
        if not folder.is_dir():
            raise RuntimeError("Migrated night ledger is missing")
        hashes=v.get("originalLedgerSHA256")
        if not isinstance(hashes,dict) or len(hashes)!=v.get("ledgerCount"):
            raise RuntimeError("Migration manifest invalid")
        current=_manifest(folder)
        for name,sha in hashes.items():
            if current.get(name)!=sha:
                raise RuntimeError("Migrated night allocation modified or missing: "+name)
    return v

def prepare(target,source=None,*,fresh=False):
    """Offline only. Explicitly run AFTER legacy controller is stopped.

    source is the old controller working dir; no hardcoded home/user paths.
    Not a deployment; only the caller-designated *new* state dir is written.
    """
    target=Path(target)
    if not target.is_absolute():raise ValueError("target must be absolute")
    if target.joinpath(MARKER).exists():raise RuntimeError("Existing migration marker; refuse overwrite")
    if fresh==bool(source):raise ValueError("Choose exactly one: fresh or source")
    if source:
        source=Path(source).resolve()
        if target.resolve()==source or source in target.resolve().parents:
            raise RuntimeError("Target must not be nested in old source")
        ledger=source/LEGACY_LEDGER
        session=source/LEGACY_SESSION
        if not ledger.is_dir():raise RuntimeError("No old ledger directory: cannot prove migration")
        if not list(ledger.glob("*.json")):raise RuntimeError("No old ledgers: cannot prove migration")
        if (target/LEDGER).exists() or (target/SESSION).exists():
            raise RuntimeError("Destination contains session/ledger; refuse merge")
        original=_manifest(ledger)
        if not original:raise RuntimeError("No legacy ledgers to migrate")
        if session.exists():
            if session.is_symlink() or not session.is_file():
                raise RuntimeError("Unexpected legacy session file")
            session_data=json.loads(session.read_text())
            if not isinstance(session_data,dict) or "source" not in session_data:
                raise RuntimeError("Invalid old session; refuse automatic adoption")
        target.mkdir(parents=True,exist_ok=True)
        (target/LEDGER).parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(ledger,target/LEDGER)
        new_manifest=_manifest(target/LEDGER)
        if original!=new_manifest:
            raise RuntimeError("Ledger copy not byte-for-byte identical")
        if session.exists():
            shutil.copy2(session,target/SESSION)
        strategy="migrated"
        count=len(new_manifest)
    else:
        if (target/LEDGER).exists() or (target/SESSION).exists():
            raise RuntimeError("Old state present: fresh would lose spent budget")
        strategy="fresh";count=0;original={}
    target.mkdir(parents=True,exist_ok=True)
    marker={"schema":1,"version":__version__,"strategy":strategy,
            "createdAt":datetime.now(timezone.utc).isoformat(),
            "ledgerCount":count,"originalLedgerSHA256":original}
    tmp=target/(MARKER+".tmp")
    with tmp.open("x") as f:
        json.dump(marker,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,target/MARKER)
    return marker

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--state-dir",required=True)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--fresh",action="store_true")
    group.add_argument("--source",help="old controller working directory")
    a=p.parse_args(argv)
    # The CLI is operator-facing. It must never snapshot a mutable live ledger.
    from .app import _legacy_active
    conflict=_legacy_active()
    if conflict:
        raise RuntimeError("Migration must wait until legacy services are stopped: "+conflict)
    result=prepare(a.state_dir,a.source,fresh=a.fresh)
    print(json.dumps(result,indent=2))

if __name__=="__main__":main()
