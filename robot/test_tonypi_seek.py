#!/usr/bin/env python3

import unittest
from unittest.mock import patch

from tonypi_seek import (
    FaceCameraError,
    SeekStopped,
    run_local_seek,
    run_local_track,
    run_seek,
    run_track,
)


def face(zone="image_center", confidence=0.9):
    return {
        "face_result": "face_found",
        "position_zone": zone,
        "confidence": confidence,
    }


def no_face():
    return {
        "face_result": "face_not_found",
        "position_zone": "unknown",
        "confidence": 0.0,
    }


def tracked_face(center_x, center_y, confidence=0.9):
    if center_x < 0.4:
        zone = "image_left"
    elif center_x > 0.6:
        zone = "image_right"
    else:
        zone = "image_center"
    return {
        "face_result": "face_found",
        "position_zone": zone,
        "confidence": confidence,
        "mean_center_x": center_x,
        "mean_center_y": center_y,
    }


class FakeSequence:
    def __init__(self, observations):
        self.observations = list(observations)
        self.moves = []

    def observe(self):
        if not self.observations:
            raise AssertionError("unexpected observation request")
        value = self.observations.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def move(self, pose):
        self.moves.append(pose)


class FakeTrackSequence(FakeSequence):
    def move_absolute(self, pitch, yaw, duration):
        self.moves.append((int(pitch), int(yaw), round(float(duration), 2)))


class SeekPolicyTests(unittest.TestCase):
    def test_face_already_centered(self):
        fake = FakeSequence([face("image_center")])
        result = run_seek(fake.observe, fake.move)
        self.assertEqual(fake.moves, ["center", "center"])
        self.assertEqual(result["face_result"], "face_found")
        self.assertEqual(result["alignment"], "center")
        self.assertFalse(result["limit_reached"])

    def test_image_right_turns_tonypi_right_and_centers(self):
        fake = FakeSequence([face("image_right", 0.88), face("image_center", 0.94)])
        result = run_seek(fake.observe, fake.move)
        self.assertEqual(fake.moves, ["center", "right", "center"])
        self.assertEqual(result["found_at_pose"], "right")
        self.assertEqual(result["alignment"], "center")
        self.assertEqual(result["position_zone"], "image_center")

    def test_image_left_turns_tonypi_left_and_centers(self):
        fake = FakeSequence([face("image_left", 0.93), face("image_center", 0.95)])
        result = run_seek(fake.observe, fake.move)
        self.assertEqual(fake.moves, ["center", "left", "center"])
        self.assertEqual(result["found_at_pose"], "left")
        self.assertEqual(result["alignment"], "center")

    def test_safe_limit_returns_off_center_without_chasing(self):
        fake = FakeSequence([face("image_left"), face("image_left")])
        result = run_seek(fake.observe, fake.move)
        self.assertEqual(fake.moves, ["center", "left", "center"])
        self.assertEqual(result["face_result"], "face_found")
        self.assertEqual(result["alignment"], "off_center")
        self.assertTrue(result["limit_reached"])

    def test_no_face_scans_both_sides_and_completes_normally(self):
        fake = FakeSequence([no_face(), no_face(), no_face()])
        result = run_seek(fake.observe, fake.move)
        self.assertEqual(fake.moves, ["center", "left", "center", "right", "center"])
        self.assertEqual(result["face_result"], "face_not_found")
        self.assertTrue(result["search_exhausted"])
        self.assertEqual(result["return_policy"], "center_before_decide")
        self.assertEqual(result["observation_level"], "presence_only")
        self.assertFalse(result["visual_model_called"])
        self.assertFalse(result["speech_requested"])
        self.assertEqual(result["decision_owner"], "server_after_receipt")

    def test_face_found_during_left_scan(self):
        fake = FakeSequence([no_face(), face("image_center", 0.91)])
        result = run_seek(fake.observe, fake.move)
        self.assertEqual(fake.moves, ["center", "left", "center"])
        self.assertEqual(result["face_result"], "face_found")
        self.assertEqual(result["found_at_pose"], "left")

    def test_exception_still_returns_center(self):
        fake = FakeSequence([RuntimeError("camera_failed")])
        with self.assertRaisesRegex(RuntimeError, "camera_failed"):
            run_seek(fake.observe, fake.move)
        self.assertEqual(fake.moves, ["center", "center"])

    def test_emergency_stop_uses_unconditional_safe_center(self):
        fake = FakeSequence([face("image_center")])
        checks = {"count": 0}

        def should_stop():
            checks["count"] += 1
            return checks["count"] >= 3

        with self.assertRaisesRegex(SeekStopped, "stopped_by_emergency_command"):
            run_seek(
                fake.observe,
                fake.move,
                return_center=lambda: fake.move("safe_center"),
                should_stop=should_stop,
            )
        self.assertEqual(fake.moves, ["center", "safe_center"])

    @patch("tonypi_seek.LocalFaceObserver")
    def test_camera_open_failure_also_attempts_center(self, observer_class):
        observer_class.return_value.__enter__.side_effect = FaceCameraError("camera_open_failed")
        moves = []
        with self.assertRaisesRegex(FaceCameraError, "camera_open_failed"):
            run_local_seek(moves.append)
        self.assertEqual(moves, ["center"])


