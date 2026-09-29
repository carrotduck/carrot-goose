#!/usr/bin/env python3

"""Ephemeral, pose-bound cache for precompiled TonyPi expression trajectories."""

import copy
import hashlib
import json
import math
import threading
import time

from tonypi_motion_catalog import (
    ARM_IDLE_POSE,
    ARM_SERVO_IDS,
    BUS_SERVO_MAX,
    BUS_SERVO_MIN,
    compile_motion_phrase,
)


MOTION_CACHE_SCHEMA_VERSION = "tonypi-motion-cache/v1"
DEFAULT_CACHE_TTL_SECONDS = 20.0
MAX_CACHE_TTL_SECONDS = 60.0
DEFAULT_CACHE_CAPACITY = 8
START_POSE_TOLERANCE = 12


def _normalize_arm_pose(raw_pose):
    if isinstance(raw_pose, dict):
        items = raw_pose.items()
    elif isinstance(raw_pose, (list, tuple)):
        items = raw_pose
    else:
        raise ValueError("motion_cache_pose_invalid")

    normalized = {}
    try:
        for raw_servo_id, raw_pulse in items:
            if isinstance(raw_servo_id, bool) or isinstance(raw_pulse, bool):
                raise ValueError("motion_cache_pose_invalid")
            servo_id = int(raw_servo_id)
            pulse = int(raw_pulse)
            if float(raw_servo_id) != servo_id or float(raw_pulse) != pulse:
                raise ValueError("motion_cache_pose_invalid")
            if not BUS_SERVO_MIN <= pulse <= BUS_SERVO_MAX:
                raise ValueError("motion_cache_pose_invalid")
            if servo_id in ARM_SERVO_IDS:
                normalized[servo_id] = pulse
    except (TypeError, ValueError, OverflowError):
        raise ValueError("motion_cache_pose_invalid") from None

    if set(normalized) != set(ARM_SERVO_IDS):
        raise ValueError("motion_cache_pose_invalid")
    return normalized


def _pose_matches(actual, expected, tolerance=START_POSE_TOLERANCE):
    return all(
        abs(int(actual[servo_id]) - int(expected[servo_id])) <= tolerance
        for servo_id in ARM_SERVO_IDS
    )


def _validate_ttl(ttl_seconds):
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
        raise ValueError("motion_cache_ttl_invalid")
    ttl_seconds = float(ttl_seconds)
    if (
        not math.isfinite(ttl_seconds)
        or ttl_seconds <= 0.0
        or ttl_seconds > MAX_CACHE_TTL_SECONDS
    ):
        raise ValueError("motion_cache_ttl_invalid")
    return ttl_seconds


