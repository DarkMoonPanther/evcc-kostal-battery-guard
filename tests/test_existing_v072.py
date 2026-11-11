#!/usr/bin/env python3
"""0.7.2 offline regressions. No EVCC POST, KOSTAL or network calls."""
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import os
os.environ.setdefault("BCG_STATE_DIR", "/tmp/bcg-beta-unittest")
os.environ.setdefault("BCG_EVCC_API_URL", "http://127.0.0.1:7070/api")
os.environ.setdefault("BCG_VEHICLE_NAME", "db:999")
from battery_control_guard import recovery as rec, intelligent as ctrl
ROOT=Path(__file__).resolve().parents[1]
TZ=ZoneInfo("Europe/Berlin")

def lp(slot="07:00:00",goal=65,deadline="2026-11-05T06:00:00Z"):
    return {"vehicleName":"db:999","effectivePlanId":1,"effectivePlanTime":deadline,
            "effectivePlanSoc":goal,"planActive":True,"charging":True,
            "connected":True,"vehicleSoc":52,"mode":"smart","alwaysCharge":"off",
            "chargePower":9700,"vehicleClimaterActive":False,"minSocNotReached":False,
            "smartCostActive":False,"batteryBoost":False,
            "plan":[{"end":"2026-11-05T"+slot+"+01:00"}]}

def session(l,phase="battery",allocation=2.4862,spent=0.0895):
    return {"source":"plan","planId":1,"planTime":l["effectivePlanTime"],
        "planSoc":l["effectivePlanSoc"],
        "planKey":rec.stable_plan_identity({"loadpoints":[l]}),
        "phase":phase,"budgetKwh":allocation,"allowedTotalKwh":allocation,
        "spentKwh":spent,"lastSample":time.time()-5,"floorPct":10,
        "stopBy":time.time()+3600}

class ForecastIdentityTest(unittest.TestCase):
    def test_slots_recalculated_99sec_do_not_change_horizon(self):
        a=lp("07:00:00");b=lp("07:01:39")
        self.assertEqual(rec.stable_plan_identity({"loadpoints":[a]}),
                         rec.stable_plan_identity({"loadpoints":[b]}))
        self.assertEqual(rec.vehicle_pv_competition_until({"loadpoints":[a]}),
                         rec.vehicle_pv_competition_until({"loadpoints":[b]}))
        self.assertEqual(datetime.fromtimestamp(rec.vehicle_pv_competition_until({"loadpoints":[a]}),TZ).strftime("%H:%M"),"07:30")
    def test_far_overrun_never_underreserves_pv(self):
        a=lp("07:45:00")
        self.assertEqual(datetime.fromtimestamp(rec.vehicle_pv_competition_until({"loadpoints":[a]}),TZ).strftime("%H:%M"),"07:45")
    def test_user_goal_and_deadline_changes_invalidate(self):
        a=rec.stable_plan_identity({"loadpoints":[lp()]})
        self.assertNotEqual(a,rec.stable_plan_identity({"loadpoints":[lp(goal=85)]}))
        self.assertNotEqual(a,rec.stable_plan_identity({"loadpoints":[lp(deadline="2026-11-05T06:15:00Z")]}))
    def test_unidentifiable_active_plan_must_fail(self):
        p=lp();p["effectivePlanId"]=0
        with self.assertRaisesRegex(ValueError,"identity"):
            rec.vehicle_pv_competition_until({"loadpoints":[p]})
    def test_report_accepts_recalculation_rejects_real_plan_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=lp()
            tomorrow=(datetime.now(TZ).date()+timedelta(days=1) if datetime.now(TZ).hour>=16 else datetime.now(TZ).date())
            data={"schema":3,"version":"0.8.0-beta","mode":"observe_only","eligibleForControl":False,
                  "asOf":datetime.now(timezone.utc).isoformat(),
                  "targetDate":tomorrow.isoformat(),"batterySocPct":47,
                  "capacityKwh":20.0,"forecast":{
                      "planFingerprint":rec.stable_plan_identity({"loadpoints":[a]}),
                      "planPvCompetitionThrough":datetime.fromtimestamp(rec.vehicle_pv_competition_until({"loadpoints":[a]}),TZ).isoformat(),
                      "recoveryFound":True,"recoveryAt":datetime.combine(tomorrow,datetime.min.time(),TZ).replace(hour=23,minute=55).isoformat(),
                      "uncertaintyAllowanceKwh":0.0,
                      "budgetPolicy":"forecast_trough_minus_live_soc_floor_no_extra_kwh_margin","projectedTroughSocPct":42.58}}
            path=Path(tmp)/"forecast.json";path.write_text(json.dumps(data))
            state={"loadpoints":[lp("07:01:39")],"battery":{"soc":47,"capacity":20.0}}
            with patch.object(ctrl,"FORECAST",path):
                budget,_,_=ctrl.forecast(state,20.0,10)
                self.assertGreater(budget,0)
                state["loadpoints"]=[lp(goal=85)]
                with self.assertRaisesRegex(ValueError,"FORECAST_PLAN_CHANGED"):
                    ctrl.forecast(state,20.0,10)
                state["loadpoints"]=[lp("07:45:00")]
                with self.assertRaisesRegex(ValueError,"NOT_COVERED"):
                    ctrl.forecast(state,20.0,10)

