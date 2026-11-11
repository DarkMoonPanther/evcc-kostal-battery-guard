"""Physical floor freshness and independent legacy v0.6.2 parity regression."""
import json,os,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("BCG_STATE_DIR","/tmp/bcg-beta-unittest")
os.environ.setdefault("BCG_EVCC_API_URL","http://127.0.0.1:7070/api")
os.environ.setdefault("BCG_VEHICLE_NAME","db:999")
from battery_control_guard import decision,intelligent,shadow,protection
from test_integration_beta import base_state,cfg

LEGACY=Path(os.environ.get("BCG_PARITY_LEGACY_SOURCE", "/nonexistent/bcg-legacy-reference-not-shipped.py"))
HASH="19f01356a25a1c0727"

class FloorCacheTests(unittest.TestCase):
    def tearDown(self):decision.invalidate_kostal_min_soc()
    def test_absent_floor_rejects(self):
        decision.invalidate_kostal_min_soc()
        with self.assertRaisesRegex(RuntimeError,"missing or stale"):
            decision.get_kostal_min_soc()
    def test_expired_1042_is_not_used(self):
        decision.publish_kostal_min_soc(8.0,now=100.0)
        self.assertEqual(decision.get_kostal_min_soc(now=134.0),8.0)
        with self.assertRaisesRegex(RuntimeError,"missing or stale"):
            decision.get_kostal_min_soc(now=136.0)
    def test_invalid_1042_never_becomes_grant(self):
        for bad in (None,float("nan"),-1,101,True):
            with self.assertRaises(ValueError):decision.publish_kostal_min_soc(bad)
        with self.assertRaises(RuntimeError):decision.get_kostal_min_soc()
    def test_native_1042_and_evcc_min_respected_without_ha(self):
        decision.publish_kostal_min_soc(12.0)
        state=base_state(plan=True)
        with patch.object(intelligent,"read_floor",return_value=10.0):
            self.assertEqual(intelligent.read_effective_floor(state),12.0)
            state["battery"]["devices"][0]["minSoc"]=14.0
            self.assertEqual(intelligent.read_effective_floor(state),14.0)
        decision.invalidate_kostal_min_soc()
        with patch.object(intelligent,"read_floor",return_value=10.0):
            with self.assertRaisesRegex(RuntimeError,"missing or stale"):
                intelligent.read_effective_floor(state)

@unittest.skipUnless(LEGACY.exists(),"optional independent private legacy source not supplied")
class LegacyParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy,cls.policy,cls.hash=shadow.load_reference(LEGACY,HASH)
    def setUp(self):
        self.original_vehicle_name=os.environ.get("BCG_VEHICLE_NAME")
        os.environ["BCG_VEHICLE_NAME"]="demo-vehicle"
    def tearDown(self):
        if self.original_vehicle_name is None:
            os.environ.pop("BCG_VEHICLE_NAME",None)
        else:
            os.environ["BCG_VEHICLE_NAME"]=self.original_vehicle_name
    def test_legacy_source_hash_known(self):
        self.assertTrue(self.hash.startswith(HASH))
    def scenarios(self):
        a=base_state(plan=False)
        a["loadpoints"][0]["vehicleName"]="demo-vehicle"
        yield "now",a
        b=base_state(plan=True);b["loadpoints"][0]["vehicleName"]="demo-vehicle"
        yield "plan",b
        c=base_state(plan=False);c["loadpoints"][0].update(mode="smart",alwaysCharge="once",vehicleName="demo-vehicle")
        yield "once",c
        d=base_state(plan=False);d["loadpoints"][0].update(mode="smart",charging=False,chargePower=0)
        d["grid"]["power"]=1000
        d["homePower"]=2000
        yield "idle_smart",d
        e=base_state(plan=True);e["loadpoints"][0].update(vehicleClimaterActive=True,vehicleName="demo-vehicle")
        yield "hvac",e
    def test_same_state_compare_old_new_without_writes(self):
        config={"application":{"mode":"protection"}}
        for name,state in self.scenarios():
            with self.subTest(name=name):
                with patch.object(protection.ModbusTCP,"__init__",side_effect=AssertionError("No network Modbus")):
                    report=shadow.sample(config,self.legacy,type(self).policy,state)
                self.assertEqual(report["independentDifferences"],{})
                self.assertEqual(report["modbusWrites"],0)
                self.assertEqual(report["evccPosts"],0)
    def test_mismatched_vehicle_name_is_reported_not_hidden(self):
        os.environ["BCG_VEHICLE_NAME"]="another-evcc-vehicle"
        try:
            report=shadow.sample({"application":{"mode":"protection"}},self.legacy,type(self).policy,dict(base_state(plan=True),loadpoints=[dict(base_state(plan=True)["loadpoints"][0],vehicleName="demo-vehicle")]))
            self.assertIn("intelligent_plan",report["independentDifferences"])
        finally:
            os.environ["BCG_VEHICLE_NAME"]="demo-vehicle"

if __name__=="__main__":unittest.main()
