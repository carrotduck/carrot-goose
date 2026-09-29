#!/usr/bin/env python3

import sys
import time
from collections import Counter


TONYPI_ROOT = "/home/pi/TonyPi"
CAMERA_COORDINATE_FRAME = "camera_image"
GAZE_COORDINATE_FRAME = "tonypi_body"
VALID_ZONES = {"image_left", "image_center", "image_right", "unknown"}
TRACK_TARGET_X = 0.5
TRACK_TARGET_Y = 0.5
TRACK_X_DEADZONE = 0.06
TRACK_Y_DEADZONE = 0.08
TRACK_YAW_GAIN = 320.0
TRACK_PITCH_GAIN = 260.0
TRACK_MAX_YAW_STEP = 24
TRACK_MAX_PITCH_STEP = 20


class FaceCameraError(RuntimeError):
    pass


class SeekStopped(RuntimeError):
    pass


class _CenterReturnGuard:
    """Run a center callback once, while allowing a retry after failure."""

    def __init__(self, callback):
        self.callback = callback
        self.completed = False

    def __call__(self):
        if self.completed:
            return False
        self.callback()
        self.completed = True
        return True


def _zone_for_center_x(center_x):
    if center_x < 0.4:
        return "image_left"
    if center_x > 0.6:
        return "image_right"
    return "image_center"


def _normalize_observation(observation):
    if not isinstance(observation, dict):
        raise ValueError("face observation must be an object")
    face_result = str(observation.get("face_result") or "").strip()
    if face_result not in {"face_found", "face_not_found"}:
        raise ValueError(f"invalid face_result: {face_result!r}")
    zone = str(observation.get("position_zone") or "unknown").strip()
    if zone not in VALID_ZONES:
        raise ValueError(f"invalid position_zone: {zone!r}")
    if face_result == "face_not_found":
        zone = "unknown"
    confidence = max(0.0, min(1.0, float(observation.get("confidence") or 0.0)))
    normalized = dict(observation)
    normalized.update({
        "face_result": face_result,
        "position_zone": zone,
        "confidence": round(confidence, 4),
        "coordinate_frame": CAMERA_COORDINATE_FRAME,
    })
    return normalized


def _found_result(observation, found_at_pose, attempted_alignment):
    zone = observation["position_zone"]
    centered = zone == "image_center"
    return {
        "face_result": "face_found",
        "position_zone": zone,
        "confidence": observation["confidence"],
        "alignment": "center" if centered else "off_center",
        "limit_reached": bool(attempted_alignment and not centered),
        "search_exhausted": False,
        "found_at_pose": found_at_pose,
    }


def _clamp(value, limits):
    return max(int(limits[0]), min(int(limits[1]), int(value)))


def _bounded_track_adjustment(
    observation,
    current_pitch,
    current_yaw,
    pitch_limits,
    yaw_limits,
):
    zone_x = {
        "image_left": 0.32,
        "image_center": TRACK_TARGET_X,
        "image_right": 0.68,
    }
    center_x = max(0.0, min(1.0, float(
        observation.get("mean_center_x", zone_x.get(observation["position_zone"], TRACK_TARGET_X))
    )))
    center_y = max(0.0, min(1.0, float(observation.get("mean_center_y", TRACK_TARGET_Y))))
    error_x = TRACK_TARGET_X - center_x
    error_y = TRACK_TARGET_Y - center_y

    yaw_delta = 0
    if abs(error_x) > TRACK_X_DEADZONE:
        yaw_delta = max(
            -TRACK_MAX_YAW_STEP,
            min(TRACK_MAX_YAW_STEP, int(round(error_x * TRACK_YAW_GAIN))),
        )
    pitch_delta = 0
    if abs(error_y) > TRACK_Y_DEADZONE:
        pitch_delta = max(
            -TRACK_MAX_PITCH_STEP,
            min(TRACK_MAX_PITCH_STEP, int(round(error_y * TRACK_PITCH_GAIN))),
        )

    requested_pitch = int(current_pitch) + pitch_delta
    requested_yaw = int(current_yaw) + yaw_delta
    target_pitch = _clamp(requested_pitch, pitch_limits)
    target_yaw = _clamp(requested_yaw, yaw_limits)
    return {
        "center_x": round(center_x, 4),
        "center_y": round(center_y, 4),
        "error_x": round(error_x, 4),
        "error_y": round(error_y, 4),
        "target_pitch": target_pitch,
        "target_yaw": target_yaw,
        "centered": yaw_delta == 0 and pitch_delta == 0,
        "moved": target_pitch != int(current_pitch) or target_yaw != int(current_yaw),
        "limit_reached": target_pitch != requested_pitch or target_yaw != requested_yaw,
    }


