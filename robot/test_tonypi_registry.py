#!/usr/bin/env python3

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tonypi_registry import TonyPiRegistryGate


ROOT = Path(__file__).resolve().parent
ACTIVE_REGISTRY = ROOT / "protocol" / "tonypi_action_registry.json"


def command_for(gate, action, **updates):
    now = datetime.now(timezone.utc)
    command = {
        "schema_version": "tonypi-command/v1",
        "registry_version": gate.registry_version,
        "registry_sha256": gate.registry_sha256,
        "plan_id": "plan-test",
        "command_id": "command-test",
        "command_type": "action",
        "action": action,
        "parameters": {},
        "execution_context": {"mode": "autonomous", "user_present": False},
        "source": "unit_test",
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=35)).isoformat(),
    }
    command.update(updates)
    return command


class RegistryGateTests(unittest.TestCase):
    def make_gate(self, registry_path=ACTIVE_REGISTRY, mode="enforce"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        mode_path = Path(temporary.name) / "mode"
        mode_path.write_text(mode, encoding="utf-8")
        return TonyPiRegistryGate(registry_path, mode_path)

    def test_active_registry_loads(self):
        gate = self.make_gate()
        self.assertEqual(gate.registry_version, "1.5.1")
        self.assertEqual(len(gate.actions), 31)

    def test_motion_phrase_acceptance_cases_are_supervised_and_unverified(self):
        gate = self.make_gate()
        names = {
            "quiet_acknowledge_low",
            "quiet_acknowledge_medium",
            "quiet_acknowledge_high",
            "happy_greeting_low",
            "happy_greeting_medium",
            "happy_greeting_high",
        }
        for name in names:
            action = gate.actions[name]
            self.assertFalse(action["verified"], name)
            self.assertEqual(action["autonomy"], "supervised", name)
            self.assertTrue(action["requires_supervision"], name)
            self.assertEqual(action["resources"], ["body"], name)
            self.assertEqual(action["uses"], ["arms"], name)
            self.assertEqual(action["final_pose"], "return_idle", name)
            self.assertFalse(gate.validate_command(command_for(gate, name))["allowed"])
            supervised = command_for(
                gate,
                name,
                execution_context={"mode": "supervised", "user_present": True},
            )
            self.assertTrue(gate.validate_command(supervised)["allowed"], name)

    def test_parametric_expression_actions_use_one_bounded_intensity(self):
        gate = self.make_gate()
        names = {
            "hands_ready",
            "happy_wiggle",
            "gaze_glance_left",
            "gaze_glance_right",
            "gaze_glance_up",
            "gaze_glance_down",
        }
        for name in names:
            schema = gate.actions[name]["parameters_schema"]
            self.assertFalse(schema["additionalProperties"], name)
            self.assertEqual(
                schema["properties"]["intensity"],
                {"type": "number", "minimum": 0.35, "maximum": 1.0},
                name,
            )
        self.assertNotIn(
            "properties",
            gate.actions["happy_wave"]["parameters_schema"],
        )

    def test_verified_gesture_observation_stays_supervised(self):
        gate = self.make_gate()
        action = gate.actions["observe_gesture_once"]
        self.assertTrue(action["verified"])
        self.assertEqual(
            action["verification_level"],
            "supervised_physical_acceptance_with_emergency_stop",
        )
        self.assertEqual(action["autonomy"], "supervised")
        self.assertTrue(action["requires_supervision"])
        self.assertEqual(action["resources"], ["camera"])

    def test_monitor_allows_legacy_command_but_reports_warnings(self):
        gate = self.make_gate(mode="monitor")
        decision = gate.validate_command({"action": "happy_wave"})
        self.assertTrue(decision["allowed"])
        self.assertIn("schema_version_unsupported", decision["warnings"])
        self.assertIn("registry_version_mismatch", decision["warnings"])

    def test_enforce_allows_complete_autonomous_command(self):
        gate = self.make_gate()
        decision = gate.validate_command(command_for(gate, "happy_wave"))
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["warnings"], [])

    def test_alias_is_rejected_on_device(self):
        gate = self.make_gate()
        decision = gate.validate_command(command_for(gate, "wave!!"))
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["error_code"], "noncanonical_action")
        self.assertEqual(decision["canonical_action"], "happy_wave")

    def test_registry_mismatch_is_rejected_but_stop_remains_allowed(self):
        gate = self.make_gate()
        command = command_for(gate, "happy_wave", registry_version="9.9.9")
        self.assertEqual(gate.validate_command(command)["error_code"], "registry_version_mismatch")
        stop = {"command_type": "stop", "schema_version": "tonypi-command/v1"}
        self.assertTrue(gate.validate_command(stop)["allowed"])

    def test_supervised_seek_requires_presence_context(self):
        gate = self.make_gate()
        missing = command_for(gate, "seek_user")
        self.assertEqual(gate.validate_command(missing)["error_code"], "supervision_required")
        supervised = command_for(
            gate,
            "seek_user",
            execution_context={"mode": "supervised", "user_present": True},
        )
        self.assertTrue(gate.validate_command(supervised)["allowed"])

    def test_startup_recover_requires_supervision(self):
        gate = self.make_gate()
        autonomous = command_for(gate, "startup_recover")
        self.assertEqual(gate.validate_command(autonomous)["error_code"], "supervision_required")
        supervised = command_for(
            gate,
            "startup_recover",
            execution_context={"mode": "supervised", "user_present": True},
        )
        self.assertTrue(gate.validate_command(supervised)["allowed"])

    def test_brief_face_tracking_requires_supervision(self):
        gate = self.make_gate()
        autonomous = command_for(gate, "track_face_brief")
        self.assertEqual(gate.validate_command(autonomous)["error_code"], "supervision_required")
        supervised = command_for(
            gate,
            "track_face_brief",
            execution_context={"mode": "supervised", "user_present": True},
        )
        self.assertTrue(gate.validate_command(supervised)["allowed"])

    def test_gesture_observation_requires_supervision(self):
        gate = self.make_gate()
        autonomous = command_for(gate, "observe_gesture_once")
        self.assertEqual(gate.validate_command(autonomous)["error_code"], "supervision_required")
        supervised = command_for(
            gate,
            "observe_gesture_once",
            execution_context={"mode": "supervised", "user_present": True},
        )
        self.assertTrue(gate.validate_command(supervised)["allowed"])

    def test_expired_command_is_rejected(self):
        gate = self.make_gate()
        now = datetime.now(timezone.utc)
        command = command_for(gate, "happy_wave", expires_at=(now - timedelta(seconds=1)).isoformat())
        self.assertEqual(gate.validate_command(command, now=now)["error_code"], "command_expired")

    def test_unknown_parameters_are_rejected(self):
        gate = self.make_gate()
        command = command_for(gate, "happy_wave", parameters={"speed": 2})
        self.assertEqual(gate.validate_command(command)["error_code"], "parameters_invalid")

    def test_bounded_numeric_parameters_validate_type_and_range(self):
        registry = json.loads(ACTIVE_REGISTRY.read_text(encoding="utf-8"))
        registry["registry_version"] = "test-intensity"
        action = next(item for item in registry["actions"] if item["name"] == "happy_wiggle")
        action["parameters_schema"] = {
            "type": "object",
            "properties": {
                "intensity": {
                    "type": "number",
                    "minimum": 0.35,
                    "maximum": 1.0,
                }
            },
            "additionalProperties": False,
        }
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        registry_path = Path(temporary.name) / "registry.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        gate = self.make_gate(registry_path=registry_path)

        for value in (0.35, 0.7, 1):
            decision = gate.validate_command(
                command_for(gate, "happy_wiggle", parameters={"intensity": value})
            )
            self.assertTrue(decision["allowed"], value)
        for value in (0.34, 1.01, "0.7", True, float("nan")):
            decision = gate.validate_command(
                command_for(gate, "happy_wiggle", parameters={"intensity": value})
            )
            self.assertEqual(decision["error_code"], "parameters_invalid", value)

    def test_monitor_still_rejects_unknown_and_blocked_actions(self):
        gate = self.make_gate(mode="monitor")
        unknown = gate.validate_command(command_for(gate, "not_a_real_action"))
        blocked = gate.validate_command(command_for(gate, "soft_hug"))
        self.assertFalse(unknown["allowed"])
        self.assertEqual(unknown["error_code"], "action_not_registered")
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["error_code"], "action_blocked")

    def test_monitor_still_rejects_expired_commands(self):
        gate = self.make_gate(mode="monitor")
        now = datetime.now(timezone.utc)
        command = command_for(gate, "happy_wave", expires_at=(now - timedelta(seconds=1)).isoformat())
        decision = gate.validate_command(command, now=now)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["error_code"], "command_expired")

    def test_blocked_action_stays_blocked_even_when_supervised(self):
        gate = self.make_gate()
        command = command_for(
            gate,
            "soft_hug",
            execution_context={"mode": "supervised", "user_present": True},
        )
        self.assertEqual(gate.validate_command(command)["error_code"], "action_blocked")

    def test_compiler_injected_physical_contract_must_match_registry(self):
        gate = self.make_gate()
        action = gate.actions["happy_wiggle"]
        command = command_for(
            gate,
            "happy_wiggle",
            resource_claims=action["resources"],
            expected_final_pose=action["final_pose"],
            return_policy=action["return_policy"],
            timeout_ms=action["timeout_ms"],
            performance_phase="expression",
        )
        self.assertTrue(gate.validate_command(command)["allowed"])

        mismatches = (
            {"resource_claims": ["camera"]},
            {"expected_final_pose": "hands_ready_hold"},
            {"return_policy": "hold"},
            {"timeout_ms": action["timeout_ms"] + 1},
        )
        expected_errors = (
            "resource_claims_mismatch",
            "expected_final_pose_mismatch",
            "return_policy_mismatch",
            "timeout_invalid",
        )
        for updates, error_code in zip(mismatches, expected_errors):
            invalid = dict(command)
            invalid.update(updates)
            self.assertEqual(gate.validate_command(invalid)["error_code"], error_code)

    def test_model_only_fields_are_never_allowed_to_reach_device(self):
        gate = self.make_gate(mode="monitor")
        command = command_for(
            gate,
            "happy_wave",
            interpersonal_target="zhenzhen",
            utterance={"text": "hello"},
        )
        decision = gate.validate_command(command)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["error_code"], "command_contains_brain_fields")

    def test_follow_up_command_keeps_plan_causality_without_private_target(self):
        gate = self.make_gate()
        command = command_for(
            gate,
            "gaze_center",
            plan_id="follow-up-plan",
            parent_plan_id="seek-plan",
            caused_by_receipt_id="receipt:seek-command:completed",
            performance_phase="follow_up",
        )
        self.assertTrue(gate.validate_command(command)["allowed"])
        missing_parent = dict(command)
        missing_parent.pop("parent_plan_id")
        self.assertEqual(
            gate.validate_command(missing_parent)["error_code"],
            "caused_by_receipt_requires_parent_plan",
        )

    def test_unknown_performance_phase_is_rejected(self):
        gate = self.make_gate()
        command = command_for(gate, "happy_wave", performance_phase="model_whim")
        self.assertEqual(
            gate.validate_command(command)["error_code"],
            "performance_phase_invalid",
        )


if __name__ == "__main__":
    unittest.main()
