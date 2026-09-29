"""Candidate supervised four-stage demo. Default offline; --run only preflights.

--run --motion permits ONE historical right-arm sequence, never new routes.
Cancellation does not remove torque. Operator must support and power off on fault.
Not commissioned on hardware; no web bridge or autonomous invocation.
"""
from contextlib import ExitStack
import argparse
import json
import math
import signal
import statistics
import struct
import time
from pathlib import Path
from thermal_sample import Sampler, ThermalGate, StopSampling, crc8, request_packet, decode_reply, check_services_and_port, voltage_gate

IDLE = {6:535,7:803,8:690,14:425,15:200,16:275}
STAGES = (
    ('hey', (399,204,401), 1.6, .6),
    ('hesitate', (412,202,338), 1.2, .45),
    ('invite_again', (399,204,401), 1.4, .8),
    ('rest', (425,200,275), 2.4, 0),
)
RIGHT = (14,15,16)


class RehearsalTemperature:
    """Only for one supervised historical sequence; not a device safety rating.

    Start below 45; relative +5 is advisory below 50. At 50 select rest
    after the current move, without optional holds. At 55 abort.
    These are provisional short-take limits, not datasheet internal ratings.
    Never used by the diagnostic sampler or automatic startup.
    """
    profile='rehearsal'
    start_limit=45
    finish_limit=50
    stop_limit=55

    def __init__(self,emit):
        self.baseline={};self.warned=set();self.finish_requested=False;self.emit=emit

    def check(self,sid,value):
        if type(value) is not int or not 0<=value<=125:
            raise StopSampling('temperature_implausible')
        if value>=self.stop_limit:raise StopSampling(f'{self.profile}_temperature_at_least_{self.stop_limit}')
        if sid not in self.baseline:
            if value>=self.start_limit:raise StopSampling(f'{self.profile}_start_at_least_{self.start_limit}')
            self.baseline[sid]=value
        if value-self.baseline[sid]>=5 and sid not in self.warned:
            self.warned.add(sid)
            self.emit(dict(kind='temperature_advisory',servo_id=sid,value=value,
                           rise=value-self.baseline[sid],action='continue_bounded_take'))
        if value>=self.finish_limit and not self.finish_requested:
            self.finish_requested=True
            self.emit(dict(kind='finish_requested',servo_id=sid,value=value,
                           reason=f'temperature_at_least_{self.finish_limit}'))


class RecordingTemperature(RehearsalTemperature):
    """Explicit temporary software profile; not a manufacturer rating.

    No device limits or torque settings are written. Refuse a new take at 75,
    finish an existing move and return at 75, abort at 80.
    """
    profile='recording'
    start_limit=75
    finish_limit=75
    stop_limit=80

    def __init__(self,emit):
        super().__init__(emit);self.defer_finish=False;self.deferred_peaks={}

    def check(self,sid,value):
        if not self.defer_finish:return super().check(sid,value)
        if type(value) is not int or not 0<=value<=125:raise StopSampling('temperature_implausible')
        if value>=self.stop_limit:raise StopSampling('recording_temperature_at_least_80')
        self.baseline.setdefault(sid,value)
        if value>=self.finish_limit:
            self.deferred_peaks[sid]=max(value,self.deferred_peaks.get(sid,0))
        # Only an already-preflighted full take may defer the soft reminder.
        # No hardware limit, hard-stop threshold or malformed read is bypassed.


def frame(payload):
    body=bytes((5,len(payload)))+payload
    return b'\xaa\x55'+body+bytes((crc8(body),))


def position_request(sid, command):
    if command != 5:
        return request_packet(sid,command)
    if type(sid) is not int or sid not in IDLE:
        raise StopSampling('position_id_not_allowed')
    return frame(bytes((5,sid)))


def position_reply(payload,sid,command):
    if command != 5:
        return decode_reply(payload,sid,command)
    if len(payload)!=5: raise StopSampling('position_reply_length')
    rid,cmd,status,value=struct.unpack('<BBbh',payload)
    if (rid,cmd,status)!=(sid,5,0) or not 0<=value<=1000:
        raise StopSampling('position_reply_invalid')
    return value