def run_track(
    observe,
    move_absolute,
    center_pitch,
    center_yaw,
    pitch_limits,
    yaw_limits,
    duration_seconds=8.0,
    max_samples=14,
    return_center=None,
    should_stop=None,
):
    """Track a face briefly inside fixed gaze limits and always return center."""
    started = time.monotonic()
    current_pitch = _clamp(center_pitch, pitch_limits)
    current_yaw = _clamp(center_yaw, yaw_limits)
    max_samples = max(1, min(30, int(max_samples)))
    duration_seconds = max(1.0, min(15.0, float(duration_seconds)))
    face_samples = 0
    lost_samples = 0
    centered_samples = 0
    track_updates = 0
    max_confidence = 0.0
    last_face = None
    last_centered = False
    limit_reached = False
    trace = []

    def ensure_running():
        if should_stop is not None and should_stop():
            raise SeekStopped("stopped_by_emergency_command")

    try:
        ensure_running()
        move_absolute(current_pitch, current_yaw, 0.65)
        ensure_running()
        for sample_index in range(max_samples):
            if time.monotonic() - started >= duration_seconds:
                break
            ensure_running()
            observation = _normalize_observation(observe())
            ensure_running()
            if observation["face_result"] == "face_not_found":
                lost_samples += 1
                if len(trace) < 12:
                    trace.append({"sample": sample_index, "face_result": "face_not_found"})
                continue

            face_samples += 1
            last_face = observation
            max_confidence = max(max_confidence, observation["confidence"])
            adjustment = _bounded_track_adjustment(
                observation,
                current_pitch,
                current_yaw,
                pitch_limits,
                yaw_limits,
            )
            last_centered = adjustment["centered"]
            limit_reached = limit_reached or adjustment["limit_reached"]
            if adjustment["centered"]:
                centered_samples += 1
            if adjustment["moved"]:
                max_delta = max(
                    abs(adjustment["target_pitch"] - current_pitch),
                    abs(adjustment["target_yaw"] - current_yaw),
                )
                move_duration = max(0.18, min(0.32, max_delta / 80.0))
                move_absolute(
                    adjustment["target_pitch"],
                    adjustment["target_yaw"],
                    move_duration,
                )
                current_pitch = adjustment["target_pitch"]
                current_yaw = adjustment["target_yaw"]
                track_updates += 1
            if len(trace) < 12:
                trace.append({
                    "sample": sample_index,
                    "face_result": "face_found",
                    "position_zone": observation["position_zone"],
                    "confidence": observation["confidence"],
                    "center_x": adjustment["center_x"],
                    "center_y": adjustment["center_y"],
                    "target_pitch": adjustment["target_pitch"],
                    "target_yaw": adjustment["target_yaw"],
                    "moved": adjustment["moved"],
                })
    finally:
        if return_center is None:
            move_absolute(int(center_pitch), int(center_yaw), 0.65)
        else:
            return_center()

    if last_face is None:
        face_result = "face_not_found"
        position_zone = "unknown"
        confidence = 0.0
        alignment = "not_applicable"
    else:
        face_result = "face_found"
        position_zone = last_face["position_zone"]
        confidence = round(max_confidence, 4)
        alignment = "center" if last_centered else "off_center"

    return {
        "face_result": face_result,
        "position_zone": position_zone,
        "confidence": confidence,
        "alignment": alignment,
        "limit_reached": limit_reached,
        "search_exhausted": False,
        "coordinate_frame": CAMERA_COORDINATE_FRAME,
        "return_policy": "center_after_tracking",
        "observation_level": "presence_only",
        "visual_model_called": False,
        "speech_requested": False,
        "decision_owner": "server_after_receipt",
        "final_gaze_pose": {
            "coordinate_frame": GAZE_COORDINATE_FRAME,
            "name": "center",
        },
        "face_samples": face_samples,
        "lost_samples": lost_samples,
        "centered_samples": centered_samples,
        "track_updates": track_updates,
        "trace": trace,
        "tracking_duration_ms": int((time.monotonic() - started) * 1000),
        "image_saved": False,
    }


