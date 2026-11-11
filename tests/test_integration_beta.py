"""Safety regressions: pure functions, no network, no KOSTAL writes."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("BCG_STATE_DIR","/tmp/bcg-beta-unittest")
os.environ.setdefault("BCG_EVCC_API_URL","http://127.0.0.1:7070/api")
os.environ.setdefault("BCG_VEHICLE_NAME","db:999")

from battery_control_guard import decision, protection, app, intelligent

def cfg():
    return protection.Config(
        armed=False,evcc_state_url="http://127.0.0.1:7070/api/state",
        kostal_host="198.51.100.100",kostal_port=1502,kostal_unit=71,
        poll_interval_s=15,refresh_interval_s=30,min_change_w=100,
        grid_margin_w=100,min_charge_power_w=500,min_soc_hysteresis_pct=.5,
        state_coherence_w=500,readback_tolerance_w=50,
        max_reasonable_power_w=30000,http_timeout_s=3,
        modbus_timeout_s=3,state_dir=Path(tempfile.gettempdir())/"bcg_test")
def base_state(plan=False):
    lp={"charging":True,"mode":"smart" if plan else "now",
        "chargePower":9700,"alwaysCharge":"off",
        "planActive":plan,"effectivePlanId":1 if plan else 0,
        "effectivePlanTime":"2026-11-08T06:00:00+01:00" if plan else None,
        "vehicleName":"db:999","vehicleClimaterActive":False,
        "minSocNotReached":False,"smartCostActive":False,"batteryBoost":False}
    # grid + PV + battery - car = 10700 + 500 + 500 - 9700 = 2000
    return {"batteryDischargeControl":False,"batteryMode":"normal",
            "homePower":2000,"pv":[{"power":500}],
            "grid":{"power":10700},
            "battery":{"power":500,"soc":50,"devices":[{"minSoc":8}]},
            "loadpoints":[lp]}
def status(now=None,source="plan",permitted=True,plan_id=1):
    now=time.time() if now is None else now
    return {"schema":1,"phase":"battery" if permitted else "grid",
            "permitted":permitted,"updatedAt":now,"expiresAt":now+9,
            "source":source,"planId":plan_id,
            "planTime":"2026-11-08T06:00:00+01:00",
            "totalFloorPct":10}

class ProtectionDecision(unittest.TestCase):
    def tearDown(self):decision.clear()
    def test_fast_protection_never_uses_intelligence(self):
        state=base_state(False);m=protection.metrics(state,cfg())
        decision.publish(status())
        value,reason=decision.compute_target(m,state,cfg(),8,7359,decision.snapshot())
        self.assertEqual(value,1400);self.assertEqual(reason,"classic")
    def test_plan_without_permission_house_only(self):
        state=base_state(True);m=protection.metrics(state,cfg())
        self.assertTrue(m["intelligent_plan"])
        value,reason=decision.compute_target(m,state,cfg(),8,7359,None)
        self.assertEqual(value,1400)
        self.assertIn("missing",reason)
    def test_plan_valid_lease_expands_only_to_existing_baseline(self):
        state=base_state(True);m=protection.metrics(state,cfg())
        decision.publish(status())
        value,reason=decision.compute_target(m,state,cfg(),8,7359,decision.snapshot())
        self.assertEqual(value,7359)
        self.assertIn("authorized",reason)
    def test_wrong_plan_id_denied(self):
        state=base_state(True);m=protection.metrics(state,cfg())
        decision.publish(status(plan_id=2))
        self.assertEqual(decision.compute_target(m,state,cfg(),8,7359,decision.snapshot())[0],1400)
    def test_expired_lease_denied(self):
        decision.publish(status(now=time.time()-40))
        self.assertIsNone(decision.snapshot())
    def test_false_permission_denied(self):
        state=base_state(True);m=protection.metrics(state,cfg())
        decision.publish(status(permitted=False))
        self.assertEqual(decision.compute_target(m,state,cfg(),8,7359,decision.snapshot())[0],1400)
    def test_soc_hard_floor_stops(self):
        state=base_state(True);state["battery"]["soc"]=10
        m=protection.metrics(state,cfg())
        decision.publish(status())
        value,_=decision.compute_target(m,state,cfg(),8,7359,decision.snapshot())
        self.assertEqual(value,0)
    def test_ha_evcc_kostal_floor_takes_maximum(self):
        state=base_state(True)
        self.assertEqual(decision.floor_with_limits(12,state,10),12)
        self.assertEqual(decision.floor_with_limits(8,state,15),15)
    def test_bad_min_soc_blocks(self):
        state=base_state(True);state["battery"]["devices"][0]["minSoc"]=float("nan")
        with self.assertRaises(RuntimeError):decision.floor_with_limits(8,state,10)
    def test_controller_publication_is_ephemeral(self):
        intelligent.setstatus("battery",True,totalFloorPct=10,source="plan",
                              planId=1,planTime=status()["planTime"])
        self.assertTrue(decision.snapshot()["permitted"])
        intelligent.setstatus("grid",False,totalFloorPct=10)
        self.assertIsNone(decision.snapshot())

class AppSafety(unittest.TestCase):
    def test_observe_does_not_instantiate_modbus_or_write_evcc(self):
        c={"application":{"mode":"protection"}}
        with patch.object(protection.ModbusTCP,"__init__",side_effect=AssertionError("Modbus opened")),\
             patch.object(intelligent,"post",side_effect=AssertionError("EVCC POST")):
            result=app._observe(c,base_state(False))
        self.assertEqual(result["modbusWrites"],0)
        self.assertEqual(result["evccPosts"],0)
        self.assertTrue(result["measurementsCoherent"])
    def test_run_never_arms_when_legacy_active(self):
        c={"application":{"mode":"protection","execution":"active","armed":True}}
        with patch.object(app,"_legacy_active",return_value="old writer active"):
            with self.assertRaisesRegex(RuntimeError,"WRITE LOCKOUT"):app.active(c)
    def test_run_refuses_without_explicit_arming(self):
        for settings in ({"execution":"observe","armed":True},{"execution":"active","armed":False}):
            c={"application":{"mode":"protection",**settings}}
            with self.assertRaisesRegex(app.ConfigurationError,"Refusing"):app.active(c)
    def test_replay_pure(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"replay.json"
            source.write_text(json.dumps([{"evcc":base_state(False),"expectHomeTargetW":1400}]))
            with patch.object(protection.ModbusTCP,"__init__",side_effect=AssertionError("No Modbus")):
                self.assertEqual(app.replay({"application":{"mode":"protection"}},source),0)
    def test_config_rejects_unknown_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"config.toml"
            p.write_text('[application]\nmode="protection"\nstate_dir="/tmp/bcg"\n[evcc]\nstate_url="http://127.0.0.1:7070/api/state"\n[danger]\nx=3\n')
            with self.assertRaisesRegex(app.ConfigurationError,"Unknown"):app.load_config(p)

if __name__=="__main__":unittest.main()