def move_packet(index):
    if type(index) is not int or not 0<=index<len(STAGES):
        raise StopSampling('stage_not_allowed')
    _,pose,duration,_=STAGES[index]
    payload=bytes((1,))+struct.pack('<H',round(duration*1000))+bytes((3,))
    return frame(payload+b''.join(struct.pack('<BH',sid,v) for sid,v in zip(RIGHT,pose)))


class DemoSampler(Sampler):
    make_request=staticmethod(position_request)
    parse_reply=staticmethod(position_reply)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.imu=[]
        self.buffered=False
        self.read_retries=0

    def read(self,sid,command,round_deadline):
        try:return super().read(sid,command,round_deadline)
        except StopSampling as error:
            # A correctly framed vendor status -1 contains no measurement.
            # Retry only this read once, within its original deadline; never
            # reuse an old value, retry motion, or suppress CRC/identity errors.
            if str(error)!='device_error:-1' or command not in (5,7,9) or self.read_retries>=3:
                raise
            if min(round_deadline,self.deadline)-self.clock()<.18:raise
            self.read_retries+=1
            self.emit(dict(kind='measurement_read_retry',servo_id=sid,command=command,attempt=1,
                           session_retry_count=self.read_retries))
            self.idle_until(self.clock()+.12)
            return super().read(sid,command,round_deadline)

    def drain_before_request(self,until):
        self.buffered=True
        try: super().drain_before_request(until)
        finally: self.buffered=False

    def receive(self,byte,received):
        frames=super().receive(byte,received)
        for function,payload,_ in frames:
            if function==7 and not self.buffered:
                if len(payload)!=24: raise StopSampling('imu_length')
                values=struct.unpack('<6f',payload)
                if not all(math.isfinite(v) for v in values): raise StopSampling('imu_nonfinite')
                self.imu.append((received,values));self.imu=self.imu[-100:]
        return frames

    def upright(self,stable=False):
        now=self.clock()
        recent=[v for t,v in self.imu if now-t<=.6]
        if not self.imu or now-self.imu[-1][0]>.3 or len(recent)<(20 if stable else 3):
            raise StopSampling('imu_missing_or_stale')
        for ax,ay,az,*_ in recent:
            if not (-1.15<=ax<=-.85 and abs(ay)<=.30 and abs(az)<=.35
                    and .8<=math.sqrt(ax*ax+ay*ay+az*az)<=1.2):
                self.emit(dict(kind='upright_rejected',sample=[ax,ay,az],
                               recent_samples=[{'age':round(now-t,4),'values':list(v)} for t,v in self.imu if now-t<=.6]))
                raise StopSampling('upright_gate')
        if stable:
            std=[statistics.pstdev(a) for a in zip(*recent)]
            self.emit(dict(kind='stability_window',sample_count=len(recent),std=std,
                           newest_age=now-self.imu[-1][0]))
            if max(std[:3])>.04 or max(std[3:])>.75: raise StopSampling('stability_gate')


