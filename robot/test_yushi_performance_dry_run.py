#!/usr/bin/env python3

import unittest
from datetime import datetime, timezone

from tonypi_motion_cache import MotionTrajectoryCache
from tonypi_motion_catalog import ARM_IDLE_POSE
from yushi_performance_dry_run import (
    INTENT_SCHEMA_VERSION,
    SequentialIdFactory,
    YushiPerformanceDryRunner,
    run_default_scenarios,
    validate_expression_intent,
)


class FixedDateClock:
    def __call__(self):
        return datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


def intent(**overrides):
    value = {
        "schema_version": INTENT_SCHEMA_VERSION,
        "utterance_candidate": None,
        "affective_tone": "neutral",
        "expressive_intensity": 0.5,
        "desired_outlets": [],
        "body_expression_intent": "none",
        "gaze_intent": "none",
        "observe_level": "none",
        "after_result": "silent",
    }
    value.update(overrides)
    return value


class PerformanceDryRunTests(unittest.TestCase):
    def make_runner(self):
        return YushiPerformanceDryRunner(
            clock=FixedDateClock(),
            id_factory=SequentialIdFactory(),
            motion_cache=MotionTrajectoryCache(),
        )

    def test_model_intent_rejects_any_physical_field(self):
        value = intent()
        value["action"] = "happy_wiggle"

        with self.assertRaisesRegex(ValueError, "expression_intent_invalid"):
            validate_expression_intent(value)

    def test_happy_reply_compiles_canonical_command_and_pose_bound_preview(self):
        runner = self.make_runner()
        compiled = runner.compile_plan(intent(
            utterance_candidate="Good.",
            affective_tone="bright",
            expressive_intensity=0.8,
            desired_outlets=["text", "audio", "web_mood", "body"],
            body_expression_intent="delight",
        ), {
            "source": "main_chat",
            "execution_mode": "autonomous",
            "user_present": True,
            "robot_online": True,
            "audio_owner": "robot",
        })
        dispatched = runner.dispatch(
            compiled,
            current_arm_pose=dict(ARM_IDLE_POSE),
        )

        self.assertEqual(dispatched["plan"]["web"]["mood"], "spark")
        self.assertEqual(dispatched["plan"]["audio_owner"], "robot")
        self.assertEqual(len(dispatched["commands"]), 1)
        command = dispatched["commands"][0]["command"]
        self.assertEqual(command["action"], "happy_wiggle")
        self.assertNotIn("utterance", command)
        self.assertNotIn("affective_tone", command)
        self.assertTrue(dispatched["commands"][0]["registry_decision"]["allowed"])
        self.assertEqual(dispatched["commands"][0]["registry_decision"]["warnings"], [])
        self.assertEqual(len(dispatched["motion_previews"]), 1)

    def test_offline_receipts_can_never_write_body_memory(self):
        runner = self.make_runner()
        compiled = runner.compile_plan(intent(
            expressive_intensity=0.4,
            desired_outlets=["gaze"],
            gaze_intent="glance",
        ), {
            "source": "hourly_arbitrator",
            "execution_mode": "autonomous",
            "user_present": False,
        })
        result = runner.simulate(runner.dispatch(compiled))

        self.assertTrue(result["simulation_only"])
        self.assertFalse(result["robot_contacted"])
        self.assertFalse(result["memory_writes"])
        self.assertTrue(all(
            receipt["write_to_body_memory"] is False
            for receipt in result["receipts"]
        ))

    def test_silent_glance_finishes_closed_silent(self):
        runner = self.make_runner()
        compiled = runner.compile_plan(intent(
            affective_tone="quiet",
            expressive_intensity=0.4,
            desired_outlets=["gaze"],
            gaze_intent="glance",
        ), {
            "source": "hourly_arbitrator",
            "execution_mode": "autonomous",
            "user_present": False,
        })
        result = runner.simulate(runner.dispatch(compiled))

        self.assertEqual(result["plan"]["state"], "closed_silent")
        self.assertEqual(result["receipts"][0]["action"], "gaze_glance_left")
        self.assertEqual(result["receipts"][0]["final_pose"], "center")

    def test_autonomous_seek_is_not_faked_as_current_capability(self):
        runner = self.make_runner()
        compiled = runner.compile_plan(intent(
            desired_outlets=["gaze", "observe"],
            gaze_intent="seek",
            observe_level="activity_once",
            after_result="decide",
        ), {
            "source": "hourly_arbitrator",
            "execution_mode": "autonomous",
            "user_present": False,
        })

        self.assertEqual(compiled["plan"]["robot_command_specs"], [])
        self.assertIn("seek_user_requires_supervision", compiled["capability_gaps"])
        self.assertIn(
            "observe_user_once_not_registered_fixture_only",
            compiled["capability_gaps"],
        )

    def test_follow_up_plan_keeps_causality_without_forcing_body_action(self):
        runner = self.make_runner()
        compiled = runner.compile_plan(intent(
            utterance_candidate="I only glanced over for a moment.",
            affective_tone="warm",
            desired_outlets=["text", "audio"],
        ), {
            "source": "hourly_arbitrator",
            "execution_mode": "autonomous",
            "user_present": True,
            "parent_plan_id": "plan-parent",
            "caused_by_receipt_id": "receipt:seek:completed",
        })
        dispatched = runner.dispatch(compiled)

        self.assertEqual(dispatched["plan"]["parent_plan_id"], "plan-parent")
        self.assertEqual(
            dispatched["plan"]["caused_by_receipt_id"],
            "receipt:seek:completed",
        )
        self.assertEqual(dispatched["commands"], [])

    def test_default_scenarios_cover_happy_silent_and_observe_follow_up(self):
        report = run_default_scenarios()

        self.assertEqual(set(report["scenarios"]), {
            "happy_reply",
            "silent_glance",
            "observe_then_decide",
        })
        self.assertEqual(
            report["scenarios"]["happy_reply"]["plan"]["state"],
            "completed",
        )
        self.assertEqual(
            report["scenarios"]["silent_glance"]["plan"]["state"],
            "closed_silent",
        )
        observe = report["scenarios"]["observe_then_decide"]
        self.assertTrue(observe["visual_fixture"]["fixture_only"])
        self.assertEqual(
            observe["follow_up_phase"]["plan"]["parent_plan_id"],
            observe["seek_phase"]["plan"]["plan_id"],
        )


if __name__ == "__main__":
    unittest.main()