class MotionTrajectoryCache:
    def __init__(
        self,
        *,
        capacity=DEFAULT_CACHE_CAPACITY,
        default_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
        clock=None,
    ):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("motion_cache_capacity_invalid")
        self.capacity = capacity
        self.default_ttl_seconds = _validate_ttl(default_ttl_seconds)
        self._clock = clock or time.monotonic
        self._entries = {}
        self._counter = 0
        self._lock = threading.Lock()

    @staticmethod
    def expected_start_pose():
        return {int(servo_id): int(pulse) for servo_id, pulse in ARM_IDLE_POSE}

    def _purge_expired_locked(self, now):
        expired_ids = [
            cache_id
            for cache_id, entry in self._entries.items()
            if now >= entry["expires_at_monotonic"]
        ]
        for cache_id in expired_ids:
            self._entries.pop(cache_id, None)
        return expired_ids

    def _make_cache_id(self, phrase_name, genome, start_pose, plan_id, created_at):
        self._counter += 1
        material = {
            "phrase": phrase_name,
            "genome": genome,
            "start_pose": start_pose,
            "plan_id": plan_id,
            "created_at": round(created_at, 6),
            "counter": self._counter,
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        return f"motion-{digest}"

    def prepare(
        self,
        phrase_name,
        genome,
        current_pose,
        *,
        plan_id=None,
        ttl_seconds=None,
    ):
        if plan_id is not None and (
            not isinstance(plan_id, str) or not plan_id or len(plan_id) > 128
        ):
            raise ValueError("motion_cache_plan_id_invalid")
        ttl_seconds = _validate_ttl(
            self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        )
        observed_start_pose = _normalize_arm_pose(current_pose)
        expected_start_pose = self.expected_start_pose()
        if not _pose_matches(observed_start_pose, expected_start_pose):
            raise ValueError("motion_cache_start_pose_mismatch")

        compiled = compile_motion_phrase(phrase_name, genome)
        if not compiled["kinematic_audit"]["passed"]:
            raise ValueError("motion_cache_compiled_audit_failed")

        now = float(self._clock())
        with self._lock:
            self._purge_expired_locked(now)
            while len(self._entries) >= self.capacity:
                oldest_id = min(
                    self._entries,
                    key=lambda cache_id: self._entries[cache_id]["created_at_monotonic"],
                )
                self._entries.pop(oldest_id)
            cache_id = self._make_cache_id(
                phrase_name,
                compiled["applied_genome"],
                observed_start_pose,
                plan_id,
                now,
            )
            entry = {
                "cache_schema_version": MOTION_CACHE_SCHEMA_VERSION,
                "cache_id": cache_id,
                "state": "prepared",
                "plan_id": plan_id,
                "phrase": phrase_name,
                "applied_genome": dict(compiled["applied_genome"]),
                "motion_contract_version": compiled["motion_contract_version"],
                "created_at_monotonic": now,
                "expires_at_monotonic": now + ttl_seconds,
                "ttl_seconds": ttl_seconds,
                "observed_start_pose": dict(observed_start_pose),
                "expected_start_pose": expected_start_pose,
                "start_pose_tolerance": START_POSE_TOLERANCE,
                "compiled": compiled,
            }
            self._entries[cache_id] = entry
            return copy.deepcopy({
                key: value
                for key, value in entry.items()
                if key != "compiled"
            })

    def take(self, cache_id, current_pose):
        if not isinstance(cache_id, str) or not cache_id:
            raise ValueError("motion_cache_id_invalid")
        observed_pose = _normalize_arm_pose(current_pose)
        now = float(self._clock())
        with self._lock:
            entry = self._entries.get(cache_id)
            if entry is None:
                raise KeyError("motion_cache_miss")
            if now >= entry["expires_at_monotonic"]:
                self._entries.pop(cache_id, None)
                raise TimeoutError("motion_cache_expired")
            if not _pose_matches(observed_pose, entry["observed_start_pose"]):
                self._entries.pop(cache_id, None)
                raise ValueError("motion_cache_start_pose_drift")
            if not _pose_matches(observed_pose, entry["expected_start_pose"]):
                self._entries.pop(cache_id, None)
                raise ValueError("motion_cache_start_pose_mismatch")
            entry = self._entries.pop(cache_id)

        return {
            "cache_schema_version": MOTION_CACHE_SCHEMA_VERSION,
            "cache_id": cache_id,
            "state": "consumed",
            "plan_id": entry["plan_id"],
            "phrase": entry["phrase"],
            "prepared_age_seconds": round(now - entry["created_at_monotonic"], 6),
            "motion_contract_version": entry["motion_contract_version"],
            "compiled": copy.deepcopy(entry["compiled"]),
        }

    def cancel(self, cache_id):
        with self._lock:
            return self._entries.pop(cache_id, None) is not None

    def status(self):
        now = float(self._clock())
        with self._lock:
            expired_ids = self._purge_expired_locked(now)
            entries = [
                {
                    "cache_id": entry["cache_id"],
                    "plan_id": entry["plan_id"],
                    "phrase": entry["phrase"],
                    "age_seconds": round(now - entry["created_at_monotonic"], 6),
                    "expires_in_seconds": round(
                        entry["expires_at_monotonic"] - now,
                        6,
                    ),
                }
                for entry in sorted(
                    self._entries.values(),
                    key=lambda item: item["created_at_monotonic"],
                )
            ]
        return {
            "cache_schema_version": MOTION_CACHE_SCHEMA_VERSION,
            "capacity": self.capacity,
            "entry_count": len(entries),
            "expired_purged": len(expired_ids),
            "entries": entries,
        }
