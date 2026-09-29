import unittest
from types import SimpleNamespace
from guarded_invitation import DemoSampler
from thermal_sample import StopSampling,Frames,decode_reply

class DiagnosticsTests(unittest.TestCase):
    def test_rejected_window_preserves_actual_values_without_relaxing_gate(self):
        rows=[]
        samples=[(10-i*.01,(-1.,0.,0.,0.,0.,0.)) for i in range(30)]
        samples[4]=(9.96,(-1.18,.04,.02,0.,0.,0.))
        s=SimpleNamespace(clock=lambda:10,imu=sorted(samples),emit=rows.append)
        with self.assertRaisesRegex(StopSampling,'upright_gate'):DemoSampler.upright(s)
        self.assertEqual(rows[0]['kind'],'upright_rejected')
        self.assertEqual(rows[0]['sample'],[-1.18,.04,.02])
        self.assertEqual(len(rows[0]['recent_samples']),30)
    def test_valid_upright_window_still_passes(self):
        s=SimpleNamespace(clock=lambda:10,imu=[(9.71+i*.01,(-1.,0.,0.,0.,0.,0.)) for i in range(30)],emit=lambda _:None)
        DemoSampler.upright(s,stable=True)
    def test_actual_70_degree_frame_is_crc_valid_and_matches_servo_6(self):
        frames=Frames().feed(bytes.fromhex('aa55050406090046e8'))
        self.assertEqual(len(frames),1)
        self.assertEqual(decode_reply(frames[0][1],6,9),70)

if __name__=='__main__':unittest.main()
