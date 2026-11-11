"""HA v0.8.0 bridge: no control access; strict freshness and schema."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime,timezone,timedelta

from battery_control_guard import public

BRIDGE=Path(__file__).resolve().parents[1] / "scripts" / "ha_status_export.py"
spec=importlib.util.spec_from_file_location("bcg_ha_bridge_testable",BRIDGE)
bridge=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

def nowiso(delta=0):
    return (datetime.now(timezone.utc)+timedelta(seconds=delta)).isoformat()

class PublicExportTests(unittest.TestCase):
    def test_whitelisted_status_atomic_and_publicly_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(public,"PUBLIC_DIR",Path(tmp)):
                self.assertTrue(public.publish("status-intelligent.json",
                                               {"schema":1,"version":"0.8.0-beta"}))
                p=Path(tmp)/"status-intelligent.json"
                self.assertEqual(json.loads(p.read_text())["version"],"0.8.0-beta")
                self.assertTrue(bool(p.stat().st_mode & stat.S_IROTH))
                self.assertEqual(list(Path(tmp).glob(".*tmp")),[])
    def test_secret_or_unapproved_name_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(public,"PUBLIC_DIR",Path(tmp)):
                with self.assertRaises(ValueError):
                    public.publish("ha-authorization-header",{"token":"secret"})
    def test_symlink_export_target_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=Path(tmp)
            (t/"status-intelligent.json").symlink_to(t/"nowhere")
            with patch.object(public,"PUBLIC_DIR",t):
                with self.assertRaisesRegex(RuntimeError,"symlink"):
                    public.publish("status-intelligent.json",{"schema":1})
    def test_no_runtime_directory_returns_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(public,"PUBLIC_DIR",Path(tmp)/"missing"):
                self.assertFalse(public.publish("status-intelligent.json",{"schema":1}))

class HABridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p=Path(self.tmp.name)
        self.src=p/"src";self.dst=p/"dst"
        self.src.mkdir();self.dst.mkdir()
        self.a=patch.object(bridge,"SRC",self.src);self.b=patch.object(bridge,"DST",self.dst)
        self.a.start();self.b.start()
        self.addCleanup(self.a.stop);self.addCleanup(self.b.stop)
    def write(self,name,obj):
        (self.src/name).write_text(json.dumps(obj))
    def sample_status(self,**kw):
        o={"schema":1,"version":"0.8.0-beta","generatedAt":nowiso(),
           "validUntil":nowiso(35),"permissionActive":False,
           "haReservePct":10,"reasonCode":"WAITING_FOR_EVCC_CHARGING"}
        o.update(kw)
        return o
    def sample_forecast(self,**kw):
        o={"schema":3,"version":"0.8.0-beta","asOf":nowiso(),
           "mode":"observe_only","eligibleForControl":False,
           "forecast":{"recoveryAt":nowiso(20000)}}
        o.update(kw)
        return o
    def test_status_copy_and_drop_extra_unrecognized_field(self):
        self.write("status-intelligent.json",
                   self.sample_status(secrettoken="should-not-export"))
        x=bridge.validated("status-intelligent.json",1,time.time())
        self.assertNotIn("secrettoken",x)
        bridge.publish("guard-v070-status.json",x)
        copied=json.loads((self.dst/"guard-v070-status.json").read_text())
        self.assertEqual(copied["haReservePct"],10)
        self.assertEqual(copied["reasonCode"],"WAITING_FOR_EVCC_CHARGING")
    def test_stale_status_denied(self):
        self.write("status-intelligent.json",self.sample_status(
            generatedAt=nowiso(-80),validUntil=nowiso(-15)))
        with self.assertRaisesRegex(ValueError,"stale"):
            bridge.validated("status-intelligent.json",1,time.time())
    def test_invalid_future_status_denied(self):
        self.write("status-intelligent.json",self.sample_status(generatedAt=nowiso(500)))
        with self.assertRaisesRegex(ValueError,"stale"):
            bridge.validated("status-intelligent.json",1,time.time())
    def test_wrong_version_denied(self):
        self.write("status-intelligent.json",self.sample_status(version="0.7.2"))
        with self.assertRaisesRegex(ValueError,"schema/version"):
            bridge.validated("status-intelligent.json",1,time.time())
    def test_forecast_must_be_observe_only(self):
        self.write("forecast.json",self.sample_forecast(eligibleForControl=True))
        with self.assertRaisesRegex(ValueError,"unsafe"):
            bridge.validated("forecast.json",3,time.time())
    def test_fresh_observe_forecast_valid(self):
        self.write("forecast.json",self.sample_forecast())
        x=bridge.validated("forecast.json",3,time.time())
        self.assertEqual(x["version"],"0.8.0-beta")
    def test_symlink_source_denied(self):
        p=self.src/"status-intelligent.json"
        outside=Path(self.tmp.name)/"elsewhere"
        outside.write_text(json.dumps(self.sample_status()))
        p.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,"symlink"):
            bridge.validated("status-intelligent.json",1,time.time())
    def test_symlink_destination_denied(self):
        target=Path(self.tmp.name)/"target"
        target.write_text("no change")
        (self.dst/"guard-v070-status.json").symlink_to(target)
        with self.assertRaisesRegex(RuntimeError,"symlink"):
            bridge.publish("guard-v070-status.json",self.sample_status())
        self.assertEqual(target.read_text(),"no change")
    def test_inactive_root_unit_writes_nothing(self):
        self.write("status-intelligent.json",self.sample_status())
        with patch.object(bridge.subprocess,"run") as sp:
            sp.return_value.returncode=3
            bridge.main()
        self.assertFalse((self.dst/"guard-v070-status.json").exists())
    def test_active_root_unit_publishes_both_with_correct_version(self):
        self.write("status-intelligent.json",self.sample_status())
        self.write("forecast.json",self.sample_forecast())
        with patch.object(bridge.subprocess,"run") as sp:
            sp.return_value.returncode=0
            bridge.main()
        self.assertEqual(json.loads((self.dst/"guard-v070-status.json").read_text())["version"],"0.8.0-beta")
        self.assertEqual(json.loads((self.dst/"guard-recovery-v072.json").read_text())["version"],"0.8.0-beta")

if __name__=="__main__":
    unittest.main(verbosity=2)
