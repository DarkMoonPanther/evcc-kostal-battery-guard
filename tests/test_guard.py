"""Offline regression tests. Never connect to an inverter or EVCC."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("evcc_battery_guard", ROOT / "evcc-battery-guard.py")
guard = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)


def cfg(**updates):
    data = dict(
        armed=False, evcc_state_url="http://127.0.0.1:7070/api/state",
        kostal_host="192.0.2.10", kostal_port=1502, kostal_unit=71,
        poll_interval_s=5, refresh_interval_s=15, min_change_w=100,
        grid_margin_w=100, min_charge_power_w=500,
        min_soc_hysteresis_pct=0.5, state_coherence_w=500,
        readback_tolerance_w=50, max_reasonable_power_w=30000,
        http_timeout_s=3, modbus_timeout_s=3,
        state_dir=Path(tempfile.gettempdir()) / "guard-unittest-unused",
    )
    data.update(updates)
    return guard.Config(**data)


def sample_state(**lp_overrides):
    lp = dict(charging=True, mode="now", chargePower=9700)
    lp.update(lp_overrides)
    # grid + PV + battery - EV = household: 9700 + 1500 + 500 - 9700 = 2000
    return {
        "apiReady": True,
        "batteryDischargeControl": False,
        "homePower": 2000,
        "pvPower": 1500,
        "grid": {"power": 9700},
        "battery": {"power": 500, "soc": 40},
        "loadpoints": [lp],
    }


class ClassificationTests(unittest.TestCase):
    def test_fast_now(self):
        self.assertTrue(guard.protected_fast_charge(sample_state()["loadpoints"][0], cfg()))

    def test_plan(self):
        lp = sample_state(mode="pv", planActive=True)["loadpoints"][0]
        self.assertTrue(guard.protected_fast_charge(lp, cfg()))

    def test_smart_cost(self):
        lp = sample_state(mode="pv", smartCostActive=True)["loadpoints"][0]
        self.assertTrue(guard.protected_fast_charge(lp, cfg()))

    def test_min_soc(self):
        lp = sample_state(mode="pv", minSocNotReached=True)["loadpoints"][0]
        self.assertTrue(guard.protected_fast_charge(lp, cfg()))

    def test_normal_pv_not_guarded(self):
        lp = sample_state(mode="pv")["loadpoints"][0]
        self.assertFalse(guard.protected_fast_charge(lp, cfg()))

    def test_not_charging(self):
        lp = sample_state(charging=False)["loadpoints"][0]
        self.assertFalse(guard.protected_fast_charge(lp, cfg()))

    def test_low_charge_power(self):
        lp = sample_state(chargePower=100)["loadpoints"][0]
        self.assertFalse(guard.protected_fast_charge(lp, cfg()))


class MeterTests(unittest.TestCase):
    def test_balanced_measurements_and_limit_input(self):
        m = guard.metrics(sample_state(), cfg())
        self.assertTrue(m["coherent"])
        self.assertEqual(m["coherence_error"], 0)
        self.assertEqual(m["home"], 2000)
        self.assertEqual(m["pv"], 1500)
        self.assertEqual(max(0, m["home"] - m["pv"] - cfg().grid_margin_w), 400)
        self.assertTrue(m["guard_requested"])

    def test_incoherent_state(self):
        state = sample_state()
        state["homePower"] = 1000
        self.assertFalse(guard.metrics(state, cfg())["coherent"])

    def test_invalid_soc(self):
        state = sample_state()
        state["battery"]["soc"] = 101
        with self.assertRaises(RuntimeError):
            guard.metrics(state, cfg())

    def test_battery_array_rejected_for_soc(self):
        state = sample_state()
        state["battery"] = [state["battery"]]
        with self.assertRaises(RuntimeError):
            guard.metrics(state, cfg())


class ModbusCodecTests(unittest.TestCase):
    def test_float_roundtrip_both_word_orders(self):
        inverter = guard.Kostal(cfg())
        for order in (0, 1):
            inverter.byte_order = order
            for value in (0.0, 1.0, 500.0, 9700.0):
                with self.subTest(order=order, value=value):
                    self.assertAlmostEqual(inverter.decode_float(inverter.encode_float(value)), value)

    def test_different_encodings(self):
        inverter = guard.Kostal(cfg())
        inverter.byte_order = 0
        swapped = inverter.encode_float(500.0)
        inverter.byte_order = 1
        normal = inverter.encode_float(500.0)
        self.assertEqual(swapped, list(reversed(normal)))


class SafetyTests(unittest.TestCase):
    def test_unarmed_no_reads_or_writes(self):
        instance = guard.Guard(cfg(armed=False))
        with patch.object(instance.kostal, "detect_byte_order", side_effect=AssertionError("inverter contacted")):
            self.assertEqual(instance.run(), 0)

    def test_min_soc_hysteresis(self):
        instance = guard.Guard(cfg())
        self.assertFalse(instance.min_soc_allows_discharge(8, 8))
        self.assertFalse(instance.min_soc_allows_discharge(8.49, 8))
        self.assertTrue(instance.min_soc_allows_discharge(8.5, 8))

    def test_relinquish_does_not_write(self):
        instance = guard.Guard(cfg())
        instance.baseline = 4000
        with patch.object(instance.kostal, "write_float", side_effect=AssertionError("write attempted")):
            with patch.object(instance, "_clear_session"):
                instance.relinquish("test")
        self.assertIsNone(instance.baseline)

    def test_public_default_no_lan_device(self):
        with patch.dict(os.environ, {"KOSTAL_HOST": "192.0.2.10", "ARMED": "false"}, clear=False):
            self.assertFalse(guard.Config.from_env().armed)
        # Test source default via direct source inspection, not by contacting host.
        source = (ROOT / "evcc-battery-guard.py").read_text()
        self.assertNotIn("192.168.", source)


if __name__ == "__main__":
    unittest.main()
