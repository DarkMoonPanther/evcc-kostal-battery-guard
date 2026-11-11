"""Public v0.4 and private legacy systemd service conflict tests (offline)."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from battery_control_guard import app


def fake_runner(active=(), enabled=()):
    def run(command, **_):
        name = command[-1]
        if command[0] == "pgrep":
            return SimpleNamespace(returncode=1, stdout="")
        if command[1] == "is-active":
            return SimpleNamespace(returncode=0 if name in active else 3, stdout="")
        if command[1] == "is-enabled":
            return SimpleNamespace(returncode=0 if name in enabled else 1,
                                   stdout="enabled" if name in enabled else "disabled")
        raise AssertionError("unexpected command")
    return run


class PublicLegacySafetyTests(unittest.TestCase):
    def test_old_public_service_active_blocks(self):
        with patch.object(app.subprocess, "run",
                          side_effect=fake_runner(active=("evcc-battery-guard.service",))):
            self.assertIn("evcc-battery-guard.service", app._legacy_active())

    def test_old_public_service_enabled_blocks(self):
        with patch.object(app.subprocess, "run",
                          side_effect=fake_runner(enabled=("evcc-battery-guard.service",))):
            self.assertIn("evcc-battery-guard.service", app._legacy_active())

    def test_private_legacy_still_blocks(self):
        with patch.object(app.subprocess, "run",
                          side_effect=fake_runner(active=("mokka-battery-guard.service",))):
            self.assertIn("mokka-battery-guard.service", app._legacy_active())

    def test_no_legacy_allows(self):
        with patch.object(app.subprocess, "run", side_effect=fake_runner()):
            self.assertIsNone(app._legacy_active())


if __name__ == "__main__":
    unittest.main()
