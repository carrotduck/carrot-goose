"""Single-writer six-arm/PWM executor. Importing never opens hardware."""
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from guarded_invitation import Demo, IDLE, RecordingTemperature
from thermal_sample import StopSampling, crc8, voltage_gate

class FinishTake(StopSampling):pass

HUG_ARMS=[dict(zip((6,7,8,14,15,16),row)) for row in (
    (761,831,423,352,211,634),(831,845,380,170,215,662),
    (761,592,366,380,352,665),(761,803,366,380,113,665),
    (718,690,423,394,268,634),(577,803,690,437,169,282))]

# Compact candidate: elbows lightly bent, shoulders near idle; no leg channels.
HAPPY_CLOSE={6:545,7:803,8:610,14:415,15:200,16:355}
HAPPY_LOW={6:545,7:803,8:650,14:415,15:200,16:315}
HAPPY_SEQUENCE=[dict(arms=dict(arms),head={'pitch':p,'yaw':y},move_s=.9,hold_s=.12)
                for arms,p,y in ((HAPPY_CLOSE,1460,1450),(HAPPY_LOW,1580,1620),
                                 (HAPPY_CLOSE,1460,1460),(HAPPY_LOW,1580,1610))]
HAPPY_SEQUENCE.append(dict(arms=dict(IDLE),head={'pitch':1520,'yaw':1530},move_s=1.1,hold_s=.25))

# New candidate: keep lateral clearance, lower through the compact cheer
# corridor, then offer both arms forward. Not yet physically commissioned.
CARE_ENTRY={6:614,7:813,8:597,14:399,15:204,16:401}
CARE_SEQUENCE=[
    dict(arms={**CARE_ENTRY,7:777,15:246},move_s=1.8,hold_s=.2),
    dict(arms={**HAPPY_LOW,7:777,15:246},move_s=3.0,hold_s=.2),
    dict(arms={**HAPPY_CLOSE,7:777,15:246},move_s=1.6,hold_s=.2),
]

def packet(function,payload):
    body=bytes((function,len(payload)))+payload
    return b'\xaa\x55'+body+bytes((crc8(body),))

def targets_packet(function,positions,duration):
    allowed=set(IDLE) if function==5 else {1,2} if function==4 else set()
    if set(positions)!=allowed:raise StopSampling('invalid_joint_set')
    if not .1<=duration<=10:raise StopSampling('invalid_motion_duration')
    for sid,value in positions.items():
        lo,hi=(125,875) if function==5 else (1400,1650)
        if type(value) is not int or not lo<=value<=hi:raise StopSampling('invalid_joint_target')
    payload=bytes((1,))+struct.pack('<H',round(duration*1000))+bytes((len(positions),))
    payload+=b''.join(struct.pack('<BH',sid,v) for sid,v in sorted(positions.items()))
    return packet(function,payload)

def changed_arm_packet(target,previous,duration):
    # Validate the entire planned pose before selecting changed joints. Sending
    # unchanged targets can re-enable holding torque on a resting arm.
    targets_packet(5,target,duration)
    changed={sid:value for sid,value in target.items() if value!=previous[sid]}
    if not changed:return None
    payload=bytes((1,))+struct.pack('<H',round(duration*1000))+bytes((len(changed),))
    payload+=b''.join(struct.pack('<BH',sid,value) for sid,value in sorted(changed.items()))
    return packet(5,payload)