class ControllerSessionTest(unittest.TestCase):
    def step(self,s,l,model=(2.243,40.85,0),battery=490,soc=47,car=9750):
        with patch.object(ctrl,"get_state",return_value={}),\
             patch.object(ctrl,"forecast",return_value=model) if not isinstance(model,Exception) else patch.object(ctrl,"forecast",side_effect=model),\
             patch.object(ctrl,"write_state"),patch.object(ctrl,"setstatus"),patch.object(ctrl,"log"):
            return ctrl.plan_step(s,l,soc,20.0,500,battery,car,0,1000,10)
    def test_forecast_failure_then_new_report_can_resume(self):
        l=lp();s=session(l)
        self.step(s,l,ValueError("FORECAST_PLAN_CHANGED"))
        self.assertEqual(s["phase"],"paused_forecast")
        self.step(s,l)
        self.assertEqual(s["phase"],"paused_forecast")
        s["pausedAt"]=time.time()-45
        self.step(s,l)
        self.assertEqual(s["phase"],"paused_forecast")
        s["validSince"]=time.time()-35
        self.step(s,l)
        self.assertEqual(s["phase"],"battery")
        self.assertLessEqual(s["allowedTotalKwh"],2.4862)
    def test_budget_shrinks_monotonically_no_double_spend(self):
        l=lp();s=session(l)
        self.step(s,l,(2.243,40,0))
        a=s["allowedTotalKwh"]
        self.assertLess(a,2.4862)
        self.step(s,l,(5.0,50,0))
        self.assertAlmostEqual(s["allowedTotalKwh"],a,places=5)
        self.assertEqual(s["phase"],"battery")
    def test_exhausted_cannot_resume_even_with_good_forecast(self):
        l=lp();s=session(l,spent=2.4862)
        self.step(s,l,(5.0,55,0))
        self.assertEqual(s["phase"],"exhausted")
        self.step(s,l,(5.0,55,0))
        self.assertEqual(s["phase"],"exhausted")
    def test_locked_cannot_resume(self):
        l=lp();s=session(l,phase="locked")
        self.step(s,l,(5.0,55,0))
        self.assertEqual(s["phase"],"locked")
    def test_climate_pauses_and_target_closes(self):
        l=lp();s=session(l);l["vehicleClimaterActive"]=True
        self.step(s,l)
        self.assertEqual(s["phase"],"paused_priority")
        l["vehicleSoc"]=65
        with patch.object(ctrl,"restore") as r:
            self.assertIsNone(self.step(s,l))
            r.assert_called_once()
    def test_plan_changed_closes_without_reallocating(self):
        l=lp();s=session(l);l["effectivePlanSoc"]=80
        with patch.object(ctrl,"restore") as r:
            self.assertIsNone(self.step(s,l))
            r.assert_called_once()
    def test_floor_change_locks(self):
        l=lp();s=session(l)
        with patch.object(ctrl,"get_state",return_value={}),patch.object(ctrl,"forecast",return_value=(5,55,0)),patch.object(ctrl,"write_state"),patch.object(ctrl,"setstatus"),patch.object(ctrl,"log"):
            ctrl.plan_step(s,l,47,20.0,500,490,9750,0,1000,15)
        self.assertEqual(s["phase"],"locked")
    def test_small_invalid_idle_meter_offset(self):
        l=lp();l.update(charging=False,chargePower=-31.289,planActive=False)
        state={"batteryDischargeControl":False,"batteryMode":"normal",
            "batteryGridChargeActive":False,"batteryGridDischargeActive":False,
            "bufferSoc":0,"bufferStartSoc":0,"homePower":500,
            "battery":{"soc":47,"capacity":20.0,"power":500,"devices":[{"minSoc":8}]},
            "pv":[{"power":0}],"grid":{"power":0},"loadpoints":[l]}
        self.assertEqual(ctrl.quality(state)[6],0)
        l["charging"]=True
        with self.assertRaisesRegex(ValueError,"invalid numeric metric"):
            ctrl.quality(state)
    def test_nightly_ledger_single_allocation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(ctrl,"LEDGER_DIR",Path(tmp)),patch.object(ctrl,"nightly_key",return_value="2026-11-04"):
            first=ctrl.allocate_night_budget({"source":"plan","budgetKwh":2.4862})
            second=ctrl.allocate_night_budget({"source":"plan","budgetKwh":2.4862})
            self.assertIsNotNone(first)
            self.assertIsNone(second)