def run_seek(observe, move_pose, return_center=None, should_stop=None):
    """Run a bounded local seek and always restore the center gaze pose."""
    observations = []

    def ensure_running():
        if should_stop is not None and should_stop():
            raise SeekStopped("stopped_by_emergency_command")

    def move(pose):
        ensure_running()
        move_pose(pose)
        ensure_running()

    def sample(pose):
        ensure_running()
        observation = _normalize_observation(observe())
        ensure_running()
        observations.append({"gaze_pose": pose, **observation})
        return observation

    result = None
    try:
        move("center")
        initial = sample("center")
        if initial["face_result"] == "face_found":
            initial_zone = initial["position_zone"]
            if initial_zone == "image_center":
                result = _found_result(initial, "center", attempted_alignment=False)
            else:
                target_pose = "left" if initial_zone == "image_left" else "right"
                move(target_pose)
                aligned = sample(target_pose)
                if aligned["face_result"] == "face_found":
                    result = _found_result(aligned, target_pose, attempted_alignment=True)
                else:
                    result = {
                        "face_result": "face_not_found",
                        "position_zone": "unknown",
                        "confidence": 0.0,
                        "alignment": "not_applicable",
                        "limit_reached": True,
                        "search_exhausted": False,
                        "found_at_pose": None,
                    }
        else:
            for index, target_pose in enumerate(("left", "right")):
                if index:
                    move("center")
                move(target_pose)
                scanned = sample(target_pose)
                if scanned["face_result"] == "face_found":
                    result = _found_result(scanned, target_pose, attempted_alignment=True)
                    break
            if result is None:
                result = {
                    "face_result": "face_not_found",
                    "position_zone": "unknown",
                    "confidence": 0.0,
                    "alignment": "not_applicable",
                    "limit_reached": False,
                    "search_exhausted": True,
                    "found_at_pose": None,
                }
    finally:
        if return_center is None:
            move_pose("center")
        else:
            return_center()

    result.update({
        "coordinate_frame": CAMERA_COORDINATE_FRAME,
        "return_policy": "center_before_decide",
        "observation_level": "presence_only",
        "visual_model_called": False,
        "speech_requested": False,
        "decision_owner": "server_after_receipt",
        "final_gaze_pose": {
            "coordinate_frame": GAZE_COORDINATE_FRAME,
            "name": "center",
        },
        "observations": observations,
        "image_saved": False,
    })
    return result


