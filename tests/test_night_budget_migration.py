"""Migration keeps actual allocation; never reissues a previously allotted night."""
import json,tempfile,unittest,os
os.environ.setdefault("BCG_EVCC_API_URL","http://127.0.0.1:7070/api")
os.environ.setdefault("BCG_STATE_DIR","/tmp/bcg-beta-tests")
from pathlib import Path
from unittest.mock import patch
from battery_control_guard import migrate,intelligent

class NightBudgetMigration(unittest.TestCase):
    def make_old(self,tmp,allocation=2.4862):
        old=Path(tmp)/"old"
        p=old/migrate.LEGACY_LEDGER/"2026-11-07.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"date":"2026-11-07","allocatedKwh":allocation,
                                 "lastSource":"plan","policy":"dynamic_forecast_once_per_night"}))
        return old,p
    def test_no_second_allocation_after_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            old,_=self.make_old(tmp)
            target=Path(tmp)/"new"
            migrate.prepare(target,old)
            self.assertEqual(migrate.validate_marker(target)["ledgerCount"],1)
            proposal={"source":"plan","budgetKwh":8.5}
            with patch.object(intelligent,"LEDGER_DIR",target/migrate.LEDGER),\
                 patch.object(intelligent,"nightly_key",return_value="2026-11-07"):
                self.assertIsNone(intelligent.allocate_night_budget(proposal))
                self.assertIsNone(intelligent.allocate_night_budget(proposal))
    def test_migrated_zero_kwh_ledger_stays_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            old,_=self.make_old(tmp,allocation=0)
            target=Path(tmp)/"new"
            migrate.prepare(target,old)
            p=target/migrate.LEDGER/"2026-11-07.json"
            before=p.read_bytes()
            with patch.object(intelligent,"LEDGER_DIR",target/migrate.LEDGER),\
                 patch.object(intelligent,"nightly_key",return_value="2026-11-07"):
                self.assertIsNone(intelligent.allocate_night_budget(
                    {"source":"plan","budgetKwh":5.0}))
            self.assertEqual(p.read_bytes(),before)
            migrate.validate_marker(target)

    def test_migrated_ledger_tampering_blocks_active_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            old,_=self.make_old(tmp)
            target=Path(tmp)/"new"
            migrate.prepare(target,old)
            p=target/migrate.LEDGER/"2026-11-07.json"
            raw=json.loads(p.read_text());raw["allocatedKwh"]=0
            p.write_text(json.dumps(raw))
            with self.assertRaisesRegex(RuntimeError,"modified or missing"):
                migrate.validate_marker(target)
    def test_bad_legacy_budget_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            old,p=self.make_old(tmp,allocation=-1)
            target=Path(tmp)/"new"
            with self.assertRaisesRegex(RuntimeError,"Invalid persisted"):
                migrate.prepare(target,old)
            self.assertFalse((target/migrate.MARKER).exists())
    def test_original_state_is_never_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            old,oldfile=self.make_old(tmp)
            original_bytes=oldfile.read_bytes()
            target=Path(tmp)/"new"
            migrate.prepare(target,old)
            self.assertEqual(oldfile.read_bytes(),original_bytes)

if __name__=="__main__":unittest.main()
