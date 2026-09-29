"""Receipt-driven full scene sequencer. Hardware-free, one explicit completion per action.

The output is an intent for a commissioned executor, never servo authority.
No time-based substitute for text/withdrawal events and no invented audio receipts.
"""
import json
import math
from pathlib import Path

EVENTS=('happy_reply','hand_withdrawn','hug_reply')
class SceneError(RuntimeError):pass

def load_scene():
    return json.loads((Path(__file__).parent/'full_scene_candidate.json').read_text(encoding='utf-8'))

class Scene:
    def __init__(self,take_id,user_id,plan=None):
        self.take_id,self.user_id=take_id,user_id
        self.plan=plan or load_scene()
        self.index=0;self.pending=None;self.receipts={};self.closed=False
        self.device_receipts=[]

    def accept(self,receipt,now_ms):
        if self.closed:raise SceneError('scene_closed')
        if receipt.get('schema')!='duck-body-receipt/v1' or receipt.get('mode')!='receipts_only':raise SceneError('invalid_receipt')
        if receipt.get('take_id')!=self.take_id or receipt.get('user_id')!=self.user_id:raise SceneError('wrong_take_or_account')
        event=receipt.get('event')
        if event not in EVENTS or type(receipt.get('expires_at')) not in (int,float) or not math.isfinite(receipt['expires_at']) or receipt['expires_at']<=now_ms:raise SceneError('unknown_or_expired_event')
        if receipt.get('sequence')!=EVENTS.index(event)+1:raise SceneError('wrong_sequence')
        if event in self.receipts:
            if self.receipts[event]!=receipt:raise SceneError('conflicting_duplicate')
            return False
        if event!=EVENTS[len(self.receipts)]:raise SceneError('predecessor_missing')
        if event=='hand_withdrawn':
            if receipt.get('source') not in ('operator','camera','choreography'):raise SceneError('withdrawal_not_confirmed')
            if receipt.get('source')=='choreography':
                if not self.plan.get('choreographed_withdrawal') or receipt.get('completed_step')!=17 or receipt.get('pause_ms')!=3000 or receipt.get('physical_withdrawal_observed') is not False:
                    raise SceneError('invalid_choreography_cue')
            if receipt.get('source')=='camera':
                if not (type(receipt.get('seen_frames')) is int and 3<=receipt['seen_frames']<=1000
                        and type(receipt.get('absent_ms')) is int and 900<=receipt['absent_ms']<=30000
                        and type(receipt.get('observation_age_ms')) is int and 0<=receipt['observation_age_ms']<=350):
                    raise SceneError('invalid_camera_withdrawal')
        elif receipt.get('source')!='web_text_committed' or not receipt.get('assistant_message_id') or receipt.get('reply_to_message_id')!=receipt.get('user_message_id'):
            raise SceneError('unmatched_text')
        self.receipts[event]=dict(receipt)
        return True

    def next(self,now_ms):
        if self.closed:return {'state':'closed'}
        if self.pending:return {'state':'await_completion','action_id':self.pending['action_id']}
        if self.index==len(self.plan['steps']):return {'state':'complete','executed_steps':self.index}
        step=self.plan['steps'][self.index]
        gate=step.get('gate')
        if gate:
            receipt=self.receipts.get(gate)
            if not receipt:return {'state':'waiting','event':gate,'arms_raised':step['wait_arms_raised']}
            if receipt['expires_at']<=now_ms:raise SceneError('unconsumed_event_expired')
        self.pending={**step,'action_id':f'{self.take_id}:{self.index}',
                      'mode':'candidate_intent','hardware_commissioned':False}
        return {'state':'dispatch','action':self.pending}

    def complete(self,action_id,*,success,arms_verified=False,head_observed=False,audio_completed=False):
        if self.closed:raise SceneError('scene_closed')
        if not self.pending or self.pending['action_id']!=action_id:raise SceneError('wrong_action_receipt')
        if not success:
            self.closed=True;self.pending=None;return
        if not arms_verified:raise SceneError('arm_result_unverified')
        if self.pending.get('utterance') and not audio_completed:raise SceneError('audio_not_complete')
        self.device_receipts.append({'action_id':action_id,'arms_verified':arms_verified,'head_observed':head_observed,'audio_completed':audio_completed})
        self.index+=1;self.pending=None

    def cancel(self):
        self.closed=True;self.pending=None;self.receipts.clear()
