#!/usr/bin/env python3
"""Offline prepublication audit; never prints the matched secret value."""
from __future__ import annotations
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLOCKED_PATHS = {
    "config.toml",
    "migration.json",
    "intelligent-session.json",
    "status-intelligent.json",
    "forecast.json",
}
BLOCKED_PREFIXES = (
    "runtime/", "evidence/", "backups/", ".release-review/",
    "night-ledgers/", "state/", ".venv/",
)
RULES = {
    "private LAN IPv4": re.compile(
        r"(?<!\d)(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?!\d)"
    ),
    "local user home path": re.compile(r"/home/" + r"[A-Za-z0-9._-]+/" + r"|/Users/[A-Za-z0-9._-]+/"),
    "personal email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "token-like secret": re.compile(
        r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{12,}|Bearer\s+[A-Za-z0-9_.-]{24,}|sk-[A-Za-z0-9]{20,})",
        re.IGNORECASE,
    ),
}

def main():
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, text=True,
    )
    paths = sorted(set(output.splitlines()))
    bad = []
    checked = 0
    for rel in paths:
        p = ROOT / rel
        if not p.is_file():
            continue
        checked += 1
        if rel in BLOCKED_PATHS or rel.startswith(BLOCKED_PREFIXES):
            bad.append((rel, "disallowed file in public tree"))
            continue
        if p.stat().st_size > 1_000_000:
            bad.append((rel, "file unusually large: manual review required"))
            continue
        s = p.read_text(encoding="utf-8", errors="replace")
        for name, pattern in RULES.items():
            for line_no, line in enumerate(s.splitlines(), 1):
                if pattern.search(line):
                    # Deliberately suppress actual matching content.
                    bad.append((rel, name + " at line " + str(line_no)))
    for rel, reason in bad:
        print("BLOCK:", rel, "—", reason)
    print("Reviewed public paths:", checked, "issues:", len(bad))
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
