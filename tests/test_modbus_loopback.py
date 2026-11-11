"""End-to-end protocol mock: test ONLY on loopback with fake Modbus server."""
import json, socketserver, struct, tempfile, threading, unittest
from pathlib import Path
from dataclasses import replace
from battery_control_guard import protection

class FakeState:
    def __init__(self):
        self.words={5:0}
        self.writes=[]
        self.bad_readback=False
        self.set_float(1040,7359.4)
        self.set_float(1042,8.0)
        self.set_float(1078,9048.7)
    def set_float(self,addr,value):
        hi,lo=struct.unpack(">HH",struct.pack(">f",value))
        self.words[addr]=lo;self.words[addr+1]=hi

class FakeHandler(socketserver.BaseRequestHandler):
    def recvn(self,n):
        b=b""
        while len(b)<n:
            part=self.request.recv(n-len(b))
            if not part:raise ConnectionError
            b+=part
        return b
    def handle(self):
        h=self.recvn(7)
        tid,proto,length,unit=struct.unpack(">HHHB",h)
        pdu=self.recvn(length-1)
        func=pdu[0]
        state=self.server.state
        if func==3:
            addr,count=struct.unpack(">HH",pdu[1:5])
            words=[state.words.get(a,0) for a in range(addr,addr+count)]
            if state.bad_readback and addr==1040:
                words=[w ^ 0x0100 for w in words]
            resp=bytes([3,count*2])+struct.pack(">"+("H"*count),*words)
        elif func==16:
            addr,count,size=struct.unpack(">HHB",pdu[1:6])
            words=struct.unpack(">"+("H"*count),pdu[6:6+size])
            state.writes.append((addr,list(words)))
            for j,w in enumerate(words):state.words[addr+j]=w
            resp=bytes([16])+struct.pack(">HH",addr,count)
        else:resp=bytes([func|0x80,1])
        self.request.sendall(struct.pack(">HHHB",tid,0,len(resp)+1,unit)+resp)

class FakeModbusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=socketserver.ThreadingTCPServer(("127.0.0.1",0),FakeHandler)
        self.server.daemon_threads=True
        self.server.state=FakeState()
        self.t=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.t.start()
        self.cfg=protection.Config(
            armed=False,evcc_state_url="http://127.0.0.1:7070/api/state",
            kostal_host="127.0.0.1",kostal_port=self.server.server_address[1],
            kostal_unit=71,poll_interval_s=15,refresh_interval_s=30,
            min_change_w=100,grid_margin_w=100,min_charge_power_w=500,
            min_soc_hysteresis_pct=.5,state_coherence_w=500,
            readback_tolerance_w=50,max_reasonable_power_w=30000,
            http_timeout_s=3,modbus_timeout_s=2,state_dir=Path(self.temp.name))
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.t.join(3)
        self.temp.cleanup()
    def test_read_register_5_and_float_1042(self):
        k=protection.Kostal(self.cfg)
        self.assertEqual(k.detect_byte_order(),0)
        self.assertAlmostEqual(k.read_float(1042),8.0,places=3)
    def test_single_1040_write_with_readback(self):
        k=protection.Kostal(self.cfg)
        self.assertAlmostEqual(k.write_float(1040,600.0),600.0,places=2)
        self.assertEqual([a for a,_ in self.server.state.writes],[1040])
    def test_guard_caps_bms_and_relinquishes_without_write(self):
        g=protection.Guard(self.cfg)
        self.assertTrue(g.enter_session())
        g.write_limit(1500,"simulated guard request")
        self.assertEqual(g.last_target,1500)
        written=len(self.server.state.writes)
        g.relinquish("test end")
        self.assertEqual(len(self.server.state.writes),written)
    def test_guard_never_exceeds_bms_readout(self):
        self.server.state.set_float(1078,500)
        g=protection.Guard(self.cfg)
        self.assertTrue(g.enter_session())
        g.write_limit(5000,"simulated BMS cap")
        self.assertEqual(g.last_target,500)
        self.assertEqual([a for a,_ in self.server.state.writes],[1040])
    def test_write_readback_mismatch_is_rejected(self):
        k=protection.Kostal(self.cfg)
        self.server.state.bad_readback=True
        with self.assertRaises(protection.ModbusError):
            k.write_float(1040,1000)

if __name__=="__main__":unittest.main()
