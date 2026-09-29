#!/usr/bin/env python3

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT / "protocol"


class PerformanceProtocolTests(unittest.TestCase):
    def load_schema(self, name):
        return json.loads((PROTOCOL / name).read_text(encoding="utf-8"))

    def test_expression_intent_contains_no_physical_control_fields(self):
        schema = self.load_schema("yushi_expression_intent.schema.json")
        properties = set(schema["properties"])
        self.assertTrue(schema["additionalProperties"] is False)
        self.assertFalse(properties & {
            "action",
            "command_id",
            "expected_final_pose",
            "registry_sha256",
            "registry_version",
            "resource_claims",
            "timeout_ms",
        })

    def test_performance_plan_has_waiting_and_silent_terminal_states(self):
        schema = self.load_schema("yushi_performance_plan.schema.json")
        states = set(schema["properties"]["state"]["enum"])
        self.assertTrue({
            "awaiting_result",
            "cancelled",
            "expired",
            "closed_silent",
        } <= states)

    def test_robot_command_specs_are_registry_compiled_not_model_authored(self):
        schema = self.load_schema("yushi_performance_plan.schema.json")
        command_spec = schema["properties"]["robot_command_specs"]["items"]
        required = set(command_spec["required"])
        self.assertTrue({
            "action",
            "parameters",
            "registry_version",
            "registry_sha256",
            "resource_claims",
            "timeout_ms",
            "return_policy",
            "expected_final_pose",
        } <= required)
        self.assertNotIn("command_id", command_spec["properties"])

    def test_plan_keeps_audio_owner_separate_from_text_targets(self):
        schema = self.load_schema("yushi_performance_plan.schema.json")
        self.assertEqual(
            schema["properties"]["audio_owner"]["enum"],
            ["web", "robot", "none"],
        )
        self.assertIn("text_targets", schema["properties"])


if __name__ == "__main__":
    unittest.main()
