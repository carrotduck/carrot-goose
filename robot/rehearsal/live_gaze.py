"""Pure camera-coordinate controller. No hardware or camera imports."""
import math

class GazeController:
    def __init__(self):
        self.sequence=-1;self.last_frame=None;self.target=None;self.target_since=0
        self.filtered=None;self.last_move=None;self.hand_frames=0;self.missing_since=None
        self.withdrawn=False

    def update(self,observation,now,current,mode='auto',allow_withdraw=False):
        if mode not in ('auto','face','hand','off'):raise ValueError('invalid_gaze_mode')
        result={'head':None,'withdrawal':None,'target':None}
        if not observation or observation.get('error'):return result
        stamp=observation.get('time');sequence=observation.get('sequence')
        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or not 0<=now-stamp<=.35:return result
        if not isinstance(sequence,int) or sequence<=self.sequence:return result
        self.sequence=sequence
        contiguous=self.last_frame is not None and 0<stamp-self.last_frame<=.35
        self.last_frame=stamp
        def point(kind):
            p=observation.get(kind)
            if not p or len(p)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in p):return None
            return p
        hand,face=point('hand'),point('face')
        if not contiguous:self.hand_frames=0;self.missing_since=None
        if hand:
            self.hand_frames=min(5,self.hand_frames+1);self.missing_since=None
        elif observation.get('hand_present'):
            self.missing_since=None # Folding the index is not withdrawing a hand.
        elif self.hand_frames>=3:
            if self.missing_since is None:self.missing_since=stamp
            if allow_withdraw and .9<=stamp-self.missing_since<=30 and not self.withdrawn:
                self.withdrawn=True
                result['withdrawal']={'source':'camera','seen_frames':self.hand_frames,'absent_ms':round((stamp-self.missing_since)*1000),'observation_age_ms':round((now-stamp)*1000)}
        # Explicit face beats hand during face-directed beats; auto gives a
        # stable pointing finger priority, with a short loss grace period.
        kind='face' if mode=='face' and face else 'hand' if mode=='hand' and hand else None
        if mode=='auto':
            if hand and self.hand_frames>=3:kind='hand'
            elif self.target=='hand' and self.missing_since is not None and stamp-self.missing_since<.45:return result
            elif face:kind='face'
        p=hand if kind=='hand' else face if kind=='face' else None
        if p is None:return result # Never chase an old coordinate or scan blindly.
        if kind!=self.target:self.filtered=None;self.target=kind
        self.filtered=list(p) if self.filtered is None else [.7*v+.3*old for v,old in zip(p,self.filtered)]
        result['target']=kind
        if self.last_move is not None and now-self.last_move<.1:return result
        dt=.1 if self.last_move is None else min(.2,now-self.last_move)
        # Same camera signs as the earlier tonypi_seek controller. Adaptive
        # proportional velocity with deadzone and rate limits, not angle jumps.
        ex,ey=.5-self.filtered[0],.5-self.filtered[1]
        dy=0 if abs(ex)<.025 else max(-220,min(220,ex*520))*dt
        dp=0 if abs(ey)<.03 else max(-180,min(180,ey*450))*dt
        head={'yaw':max(1410,min(1650,round(current['yaw']+dy))),
              'pitch':max(1400,min(1650,round(current['pitch']+dp)))}
        self.last_move=now
        if head!=current:result['head']=head
        return result


def enable_live_gaze(plan):
    import copy
    result=copy.deepcopy(plan)
    # Scripted nods, arm gestures and HUG retain exclusive ownership. Only
    # attentive opening beats and selected pauses receive live gaze control.
    modes={1:'face',2:'auto',3:'auto',4:'auto',5:'auto',6:'hand',7:'face',
           8:'hand',9:'face',10:'auto',11:'auto',12:'face',17:'auto'}
    for i,mode in modes.items():result['steps'][i]['gaze_mode']=mode
    result['live_gaze']=True
    return result
