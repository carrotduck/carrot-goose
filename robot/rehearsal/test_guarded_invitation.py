import ast
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
import guarded_invitation as g
import thermal_sample as t


class Fake:
    def __init__(self):
        self.now=0.;self.deadline=33.;self.battery=(12000,0.)
        self.pose=dict(g.IDLE);self.writes=[];self.temp=31;self.fail=None
        self.port=self;self.temps_read=0;self.owner=True
    def clock(self):return self.now
    def ensure_owner(self):
        if not self.owner:raise t.StopSampling('owner')
    def synchronize(self):self.ensure_owner()
    def idle_until(self,due):self.now=due;self.battery=(12000,self.now)
    def upright(self,stable=False):
        if self.fail=='imu':raise t.StopSampling('imu')
    def wait_fresh_battery(self,until):self.battery=(12000,self.now)
    def read(self,sid,cmd,until):
        self.ensure_owner();self.now+=.001
        if self.fail=='timeout':raise t.StopSampling('timeout')
        if cmd==9:
            self.temps_read+=1
            return 45 if self.fail=='hot_during' and self.writes else self.temp
        if cmd==7:return 10000 if self.fail=='voltage' else 12000
        if cmd==5:return self.pose[sid]+(20 if self.fail=='position' else 0)
        raise AssertionError(cmd)
    def write(self,data):
        self.writes.append(data)
        payload=t.Frames().feed(data)[0][1]
        if payload[0]==1:
            for i in range(payload[3]):
                sid,value=struct.unpack('<BH',payload[4+3*i:7+3*i]);self.pose[sid]=value
        return len(data)


