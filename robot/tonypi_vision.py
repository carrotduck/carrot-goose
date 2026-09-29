#!/usr/bin/env python3

import sys
import time

from tonypi_perception import PerceptionCameraError, PerceptionStopped


TONYPI_ROOT = "/home/pi/TonyPi"
ACTIVITIES = {
    "using_computer",
    "using_phone",
    "reading",
    "writing",
    "gaming",
    "watching_video",
    "resting",
    "sleeping",
    "eating",
    "talking",
    "crafting",
    "moving",
    "away",
    "unknown",
}
ATTENTION_DIRECTIONS = {
    "screen",
    "phone",
    "book",
    "camera",
    "room",
    "away",
    "unknown",
}
BODY_POSTURES = {
    "sitting",
    "standing",
    "lying",
    "moving",
    "partially_visible",
    "unknown",
}
VISUAL_RESULT_KEYS = {
    "person_present",
    "scene_summary",
    "grounded_observations",
    "activity",
    "attention_direction",
    "body_posture",
    "embodied_glimpse",
    "uncertainty",
    "confidence",
}
IDENTITY_MARKERS = {"榛榛", "hazel"}


class EphemeralJpeg:
    """An in-memory JPEG that overwrites its buffer when the scope ends."""

    def __init__(self, data, width, height):
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError("jpeg data must be non-empty bytes")
        self._buffer = bytearray(data)
        self.cleared = False
        self.metadata = {
            "schema_version": "tonypi-ephemeral-frame/v1",
            "mime_type": "image/jpeg",
            "width": int(width),
            "height": int(height),
            "byte_length": len(self._buffer),
            "image_saved": False,
        }

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.clear()

    def view(self):
        if self.cleared:
            raise RuntimeError("frame_already_cleared")
        return memoryview(self._buffer)

    def clear(self):
        if self.cleared:
            return
        for index in range(len(self._buffer)):
            self._buffer[index] = 0
        self.cleared = True

    def is_zeroed(self):
        return all(value == 0 for value in self._buffer)


def capture_ephemeral_jpeg(
    resolution=(640, 480),
    max_width=640,
    jpeg_quality=75,
    timeout_seconds=2.5,
    should_stop=None,
    camera_factory=None,
    cv2_module=None,
):
    """Capture one JPEG in memory. This function never writes a file."""
    for path in (TONYPI_ROOT, f"{TONYPI_ROOT}/HiwonderSDK"):
        if path not in sys.path:
            sys.path.insert(0, path)
    if cv2_module is None:
        import cv2 as cv2_module
    if camera_factory is None:
        import hiwonder.Camera as Camera
        camera_factory = Camera.Camera

    camera = camera_factory(resolution=tuple(resolution))
    deadline = time.monotonic() + max(0.5, min(5.0, float(timeout_seconds)))
    frame = None
    try:
        camera.camera_open()
        while time.monotonic() < deadline:
            if should_stop is not None and should_stop():
                raise PerceptionStopped("stopped_by_emergency_command")
            ok, candidate = camera.read()
            if ok and candidate is not None:
                frame = candidate
                break
            time.sleep(0.02)
    except PerceptionStopped:
        raise
    except Exception as error:
        raise PerceptionCameraError("activity_camera_capture_failed") from error
    finally:
        try:
            camera.camera_close()
        except Exception:
            pass

    if frame is None:
        raise PerceptionCameraError("camera_no_frames")
    height, width = int(frame.shape[0]), int(frame.shape[1])
    max_width = max(160, min(640, int(max_width)))
    if width > max_width:
        scale = max_width / width
        width = max_width
        height = max(1, int(round(height * scale)))
        frame = cv2_module.resize(frame, (width, height))
    quality = max(40, min(90, int(jpeg_quality)))
    ok, encoded = cv2_module.imencode(
        ".jpg",
        frame,
        [int(cv2_module.IMWRITE_JPEG_QUALITY), quality],
    )
    if not ok:
        raise PerceptionCameraError("jpeg_encode_failed")
    return EphemeralJpeg(encoded.tobytes(), width, height)


def _normalize_short_text(value, field, max_length, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = " ".join(value.split())
    if not text and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(text) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    lowered = text.lower()
    if any(marker in lowered for marker in IDENTITY_MARKERS):
        raise ValueError(f"{field} contains an identity claim")
    return text


def normalize_activity_observation(payload):
    if not isinstance(payload, dict):
        raise ValueError("visual observation must be an object")
    keys = set(payload)
    if keys != VISUAL_RESULT_KEYS:
        missing = sorted(VISUAL_RESULT_KEYS - keys)
        unknown = sorted(keys - VISUAL_RESULT_KEYS)
        raise ValueError(f"visual observation keys invalid missing={missing} unknown={unknown}")

    person_present = payload["person_present"]
    if not isinstance(person_present, bool):
        raise ValueError("person_present must be boolean")
    scene_summary = _normalize_short_text(
        payload["scene_summary"],
        "scene_summary",
        160,
    )
    observations = payload["grounded_observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= 4:
        raise ValueError("grounded_observations must contain 1 to 4 items")
    grounded_observations = [
        _normalize_short_text(value, "grounded_observations", 100)
        for value in observations
    ]
    activity = str(payload["activity"] or "").strip()
    if activity not in ACTIVITIES:
        raise ValueError(f"unsupported activity: {activity}")
    attention_direction = str(payload["attention_direction"] or "").strip()
    if attention_direction not in ATTENTION_DIRECTIONS:
        raise ValueError(f"unsupported attention_direction: {attention_direction}")
    body_posture = str(payload["body_posture"] or "").strip()
    if body_posture not in BODY_POSTURES:
        raise ValueError(f"unsupported body_posture: {body_posture}")
    embodied_glimpse = _normalize_short_text(
        payload["embodied_glimpse"],
        "embodied_glimpse",
        180,
    )
    uncertainty = _normalize_short_text(
        payload["uncertainty"],
        "uncertainty",
        120,
        allow_empty=True,
    )
    confidence_value = payload["confidence"]
    if isinstance(confidence_value, bool):
        raise ValueError("confidence must be numeric")
    confidence = float(confidence_value)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if not person_present and activity not in {"away", "unknown"}:
        raise ValueError("activity requires person_present=true")
    if not person_present and attention_direction not in {"away", "unknown"}:
        raise ValueError("attention_direction requires person_present=true")
    if not person_present and body_posture != "unknown":
        raise ValueError("body_posture must be unknown when no person is present")

    return {
        "schema_version": "yushi-visual-observation/v2",
        "person_present": person_present,
        "scene_summary": scene_summary,
        "grounded_observations": grounded_observations,
        "activity": activity,
        "attention_direction": attention_direction,
        "body_posture": body_posture,
        "embodied_glimpse": embodied_glimpse,
        "uncertainty": uncertainty,
        "confidence": round(confidence, 4),
    }


def observe_activity_once(capture_frame, provider):
    """Call one provider with one frame, then wipe the frame even on failure."""
    frame = capture_frame()
    with frame:
        view = frame.view()
        try:
            raw_result = provider(view, dict(frame.metadata))
        finally:
            view.release()
        return normalize_activity_observation(raw_result)
