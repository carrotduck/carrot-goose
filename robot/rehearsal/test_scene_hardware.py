import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave
import thermal_sample as t
from guarded_invitation import IDLE
from scene_hardware import Hardware,WaveAudio,targets_packet,changed_arm_packet,FinishTake
from scene_sequence import Scene,load_scene
from run_scene_take import perform,arm_test_plan,Journal,open_lock
from test_guarded_invitation import Fake
from test_scene_sequence import receipt

class Port(Fake):
    def write(self,data):
        self.writes.append(data)
        function,payload,_=t.Frames().feed(data)[0]
        if function==5 and payload[0]==1:
            for i in range(payload[3]):
                sid,value=struct.unpack('<BH',payload[4+3*i:7+3*i]);self.pose[sid]=value
        return len(data)
class Audio:
    def __init__(self,clock):self.clock=clock;self.until=0;self.texts=[];self.cancelled=False
    def start(self,text):self.texts.append(text);self.until=self.clock()+.4
    def finished(self):return self.clock()>=self.until
    def cancel(self):self.cancelled=True
class JournalFake:
    def __init__(self):self.rows=[]
    def write(self,r):self.rows.append(r)
class Link:
    def __init__(self):self.rows=[]
    def drain(self,s):
        for e in ('happy_reply','hand_withdrawn','hug_reply'):
            if e not in s.receipts:s.accept(receipt(e),0)
    def report(self,r,pump):self.rows.append(r)

