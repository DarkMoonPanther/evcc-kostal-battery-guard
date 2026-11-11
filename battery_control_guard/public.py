"""Local read-only export to Home Assistant user bridge.

The single active systemd service owns /run/battery-control-guard.
Only already-computed nonsecret status and forecast data is exported.
This module contains no EVCC, MQTT, Modbus or HA write client.
"""
from __future__ import annotations
import json
import os
import stat
from pathlib import Path

PUBLIC_DIR=Path("/run/battery-control-guard")
ALLOWED=frozenset({"status-intelligent.json","forecast.json"})

def publish(name, value):
    if name not in ALLOWED:
        raise ValueError("unsupported public export")
    directory=PUBLIC_DIR
    # The runtime directory is created by systemd for bcguard, not by this app.
    if directory.is_symlink() or not directory.is_dir():
        return False
    meta=directory.stat()
    if meta.st_uid != os.geteuid() or not stat.S_ISDIR(meta.st_mode):
        raise RuntimeError("public export directory not owned by guard process")
    dest=directory/name
    if dest.is_symlink():
        raise RuntimeError("public export symlink detected")
    tmp=directory/("."+name+"."+str(os.getpid())+".tmp")
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as fp:
            json.dump(value,fp,ensure_ascii=False,separators=(",",":"),allow_nan=False)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp,dest)
        os.chmod(dest,0o644)
    finally:
        if tmp.exists():
            tmp.unlink()
    return True