class WaveAudio:
    def __init__(self,directory,device='plughw:2,0',popen=subprocess.Popen,which=shutil.which):
        self.directory=Path(directory);self.device=device;self.popen=popen;self.which=which;self.process=None
    def preflight(self):
        if not self.which('aplay'):raise StopSampling('aplay_not_installed')
        for name in ('mm.wav','hey.wav'):
            with wave.open(str(self.directory/name),'rb') as f:
                if not .1<f.getnframes()/f.getframerate()<3 or f.getcomptype()!='NONE':raise StopSampling('invalid_audio_file')
    def start(self,text):
        names={'Mm?':'mm.wav','Hey.':'hey.wav'}
        if text not in names:raise StopSampling('unknown_vocalization')
        if self.process and self.process.poll() is None:raise StopSampling('audio_already_running')
        self.process=self.popen(['aplay','-q','-D',self.device,str(self.directory/names[text])],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def finished(self):
        code=self.process.poll() if self.process else 0
        if code not in (None,0):raise StopSampling('audio_playback_failed')
        return code==0
    def cancel(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=.5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=.5)

class Hardware:
    def __init__(self,sampler,audio,emit,pre_move=lambda:None,temperature_profile='rehearsal'):
        if temperature_profile not in ('rehearsal','recording'):
            raise ValueError('unknown_temperature_profile')
        self.s=sampler;self.audio=audio;self.emit=emit;self.pre_move=pre_move
        self.guard=Demo(sampler,emit,pre_move,rehearsal=True)
        if temperature_profile=='recording':self.guard.gate=RecordingTemperature(emit)
        gate=self.guard.gate
        emit(dict(kind='temperature_profile_selected',profile=gate.profile,
                  start_below=gate.start_limit,finish_at=gate.finish_limit,stop_at=gate.stop_limit,
                  hardware_limits_changed=False))
        self.arms=dict(IDLE);self.head=None;self.sent=False;self.cancelled=False;self.commanded_ids=set()
        self.observer=None;self.gaze=None;self.gaze_mode=None;self.allow_withdraw=False;self.on_withdraw=None;self.preset_gaze=False
        self.body_sway=None
        self.last_telemetry=None
    def configure_gaze(self,observer,on_withdraw=None):
        from live_gaze import GazeController
        self.observer=observer;self.gaze=GazeController();self.on_withdraw=on_withdraw
    def track_tick(self):
        if not self.observer:return
        observation=self.observer.read()
        result=self.gaze.update(observation,self.s.clock(),self.head or {'pitch':1500,'yaw':1530},
                                self.gaze_mode or 'off',self.allow_withdraw)
        if result['withdrawal'] and self.on_withdraw:
            self.on_withdraw(result['withdrawal']);self.emit(dict(kind='camera_hand_withdrawn',**result['withdrawal']))
        head=result['head'] if self.gaze_mode else None
        if head:
            self.s.ensure_owner()
            if self.s.clock()-self.guard.last_health>.15:raise StopSampling('stale_gaze_health')
            raw=targets_packet(4,{1:head['pitch'],2:head['yaw']},.12)
            if self.s.port.write(raw)!=len(raw):raise StopSampling('gaze_short_write')
            self.sent=True;self.head=head
            self.emit(dict(kind='live_gaze_command',target=head,target_kind=result['target'],observation_sequence=observation['sequence']))
    def health(self,force=False):
        # Temperature and per-servo voltage do not need a full bus sweep on
        # every gaze/ack tick. Pose and streamed battery remain checked each tick.
        now=self.s.clock()
        if force or self.last_telemetry is None or now-self.last_telemetry>=.35:
            self.guard.health();self.last_telemetry=self.s.clock()
            return
        self.s.ensure_owner();self.s.upright()
        if self.s.battery is None or self.s.clock()-self.s.battery[1]>.3:
            self.s.wait_fresh_battery(min(self.s.clock()+.3,self.s.deadline))
        if self.s.battery is None or self.s.clock()-self.s.battery[1]>.3:raise StopSampling('battery_stale')
        voltage_gate(self.s.battery[0])
        self.guard.last_health=self.s.clock()
    def prepare(self):
        self.s.synchronize();self.s.idle_until(min(self.s.clock()+1,self.s.deadline))
        self.guard.health(stable=True)
        actual={sid:self.s.read(sid,5,self.s.clock()+.5) for sid in IDLE}
        # Correct a small resting-position drift by an explicit slow return;
        # do not loosen the final position tolerance or assume it is already idle.
        if any(abs(actual[k]-IDLE[k])>8 for k in IDLE) and all(abs(actual[k]-IDLE[k])<=12 for k in IDLE):
            self.arms=actual
            self.emit(dict(kind='near_idle_restore',positions=actual,target=IDLE))
            self.return_idle()
        self.guard.prepare_start(True,recovery_only=True)
        self.guard.positions(IDLE,8)
        self.sent=bool(self.guard.sent)
    def tick(self,check=lambda:None):
        check()
        if self.s.clock()>=self.s.deadline:raise StopSampling('scene_deadline')
        self.health()
        self.track_tick()
        self.s.idle_until(min(self.s.clock()+.08,self.s.deadline))
        check()
    def read_positions(self,target,tolerance):
        until=min(self.s.clock()+.8,self.s.deadline)
        measured={sid:self.s.read(sid,5,until) for sid in IDLE}
        if any(abs(measured[sid]-target[sid])>tolerance for sid in IDLE):raise StopSampling('scene_position_mismatch')
        return measured
    def execute(self,step,check=lambda:None,returning=False):
        if 'arm_sequence' in step:
            raise StopSampling('legacy_hug_disabled')
        if 'care_sequence' in step:
            sequence=[{**s,'arms':{int(k):v for k,v in s['arms'].items()}} for s in step['care_sequence']]
            if sequence!=CARE_SEQUENCE:raise StopSampling('invalid_care_sequence')
            if self.arms!=CARE_ENTRY:raise StopSampling('care_entry_mismatch')
            previous=self.arms
            for s in sequence:
                targets_packet(5,s['arms'],s['move_s'])
                targets_packet(4,{1:step['head']['pitch'],2:step['head']['yaw']},s['move_s'])
                if max(abs(s['arms'][k]-previous[k]) for k in IDLE)>s['move_s']*35+.01:
                    raise StopSampling('care_speed_budget')
                previous=s['arms']
            for i,s in enumerate(sequence):
                self.emit(dict(kind='care_frame_started',frame=i+1))
                result=self.execute({**s,'head':step['head']},check,returning)
                self.emit(dict(kind='care_frame_completed',frame=i+1,**result))
            return {**result,'care_frames_verified':len(sequence)}
        if step.get('side_clearance'):
            return self.clearance_move({int(k):v for k,v in step['arms'].items()},step['head'],check,returning)
        self.gaze_mode=step.get('gaze_mode') if self.observer and not returning and not self.preset_gaze else None
        self.allow_withdraw=False
        if step.get('face_before_center') and self.observer and not returning and not self.preset_gaze:
            if {int(k):v for k,v in step['arms'].items()}!=IDLE or self.arms!=IDLE:
                raise StopSampling('face_outro_requires_idle_arms')
            self.gaze_mode='face';end=self.s.clock()+1.6
            while self.s.clock()<end:self.tick(check)
            self.gaze_mode=None
        if 'happy_sequence' in step:
            sequence=step['happy_sequence']
            normalized=[{**s,'arms':{int(k):v for k,v in s['arms'].items()}} for s in sequence]
            if normalized!=HAPPY_SEQUENCE:raise StopSampling('invalid_happy_sequence')
            previous=self.arms
            for s in normalized:
                targets_packet(5,s['arms'],s['move_s'])
                targets_packet(4,{1:s['head']['pitch'],2:s['head']['yaw']},s['move_s'])
                if max(abs(s['arms'][k]-previous[k]) for k in IDLE)>s['move_s']*100+.01:
                    raise StopSampling('scene_speed_budget')
                previous=s['arms']
            if self.body_sway:
                try:self.body_sway.prepare(normalize=True)
                except StopSampling as error:
                    if str(error)!='body_not_at_standing_entry':raise
                    # No leg write has occurred for an incompatible entry.
                    # Keep the standing pose and perform the full arm/head cheer.
                    self.emit(dict(kind='body_sway_skipped',reason=str(error),positions=self.body_sway.base))
                    self.body_sway=None
            for i,s in enumerate(normalized):
                self.emit(dict(kind='happy_frame_started',frame=i+1))
                if self.body_sway:self.body_sway.start(i,s['move_s'])
                result=self.execute(s,check,returning)
                if self.body_sway:self.body_sway.verify(i)
                self.emit(dict(kind='happy_frame_completed',frame=i+1,**result))
            return {**result,'happy_frames_verified':len(normalized)}
        arms={int(k):v for k,v in step['arms'].items()};head=step['head']
        duration=max(.7,float(step['move_s']))
        if max(abs(arms[k]-self.arms[k]) for k in IDLE)>duration*100+.01:raise StopSampling('scene_speed_budget')
        # Build and validate both complete packets before sending either.
        arm_packet=changed_arm_packet(arms,self.arms,duration)
        head_target={1:head['pitch'],2:head['yaw']}
        head_packet=targets_packet(4,head_target,duration)
        self.pre_move();check();self.health(force=True);self.s.ensure_owner()
        if self.guard.gate.finish_requested and not returning:raise FinishTake('temperature_finish_before_next_step')
        if self.s.clock()-self.guard.last_health>.15:raise StopSampling('stale_scene_health')
        began=self.s.clock();moved=False
        if arm_packet is not None:
            self.commanded_ids.update(sid for sid in IDLE if arms[sid]!=self.arms[sid])
            self.sent=True;moved=True
            if self.s.port.write(arm_packet)!=len(arm_packet):raise StopSampling('scene_arm_short_write')
            self.emit(dict(kind='scene_arm_command',target=arms,duration=duration,
                           commanded_ids=[sid for sid in IDLE if arms[sid]!=self.arms[sid]],raw=arm_packet.hex()))
        if not self.gaze_mode and head!=self.head:
            self.sent=True;moved=True
            if self.s.port.write(head_packet)!=len(head_packet):raise StopSampling('scene_head_short_write')
            self.emit(dict(kind='scene_head_command',target=head,duration=duration,raw=head_packet.hex()))
        spoken=bool(step.get('utterance'))
        if spoken:self.audio.start(step['utterance'])
        end=began+(duration if moved or self.gaze_mode else 0)+float(step.get('hold_s',0))
        next_position_sample=began+.25
        changed_ids=tuple(sid for sid in IDLE if arms[sid]!=self.arms[sid])
        while self.s.clock()<end or (spoken and not self.audio.finished()):
            self.tick(check)
            if changed_ids and self.s.clock()>=next_position_sample:
                sampled={sid:self.s.read(sid,5,min(self.s.clock()+.4,self.s.deadline)) for sid in changed_ids}
                self.emit(dict(kind='motion_position_sample',positions=sampled,
                               target={sid:arms[sid] for sid in changed_ids},
                               imu_latest=list(self.s.imu[-1][1]) if getattr(self.s,'imu',None) else None))
                next_position_sample=self.s.clock()+.25
            if spoken and self.s.clock()-began>max(duration+float(step.get('hold_s',0)),3)+1:raise StopSampling('audio_timeout')
            if self.guard.gate.finish_requested and self.s.clock()>=began+(duration if moved else 0) and (not spoken or self.audio.finished()):break
        measured=self.read_positions(arms,8 if arms==IDLE else 12)
        self.arms=arms
        if not self.gaze_mode:self.head=dict(head)
        return dict(positions=measured,arms_verified=True,head_status='command_time_elapsed',
                    head_observed=False,audio_status='process_completed' if spoken else 'not_requested')
    def return_idle(self,check=lambda:None):
        # Only used after a completed/verified phase or an ordinary wait timeout.
        # Never called automatically after CRC, position, power, posture or stop faults.
        duration=max(2.4,max(abs(self.arms[k]-IDLE[k]) for k in IDLE)/100)
        result=self.execute(dict(arms=IDLE,head={'pitch':1500,'yaw':1530},move_s=duration,hold_s=0),check,returning=True)
        self.guard.settle();self.guard.health(stable=True)
        return result

    def clearance_move(self,target,head,check=lambda:None,returning=False):
        # Confirmed outward signs: left 7 decreases, right 15 increases.
        # Keep the side clearance until the front/back motion has completed.
        outward={**self.arms,7:min(self.arms[7],777),15:max(self.arms[15],246)}
        passing={**target,7:outward[7],15:outward[15]}
        previous=self.arms;planned=[]
        for arms in (outward,passing,target):
            duration=max(1.2,max(abs(arms[k]-previous[k]) for k in IDLE)/65)
            targets_packet(5,arms,duration)
            planned.append(dict(arms=arms,head=head,move_s=duration,hold_s=.15));previous=arms
        for i,step in enumerate(planned):
            self.emit(dict(kind='side_clearance_segment',segment=i+1,target=step['arms']))
            result=self.execute(step,check,returning)
        return result
    def cancel(self):
        if self.cancelled:return
        self.cancelled=True
        self.gaze_mode=None;self.allow_withdraw=False
        self.audio.cancel()
        ids=tuple(sorted(self.commanded_ids|({14,15,16} if self.guard.sent else set())))
        if not ids:return
        try:
            self.s.ensure_owner()
            raw=packet(5,bytes((3,len(ids),*ids)))
            n=self.s.port.write(raw)
            self.emit(dict(kind='scene_stop_unconfirmed',complete_write=n==len(raw),torque_released=False,
                           commanded_ids=list(ids),raw=raw.hex()))
        except Exception:self.emit(dict(kind='scene_stop_unavailable',torque_released=False))
