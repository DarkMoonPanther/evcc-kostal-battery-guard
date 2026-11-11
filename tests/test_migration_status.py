"""Migration, monitoring, and live writer preflight tests. No hardware access."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
os.environ.setdefault("BCG_STATE_DIR","/tmp/bcg-beta-unittest")
os.environ.setdefault("BCG_EVCC_API_URL","http://127.0.0.1:7070/api")
from battery_control_guard import app,decision,migrate,status

class MigrationTests(unittest.TestCase):
    def test_fresh_requires_empty_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"new"
            marker=migrate.prepare(dest,fresh=True)
            self.assertEqual(marker["strategy"],"fresh")
            self.assertEqual(migrate.validate_marker(dest)["strategy"],"fresh")
            with self.assertRaises(RuntimeError):migrate.prepare(dest,fresh=True)
    def test_migrated_ledger_and_session_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/"old";dest=Path(tmp)/"new"
            ledger=old/migrate.LEGACY_LEDGER;ledger.mkdir(parents=True)
            (ledger/"2026-11-07.json").write_text(json.dumps({"date":"2026-11-07","allocatedKwh":3.5,"lastSource":"plan"}))
            sess=old/migrate.LEGACY_SESSION;sess.parent.mkdir(parents=True,exist_ok=True)
            sess.write_text(json.dumps({"source":"plan","spentKwh":2.5}))
            result=migrate.prepare(dest,old)
            self.assertEqual(result["ledgerCount"],1)
            self.assertEqual(json.loads((dest/migrate.LEDGER/"2026-11-07.json").read_text())["allocatedKwh"],3.5)
            self.assertEqual(json.loads((dest/migrate.SESSION).read_text())["spentKwh"],2.5)
            self.assertTrue(sess.exists()) # old state untouched
    def test_no_old_ledger_refuses_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):migrate.prepare(Path(tmp)/"new",Path(tmp)/"old")
    def test_fresh_refuses_existing_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp);p=dest/migrate.SESSION;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('{"spentKwh":0.5}')
            with self.assertRaises(RuntimeError):migrate.prepare(dest,fresh=True)

class StatusTests(unittest.TestCase):
    def test_summary_never_mints_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=os.environ["BCG_STATE_DIR"];os.environ["BCG_STATE_DIR"]=tmp
            try:
                decision.clear()
                guard=MagicMock(baseline=None,last_target=None,last_reason=None)
                state=status.snapshot("protection",guard)
                self.assertFalse(state["intelligent"]["permissionActive"])
                self.assertIsNone(decision.snapshot())
                self.assertFalse(state["protection"]["active"])
            finally:os.environ["BCG_STATE_DIR"]=old
    def test_active_intelligence_requires_migration_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            c={"application":{"mode":"intelligent","armed":True,"execution":"active","state_dir":tmp}}
            with patch.object(app,"_legacy_active",return_value=None):
                with self.assertRaisesRegex(RuntimeError,"Migration acknowledgement missing"):
                    app.active(c)

if __name__=="__main__":unittest.main()