class HardwareTests(unittest.TestCase):
    def test_bus_telemetry_is_paced_but_pose_checked_between_sweeps(self):
        f,a,h,ev=self.fixture();h.health();n=f.temps_read
        for _ in range(3):
            f.idle_until(f.clock()+.08);h.health()
        self.assertEqual(f.temps_read,n)
        f.fail='imu'
        with self.assertRaises(t.StopSampling):h.health()
        f.fail=None;f.idle_until(f.clock()+.2);h.health()
        self.assertGreater(f.temps_read,n)

    def test_near_idle_drift_is_physically_restored_not_accepted(self):
        f,a,h,ev=self.fixture();f.pose[8]=699;h.prepare()
        self.assertEqual(f.pose[8],IDLE[8])
        self.assertTrue(any(e.get('kind')=='near_idle_restore' for e in ev))
        self.assertIn(8,h.commanded_ids)
    def test_compact_happy_sequence_finishes_idle_and_rejects_modified_joint(self):
        import copy
        from scene_hardware import HAPPY_SEQUENCE
        f,a,h,ev=self.fixture();h.prepare()
        step={'happy_sequence':copy.deepcopy(HAPPY_SEQUENCE)}
        result=h.execute(step)
        self.assertEqual(result['happy_frames_verified'],5)
        self.assertEqual(h.arms,IDLE)
        self.assertEqual(len([r for r in ev if r.get('kind')=='happy_frame_completed']),5)
        count=len(f.writes)
        step['happy_sequence'][0]['arms'][1]=500
        with self.assertRaises(t.StopSampling):h.execute(step)
        self.assertEqual(len(f.writes),count)

    def test_right_motion_does_not_command_resting_left_arm(self):
        target={**IDLE,14:399,15:204,16:401}
        raw=changed_arm_packet(target,IDLE,1.6)
        payload=t.Frames().feed(raw)[0][1]
        self.assertEqual(payload[3],3)
        self.assertEqual([payload[4+i*3] for i in range(3)],[14,15,16])
        self.assertIsNone(changed_arm_packet(IDLE,IDLE,1.6))
        with self.assertRaises(t.StopSampling):changed_arm_packet({**target,6:999},IDLE,1.6)
    def test_motion_position_trace_covers_moving_arm_only(self):
        f,a,h,ev=self.fixture();h.prepare()
        h.execute(arm_test_plan(load_scene())['steps'][0])
        rows=[e for e in ev if e.get('kind')=='motion_position_sample']
        self.assertGreaterEqual(len(rows),3)
        self.assertTrue(all(set(e['positions'])=={14,15,16} for e in rows))
    def test_head_only_cancel_does_not_touch_bus_arms(self):
        f,a,h,ev=self.fixture();h.prepare();h.execute(load_scene()['steps'][0])
        n=len(f.writes);h.cancel();self.assertEqual(len(f.writes),n)
    def test_existing_lock_open_does_not_create_or_replace_inode(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'lock';p.write_text('owner')
            ino=p.stat().st_ino
            original=os.open
            with patch('run_scene_take.os.open',wraps=original) as opened:
                with open_lock(p):pass
                self.assertFalse(opened.call_args.args[1]&os.O_CREAT)
            self.assertEqual(p.stat().st_ino,ino);self.assertEqual(p.read_text(),'owner')
    def fixture(self):
        f=Port();f.deadline=100;audio=Audio(f.clock);events=[]
        return f,audio,Hardware(f,audio,events.append),events
    def test_complete_31_step_scene_actual_packets_readback_and_audio_receipts(self):
        f,a,h,events=self.fixture();h.prepare();link=Link();journal=JournalFake()
        s=Scene('take','user');perform(s,h,link,journal,events.append,wall_clock=lambda:0)
        self.assertEqual(s.index,31)
        self.assertEqual(a.texts,['Mm?','Hey.'])
        self.assertEqual(h.arms,IDLE);self.assertEqual(h.head,{'pitch':1500,'yaw':1530})
        self.assertEqual([r['status'] for r in link.rows],['started','completed']*31)
        self.assertTrue(all(not r['head_observed'] for r in link.rows if r['status']=='completed'))
        self.assertEqual(events[-1]['kind'],'full_take_complete')
        self.assertTrue(any(t.Frames().feed(w)[0][0]==4 for w in f.writes))
        self.assertTrue(any(6 in [w[8+i*3] for i in range(w[7])] for w in f.writes if w[2]==5 and w[4]==1))
    def test_bimanual_test_returns_both_arms_and_head(self):
        f,a,h,ev=self.fixture();h.prepare()
        s=Scene('take','user',arm_test_plan(load_scene()))
        perform(s,h,Link(),JournalFake(),ev.append,wall_clock=lambda:0)
        self.assertEqual(s.index,4);self.assertEqual(h.arms,IDLE);self.assertEqual(a.texts,[])
    def test_position_failure_never_reports_completed_and_stops_only_commanded_arm(self):
        f,a,h,ev=self.fixture();h.prepare();f.fail='position'
        l=Link()
        with self.assertRaisesRegex(t.StopSampling,'position_mismatch'):
            perform(Scene('take','user',arm_test_plan(load_scene())),h,l,JournalFake(),ev.append,wall_clock=lambda:0)
        self.assertFalse(any(r['status']=='completed' for r in l.rows))
        h.cancel();self.assertEqual(t.Frames().feed(f.writes[-1])[0][1],bytes((3,3,14,15,16)))
    def test_audio_failure_does_not_complete_phase(self):
        f,a,h,ev=self.fixture();h.prepare()
        def bad():raise t.StopSampling('audio_playback_failed')
        a.finished=bad
        step=dict(load_scene()['steps'][6]);step['action_id']='take:6'
        with self.assertRaisesRegex(t.StopSampling,'audio_playback_failed'):h.execute(step)
    def test_unvalidated_targets_rejected_before_write(self):
        for targets in ({**IDLE,1:500},{**IDLE,14:999}):
            with self.assertRaises(t.StopSampling):targets_packet(5,targets,1)
    def test_explicit_stop_during_motion_does_not_blindly_return(self):
        f,a,h,ev=self.fixture();h.prepare();calls=0
        def stop():
            nonlocal calls
            calls+=1
            if calls>1:raise t.StopSampling('user_stop')
        with self.assertRaisesRegex(t.StopSampling,'user_stop'):h.execute(load_scene()['steps'][19],stop)
        before=len(f.writes);h.cancel();self.assertEqual(len(f.writes),before+1)
        self.assertEqual(t.Frames().feed(f.writes[-1])[0][1][0],3)
    def test_crashed_or_completed_take_cannot_replay(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'take.jsonl';j=Journal(p);j.write({'status':'started'});j.close()
            with self.assertRaises(FileExistsError):Journal(p)
    def test_wav_assets_real_pcm_duration_and_not_silent(self):
        if not (Path(__file__).parent/"audio/mm.wav").exists():self.skipTest("User-selected voice assets are not distributed")
        for name in ('mm.wav','hey.wav'):
            with wave.open(str(Path(__file__).parent/'audio'/name),'rb') as f:
                self.assertGreater(f.getnframes()/f.getframerate(),.1)
                self.assertLess(f.getnframes()/f.getframerate(),3)
                self.assertGreater(max(f.readframes(f.getnframes())),0)
    def test_aplay_arguments_and_exit_status(self):
        captured=[]
        class Process:
            code=None
            def poll(self):return self.code
        p=Process()
        def launch(args,**kw):captured.append(args);return p
        import tempfile,wave
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        for name in ('mm.wav','hey.wav'):
            with wave.open(str(Path(folder.name)/name),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050);wav.writeframes(b'\x01\x00'*4410)
        a=WaveAudio(Path(folder.name),popen=launch,which=lambda _:True)
        a.preflight();a.start('Hey.');self.assertFalse(a.finished())
        self.assertEqual(captured[0][:4],['aplay','-q','-D','plughw:2,0'])
        p.code=1
        with self.assertRaises(t.StopSampling):a.finished()
    def test_missing_event_returns_to_idle_without_inventing_reply(self):
        from scene_transport import LocalLink
        f,a,h,ev=self.fixture();h.prepare()
        plan=arm_test_plan(load_scene());plan['steps']=plan['steps'][:1]+[{**plan['steps'][1],'gate':'hug_reply','wait_arms_raised':True}]
        s=Scene('take','user',plan);j=JournalFake()
        perform(s,h,LocalLink(),j,ev.append,wall_clock=lambda:0)
        self.assertTrue(s.closed);self.assertEqual(s.index,1);self.assertEqual(h.arms,IDLE)
        self.assertEqual(ev[-1]['kind'],'take_ended_at_idle')
        self.assertEqual(sum(r.get('status')=='completed' for r in j.rows),1)
    def test_temperature_finish_completes_current_move_then_returns(self):
        f,a,h,ev=self.fixture();h.prepare();original=f.write
        def write(data):
            result=original(data);f.temp=50;return result
        f.write=write
        s=Scene('take','user',arm_test_plan(load_scene()))
        perform(s,h,Link(),JournalFake(),ev.append,wall_clock=lambda:0)
        self.assertEqual(s.index,1);self.assertTrue(s.closed);self.assertEqual(h.arms,IDLE)
        self.assertFalse(any(e.get('kind')=='full_take_complete' for e in ev))
    def test_ack_failure_stops_before_network_failure_report(self):
        f,a,h,ev=self.fixture();h.prepare()
        class BrokenLink(Link):
            def report(self,r,pump):
                if r['status']=='completed':raise t.StopSampling('network_lost')
                if r['status']=='failed':
                    self.cancelled_before_report=h.cancelled
                    self.stop_packet_before_report=t.Frames().feed(f.writes[-1])[0][1][0]==3
        l=BrokenLink();s=Scene('take','user',arm_test_plan(load_scene()))
        with self.assertRaisesRegex(t.StopSampling,'network_lost'):perform(s,h,l,JournalFake(),ev.append,wall_clock=lambda:0)
        self.assertTrue(l.cancelled_before_report);self.assertTrue(l.stop_packet_before_report)
        self.assertEqual(s.index,0)
if __name__=='__main__':unittest.main()
