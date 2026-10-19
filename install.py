#!/usr/bin/env python3
"""Conservative, first-time installer. Never starts or disables a service."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

SRC = Path(__file__).resolve().parent
SOURCES = {
    SRC / "evcc-battery-guard.py": Path("/usr/local/libexec/evcc-battery-guard"),
    SRC / "evcc-battery-guard.conf.example": Path("/etc/evcc-battery-guard.conf"),
    SRC / "evcc-battery-guard.service": Path("/etc/systemd/system/evcc-battery-guard.service"),
}


def main() -> int:
    if os.geteuid() != 0:
        print("Run as root with sudo.", file=sys.stderr)
        return 2
    for source, target in SOURCES.items():
        if not source.is_file():
            print(f"Missing source: {source}", file=sys.stderr)
            return 2
        if target.exists() or target.is_symlink():
            print(f"Refusing to overwrite existing installation: {target}", file=sys.stderr)
            return 3

    # Validate before touching global paths.
    subprocess.run([sys.executable, "-m", "py_compile", str(SRC / "evcc-battery-guard.py")], check=True)
    config = (SRC / "evcc-battery-guard.conf.example").read_text(encoding="utf-8")
    if "ARMED=false" not in config or "KOSTAL_HOST=192.0.2.10" not in config:
        raise RuntimeError("Unexpected or unsafe example configuration")

    for source, target in SOURCES.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        os.chmod(target, 0o600 if target.name.endswith(".conf") else (0o755 if target.parent.name == "libexec" else 0o644))

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    print("Installed, but NOT started or enabled. ARMED=false.")
    print("Edit /etc/evcc-battery-guard.conf, run the read-only check, then review SAFETY.md.")
    print("No EVCC configuration, existing service, or inverter register was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
