#!/usr/bin/env python3

import unittest

from tonypi_vision import (
    EphemeralJpeg,
    capture_ephemeral_jpeg,
    normalize_activity_observation,
    observe_activity_once,
)


VALID_RESULT = {
    "person_present": True,
    "scene_summary": "一个人坐在桌前，身体朝向电脑。",
    "grounded_observations": [
        "画面中的人坐在电脑前。",
        "一只手靠近键盘区域。",
        "脸没有朝向摄像头。",
    ],
    "activity": "using_computer",
    "attention_direction": "screen",
    "body_posture": "sitting",
    "embodied_glimpse": "我这一眼看见有人还坐在电脑前，像是在忙手头的东西。",
    "uncertainty": "看不清屏幕内容，也不能仅凭画面判断情绪。",
    "confidence": 0.82,
}


class FakeFrame:
    shape = (480, 640, 3)


class FakeEncoded:
    def tobytes(self):
        return b"fake-jpeg"


class FakeCv2:
    IMWRITE_JPEG_QUALITY = 1

    def __init__(self):
        self.encode_calls = []

    def resize(self, frame, size):
        raise AssertionError(f"unexpected resize: {frame} {size}")

    def imencode(self, suffix, frame, options):
        self.encode_calls.append((suffix, frame, options))
        return True, FakeEncoded()


class FakeCamera:
    def __init__(self):
        self.opened = False
        self.closed = False

    def camera_open(self):
        self.opened = True

    def read(self):
        return True, FakeFrame()

    def camera_close(self):
        self.closed = True


class VisionContractTests(unittest.TestCase):
    def test_ephemeral_frame_is_zeroed_after_scope(self):
        frame = EphemeralJpeg(b"secret", 640, 480)
        with frame:
            self.assertEqual(bytes(frame.view()), b"secret")
        self.assertTrue(frame.cleared)
        self.assertTrue(frame.is_zeroed())

    def test_provider_receives_one_frame_and_result_is_normalized(self):
        frame = EphemeralJpeg(b"one-frame", 640, 480)
        provider_calls = []

        def provider(jpeg, metadata):
            provider_calls.append((bytes(jpeg), metadata))
            return dict(VALID_RESULT)

        result = observe_activity_once(lambda: frame, provider)
        self.assertEqual(len(provider_calls), 1)
        self.assertEqual(provider_calls[0][0], b"one-frame")
        self.assertFalse(provider_calls[0][1]["image_saved"])
        self.assertEqual(result["schema_version"], "yushi-visual-observation/v2")
        self.assertTrue(frame.cleared)
        self.assertTrue(frame.is_zeroed())

    def test_provider_failure_still_zeroes_frame(self):
        frame = EphemeralJpeg(b"one-frame", 640, 480)

        def provider(_jpeg, _metadata):
            raise RuntimeError("provider_failed")

        with self.assertRaisesRegex(RuntimeError, "provider_failed"):
            observe_activity_once(lambda: frame, provider)
        self.assertTrue(frame.cleared)
        self.assertTrue(frame.is_zeroed())

    def test_result_rejects_identity_or_free_text_fields(self):
        payload = dict(VALID_RESULT)
        payload["person_name"] = "someone"
        with self.assertRaisesRegex(ValueError, "unknown"):
            normalize_activity_observation(payload)

        payload = dict(VALID_RESULT, embodied_glimpse="我看见榛榛在电脑前。")
        with self.assertRaisesRegex(ValueError, "identity claim"):
            normalize_activity_observation(payload)

    def test_result_rejects_activity_without_person(self):
        payload = dict(VALID_RESULT, person_present=False)
        with self.assertRaisesRegex(ValueError, "requires person_present"):
            normalize_activity_observation(payload)

    def test_no_person_result_keeps_observation_natural_but_bounded(self):
        payload = dict(
            VALID_RESULT,
            person_present=False,
            scene_summary="画面里暂时没有看见人。",
            grounded_observations=["椅子和电脑仍在画面中。"],
            activity="away",
            attention_direction="away",
            body_posture="unknown",
            embodied_glimpse="我这一眼没有在画面里看见人。",
            uncertainty="不知道人只是离开了座位，还是在画面外。",
            confidence=0.76,
        )
        result = normalize_activity_observation(payload)
        self.assertFalse(result["person_present"])
        self.assertEqual(result["activity"], "away")

    def test_grounded_observations_are_short_and_limited(self):
        payload = dict(VALID_RESULT, grounded_observations=[])
        with self.assertRaisesRegex(ValueError, "1 to 4"):
            normalize_activity_observation(payload)
        payload = dict(VALID_RESULT, grounded_observations=["x"] * 5)
        with self.assertRaisesRegex(ValueError, "1 to 4"):
            normalize_activity_observation(payload)

    def test_capture_uses_memory_and_closes_camera(self):
        camera = FakeCamera()
        cv2 = FakeCv2()

        frame = capture_ephemeral_jpeg(
            camera_factory=lambda resolution: camera,
            cv2_module=cv2,
        )

        self.assertTrue(camera.opened)
        self.assertTrue(camera.closed)
        self.assertEqual(bytes(frame.view()), b"fake-jpeg")
        self.assertEqual(frame.metadata["width"], 640)
        self.assertEqual(frame.metadata["height"], 480)
        self.assertFalse(frame.metadata["image_saved"])
        self.assertEqual(len(cv2.encode_calls), 1)
        frame.clear()


if __name__ == "__main__":
    unittest.main()