class GuardedTests(unittest.TestCase):
    def rehearsal_fixture(self,temperature):
        f=Fake();f.temp=32;old=f.read;events=[]
        def read(sid,cmd,until):
            value=old(sid,cmd,until)
            return temperature if sid==14 and cmd==9 and f.writes else value
        f.read=read
        return f,events,g.Demo(f,events.append,rehearsal=True)

    def test_rehearsal_37_finishes_all_four_stages(self):
        f,events,d=self.rehearsal_fixture(37);d.run(True)
        self.assertEqual(f.writes,[g.move_packet(i) for i in range(4)])
        self.assertEqual(f.pose,g.IDLE)
        self.assertEqual(events[-1]['kind'],'demo_complete')
        self.assertEqual(sum(e['kind']=='temperature_advisory' for e in events),1)

    def test_rehearsal_38_to_49_does_not_cancel_normal_return(self):
        for value in (38,40,44,49):
            with self.subTest(value=value):
                f,events,d=self.rehearsal_fixture(value);d.run(True)
                self.assertEqual(f.writes,[g.move_packet(i) for i in range(4)])
                self.assertEqual(f.pose,g.IDLE)
                self.assertEqual(events[-1]['kind'],'demo_complete')

    def test_rehearsal_50_selects_rest_without_more_invitation(self):
        f,events,d=self.rehearsal_fixture(50)
        sent_at=[];old=f.write
        def timed_write(data):sent_at.append(f.now);return old(data)
        f.write=timed_write;d.run(True)
        self.assertEqual(f.writes,[g.move_packet(0),g.move_packet(3)])
        self.assertEqual(f.pose,g.IDLE)
        self.assertEqual(events[-1]['kind'],'take_closed_early')
        self.assertEqual(events[-1]['final_pose'],'idle_verified')
        self.assertLess(sent_at[1]-sent_at[0],2.1,'No extra hold or quiet pause before early rest')

    def test_rehearsal_55_stops_without_blind_recovery(self):
        f,events,d=self.rehearsal_fixture(55)
        with self.assertRaises(t.StopSampling):d.run(True)
        d.cancel()
        self.assertEqual(f.writes[0],g.move_packet(0))
        self.assertEqual(t.Frames().feed(f.writes[1])[0][1],bytes((3,3,14,15,16)))
        self.assertFalse(any(e['kind'] in ('demo_complete','take_closed_early') for e in events))

    def test_rehearsal_requires_lower_start_and_keeps_diagnostic_rules(self):
        for value in (45,55,None,float('nan')):
            gate=g.RehearsalTemperature(lambda _:None)
            with self.assertRaises(t.StopSampling):gate.check(14,value)
        gate=t.ThermalGate();gate.check(14,32)
        with self.assertRaises(t.StopSampling):gate.check(14,37)

    def test_rehearsal_recovery_then_full_demo_under_37(self):
        f,events,d=self.rehearsal_fixture(37)
        f.pose.update({14:407,15:202,16:399});d.run(True)
        self.assertEqual(f.writes,[g.move_packet(3)]+[g.move_packet(i) for i in range(4)])
        self.assertEqual(f.pose,g.IDLE)

    def test_rehearsal_bad_final_position_is_not_success(self):
        f,events,d=self.rehearsal_fixture(50);old=f.write
        def stuck(data):
            result=old(data)
            if data==g.move_packet(3):f.pose[16]=399
            return result
        f.write=stuck
        with self.assertRaises(t.StopSampling):d.run(True)
        self.assertFalse(any(e['kind']=='take_closed_early' for e in events))

    def test_complete_historical_sequence(self):
        f=Fake();events=[];d=g.Demo(f,events.append);d.run(True)
        self.assertEqual(f.writes,[g.move_packet(i) for i in range(4)])
        self.assertEqual(f.pose,g.IDLE);self.assertGreater(f.temps_read,4*12)
        self.assertLess(f.now,33);self.assertEqual(events[-1]['kind'],'demo_complete')
        with self.assertRaises(t.StopSampling):d.run(True)
    def test_default_no_motion(self):
        f=Fake();g.Demo(f,lambda _:None).run();self.assertEqual(f.writes,[])
    def test_small_forearm_offset_recovers_then_demonstrates(self):
        f=Fake();f.pose[16]=304;events=[]
        g.Demo(f,events.append).run(True)
        self.assertEqual(f.writes,[g.move_packet(3)]+[g.move_packet(i) for i in range(4)])
        self.assertEqual(f.pose,g.IDLE)
        self.assertIn('recovery_complete',[e['kind'] for e in events])
    def test_stability_uses_post_motion_window(self):
        f=Fake();f.pose[16]=304;f.motion_end=-10.;old=f.write
        def write(data):
            payload=t.Frames().feed(data)[0][1]
            if payload[0]==1:f.motion_end=f.now+struct.unpack('<H',payload[1:3])[0]/1000
            return old(data)
        def upright(stable=False):
            if stable and f.now-f.motion_end<.6:raise t.StopSampling('moving_window')
        f.write=write;f.upright=upright
        g.Demo(f,lambda _:None).run(True)
        self.assertEqual(len(f.writes),5)
    def test_no_unbounded_or_readonly_recovery(self):
        for sid,value,motion in [(16,304,False),(16,500,True),(14,350,True),(6,600,True)]:
            f=Fake();f.pose[sid]=value
            with self.assertRaises(t.StopSampling):g.Demo(f,lambda _:None).run(motion)
            self.assertEqual(f.writes,[])
    def test_recovery_only_from_invitation_never_starts_demo(self):
        f=Fake();f.pose.update({14:407,15:202,16:399});events=[]
        g.Demo(f,events.append).run(recovery_only=True)
        self.assertEqual(f.writes,[g.move_packet(3)])
        self.assertEqual(events[-1]['kind'],'recovery_only_complete')
        self.assertEqual(f.pose,g.IDLE)
    def test_recovery_only_rejects_unknown_pose_and_heat(self):
        for pose,temp in [({16:600},31),({14:300},31),({16:399},40)]:
            f=Fake();f.pose.update(pose);f.temp=temp
            with self.assertRaises(t.StopSampling):g.Demo(f,lambda _:None).run(recovery_only=True)
            self.assertEqual(f.writes,[])
    def test_failed_recovery_cannot_start_demo(self):
        f=Fake();f.pose[16]=304;old=f.write
        def stuck(data):
            result=old(data);f.pose[16]=304;return result
        f.write=stuck
        with self.assertRaises(t.StopSampling):g.Demo(f,lambda _:None).run(True)
        self.assertEqual(f.writes,[g.move_packet(3)])
    def test_preflight_faults_never_move(self):
        for fault in ('timeout','imu','voltage','position'):
            with self.subTest(fault=fault):
                f=Fake();f.fail=fault;d=g.Demo(f,lambda _:None)
                with self.assertRaises(t.StopSampling):d.run(True)
                d.cancel();self.assertEqual(f.writes,[])
        f=Fake();f.temp=40
        with self.assertRaises(t.StopSampling):g.Demo(f,lambda _:None).run(True)
        self.assertEqual(f.writes,[])
    def test_heat_in_first_move_cancels_rest_no_return(self):
        f=Fake();f.fail='hot_during';d=g.Demo(f,lambda _:None)
        with self.assertRaises(t.StopSampling):d.run(True)
        d.cancel();self.assertEqual(len(f.writes),2)
        self.assertEqual(t.Frames().feed(f.writes[-1])[0][1],bytes((3,3,14,15,16)))
        self.assertNotEqual(f.pose,g.IDLE)
    def test_owner_change_no_stop_to_new_owner(self):
        f=Fake();d=g.Demo(f,lambda _:None);d.sent=1;f.owner=False;d.cancel()
        self.assertEqual(f.writes,[])
    def test_pre_move_service_guard(self):
        f=Fake()
        def reject():raise t.StopSampling('service')
        with self.assertRaises(t.StopSampling):g.Demo(f,lambda _:None,reject).run(True)
        self.assertEqual(f.writes,[])
    def test_fixed_stage_allowlist(self):
        for bad in (-1,4,True,1.1,'hey'):
            with self.assertRaises(t.StopSampling):g.move_packet(bad)
        for i in range(4):
            payload=t.Frames().feed(g.move_packet(i))[0][1]
            self.assertEqual([payload[4+j*3] for j in range(3)],[14,15,16])
    def test_real_imu_gate_rejects_stale_tilt_and_nonfinite(self):
        f=Fake();s=g.DemoSampler(f,33,lambda _:None,f.ensure_owner,clock=f.clock)
        good=(-1.,0.,0.,0.,0.,0.)
        s.imu=[(0.,good)]*25;s.upright(True)
        f.now=.4
        with self.assertRaises(t.StopSampling):s.upright()
        f.now=0.;s.imu=[(0.,(0.,0.,1.,0.,0.,0.))]*25
        with self.assertRaises(t.StopSampling):s.upright(True)
        body=bytes((7,24))+struct.pack('<6f',float('nan'),0.,0.,0.,0.,0.)
        with self.assertRaises(t.StopSampling):s.receive(b'\xaa\x55'+body+bytes((t.crc8(body),)),0.)
    def test_position_identity_and_unsigned_confusion(self):
        self.assertEqual(g.position_reply(struct.pack('<BBbh',14,5,0,425),14,5),425)
        for payload in (struct.pack('<BBbh',15,5,0,425),struct.pack('<BBbh',14,7,0,425),
                        struct.pack('<BBbh',14,5,1,425),struct.pack('<BBbh',14,5,0,-1),b''):
            with self.assertRaises(t.StopSampling):g.position_reply(payload,14,5)
        # Existing read-only sampler remains read-only after extension hooks.
        with self.assertRaises(t.StopSampling):t.Sampler.make_request(14,5)
    def test_sdk_wire_compatibility_without_import(self):
        source=Path(__file__).resolve().parents[2]/'.tmp/ros_robot_controller_sdk.installed.py'
        if not source.exists():self.skipTest('Optional vendor SDK source fixture is not distributed')
        tree=ast.parse(source.read_text(encoding='utf-8'))
        board=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Board')
        methods=[n for n in board.body if isinstance(n,ast.FunctionDef) and n.name in ('bus_servo_set_position','bus_servo_stop')]
        ns={'struct':struct,'PacketFunction':SimpleNamespace(PACKET_FUNC_BUS_SERVO=5)}
        exec(compile(ast.Module(body=methods,type_ignores=[]),str(source),'exec'),ns)
        captured=[];fake=SimpleNamespace(buf_write=lambda fn,p:captured.append(g.frame(bytes(p))))
        for i,(_,pose,duration,_) in enumerate(g.STAGES):
            ns['bus_servo_set_position'](fake,duration,list(zip(g.RIGHT,pose)))
            self.assertEqual(captured[-1],g.move_packet(i))
        ns['bus_servo_stop'](fake,list(g.RIGHT))
        self.assertEqual(captured[-1],g.frame(bytes((3,3,14,15,16))))


if __name__=='__main__':unittest.main()
