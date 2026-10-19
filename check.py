#!/usr/bin/env python3
"""Run the read-only --check mode with the installed configuration."""
import os
from pathlib import Path
import subprocess

CONFIG = Path("/etc/evcc-battery-guard.conf")
SCRIPT = Path("/usr/local/libexec/evcc-battery-guard")


def main():
    if not CONFIG.is_file() or not SCRIPT.is_file():
        raise SystemExit("Install the project and configure the host first.")
    env = os.environ.copy()
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise SystemExit("Malformed configuration line")
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip()
    return subprocess.run([str(SCRIPT), "--check"], env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
