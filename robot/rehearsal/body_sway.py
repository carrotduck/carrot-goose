"""Explicit small body candidate derived from factory twist.d6a; never auto-runs."""
import struct
from guarded_invitation import DemoSampler,position_request,frame
from thermal_sample import StopSampling,voltage_gate

LEG_IDS=(1,2,3,4,5,9,10,11,12,13)
STAND=dict(zip(LEG_IDS,(500,388,500,594,500,500,612,500,406,500)))
TWIST_A=dict(zip(LEG_IDS,(560,368,528,608,612,526,578,584,455,575)))
TWIST_B=dict(zip(LEG_IDS,(473,421,415,545,425,440,631,471,391,387)))

class BodySampler(DemoSampler):
    @staticmethod
    def make_request(sid,command):
        if sid in LEG_IDS and command in (5,7,9):return frame(bytes((command,sid)))
        return position_request(sid,command)

def candidates(base):
    if set(base)!=set(LEG_IDS) or any(type(base[k]) is not int or abs(base[k]-STAND[k])>18 for k in LEG_IDS):
        raise StopSampling('body_not_at_standing_entry')
    return [{k:base[k]+round(.2*(source[k]-STAND[k])) for k in LEG_IDS}
            for source in (TWIST_A,TWIST_B,TWIST_A,TWIST_B,STAND)]

def body_packet(base,index,duration):
    if type(index) is not int or not 0<=index<5 or not .9<=duration<=2:
        raise StopSampling('invalid_body_segment')
    target=candidates(base)[index]
    payload=bytes((1,))+struct.pack('<H',round(duration*1000))+bytes((len(LEG_IDS),))
    return frame(payload+b''.join(struct.pack('<BH',k,target[k]) for k in LEG_IDS))

class BodySway:
    def __init__(self,hardware):self.h=hardware;self.base=None
    def read_pose(self):
        s=self.h.s
        return {k:s.read(k,5,s.clock()+.5) for k in LEG_IDS}
    def health(self):
        s=self.h.s
        for k in LEG_IDS:
            self.h.guard.gate.check(k,s.read(k,9,s.clock()+.5))
            voltage_gate(s.read(k,7,s.clock()+.5))
        self.h.health()
    def prepare(self,normalize=False):
        self.health();self.h.guard.health(stable=True)
        self.base=self.read_pose()
        if any(abs(self.base[k]-STAND[k])>18 for k in LEG_IDS):
            if not normalize or any(abs(self.base[k]-STAND[k])>35 for k in LEG_IDS):
                raise StopSampling('body_not_at_standing_entry')
            self.h.s.ensure_owner();self.h.commanded_ids.update(LEG_IDS)
            raw=body_packet(STAND,4,2)
            if self.h.s.port.write(raw)!=len(raw):raise StopSampling('body_center_short_write')
            self.h.emit(dict(kind='body_stand_restore',from_positions=self.base,target=STAND,duration=2))
            end=self.h.s.clock()+2.2
            while self.h.s.clock()<end:self.h.tick()
            actual=self.read_pose()
            if any(abs(actual[k]-STAND[k])>10 for k in LEG_IDS):raise StopSampling('body_center_position_mismatch')
            self.h.guard.settle();self.h.guard.health(stable=True)
            self.base=dict(STAND)
        candidates(self.base)
        self.h.emit(dict(kind='body_sway_entry',positions=self.base,scale=.2,source='twist.d6a'))
    def start(self,index,duration):
        raw=body_packet(self.base,index,duration)
        self.health();self.h.s.ensure_owner()
        if self.h.guard.gate.finish_requested:raise StopSampling('body_temperature_finish')
        self.h.commanded_ids.update(LEG_IDS)
        if self.h.s.port.write(raw)!=len(raw):raise StopSampling('body_short_write')
        self.h.emit(dict(kind='body_sway_command',frame=index+1,target=candidates(self.base)[index],duration=duration))
    def verify(self,index):
        target=candidates(self.base)[index];actual=self.read_pose()
        if any(abs(actual[k]-target[k])>10 for k in LEG_IDS):raise StopSampling('body_position_mismatch')
        self.h.emit(dict(kind='body_sway_verified',frame=index+1,positions=actual))