class LocalFaceObserver:
    def __init__(self, duration_seconds=1.2, sample_interval=0.12, should_stop=None):
        self.duration_seconds = max(0.3, min(3.0, float(duration_seconds)))
        self.sample_interval = max(0.08, min(0.5, float(sample_interval)))
        self.should_stop = should_stop
        self.camera = None
        self.detector = None
        self.cv2 = None

    def __enter__(self):
        for path in (TONYPI_ROOT, f"{TONYPI_ROOT}/HiwonderSDK"):
            if path not in sys.path:
                sys.path.insert(0, path)
        import cv2
        import mediapipe as mp
        import hiwonder.Camera as Camera

        self.cv2 = cv2
        self.camera = Camera.Camera(resolution=(640, 480))
        self.detector = mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.7,
        )
        self.camera.camera_open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        if self.camera is not None:
            self.camera.camera_close()
        if self.detector is not None:
            self.detector.close()

    def observe(self):
        started = time.monotonic()
        next_sample = started
        frames_sampled = 0
        frames_with_face = 0
        max_confidence = 0.0
        center_x_total = 0.0
        center_y_total = 0.0
        zones = Counter()

        while time.monotonic() - started < self.duration_seconds:
            if self.should_stop is not None and self.should_stop():
                raise SeekStopped("stopped_by_emergency_command")
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
            detection_result = self.detector.process(rgb)
            detections = list(detection_result.detections or [])
            if not detections:
                continue

            best = max(detections, key=lambda item: float(item.score[0]))
            confidence = float(best.score[0])
            box = best.location_data.relative_bounding_box
            center_x = max(0.0, min(1.0, float(box.xmin + box.width / 2.0)))
            center_y = max(0.0, min(1.0, float(box.ymin + box.height / 2.0)))
            zone = _zone_for_center_x(center_x)
            frames_with_face += 1
            max_confidence = max(max_confidence, confidence)
            center_x_total += center_x
            center_y_total += center_y
            zones[zone] += 1

        if frames_sampled == 0:
            raise FaceCameraError("camera_no_frames")
        if frames_with_face == 0:
            return {
                "face_result": "face_not_found",
                "position_zone": "unknown",
                "confidence": 0.0,
                "frames_sampled": frames_sampled,
                "frames_with_face": 0,
            }

        dominant_zone = zones.most_common(1)[0][0]
        return {
            "face_result": "face_found",
            "position_zone": dominant_zone,
            "confidence": round(max_confidence, 4),
            "mean_center_x": round(center_x_total / frames_with_face, 4),
            "mean_center_y": round(center_y_total / frames_with_face, 4),
            "frames_sampled": frames_sampled,
            "frames_with_face": frames_with_face,
            "zone_counts": dict(sorted(zones.items())),
        }


def run_local_seek(
    move_pose,
    duration_seconds=1.2,
    sample_interval=0.12,
    return_center=None,
    should_stop=None,
):
    center_guard = _CenterReturnGuard(
        return_center if return_center is not None else lambda: move_pose("center")
    )
    try:
        with LocalFaceObserver(duration_seconds, sample_interval, should_stop=should_stop) as observer:
            return run_seek(
                observer.observe,
                move_pose,
                return_center=center_guard,
                should_stop=should_stop,
            )
    except Exception as seek_error:
        try:
            center_guard()
        except Exception as center_error:
            raise RuntimeError(
                f"seek failed ({seek_error}); center return also failed ({center_error})"
            ) from center_error
        raise


def run_local_track(
    move_absolute,
    center_pitch,
    center_yaw,
    pitch_limits,
    yaw_limits,
    duration_seconds=8.0,
    sample_window_seconds=0.45,
    sample_interval=0.09,
    return_center=None,
    should_stop=None,
):
    center_guard = _CenterReturnGuard(
        return_center
        if return_center is not None
        else lambda: move_absolute(int(center_pitch), int(center_yaw), 0.65)
    )
    try:
        with LocalFaceObserver(
            sample_window_seconds,
            sample_interval,
            should_stop=should_stop,
        ) as observer:
            return run_track(
                observer.observe,
                move_absolute,
                center_pitch,
                center_yaw,
                pitch_limits,
                yaw_limits,
                duration_seconds=duration_seconds,
                return_center=center_guard,
                should_stop=should_stop,
            )
    except Exception as track_error:
        try:
            center_guard()
        except Exception as center_error:
            raise RuntimeError(
                f"track failed ({track_error}); center return also failed ({center_error})"
            ) from center_error
        raise
