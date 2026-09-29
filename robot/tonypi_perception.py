#!/usr/bin/env python3

import math
import sys
import time
from collections import Counter


TONYPI_ROOT = "/home/pi/TonyPi"
CAMERA_COORDINATE_FRAME = "camera_image"
GESTURES = {"open_palm", "pointing", "closed_fist", "unknown"}
FINGER_JOINTS = {
    "index": (5, 6, 8),
    "middle": (9, 10, 12),
    "ring": (13, 14, 16),
    "pinky": (17, 18, 20),
}


class PerceptionCameraError(RuntimeError):
    pass


class PerceptionStopped(RuntimeError):
    pass


def _xy(landmark):
    if hasattr(landmark, "x") and hasattr(landmark, "y"):
        return float(landmark.x), float(landmark.y)
    if isinstance(landmark, dict):
        return float(landmark["x"]), float(landmark["y"])
    return float(landmark[0]), float(landmark[1])


def _distance(first, second):
    ax, ay = _xy(first)
    bx, by = _xy(second)
    return math.hypot(ax - bx, ay - by)


def _joint_angle(first, middle, last):
    ax, ay = _xy(first)
    bx, by = _xy(middle)
    cx, cy = _xy(last)
    left = (ax - bx, ay - by)
    right = (cx - bx, cy - by)
    left_length = math.hypot(*left)
    right_length = math.hypot(*right)
    if left_length <= 1e-6 or right_length <= 1e-6:
        return 0.0
    cosine = (left[0] * right[0] + left[1] * right[1]) / (left_length * right_length)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def classify_hand_landmarks(landmarks):
    """Classify a few static gestures without dispatching any motion."""
    if len(landmarks) < 21:
        raise ValueError("expected 21 hand landmarks")

    wrist = landmarks[0]
    finger_states = {}
    finger_angles = {}
    for name, (mcp_index, pip_index, tip_index) in FINGER_JOINTS.items():
        angle = _joint_angle(
            landmarks[mcp_index],
            landmarks[pip_index],
            landmarks[tip_index],
        )
        extension_margin = (
            _distance(landmarks[tip_index], wrist)
            - _distance(landmarks[pip_index], wrist)
        )
        finger_states[name] = angle >= 150.0 and extension_margin >= 0.02
        finger_angles[name] = round(angle, 1)

    extended = [name for name, is_extended in finger_states.items() if is_extended]
    if len(extended) == 4:
        gesture = "open_palm"
    elif extended == ["index"]:
        gesture = "pointing"
    elif not extended:
        gesture = "closed_fist"
    else:
        gesture = "unknown"

    return {
        "gesture": gesture,
        "extended_fingers": extended,
        "finger_states": finger_states,
        "finger_angles": finger_angles,
    }


class LocalGestureObserver:
    def __init__(self, duration_seconds=1.8, sample_interval=0.12, should_stop=None):
        self.duration_seconds = max(0.5, min(5.0, float(duration_seconds)))
        self.sample_interval = max(0.08, min(0.5, float(sample_interval)))
        self.should_stop = should_stop
        self.camera = None
        self.detector = None
        self.cv2 = None

    def __enter__(self):
        for path in (TONYPI_ROOT, f"{TONYPI_ROOT}/HiwonderSDK"):
            if path not in sys.path:
                sys.path.insert(0, path)
        try:
            import cv2
            import mediapipe as mp
            import hiwonder.Camera as Camera

            self.cv2 = cv2
            self.camera = Camera.Camera(resolution=(640, 480))
            self.detector = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.65,
                min_tracking_confidence=0.60,
            )
            self.camera.camera_open()
            return self
        except Exception as error:
            self.__exit__(None, None, None)
            raise PerceptionCameraError("gesture_camera_open_failed") from error

    def __exit__(self, _exc_type, _exc, _traceback):
        if self.camera is not None:
            try:
                self.camera.camera_close()
            except Exception:
                pass
        if self.detector is not None:
            try:
                self.detector.close()
            except Exception:
                pass

    def _ensure_running(self):
        if self.should_stop is not None and self.should_stop():
            raise PerceptionStopped("stopped_by_emergency_command")

    def observe(self):
        started = time.monotonic()
        next_sample = started
        frames_sampled = 0
        frames_with_hand = 0
        gesture_counts = Counter()

        while time.monotonic() - started < self.duration_seconds:
            self._ensure_running()
            now = time.monotonic()
            if now < next_sample:
                time.sleep(min(0.02, next_sample - now))
                continue
            ok, frame = self.camera.read()
            if not ok or frame is None:
                time.sleep(0.02)
                continue

            next_sample = now + self.sample_interval
            frames_sampled += 1
            rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
            detection = self.detector.process(rgb)
            hands = list(detection.multi_hand_landmarks or [])
            if not hands:
                continue

            frames_with_hand += 1
            classified = classify_hand_landmarks(hands[0].landmark)
            gesture_counts[classified["gesture"]] += 1

        self._ensure_running()
        if frames_sampled == 0:
            raise PerceptionCameraError("camera_no_frames")
        if frames_with_hand == 0:
            return {
                "schema_version": "tonypi-gesture-observation/v1",
                "hand_result": "hand_not_found",
                "gesture": "unknown",
                "confidence": 0.0,
                "coordinate_frame": CAMERA_COORDINATE_FRAME,
                "frames_sampled": frames_sampled,
                "frames_with_hand": 0,
                "gesture_counts": {},
                "image_saved": False,
                "raw_landmarks_saved": False,
                "motion_requested": False,
            }

        gesture, votes = gesture_counts.most_common(1)[0]
        return {
            "schema_version": "tonypi-gesture-observation/v1",
            "hand_result": "hand_found",
            "gesture": gesture if gesture in GESTURES else "unknown",
            "confidence": round(votes / frames_with_hand, 4),
            "coordinate_frame": CAMERA_COORDINATE_FRAME,
            "frames_sampled": frames_sampled,
            "frames_with_hand": frames_with_hand,
            "gesture_counts": dict(sorted(gesture_counts.items())),
            "image_saved": False,
            "raw_landmarks_saved": False,
            "motion_requested": False,
        }


def observe_gesture_once(
    duration_seconds=1.8,
    sample_interval=0.12,
    should_stop=None,
):
    with LocalGestureObserver(
        duration_seconds=duration_seconds,
        sample_interval=sample_interval,
        should_stop=should_stop,
    ) as observer:
        return observer.observe()