class TrackPolicyTests(unittest.TestCase):
    def run_tracking(self, fake, **kwargs):
        return run_track(
            fake.observe,
            fake.move_absolute,
            center_pitch=1500,
            center_yaw=1530,
            pitch_limits=(1400, 1600),
            yaw_limits=(1410, 1650),
            duration_seconds=10.0,
            **kwargs,
        )

    def test_tracks_face_in_small_steps_and_returns_center(self):
        fake = FakeTrackSequence([
            tracked_face(0.30, 0.30, 0.91),
            tracked_face(0.46, 0.48, 0.95),
        ])
        result = self.run_tracking(fake, max_samples=2)
        self.assertEqual(fake.moves[0], (1500, 1530, 0.65))
        self.assertEqual(fake.moves[1][0:2], (1520, 1554))
        self.assertEqual(fake.moves[-1], (1500, 1530, 0.65))
        self.assertEqual(result["face_result"], "face_found")
        self.assertEqual(result["alignment"], "center")
        self.assertEqual(result["track_updates"], 1)
        self.assertFalse(result["limit_reached"])
        self.assertFalse(result["image_saved"])

    def test_tracking_never_exceeds_verified_limits(self):
        fake = FakeTrackSequence([tracked_face(0.0, 0.0)] * 8)
        result = self.run_tracking(fake, max_samples=8)
        for pitch, yaw, _duration in fake.moves:
            self.assertGreaterEqual(pitch, 1400)
            self.assertLessEqual(pitch, 1600)
            self.assertGreaterEqual(yaw, 1410)
            self.assertLessEqual(yaw, 1650)
        self.assertTrue(result["limit_reached"])
        self.assertEqual(fake.moves[-1], (1500, 1530, 0.65))

    def test_no_face_holds_then_returns_center(self):
        fake = FakeTrackSequence([no_face(), no_face(), no_face()])
        result = self.run_tracking(fake, max_samples=3)
        self.assertEqual(fake.moves, [(1500, 1530, 0.65), (1500, 1530, 0.65)])
        self.assertEqual(result["face_result"], "face_not_found")
        self.assertEqual(result["track_updates"], 0)
        self.assertEqual(result["lost_samples"], 3)
        self.assertEqual(result["observation_level"], "presence_only")
        self.assertFalse(result["visual_model_called"])
        self.assertFalse(result["speech_requested"])
        self.assertEqual(result["decision_owner"], "server_after_receipt")

    def test_emergency_stop_still_returns_center(self):
        fake = FakeTrackSequence([tracked_face(0.30, 0.30)])
        checks = {"count": 0}

        def should_stop():
            checks["count"] += 1
            return checks["count"] >= 4

        with self.assertRaisesRegex(SeekStopped, "stopped_by_emergency_command"):
            self.run_tracking(fake, max_samples=1, should_stop=should_stop)
        self.assertEqual(fake.moves[-1], (1500, 1530, 0.65))

    @patch("tonypi_seek.LocalFaceObserver")
    def test_camera_open_failure_also_attempts_center(self, observer_class):
        observer_class.return_value.__enter__.side_effect = FaceCameraError("camera_open_failed")
        moves = []
        with self.assertRaisesRegex(FaceCameraError, "camera_open_failed"):
            run_local_track(
                lambda pitch, yaw, duration: moves.append((pitch, yaw, duration)),
                center_pitch=1500,
                center_yaw=1530,
                pitch_limits=(1400, 1600),
                yaw_limits=(1410, 1650),
            )
        self.assertEqual(moves, [(1500, 1530, 0.65)])

    @patch("tonypi_seek.LocalFaceObserver")
    def test_tracking_error_does_not_repeat_successful_center_return(self, observer_class):
        observer = observer_class.return_value.__enter__.return_value
        observer.observe.side_effect = RuntimeError("camera_read_failed")
        moves = []

        with self.assertRaisesRegex(RuntimeError, "camera_read_failed"):
            run_local_track(
                lambda pitch, yaw, duration: moves.append((pitch, yaw, duration)),
                center_pitch=1500,
                center_yaw=1530,
                pitch_limits=(1400, 1600),
                yaw_limits=(1410, 1650),
            )

        self.assertEqual(
            moves,
            [
                (1500, 1530, 0.65),
                (1500, 1530, 0.65),
            ],
        )


if __name__ == "__main__":
    unittest.main()