class NoAdditionalMarginTest(unittest.TestCase):
    POLICY="forecast_trough_minus_live_soc_floor_no_extra_kwh_margin"
    def report_state(self, temp_path):
        local=datetime.now(TZ)
        target=(local.date()+timedelta(days=1) if local.hour>=16 else local.date())
        report={"schema":3,"version":"0.8.0-beta","mode":"observe_only",
            "eligibleForControl":False,"asOf":datetime.now(timezone.utc).isoformat(),
            "targetDate":target.isoformat(),"capacityKwh":20.0,"batterySocPct":42,
            "forecast":{
                "planFingerprint":None,"planPvCompetitionThrough":None,
                "recoveryFound":True,
                "recoveryAt":datetime.combine(target,datetime.min.time(),TZ).replace(hour=23,minute=30).isoformat(),
                "budgetPolicy":self.POLICY,"uncertaintyAllowanceKwh":0.0,
                "projectedTroughSocPct":40.0}}
        state={"loadpoints":[{"effectivePlanId":0,"planActive":False,"plan":None}],
               "battery":{"soc":42,"capacity":20.0}}
        temp_path.write_text(json.dumps(report))
        return report,state
    def test_zero_extra_kwh_margin_and_dynamic_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"report.json";report,state=self.report_state(path)
            with patch.object(ctrl,"FORECAST",path):
                budget10,_,_=ctrl.forecast(state,20.0,10)
                budget12,_,_=ctrl.forecast(state,20.0,12)
                self.assertAlmostEqual(budget10,(40.0-10)*20.0/100,places=6)
                self.assertAlmostEqual(budget12,(40.0-12)*20.0/100,places=6)
                self.assertAlmostEqual(budget10-budget12,.4,places=6)
                self.assertAlmostEqual(ctrl.forecast(state,20.0,45)[0],0,places=6)
    def test_legacy_margin_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"report.json";report,state=self.report_state(path)
            report["forecast"]["uncertaintyAllowanceKwh"]=3.3
            path.write_text(json.dumps(report))
            with patch.object(ctrl,"FORECAST",path):
                with self.assertRaisesRegex(ValueError,"EXTRA_KWH_MARGIN_NOT_ZERO"):
                    ctrl.forecast(state,20.0,10)
    def test_missing_policy_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"report.json";report,state=self.report_state(path)
            del report["forecast"]["budgetPolicy"]
            path.write_text(json.dumps(report))
            with patch.object(ctrl,"FORECAST",path):
                with self.assertRaisesRegex(ValueError,"BUDGET_POLICY_MISMATCH"):
                    ctrl.forecast(state,20.0,10)
    def test_synthetic_energy_budget_formula_no_extra_margin(self):
        # Public synthetic regression case; private historic forecast
        # snapshots are deliberately NOT included in this repository.
        trough_pct=40.0
        total_reserve_pct=10.0
        capacity_kwh=20.0
        legacy_extra_kwh_margin=3.3
        available=max(0,(trough_pct-total_reserve_pct)*capacity_kwh/100)
        historic_formula=max(0,available-legacy_extra_kwh_margin)
        self.assertAlmostEqual(available,6.0,places=6)
        self.assertAlmostEqual(historic_formula,2.7,places=6)
        self.assertAlmostEqual(available-historic_formula,3.3,places=6)

    def test_source_does_not_have_fixed_3_3_deduction(self):
        pred=(ROOT/"battery_control_guard/recovery.py").read_text()
        ctl=(ROOT/"battery_control_guard/intelligent.py").read_text()
        self.assertNotIn("ERROR_KWH = 3.3",pred)
        self.assertNotIn("-ERROR_KWH",pred)
        self.assertNotIn("num(f[\"uncertaintyAllowanceKwh\"],3",ctl)
        self.assertIn('"uncertaintyAllowanceKwh": 0.0',pred)
        self.assertIn('num(f["uncertaintyAllowanceKwh"],0,100)!=0',ctl)


if __name__=="__main__":unittest.main(verbosity=2)
