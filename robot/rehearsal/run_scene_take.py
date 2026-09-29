"""Explicit one-take execution; default prints help, never touches hardware.

full: real authenticated webpage events, recorded WAV clips, 31 phase receipts.
arms-test: independent new two-arm invitation/hug/return candidate (no web/audio).
audio-test: only the two WAV clips, no serial imports or commands.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import signal
import time
from guarded_invitation import DemoSampler, IDLE
from thermal_sample import check_services_and_port, ensure_owner, StopSampling
from scene_sequence import Scene, load_scene
from scene_hardware import Hardware, WaveAudio, FinishTake
from scene_transport import WebLink, LocalLink

HERE=Path(__file__).resolve().parent

def open_lock(name):
    # Linux protected_regular rejects O_CREAT on another user's file in /tmp,
    # even for root. Open existing locks without O_CREAT; never replace inode.
    flags=os.O_RDWR|getattr(os,'O_NOFOLLOW',0)
    try:fd=os.open(name,flags)
    except FileNotFoundError:
        try:fd=os.open(name,flags|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:fd=os.open(name,flags)
    return os.fdopen(fd,'r+')

class Journal:
    def __init__(self,path):
        # Exclusive create: a crashed or finished take can never silently replay.
        self.file=open(path,'x',encoding='utf-8')
    def write(self,data):
        self.file.write(json.dumps(data,ensure_ascii=False)+'\n');self.file.flush();os.fsync(self.file.fileno())
    def close(self):self.file.close()

def arm_test_plan(plan):
    # Keep the same fixed enhanced/hug candidates and a complete return.
    phase_ids=('phase_19','phase_23','phase_27','phase_29')
    previous={str(k):v for k,v in IDLE.items()};steps=[]
    for phase_id in phase_ids:
        s=dict(next(s for s in plan['steps'] if s['id']==phase_id))
        s.update(gate=None,utterance=None,hold_s=.3,wait_arms_raised=False)
        s['move_s']=round(max(1.6,max(abs(s['arms'][k]-previous[k]) for k in previous)/100),3)
        if phase_id=='phase_29':s['head']={'pitch':1500,'yaw':1530};s['move_s']=max(2.4,s['move_s']);s['hold_s']=0
        steps.append(s);previous=s['arms']
    return {**plan,'steps':steps}

def preset_gaze_plan(plan):
    import copy
    plan=copy.deepcopy(plan)
    plan['choreographed_withdrawal']=True
    targets={1:(1540,1530),2:(1500,1415),3:(1500,1645),4:(1600,1530),5:(1420,1530),
             6:(1420,1597),7:(1540,1530),8:(1420,1597),9:(1540,1530),10:(1420,1597)}
    for i,(pitch,yaw) in targets.items():
        step=plan['steps'][i];step['head']={'pitch':pitch,'yaw':yaw}
        step['move_s']=1.05 if i in (2,3,4,5) else .8
        step['hold_s']=.4 if i in (2,3,4,5) else max(.2,step['hold_s'])
        step['head_source']='preset_choreography_user_follows'
    plan['steps'][29]['side_clearance']=True
    return plan

def perform(scene,hardware,link,journal,emit,wall_clock=lambda:time.time()*1000):
    waiting_since=None;choreography_sent=False
    def check():link.drain(scene)
    def report(item):
        journal.write(item);emit(item)
        link.report(item,lambda:hardware.tick(check))
    while True:
        check();n=scene.next(wall_clock())
        if n['state']=='complete':
            hardware.guard.settle();hardware.guard.health(stable=True)
            emit(dict(kind='full_take_complete',steps=scene.index,head_feedback='timed_commands_not_encoder',arms_verified=True,
                      temperature_warning=getattr(hardware.guard.gate,'deferred_peaks',{})));return
        if n['state']=='waiting':
            if hardware.observer:
                hardware.gaze_mode='auto' if not n['arms_raised'] and not hardware.preset_gaze else None
                hardware.allow_withdraw=n['event']=='hand_withdrawn'
            if waiting_since is None:
                waiting_since=hardware.s.clock();emit(dict(kind='waiting_for_event',event=n['event']))
            if n['event']=='hand_withdrawn' and scene.plan.get('choreographed_withdrawal') and not choreography_sent and hardware.s.clock()-waiting_since>=3:
                link.withdrawn({'source':'choreography','completed_step':17})
                choreography_sent=True
                emit(dict(kind='choreography_withdrawal_cue',pause_s=3,physical_withdrawal_observed=False))
            # Deadlines end a take; they NEVER manufacture a missing webpage cue.
            if hardware.guard.gate.finish_requested or hardware.s.clock()-waiting_since>(8 if n['arms_raised'] else 90):
                reason='temperature_finish' if hardware.guard.gate.finish_requested else 'event_wait_timeout'
                result=hardware.return_idle(check)
                journal.write(dict(kind='early_return',reason=reason,**result))
                emit(dict(kind='take_ended_at_idle',reason=reason));scene.cancel();return
            hardware.tick(check);continue
        if n['state']!='dispatch':raise StopSampling('invalid_scene_state')
        waiting_since=None;a=n['action'];base=dict(action_id=a['action_id'],step=scene.index,label=a['label'])
        try:
            report(dict(status='started',**base))
            result=hardware.execute(a,check)
            report(dict(status='completed',**base,**result))
            scene.complete(a['action_id'],success=True,arms_verified=True,head_observed=False,audio_completed=result['audio_status']=='process_completed')
        except FinishTake:
            result=hardware.return_idle(check)
            report(dict(status='failed',**base,error='temperature_finish_returned_to_idle'))
            journal.write(dict(kind='early_return',**result));scene.cancel();return
        except BaseException as error:
            hardware.cancel() # Stop local motion/audio before waiting on any network reporting.
            journal.write(dict(status='failed',**base,error=type(error).__name__))
            try:link.report(dict(status='failed',**base,error=type(error).__name__),lambda:time.sleep(.01))
            except Exception:pass
            scene.cancel();raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',action='store_true');p.add_argument('--commission-candidates',action='store_true')
    p.add_argument('--mode',choices=['full','arms-test','audio-test'],default='full')
    p.add_argument('--live-gaze',action='store_true',help='Use local camera face/fingertip observations during attentive beats')
    p.add_argument('--preset-gaze',action='store_true',help='Use fixed head choreography; camera may still confirm withdrawal')
    p.add_argument('--auto-withdraw',action='store_true',help='Commit camera-observed hand withdrawal; requires live-gaze and updated web service')
    p.add_argument('--body-sway',action='store_true',help='Explicit supervised 20 percent factory twist candidate during the compact happy beat')
    p.add_argument('--camera-device',type=int,default=0)
    p.add_argument('--temperature-profile',choices=['rehearsal','recording'],default='rehearsal',
                   help='Explicit temporary recording profile: start below 75 C, finish at 75 C, stop at 80 C; device limits unchanged')
    p.add_argument('--take-id');p.add_argument('--user-id');p.add_argument('--audio-device',default=os.getenv('TTS_AUDIO_DEVICE','plughw:2,0'))
    p.add_argument('--journal-dir',default='/home/pi/yushi/rehearsal_runs')
    a=p.parse_args()
    if a.auto_withdraw and not a.live_gaze:p.error('--auto-withdraw requires --live-gaze')
    if a.live_gaze and a.mode!='full':p.error('--live-gaze requires full mode')
    if not a.run:p.print_help();return 0
    audio=WaveAudio(HERE/'audio',a.audio_device)
    if a.mode=='audio-test':
        audio.preflight()
        try:
            for text in ('Mm?','Hey.'):
                audio.start(text);end=time.monotonic()+4
                while not audio.finished():
                    if time.monotonic()>end:raise StopSampling('audio_timeout')
                    time.sleep(.03)
            print(json.dumps({'kind':'audio_test_complete','speaker_audibility':'requires_user_confirmation'}));return 0
        finally:audio.cancel()
    if not a.commission_candidates:p.error('New joint paths require explicit --commission-candidates for supervised commissioning')
    if not a.take_id or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',a.take_id):p.error('A unique --take-id is required')
    if a.mode=='full' and not a.user_id:p.error('--user-id is required for real webpage events')
    plan=load_scene()
    if a.preset_gaze:plan=preset_gaze_plan(plan)
    if a.live_gaze and not a.preset_gaze:
        from live_gaze import enable_live_gaze
        plan=enable_live_gaze(plan)
    if a.mode=='arms-test':plan=arm_test_plan(plan)
    else:audio.preflight()
    scene=Scene(a.take_id,a.user_id or 'local',plan)
    link=WebLink(a.user_id,a.take_id,os.environ.get('CARROTDUCK_SESSION_TOKEN','')) if a.mode=='full' else LocalLink()
    hardware=None;began=time.monotonic();trace=None
    def emit(data):
        row={'elapsed':round(time.monotonic()-began,3),**data}
        # Keep field diagnostics automatically, including the exact rejected IMU
        # window, instead of relying on a terminal's truncated output.
        if trace is not None and data.get('kind') not in ('battery','pre_request_drain'):
            saved=dict(row)
            if saved.get('kind')=='initial_sync_complete':saved.pop('discarded_prefix',None)
            trace.write(json.dumps(saved,ensure_ascii=False)+'\n');trace.flush()
        if data.get('kind') not in ('battery','pre_request_drain','reply','value','health_pass','initial_sync_complete','motion_position_sample'):
            print(json.dumps(row,ensure_ascii=False),flush=True)
    def abort(*_):raise StopSampling('signal_or_total_deadline')
    try:
        if a.mode=='full':link.start() # Complete web handshake before opening serial.
        import fcntl
        import serial
        with ExitStack() as stack:
            for name in ('/home/pi/yushi/yushi_client.lock','/tmp/tonypi-controller-serial.lock'):
                f=stack.enter_context(open_lock(name));fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            check_services_and_port()
            directory=Path(a.journal_dir);directory.mkdir(parents=True,exist_ok=True)
            journal=Journal(directory/(a.take_id+'.jsonl'));stack.callback(journal.close)
            trace=open(directory/(a.take_id+'.trace.jsonl'),'x',encoding='utf-8')
            journal.write(dict(kind='take_reserved',take_id=a.take_id,mode=a.mode,candidate_paths=True,temperature_profile=a.temperature_profile))
            for sig in (signal.SIGALRM,signal.SIGINT,signal.SIGTERM):signal.signal(sig,abort)
            signal.setitimer(signal.ITIMER_REAL,185 if a.mode=='full' else 80)
            port=serial.Serial(None,1000000,timeout=.02,write_timeout=.2,exclusive=True)
            stack.callback(port.close);port.rts=False;port.dtr=False;port.port='/dev/ttyAMA0';port.open();port.reset_input_buffer()
            from body_sway import BodySampler,BodySway
            sampler=BodySampler(port,time.monotonic()+(180 if a.mode=='full' else 75),emit,ensure_owner)
            hardware=Hardware(sampler,audio,emit,check_services_and_port,temperature_profile=a.temperature_profile)
            hardware.preset_gaze=a.preset_gaze
            if a.body_sway:hardware.body_sway=BodySway(hardware)
            try:
                hardware.prepare()
                if a.mode=='full' and a.temperature_profile=='recording':hardware.guard.gate.defer_finish=True
                if a.live_gaze:
                    from scene_camera import CameraObservations
                    camera=CameraObservations(a.camera_device);stack.callback(camera.close);camera.start()
                    until=time.monotonic()+6
                    while time.monotonic()<until:
                        observation=camera.read()
                        if observation and not observation.get('error') and time.monotonic()-observation['time']<=.35:break
                        if observation and observation.get('error'):raise StopSampling('camera_initialization_failed')
                        hardware.tick(lambda:link.drain(scene))
                    else:raise StopSampling('camera_not_ready')
                    hardware.configure_gaze(camera,link.withdrawn if a.auto_withdraw else None)
                perform(scene,hardware,link,journal,emit)
            except BaseException:
                hardware.cancel();raise
        return 0
    except (Exception,KeyboardInterrupt) as error:
        emit(dict(kind='take_failed',error=type(error).__name__,reason=str(error)[:180]));return 1
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);audio.cancel();link.close()
        try:emit(dict(kind='scene_session_closed',torque_released=False))
        finally:
            if trace is not None:trace.close()

if __name__=='__main__':raise SystemExit(main())