class Demo:
    def __init__(self,sampler,emit,pre_move=lambda:None,rehearsal=False):
        self.s=sampler;self.emit=emit;self.rehearsal=rehearsal
        self.gate=RehearsalTemperature(emit) if rehearsal else ThermalGate()
        self.sent=0;self.started=False
        self.last_health=None
        self.pre_move=pre_move

    def health(self,stable=False):
        s=self.s;start=s.clock();until=min(start+.8,s.deadline)
        temps={}
        for sid in IDLE:
            temps[sid]=s.read(sid,9,until);self.gate.check(sid,temps[sid])
        for sid in RIGHT: voltage_gate(s.read(sid,7,until))
        if s.battery is None or s.clock()-s.battery[1]>.3:s.wait_fresh_battery(until)
        if s.battery is None or s.clock()-s.battery[1]>.3: raise StopSampling('battery_stale')
        voltage_gate(s.battery[0]);s.upright(stable)
        if s.clock()-start>.8: raise StopSampling('health_snapshot_too_slow')
        self.last_health=s.clock()
        self.emit(dict(kind='health_pass',temperatures=temps,battery_mv=s.battery[0]))

    def positions(self,target,tolerance):
        until=min(self.s.clock()+.8,self.s.deadline)
        measured={sid:self.s.read(sid,5,until) for sid in IDLE}
        if any(abs(measured[sid]-target[sid])>(tolerance if sid in RIGHT else 8) for sid in IDLE):
            raise StopSampling('position_gate:'+json.dumps(measured))
        self.emit(dict(kind='positions_pass',positions=measured,tolerance=tolerance))

    def prepare_start(self,motion,recovery_only=False):
        until=min(self.s.clock()+.8,self.s.deadline)
        measured={sid:self.s.read(sid,5,until) for sid in IDLE}
        self.emit(dict(kind='start_positions',positions=measured))
        if all(abs(measured[sid]-IDLE[sid])<=8 for sid in IDLE):
            return
        # Narrow commissioning entry: only forearm 16 may be partly raised.
        # This is a bounded candidate, not arbitrary-pose collision clearance.
        allowed=all(abs(measured[sid]-IDLE[sid])<=8 for sid in IDLE if sid!=16)
        allowed=allowed and 267<=measured[16]<=346
        if recovery_only:
            allowed=(all(abs(measured[sid]-IDLE[sid])<=8 for sid in (6,7,8))
                     and 391<=measured[14]<=433 and 192<=measured[15]<=212
                     and 267<=measured[16]<=409)
        if not motion or not allowed:
            raise StopSampling('start_outside_recovery_entry:'+json.dumps(measured))
        self.pre_move();self.health(stable=True);self.s.ensure_owner()
        if self.s.clock()>=self.s.deadline or self.s.clock()-self.last_health>.15:
            raise StopSampling('stale_recovery_health')
        packet=move_packet(3) # Same fixed right-arm rest target, 2.4 seconds.
        self.sent+=1
        if self.s.port.write(packet)!=len(packet):raise StopSampling('recovery_short_write')
        self.emit(dict(kind='recovery_sent',target=dict(zip(RIGHT,STAGES[3][1]))))
        end=self.s.clock()+2.65
        while self.s.clock()<end:
            self.health()
            self.s.idle_until(min(self.s.clock()+.1,end,self.s.deadline))
            if self.s.clock()>=self.s.deadline:raise StopSampling('recovery_deadline')
        self.positions(IDLE,8);self.settle();self.health(stable=True)
        self.emit(dict(kind='recovery_complete'))

    def settle(self):
        # A fresh quiet window excludes IMU samples from the commanded move.
        # Still enforce temperature/upright/ownership; never relax thresholds.
        end=self.s.clock()+.7
        while self.s.clock()<end:
            self.health()
            self.s.idle_until(min(self.s.clock()+.1,end,self.s.deadline))
            if self.s.clock()>=self.s.deadline:raise StopSampling('settle_deadline')

    def run(self,motion=False,recovery_only=False):
        if self.started: raise StopSampling('demo_not_reentrant')
        self.started=True
        s=self.s;s.synchronize();s.idle_until(min(s.clock()+1.0,s.deadline))
        self.health(stable=True);self.prepare_start(motion or recovery_only,recovery_only or self.rehearsal);self.positions(IDLE,8)
        if recovery_only:
            self.emit(dict(kind='recovery_only_complete',motion_commands=self.sent));return
        if not motion:
            self.emit(dict(kind='preflight_only_complete',motion_commands=0));return
        early_finish=False
        for index,(name,pose,duration,hold) in enumerate(STAGES):
            self.pre_move()
            finishing=self.rehearsal and self.gate.finish_requested
            self.health(stable=not finishing)
            if self.rehearsal and self.gate.finish_requested and index<3:
                if self.sent==0:
                    self.positions(IDLE,8)
                    self.emit(dict(kind='take_skipped_at_idle',reason='temperature_finish_request'))
                    return
                index=3;name,pose,duration,hold=STAGES[3];early_finish=True
            s.ensure_owner()
            if s.clock()>=s.deadline or s.clock()-self.last_health>.15:
                raise StopSampling('stale_pre_move_health')
            packet=move_packet(index)
            self.sent+=1 # A partial write still counts as a possible motion.
            if s.port.write(packet)!=len(packet): raise StopSampling('motion_short_write')
            began=s.clock();self.emit(dict(kind='motion_sent',stage=name,index=index))
            # Poll throughout the move; no sleeping blind through the whole action.
            while s.clock()<began+duration+.25+hold:
                self.health()
                if (self.rehearsal and self.gate.finish_requested and index<3
                        and s.clock()>=began+duration+.25):
                    break # Do not keep the raised arm in an optional dramatic hold.
                s.idle_until(min(s.clock()+.1,began+duration+.25+hold,s.deadline))
                if s.clock()>=s.deadline: raise StopSampling('demo_deadline')
            target={**IDLE,**dict(zip(RIGHT,pose))}
            self.positions(target,8 if name=='rest' else 12)
            if not (self.rehearsal and self.gate.finish_requested and index<3):
                self.settle();self.health(stable=True)
            self.emit(dict(kind='stage_complete',stage=name))
            if index==3:break
        self.emit(dict(kind='take_closed_early' if early_finish else 'demo_complete',
                       motion_commands=self.sent,final_pose='idle_verified'))

    def cancel(self):
        # Best-effort SDK stop for exactly the commanded arm. No recovery/torque writes.
        if not self.sent:return
        try:
            self.s.ensure_owner()
            packet=frame(bytes((3,3,*RIGHT)))
            written=self.s.port.write(packet)
            self.emit(dict(kind='stop_sent_unconfirmed',complete_write=written==len(packet),
                           torque_released=False,operator_power_off_required=True))
        except Exception as error:
            self.emit(dict(kind='stop_unavailable',reason=str(error),operator_power_off_required=True))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--motion',action='store_true')
    parser.add_argument('--recover-only',action='store_true',help='One bounded right-arm return; never starts demonstration')
    parser.add_argument('--rehearsal',action='store_true',help='Supervised one-take warning/finish policy, historical right arm only')
    args=parser.parse_args()
    if args.rehearsal and (not args.run or not args.motion or args.recover_only):
        parser.error('--rehearsal requires --run --motion and excludes --recover-only')
    if not args.run:parser.print_help();return 0
    import fcntl
    import serial
    begin=time.monotonic();demo=None
    def emit(item):print(json.dumps(dict(elapsed=round(time.monotonic()-begin,3),**item)),flush=True)
    def abort(*_):raise StopSampling('signal_or_deadline')
    for sig in (signal.SIGALRM,signal.SIGTERM,signal.SIGINT):signal.signal(sig,abort)
    signal.setitimer(signal.ITIMER_REAL,35)
    try:
        with ExitStack() as stack:
            for path in ('/home/pi/yushi/yushi_client.lock','/tmp/tonypi-controller-serial.lock'):
                lock=stack.enter_context(open(path,'a'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            check_services_and_port()
            port=serial.Serial(None,1000000,timeout=.02,write_timeout=.2,exclusive=True)
            stack.callback(port.close);port.rts=False;port.dtr=False;port.port='/dev/ttyAMA0';port.open()
            port.reset_input_buffer()
            # Full service/port checks before each move; owner checks in receive loops.
            from thermal_sample import ensure_owner
            sampler=DemoSampler(port,begin+33,emit,ensure_owner)
            demo=Demo(sampler,emit,check_services_and_port,rehearsal=args.rehearsal)
            try:demo.run(args.motion,args.recover_only)
            except BaseException:
                demo.cancel();raise
        return 0
    except (Exception,KeyboardInterrupt) as error:
        emit(dict(kind='demo_cancelled',reason=str(error),motion_commands=demo.sent if demo else 0));return 1
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        # Closing a session is not itself a fault or a request to power-cycle.
        # Fault-specific cancellation above reports when operator help is needed.
        emit(dict(kind='session_closed',torque_released=False))


if __name__=='__main__':raise SystemExit(main())
