"""v0.8.0: no autonomous EVCC start; fail-closed KOSTAL readiness and writer lock."""
import dataclasses
import json
import os
from datetime import datetime
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault("BCG_STATE_DIR","/tmp/bcg-beta-unittest")
os.environ.setdefault("BCG_EVCC_API_URL","http://127.0.0.1:7070/api")
os.environ.setdefault("BCG_VEHICLE_NAME","db:999")

from battery_control_guard import app,intelligent as ctrl,protection,decision

class FixedDateTime(datetime):
    @classmethod
    def now(cls,tz=None):
        return datetime(2026,11,9,21,15,tzinfo=tz)

def state(*,connected=True,charging=False,once="off",mode="smart",plan=False):
    c=1380 if charging else 0
    return {
        "batteryDischargeControl":False,"batteryMode":"normal",
        "bufferSoc":0,"bufferStartSoc":0,"optimizerAutomatic":False,
        "homePower":500,"pv":[{"power":0}],"grid":{"power":380+c-1380},
        "battery":{"soc":72,"capacity":20.0,"power":1500,"devices":[{"minSoc":8}]},
        "loadpoints":[{
            "connected":connected,"charging":charging,"mode":mode,
            "chargePower":c,"alwaysCharge":once,"vehicleName":"db:999",
            "vehicleSoc":73,"effectiveLimitSoc":80,"planActive":plan,
            "effectivePlanId":1 if plan else 0,
            "effectivePlanTime":"2026-11-10T05:30:00+01:00" if plan else None,
            "vehicleClimaterActive":False,"minSocNotReached":False,
            "smartCostActive":False,"batteryBoost":False,
        }]
    }

class PassiveChargeTests(unittest.TestCase):
    def eligible(self,s):
        with tempfile.TemporaryDirectory() as td:
            forecast=Path(td)/"forecast.json"
            forecast.write_text(json.dumps({"forecast":{"recoveryAt":"2026-11-10T12:00:00+01:00"}}))
            with patch.object(ctrl,"FORECAST",forecast),\
                 patch.object(ctrl,"datetime",FixedDateTime),\
                 patch.object(ctrl,"forecast",return_value=(4.625,36.04,20)):
                return ctrl.eligible(s,10)

    def test_plugged_idle_never_qualifies(self):
        self.assertIsNone(self.eligible(state()))
        self.assertIsNone(self.eligible(state(once="once")))
    def test_ordinary_smart_pv_even_if_charging_never_qualifies(self):
        self.assertIsNone(self.eligible(state(charging=True)))
    def test_fast_charge_even_if_active_never_qualifies_for_intelligent_budget(self):
        self.assertIsNone(self.eligible(state(charging=True,mode="now",once="once")))
    def test_only_existing_smart_minimum_charge_qualifies(self):
        proposal=self.eligible(state(charging=True,once="once"))
        self.assertEqual(proposal["source"],"once")
        self.assertEqual(proposal["budgetKwh"],4.625)
    def test_wrong_vehicle_and_missing_car_never_qualify(self):
        s=state(charging=True,once="once");s["loadpoints"][0]["vehicleName"]="other"
        self.assertIsNone(self.eligible(s))
        s=state(charging=True,once="once");s["loadpoints"][0]["chargePower"]=0
        s["grid"]["power"]=-1000  # keep EVCC meter identity coherent
        self.assertIsNone(self.eligible(s))
    def test_no_network_write_even_when_restoring_session(self):
        with tempfile.TemporaryDirectory() as td:
            status=Path(td)/"intelligent-session.json"
            status.write_text('{"source":"once","spentKwh":1.2}')
            with patch.object(ctrl,"STATE",status),\
                 patch.object(ctrl,"post",side_effect=AssertionError("EVCC command forbidden")):
                ctrl.restore({"source":"once","spentKwh":1.2},"BUDGET_SPENT")
            self.assertFalse(status.exists())
    def test_no_autostart_message_or_post_call_in_core(self):
        source=Path(ctrl.__file__).read_text()
        self.assertNotIn('assert post(',source)
        self.assertNotIn('post(f"/loadpoints/',source)
        with self.assertRaisesRegex(RuntimeError,"commands forbidden"):
            ctrl.post("/loadpoints/1/alwayscharge/once")
    def test_existing_once_permission_is_bound_to_exact_vehicle(self):
        from tests.test_integration_beta import cfg
        s=state(charging=True,once="once")
        p={"source":"once","floor":10,"permitted":True,"planId":None,"planTime":None}
        m=protection.metrics(s,cfg())
        self.assertEqual(decision.compute_target(m,s,cfg(),8,7359,p)[0],1780)
        s["loadpoints"][0]["vehicleName"]="different"
        m=protection.metrics(s,cfg())
        self.assertEqual(decision.compute_target(m,s,cfg(),8,7359,p)[0],400)
    def test_fixed_backup_reserve_is_ten_when_ha_unconfigured(self):
        with patch.object(ctrl,"HA_RESERVE_ENTITY",""),\
             patch.dict(os.environ,{"BCG_FIXED_RESERVE_SOC_PCT":"10"}):
            self.assertEqual(ctrl.read_floor(),10)

class SingleWriterAndReadiness(unittest.TestCase):
    def tearDown(self):
        decision.invalidate_kostal_min_soc()
    def test_second_process_instance_lock_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with app.exclusive_writer_lock(td):
                with self.assertRaisesRegex(RuntimeError,"WRITE LOCKOUT"):
                    with app.exclusive_writer_lock(td):
                        pass
            with app.exclusive_writer_lock(td):
                pass
    def test_symlink_instance_lock_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            (p/"instance.lock").symlink_to(p/"outside.txt")
            with self.assertRaises(OSError):
                with app.exclusive_writer_lock(td):
                    pass
    def guard(self):
        from tests.test_integration_beta import cfg
        c=dataclasses.replace(cfg(),armed=True)
        return protection.Guard(c)
    def exercise(self,good_floor):
        guard=self.guard()
        decision.invalidate_kostal_min_soc()
        evcc=state()
        def stopping_sleep(_):
            guard.stop_requested=True
        def read_float(reg):
            if not good_floor:raise RuntimeError("1042 read error")
            self.assertEqual(reg,protection.REG_MIN_SOC)
            return 8.0
        with patch.object(guard.kostal,"detect_byte_order",return_value=0),\
             patch.object(guard.kostal,"read_float",side_effect=read_float),\
             patch.object(guard,"recover_session"),\
             patch.object(protection,"fetch_evcc_state",return_value=evcc),\
             patch.object(protection,"metrics",return_value={"coherent":True,"guard_requested":False,"intelligent_once":False,"battery_boost":False}),\
             patch.object(protection.time,"sleep",side_effect=stopping_sleep):
            guard.run()
        return guard.ready_event.is_set()
    def test_guard_signals_ready_after_verified_1042_and_coherent_evcc(self):
        self.assertTrue(self.exercise(True))
    def test_guard_refuses_readiness_without_verified_1042(self):
        self.assertFalse(self.exercise(False))

if __name__=="__main__":
    unittest.main(verbosity=2)
