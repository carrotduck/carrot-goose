#!/usr/bin/env python3

import unittest

from tonypi_motion_cache import MotionTrajectoryCache
from tonypi_motion_catalog import ARM_IDLE_POSE


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class MotionTrajectoryCacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.cache = MotionTrajectoryCache(clock=self.clock)
        self.idle_pose = dict(ARM_IDLE_POSE)

    def prepare(self, **overrides):
        arguments = {
            "phrase_name": "quiet_acknowledge",
            "genome": {
                "expressive_intensity": 0.45,
                "tempo": 0.9,
                "hold_ms": 250,
            },
            "current_pose": self.idle_pose,
            "plan_id": "plan-test-1",
        }
        arguments.update(overrides)
        return self.cache.prepare(**arguments)

    def test_prepared_trajectory_is_pose_bound_and_single_use(self):
        prepared = self.prepare()
        consumed = self.cache.take(prepared["cache_id"], self.idle_pose)

        self.assertEqual(consumed["state"], "consumed")
        self.assertEqual(consumed["plan_id"], "plan-test-1")
        self.assertTrue(consumed["compiled"]["kinematic_audit"]["passed"])
        self.assertEqual(self.cache.status()["entry_count"], 0)
        with self.assertRaisesRegex(KeyError, "motion_cache_miss"):
            self.cache.take(prepared["cache_id"], self.idle_pose)

    def test_expired_trajectory_cannot_execute(self):
        prepared = self.prepare(ttl_seconds=2.0)
        self.clock.advance(2.0)

        with self.assertRaisesRegex(TimeoutError, "motion_cache_expired"):
            self.cache.take(prepared["cache_id"], self.idle_pose)
        self.assertEqual(self.cache.status()["entry_count"], 0)

    def test_pose_drift_invalidates_prepared_trajectory(self):
        prepared = self.prepare()
        drifted = dict(self.idle_pose)
        drifted[16] += 13

        with self.assertRaisesRegex(ValueError, "motion_cache_start_pose_drift"):
            self.cache.take(prepared["cache_id"], drifted)
        with self.assertRaisesRegex(KeyError, "motion_cache_miss"):
            self.cache.take(prepared["cache_id"], self.idle_pose)

    def test_non_idle_pose_is_rejected_before_compilation_is_cached(self):
        non_idle = dict(self.idle_pose)
        non_idle[8] += 20

        with self.assertRaisesRegex(ValueError, "motion_cache_start_pose_mismatch"):
            self.prepare(current_pose=non_idle)
        self.assertEqual(self.cache.status()["entry_count"], 0)

    def test_full_pose_input_is_accepted_but_only_arm_pose_is_bound(self):
        full_pose = {servo_id: 500 for servo_id in range(1, 19)}
        full_pose.update(self.idle_pose)

        prepared = self.prepare(current_pose=full_pose)

        self.assertEqual(set(prepared["observed_start_pose"]), set(self.idle_pose))

    def test_capacity_evicts_oldest_prepared_entry(self):
        cache = MotionTrajectoryCache(capacity=2, clock=self.clock)
        first = cache.prepare("quiet_acknowledge", {}, self.idle_pose)
        self.clock.advance(0.1)
        second = cache.prepare("quiet_acknowledge", {}, self.idle_pose)
        self.clock.advance(0.1)
        third = cache.prepare("quiet_acknowledge", {}, self.idle_pose)

        status_ids = {entry["cache_id"] for entry in cache.status()["entries"]}
        self.assertNotIn(first["cache_id"], status_ids)
        self.assertIn(second["cache_id"], status_ids)
        self.assertIn(third["cache_id"], status_ids)

    def test_cache_metadata_never_exposes_compiled_servo_frames(self):
        prepared = self.prepare()

        self.assertNotIn("compiled", prepared)
        status = self.cache.status()
        self.assertNotIn("compiled", status["entries"][0])


if __name__ == "__main__":
    unittest.main()
