"""Battery Guard v0.4.0: offline-only regression tests; NO inverter/EVCC network calls."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "evcc-battery-guard.py"
spec = importlib.util.spec_from_file_location("evcc_battery_guard_v040", SOURCE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

def cfg():
    return mod.Config(
        armed=True, evcc_state_url="http://127.0.0.1:7070/api/state",
        kostal_host="192.0.2.10", kostal_port=1502, kostal_unit=71,
        poll_interval_s=15, refresh_interval_s=30, min_change_w=100,
        grid_margin_w=100, min_charge_power_w=500,
        min_soc_hysteresis_pct=0.5, state_coherence_w=500,
        readback_tolerance_w=50, max_reasonable_power_w=30000,
        http_timeout_s=3, modbus_timeout_s=3,
        state_dir=Path(tempfile.gettempdir()) / "evcc_guard_v040_offline_tests",
    )

def coherent():
    return {
        "apiReady": True, "batteryDischargeControl": False,
        "batteryMode": "normal", "homePower": 2000, "pvPower": 1500,
        "grid": {"power": 9700}, "battery": {"power": 500, "soc": 40},
        "loadpoints": [{"charging": True, "mode": "now", "chargePower": 9700}],
    }

def incoherent():
    state = coherent()
    state["grid"] = {"power": 26657}
    return state

class CoherenceTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(mod.VERSION, "0.4.0")

    def test_normal_coherent_does_not_refetch_or_wait(self):
        state = coherent()
        m = mod.metrics(state, cfg())
        with patch.object(mod, "fetch_evcc_state", side_effect=AssertionError("unexpected fetch")):
            with patch.object(mod.time, "sleep", side_effect=AssertionError("unexpected sleep")):
                actual_state, actual_m = mod.retry_incoherent_evcc_state(state, m, cfg())
        self.assertIs(actual_state, state)
        self.assertIs(actual_m, m)

    def test_not_guarded_does_not_refetch(self):
        state = incoherent()
        state["loadpoints"][0]["charging"] = False
        m = mod.metrics(state, cfg())
        self.assertFalse(m["guard_requested"])
        with patch.object(mod, "fetch_evcc_state", side_effect=AssertionError("unexpected fetch")):
            with patch.object(mod.time, "sleep", side_effect=AssertionError("unexpected sleep")):
                result, rm = mod.retry_incoherent_evcc_state(state, m, cfg())
        self.assertIs(result, state)
        self.assertFalse(rm["coherent"])

    def test_transient_16957w_difference_recovers_on_one_refetch(self):
        first = incoherent()
        m = mod.metrics(first, cfg())
        self.assertEqual(m["coherence_error"], 16957)
        fresh = coherent()
        with patch.object(mod, "fetch_evcc_state", return_value=fresh) as fetch:
            with patch.object(mod.time, "sleep") as sleep:
                state, new_m = mod.retry_incoherent_evcc_state(first, m, cfg())
        self.assertIs(state, fresh)
        self.assertTrue(new_m["coherent"])
        fetch.assert_called_once()
        sleep.assert_called_once_with(1.0)

    def test_persistent_mismatch_remains_incoherent(self):
        first = incoherent()
        second = incoherent()
        second["grid"]["power"] += 100
        with patch.object(mod, "fetch_evcc_state", return_value=second):
            with patch.object(mod.time, "sleep"):
                state, m = mod.retry_incoherent_evcc_state(first, mod.metrics(first, cfg()), cfg())
        self.assertIs(state, second)
        self.assertFalse(m["coherent"])
        self.assertEqual(m["coherence_error"], 17057)

    def test_retry_can_change_guard_request(self):
        first = incoherent()
        fresh = coherent()
        fresh["loadpoints"][0]["charging"] = False
        with patch.object(mod, "fetch_evcc_state", return_value=fresh):
            with patch.object(mod.time, "sleep"):
                state, m = mod.retry_incoherent_evcc_state(first, mod.metrics(first, cfg()), cfg())
        self.assertFalse(m["guard_requested"])

    def test_modbus_read_exception_has_address_and_count(self):
        bus = mod.ModbusTCP("192.0.2.10", 1502, 71, 3)
        with patch.object(bus, "_request", side_effect=mod.ModbusError("Modbus exception function=0x03 code=4")):
            with self.assertRaisesRegex(mod.ModbusError, r"function=0x03 code=4; read address=1042 count=2"):
                bus.read_holding(1042, 2)

    def test_modbus_read_success_unmodified(self):
        bus = mod.ModbusTCP("192.0.2.10", 1502, 71, 3)
        with patch.object(bus, "_request", return_value=bytes([3, 4, 0, 1, 0, 2])):
            self.assertEqual(bus.read_holding(1042, 2), [1, 2])

    def run_guard_once(self, instance, states, active_baseline=False):
        if active_baseline:
            instance.baseline = 9000
        def stop_after_poll(delay):
            if delay == instance.cfg.poll_interval_s:
                instance.stop_requested = True
        with patch.object(instance.kostal, "detect_byte_order", return_value=0), \
             patch.object(instance, "recover_session"), \
             patch.object(instance, "_clear_session"), \
             patch.object(instance, "write_limit") as write, \
             patch.object(mod, "fetch_evcc_state", side_effect=states) as fetch, \
             patch.object(mod.time, "sleep", side_effect=stop_after_poll):
            instance.run()
        return write, fetch

    def test_owner_change_during_retry_never_writes(self):
        instance = mod.Guard(cfg())
        second = coherent()
        second["batteryDischargeControl"] = True
        writes, fetch = self.run_guard_once(instance, [incoherent(), second], active_baseline=True)
        writes.assert_not_called()
        self.assertEqual(fetch.call_count, 2)

    def test_mode_conflict_during_retry_never_writes(self):
        instance = mod.Guard(cfg())
        second = coherent()
        second["batteryGridChargeActive"] = True
        writes, fetch = self.run_guard_once(instance, [incoherent(), second], active_baseline=True)
        writes.assert_not_called()
        self.assertEqual(fetch.call_count, 2)

    def test_persistent_incoherence_keeps_existing_zero_failsafe(self):
        instance = mod.Guard(cfg())
        writes, fetch = self.run_guard_once(instance, [incoherent(), incoherent()], active_baseline=True)
        writes.assert_called_once()
        self.assertEqual(writes.call_args.args[0], 0.0)
        self.assertEqual(fetch.call_count, 2)

    def test_second_fetch_failure_keeps_existing_zero_failsafe(self):
        instance = mod.Guard(cfg())
        ifetch = [incoherent(), RuntimeError("EVCC temporarily unavailable")]
        writes, fetch = self.run_guard_once(instance, ifetch, active_baseline=True)
        writes.assert_called_once()
        self.assertEqual(writes.call_args.args[0], 0.0)
        self.assertEqual(fetch.call_count, 2)

if __name__ == "__main__":
    unittest.main(verbosity=2)
