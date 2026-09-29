import unittest
from scene_sequence import Scene,SceneError,EVENTS
def receipt(event,now=0):
    return dict(schema='duck-body-receipt/v1',mode='receipts_only',take_id='take',user_id='user',event=event,
                sequence=EVENTS.index(event)+1,expires_at=now+120000,source='operator' if event=='hand_withdrawn' else 'web_text_committed',
                user_message_id=event+'-user',assistant_message_id=event+'-reply',reply_to_message_id=event+'-user')
class SceneTests(unittest.TestCase):
    def finish(self,s,a):s.complete(a['action_id'],success=True,arms_verified=True,head_observed=True,audio_completed=True)
    def test_full_scene_waits_then_executes_once_and_ends_at_idle(self):
        s=Scene('take','user');actions=[];events=[]
        for _ in range(100):
            n=s.next(0)
            if n['state']=='complete':break
            if n['state']=='waiting':
                self.assertEqual(s.next(99999999),n) # No timer fallback before an event.
                r=receipt(n['event']);s.accept(r,0);self.assertFalse(s.accept(r,0));events.append(r['event'])
            else:
                a=n['action'];self.assertEqual(s.next(0)['state'],'await_completion')
                actions.append(a);self.finish(s,a)
        self.assertEqual(len(actions),31)
        self.assertEqual(events,list(EVENTS))
        self.assertEqual(actions[-1]['arms'],actions[0]['arms'])
        self.assertEqual(actions[-1]['head'],{'pitch':1500,'yaw':1530})

    def test_early_hug_does_not_skip_intervening_actions(self):
        s=Scene('take','user')
        for e in EVENTS:s.accept(receipt(e),0)
        labels=[]
        for _ in range(31):
            a=s.next(0)['action'];labels.append(a['label']);self.finish(s,a)
        self.assertLess(next(i for i,x in enumerate(labels) if '犹豫' in x),next(i for i,x in enumerate(labels) if '邀请拥抱' in x))

    def test_failure_or_cancel_prevents_any_further_dispatch(self):
        for fail in (True,False):
            s=Scene('take','user');a=s.next(0)['action']
            if fail:s.complete(a['action_id'],success=False)
            else:s.cancel()
            self.assertEqual(s.next(0)['state'],'closed')

    def test_rejects_wrong_session_stale_and_out_of_order(self):
        for patch in ({'take_id':'other'},{'expires_at':-1},{'mode':'hardware'},{'reply_to_message_id':'wrong'}):
            with self.assertRaises(SceneError):Scene('take','user').accept({**receipt('happy_reply'),**patch},0)
        with self.assertRaises(SceneError):Scene('take','user').accept(receipt('hug_reply'),0)

    def test_audio_and_arm_receipts_are_not_invented(self):
        s=Scene('take','user');a=s.next(0)['action']
        with self.assertRaises(SceneError):s.complete(a['action_id'],success=True)
        while not a['utterance']:
            self.finish(s,a);a=s.next(0)['action']
        with self.assertRaises(SceneError):s.complete(a['action_id'],success=True,arms_verified=True)
if __name__=='__main__':unittest.main()
