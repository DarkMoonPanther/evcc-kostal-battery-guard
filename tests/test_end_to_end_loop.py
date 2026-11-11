"""Complete protection loop against an isolated fake inverter, never real KOSTAL."""
import os, socketserver, tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_modbus_loopback import FakeHandler,FakeState
from test_integration_beta import base_state,status
from battery_control_guard import decision,protection

class GuardLoopSimulation(unittest.TestCase):
    def setUp(self):
        self.old_vehicle=os.environ.get("BCG_VEHICLE_NAME")
        os.environ["BCG_VEHICLE_NAME"]="db:999"
        self.temp=tempfile.TemporaryDirectory()
        self.server=socketserver.ThreadingTCPServer(("127.0.0.1",0),FakeHandler)
        self.server.daemon_threads=True
        self.server.state=FakeState()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.cfg=protection.Config(
          armed=True,evcc_state_url="http://127.0.0.1:7070/api/state",
          kostal_host="127.0.0.1",kostal_port=self.server.server_address[1],
          kostal_unit=71,poll_interval_s=15,refresh_interval_s=30,
          min_change_w=100,grid_margin_w=100,min_charge_power_w=500,
          min_soc_hysteresis_pct=0.5,state_coherence_w=500,
          readback_tolerance_w=50,max_reasonable_power_w=30000,
          http_timeout_s=3,modbus_timeout_s=2,state_dir=Path(self.temp.name))
    def tearDown(self):
        decision.clear()
        decision.invalidate_kostal_min_soc()
        self.server.shutdown();self.server.server_close();self.thread.join(3)
        self.temp.cleanup()
        if self.old_vehicle is None:os.environ.pop("BCG_VEHICLE_NAME",None)
        else:os.environ["BCG_VEHICLE_NAME"]=self.old_vehicle
    def run_sequence(self,states,skip_retry=False):
        guard=protection.Guard(self.cfg)
        n=[0]
        def sleep(_):
            n[0]+=1
            if n[0]>=len(states):guard.stop_requested=True
        patches=[patch.object(protection,"fetch_evcc_state",side_effect=states),
                 patch.object(protection.time,"sleep",side_effect=sleep)]
        if skip_retry:
            patches.append(patch.object(protection,"retry_incoherent_evcc_state",
                                        side_effect=lambda s,m,c:(s,m)))
        with patches[0],patches[1]:
            if skip_retry:
                with patches[2]:guard.run()
            else:guard.run()
        return guard,self.server.state.writes
    def test_now_mode_prearms_before_charger_draws_current(self):
        # Regression from 10 November 2026: EVCC can report 479W for
        # 30 seconds and jump to 9.7kW between 15-second guard polls.
        pre=base_state(False)
        pre["loadpoints"][0].update(connected=True,charging=False,chargePower=0)
        pre["grid"]["power"]=1000
        m=protection.metrics(pre,self.cfg)
        self.assertTrue(m["coherent"])
        self.assertTrue(m["guard_requested"],"intentional 'now' must protect before AC ramp")
        guard,writes=self.run_sequence([pre])
        self.assertEqual(len(writes),1)
        self.assertEqual(writes[0][0],1040)
        self.assertAlmostEqual(protection.Kostal(self.cfg).read_float(1040),1400,places=1)

    def test_fast_charge_protection_is_not_prearmed_for_disconnected_vehicle(self):
        pre=base_state(False)
        pre["loadpoints"][0].update(connected=False,charging=False,chargePower=0)
        pre["grid"]["power"]=1000
        self.assertFalse(protection.metrics(pre,self.cfg)["guard_requested"])
        _,writes=self.run_sequence([pre])
        self.assertEqual(writes,[])

    def test_protects_ongoing_charge_across_now_to_smart_to_off_until_zero_watts(self):
        pre=base_state(False)
        pre["loadpoints"][0].update(connected=True,charging=False,chargePower=0)
        pre["grid"]["power"]=1000
        now=base_state(False)
        now["loadpoints"][0]["connected"]=True
        smart=base_state(False)
        smart["loadpoints"][0].update(connected=True,mode="smart")
        off=base_state(False)
        off["loadpoints"][0].update(connected=True,mode="off")
        end=base_state(False)
        end["loadpoints"][0].update(connected=True,mode="smart",charging=False,chargePower=0)
        end["grid"]["power"]=1000
        recorded=[]
        original=protection.Guard.relinquish
        def record_relinquish(g,reason):
            if g.baseline is not None:
                recorded.append(reason)
            return original(g,reason)
        with patch.object(protection.Guard,"relinquish",record_relinquish):
            guard,writes=self.run_sequence([pre,now,smart,off])
        self.assertEqual(recorded,["service stop"],
                         "mode changes during physical charging must not relinquish")
        self.assertEqual(len(writes),1,"keep 1040 capped through slow EVCC shutdown")
        self.assertIsNone(guard.baseline)
        self.assertEqual([x[0] for x in writes],[1040])

    def test_fast_charge_writes_home_only_then_leaves_without_reset_write(self):
        now=base_state(False)
        idle=base_state(False)
        idle["loadpoints"][0].update(charging=False,chargePower=0,mode="smart")
        idle["grid"]["power"]=1000
        guard,writes=self.run_sequence([now,idle])
        self.assertEqual(len(writes),1)
        self.assertEqual([x[0] for x in writes],[1040])
        self.assertIsNone(guard.baseline)
        self.assertFalse(guard.session_file.exists())
    def test_valid_plan_lease_is_physically_bounded_to_baseline(self):
        decision.publish(status())
        guard,writes=self.run_sequence([base_state(True)])
        self.assertEqual(len(writes),1)
        self.assertAlmostEqual(protection.Kostal(self.cfg).read_float(1040),7350,places=1) # 7359.4 baseline, 10W floor
    def test_expired_lease_plan_reverts_to_house_only(self):
        decision.publish(status(now=time.time()-60))
        guard,writes=self.run_sequence([base_state(True)])
        self.assertEqual(len(writes),1)
        self.assertAlmostEqual(protection.Kostal(self.cfg).read_float(1040),1400,places=1)
    def test_evcc_owner_conflict_never_writes(self):
        state=base_state(True)
        state["batteryDischargeControl"]=True
        _,writes=self.run_sequence([state])
        self.assertEqual(writes,[])
    def test_evcc_incoherent_while_guarded_writes_zero(self):
        normal=base_state(False)
        corrupt=base_state(False)
        corrupt["grid"]["power"]+=15000
        guard,writes=self.run_sequence([normal,corrupt],skip_retry=True)
        self.assertEqual(len(writes),2)
        self.assertAlmostEqual(protection.Kostal(self.cfg).read_float(1040),0,places=1)
    def test_min_soc_relinquishes_without_new_write(self):
        normal=base_state(False)
        low=base_state(False)
        low["battery"]["soc"]=8
        guard,writes=self.run_sequence([normal,low])
        self.assertEqual(len(writes),1)
        self.assertIsNone(guard.baseline)
    def test_pv_exceeds_home_zero_discharge(self):
        state=base_state(False)
        state["pv"]=[{"power":3000}]
        state["grid"]["power"]=8200
        guard,writes=self.run_sequence([state])
        self.assertAlmostEqual(protection.Kostal(self.cfg).read_float(1040),0,places=1)
        self.assertEqual(len(writes),1)

if __name__=="__main__":unittest.main()
