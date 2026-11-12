"""Offline checks for the optional Home Assistant front end."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "frontend/battery-control-guard-card.js").read_text(encoding="utf-8")
INSTALLER = (ROOT / "scripts/install_ha_ui.sh").read_text(encoding="utf-8")

class HomeAssistantFrontendTests(unittest.TestCase):
    def test_status_schema_and_freshness(self):
        self.assertIn("function validStatus", UI)
        self.assertIn("function validForecast", UI)
        self.assertIn("eligibleForControl!==false", UI)
        self.assertIn("created>=now-60000", UI)
    def test_frontend_no_vehicle_inverter_control(self):
        self.assertNotIn("fetch('/api/state'", UI)
        self.assertNotIn("sensor.mokka_", UI)
        self.assertNotIn("weather.forecast_wolsdorf", UI)
        self.assertNotIn("192.168.", UI)
        self.assertIn("customElements.define('battery-control-guard-card'", UI)
    def test_reserve_helper_is_optional(self):
        self.assertIn("input_number", UI)
        self.assertIn("this.entities.reserve", UI)
        self.assertIn("reserveInput.disabled", UI)
    def test_installer_stages_inactive_timer(self):
        self.assertIn("DRY RUN", INSTALLER)
        self.assertIn("NOT activated", INSTALLER)
        self.assertIn("Refuse symlink", INSTALLER)
        self.assertNotIn("systemctl start battery-control-guard.service", INSTALLER)

if __name__ == "__main__":
    unittest.main()
