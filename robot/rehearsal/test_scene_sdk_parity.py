"""Compare actual packet payloads with isolated vendor SDK methods, offline."""
import ast,struct,unittest
from pathlib import Path
from types import SimpleNamespace
from scene_hardware import targets_packet,changed_arm_packet
from guarded_invitation import IDLE
from thermal_sample import Frames

class PacketParityTests(unittest.TestCase):
    def sdk_payload(self,method,duration,positions):
        file=Path(__file__).resolve().parents[2]/'.tmp/ros_robot_controller_sdk.installed.py'
        if not file.exists():self.skipTest('Optional vendor SDK source fixture is not distributed')
        tree=ast.parse(file.read_text(encoding='utf-8'))
        board=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Board')
        fn=next(n for n in board.body if isinstance(n,ast.FunctionDef) and n.name==method)
        env={'struct':struct,'PacketFunction':SimpleNamespace(PACKET_FUNC_BUS_SERVO=5,PACKET_FUNC_PWM_SERVO=4)}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(file),'exec'),env)
        sent=[];owner=SimpleNamespace(buf_write=lambda func,payload:sent.append((func,bytes(payload))))
        env[method](owner,duration,positions)
        return sent[0]
    def test_head_and_full_arm_packets_match_sdk(self):
        for function,method,positions in ((4,'pwm_servo_set_position',{1:1455,2:1572}),(5,'bus_servo_set_position',IDLE)):
            expected=self.sdk_payload(method,2.4,sorted(positions.items()))
            self.assertEqual(Frames().feed(targets_packet(function,positions,2.4))[0][:2],expected)
    def test_changed_only_right_arm_packet_matches_sdk(self):
        target={**IDLE,14:392,15:205,16:437}
        expected=self.sdk_payload('bus_servo_set_position',2.4,[(14,392),(15,205),(16,437)])
        self.assertEqual(Frames().feed(changed_arm_packet(target,IDLE,2.4))[0][:2],expected)
if __name__=='__main__':unittest.main()
