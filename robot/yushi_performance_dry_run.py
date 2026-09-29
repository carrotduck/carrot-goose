#!/usr/bin/env python3

"""Offline-only compiler and simulator for unified Yushi performance plans."""

import argparse
import copy
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tonypi_motion_cache import MotionTrajectoryCache
from tonypi_motion_catalog import ARM_IDLE_POSE
from tonypi_registry import COMMAND_SCHEMA_VERSION, TonyPiRegistryGate


ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY_PATH = ROOT / "protocol" / "tonypi_action_registry.json"
INTENT_SCHEMA_VERSION = "yushi-expression-intent/v1"
PLAN_SCHEMA_VERSION = "yushi-performance-plan/v1"
DRY_RUN_SCHEMA_VERSION = "yushi-performance-dry-run/v1"

VALID_TONES = {
    "neutral", "warm", "playful", "bright", "close", "quiet",
    "hollow", "tense", "overheat",
}
VALID_OUTLETS = {"text", "audio", "web_mood", "body", "gaze", "observe"}
VALID_BODY_INTENTS = {
    "none", "greet", "delight", "open_arms", "attention", "comfort", "settle",
}
VALID_GAZE_INTENTS = {"none", "glance", "seek", "track"}
VALID_OBSERVE_LEVELS = {"none", "presence_only", "activity_once"}
VALID_AFTER_RESULT = {"silent", "decide"}
VALID_SOURCES = {
    "main_chat", "group_chat", "keepalive", "voice_call",
    "hourly_arbitrator", "user_command", "safety",
}

TONE_TO_MOOD = {
    "neutral": "neutral",
    "warm": "close",
    "playful": "spark",
    "bright": "spark",
    "close": "close",
    "quiet": "moonroom",
    "hollow": "hollow",
    "tense": "neutral",
    "overheat": "overheat",
}


def _iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _bounded_intensity(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expression_intent_invalid")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("expression_intent_invalid")
    return value


def validate_expression_intent(intent):
    required = {
        "schema_version",
        "utterance_candidate",
        "affective_tone",
        "expressive_intensity",
        "desired_outlets",
        "body_expression_intent",
        "gaze_intent",
        "observe_level",
        "after_result",
    }
    if not isinstance(intent, dict) or set(intent) != required:
        raise ValueError("expression_intent_invalid")
    if intent["schema_version"] != INTENT_SCHEMA_VERSION:
        raise ValueError("expression_intent_invalid")
    utterance = intent["utterance_candidate"]
    if utterance is not None and (
        not isinstance(utterance, str) or len(utterance) > 1200
    ):
        raise ValueError("expression_intent_invalid")
    if intent["affective_tone"] not in VALID_TONES:
        raise ValueError("expression_intent_invalid")
    _bounded_intensity(intent["expressive_intensity"])
    outlets = intent["desired_outlets"]
    if (
        not isinstance(outlets, list)
        or len(outlets) > 6
        or len(outlets) != len(set(outlets))
        or not set(outlets).issubset(VALID_OUTLETS)
    ):
        raise ValueError("expression_intent_invalid")
    if intent["body_expression_intent"] not in VALID_BODY_INTENTS:
        raise ValueError("expression_intent_invalid")
    if intent["gaze_intent"] not in VALID_GAZE_INTENTS:
        raise ValueError("expression_intent_invalid")
    if intent["observe_level"] not in VALID_OBSERVE_LEVELS:
        raise ValueError("expression_intent_invalid")
    if intent["after_result"] not in VALID_AFTER_RESULT:
        raise ValueError("expression_intent_invalid")
    return copy.deepcopy(intent)


class SequentialIdFactory:
    def __init__(self):
        self.counter = 0

    def __call__(self, prefix):
        self.counter += 1
        return f"{prefix}-{self.counter:04d}"


class YushiPerformanceDryRunner:
    def __init__(
        self,
        registry_path=DEFAULT_REGISTRY_PATH,
        *,
        clock=None,
        id_factory=None,
        motion_cache=None,
    ):
        self.registry = TonyPiRegistryGate(registry_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (
            lambda prefix: f"{prefix}-{uuid.uuid4()}"
        )
        self.motion_cache = motion_cache or MotionTrajectoryCache()

    def _new_id(self, prefix):
        return self._id_factory(prefix)

    def _action_spec(
        self,
        action_name,
        parameters,
        performance_phase,
        *,
        required=False,
        dispatch_after_ms=0,
    ):
        action = self.registry.actions[action_name]
        return {
            "command_spec_id": self._new_id("spec"),
            "performance_phase": performance_phase,
            "action": action_name,
            "parameters": copy.deepcopy(parameters),
            "registry_version": self.registry.registry_version,
            "registry_sha256": self.registry.registry_sha256,
            "resource_claims": list(action.get("resources") or []),
            "timeout_ms": int(action["timeout_ms"]),
            "return_policy": str(action["return_policy"]),
            "expected_final_pose": str(action.get("final_pose") or "none"),
            "required": bool(required),
            "dispatch_after_ms": int(dispatch_after_ms),
        }

    def _compile_body_specs(self, intent, context, gaps):
        if "body" not in intent["desired_outlets"]:
            return []
        body_intent = intent["body_expression_intent"]
        intensity = max(0.35, round(intent["expressive_intensity"], 3))
        if body_intent in {"greet", "delight"}:
            return [self._action_spec(
                "happy_wiggle",
                {"intensity": intensity},
                "expression",
            )]
        if body_intent in {"attention", "settle"}:
            return [
                self._action_spec(
                    "hands_ready",
                    {"intensity": intensity},
                    "expression",
                ),
                self._action_spec(
                    "return_idle",
                    {},
                    "recovery",
                    dispatch_after_ms=900,
                ),
            ]
        if body_intent == "open_arms":
            if context["execution_mode"] == "supervised" and context["user_present"]:
                return [self._action_spec("wings_open", {}, "expression")]
            gaps.append("open_arms_requires_supervision")
            return []
        if body_intent == "comfort":
            if context["execution_mode"] == "supervised" and context["user_present"]:
                return [self._action_spec("hug", {}, "expression")]
            gaps.append("comfort_requires_supervision")
        return []

    def _compile_gaze_specs(self, intent, context, gaps):
        if "gaze" not in intent["desired_outlets"]:
            return []
        gaze_intent = intent["gaze_intent"]
        intensity = max(0.35, round(intent["expressive_intensity"], 3))
        if gaze_intent == "glance":
            return [self._action_spec(
                "gaze_glance_left",
                {"intensity": intensity},
                "expression",
            )]
        if gaze_intent in {"seek", "track"}:
            action_name = "seek_user" if gaze_intent == "seek" else "track_face_brief"
            if context["execution_mode"] == "supervised" and context["user_present"]:
                return [self._action_spec(action_name, {}, "seek")]
            gaps.append(f"{action_name}_requires_supervision")
        return []

    def compile_plan(self, intent, context):
        intent = validate_expression_intent(intent)
        if not isinstance(context, dict):
            raise ValueError("performance_context_invalid")
        source = context.get("source", "main_chat")
        execution_mode = context.get("execution_mode", "autonomous")
        user_present = context.get("user_present", False)
        if source not in VALID_SOURCES:
            raise ValueError("performance_context_invalid")
        if execution_mode not in {"autonomous", "supervised"}:
            raise ValueError("performance_context_invalid")
        if not isinstance(user_present, bool):
            raise ValueError("performance_context_invalid")
        normalized_context = {
            **context,
            "source": source,
            "execution_mode": execution_mode,
            "user_present": user_present,
        }
        now = self._clock()
        ttl_seconds = int(context.get("ttl_seconds", 35))
        if not 1 <= ttl_seconds <= 300:
            raise ValueError("performance_context_invalid")
        plan_id = self._new_id("plan")
        gaps = []
        command_specs = self._compile_body_specs(intent, normalized_context, gaps)
        command_specs.extend(
            self._compile_gaze_specs(intent, normalized_context, gaps)
        )
        if intent["observe_level"] == "activity_once":
            gaps.append("observe_user_once_not_registered_fixture_only")
        if len(command_specs) > 3:
            raise ValueError("performance_plan_too_many_commands")

        utterance = intent["utterance_candidate"]
        desired_outlets = set(intent["desired_outlets"])
        text_targets = []
        if utterance and "text" in desired_outlets:
            text_targets = list(context.get("text_targets") or [source])
            if source not in {"main_chat", "group_chat", "keepalive"}:
                text_targets = ["main_chat"]
        if not utterance or "audio" not in desired_outlets:
            audio_owner = "none"
        else:
            preferred_audio = context.get("audio_owner", "robot")
            if preferred_audio not in {"web", "robot", "none"}:
                raise ValueError("performance_context_invalid")
            audio_owner = (
                preferred_audio
                if preferred_audio != "robot" or context.get("robot_online", True)
                else "web"
            )

        mood = (
            TONE_TO_MOOD[intent["affective_tone"]]
            if "web_mood" in desired_outlets
            else "neutral"
        )
        plan = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "state": "planned",
            "source": source,
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=ttl_seconds)),
            "affective_tone": intent["affective_tone"],
            "expressive_intensity": intent["expressive_intensity"],
            "text_targets": text_targets,
            "audio_owner": audio_owner,
            "utterance": utterance,
            "web": {
                "mood": mood,
                "duration_ms": int(context.get("mood_duration_ms", 12000)),
                "return_policy": "base",
            },
            "robot_command_specs": command_specs,
            "after_result": intent["after_result"],
        }
        for field in ("parent_plan_id", "caused_by_receipt_id", "interpersonal_target"):
            if field in context:
                plan[field] = context[field]
        return {
            "plan": plan,
            "execution_context": {
                "mode": execution_mode,
                "user_present": user_present,
            },
            "capability_gaps": gaps,
        }

    def _prepare_motion_preview(self, plan, spec, current_arm_pose):
        if spec["action"] != "happy_wiggle":
            return None
        intensity = spec["parameters"]["intensity"]
        return self.motion_cache.prepare(
            "happy_greeting",
            {
                "expressive_intensity": intensity,
                "openness": intensity,
                "tempo": 1.0,
            },
            current_arm_pose,
            plan_id=plan["plan_id"],
        )

    def dispatch(self, compiled_plan, current_arm_pose=None):
        plan = compiled_plan["plan"]
        execution_context = compiled_plan["execution_context"]
        commands = []
        previews = []
        now = self._clock()
        for spec in plan["robot_command_specs"]:
            command_id = self._new_id("command")
            command = {
                "schema_version": COMMAND_SCHEMA_VERSION,
                "registry_version": spec["registry_version"],
                "registry_sha256": spec["registry_sha256"],
                "plan_id": plan["plan_id"],
                "command_id": command_id,
                "command_type": "action",
                "performance_phase": spec["performance_phase"],
                "action": spec["action"],
                "parameters": copy.deepcopy(spec["parameters"]),
                "execution_context": copy.deepcopy(execution_context),
                "source": plan["source"],
                "issued_at": _iso(now),
                "expires_at": plan["expires_at"],
                "resource_claims": list(spec["resource_claims"]),
                "timeout_ms": spec["timeout_ms"],
                "return_policy": spec["return_policy"],
                "expected_final_pose": spec["expected_final_pose"],
            }
            if "parent_plan_id" in plan:
                command["parent_plan_id"] = plan["parent_plan_id"]
            if "caused_by_receipt_id" in plan:
                command["caused_by_receipt_id"] = plan["caused_by_receipt_id"]
            decision = self.registry.validate_command(command, now=now)
            commands.append({
                "command": command,
                "registry_decision": decision,
                "dispatch_after_ms": spec.get("dispatch_after_ms", 0),
            })
            if decision["allowed"] and not decision["warnings"] and current_arm_pose:
                preview = self._prepare_motion_preview(plan, spec, current_arm_pose)
                if preview is not None:
                    previews.append({
                        "command_id": command_id,
                        "cache": preview,
                    })
        plan["state"] = "dispatched" if commands else "degraded"
        return {
            "plan": plan,
            "commands": commands,
            "motion_previews": previews,
            "capability_gaps": list(compiled_plan["capability_gaps"]),
        }

    def simulate(self, dispatched, *, current_arm_pose=None, result_by_action=None):
        result_by_action = result_by_action or {}
        current_arm_pose = current_arm_pose or dict(ARM_IDLE_POSE)
        receipts = []
        preview_by_command = {
            item["command_id"]: item["cache"]
            for item in dispatched["motion_previews"]
        }
        any_rejected = False
        for item in dispatched["commands"]:
            command = item["command"]
            decision = item["registry_decision"]
            if not decision["allowed"] or decision["warnings"]:
                any_rejected = True
                receipts.append({
                    "receipt_id": f"receipt:{command['command_id']}:skipped",
                    "command_id": command["command_id"],
                    "plan_id": command["plan_id"],
                    "action": command["action"],
                    "status": "skipped",
                    "error_code": decision["error_code"] or "offline_registry_warning",
                    "simulation": True,
                    "write_to_body_memory": False,
                })
                continue
            if command["command_id"] in preview_by_command:
                self.motion_cache.take(
                    preview_by_command[command["command_id"]]["cache_id"],
                    current_arm_pose,
                )
            receipts.append({
                "receipt_id": f"receipt:{command['command_id']}:completed",
                "command_id": command["command_id"],
                "plan_id": command["plan_id"],
                "action": command["action"],
                "status": "completed",
                "final_pose": command["expected_final_pose"],
                "result": copy.deepcopy(result_by_action.get(command["action"])),
                "error_code": None,
                "simulation": True,
                "write_to_body_memory": False,
            })

        plan = dispatched["plan"]
        if any_rejected:
            plan["state"] = "degraded"
        elif plan["after_result"] == "silent" and not plan["utterance"]:
            plan["state"] = "closed_silent"
        elif dispatched["capability_gaps"]:
            plan["state"] = "degraded"
        else:
            plan["state"] = "completed"
        return {
            "schema_version": DRY_RUN_SCHEMA_VERSION,
            "plan": plan,
            "commands": dispatched["commands"],
            "receipts": receipts,
            "motion_previews": dispatched["motion_previews"],
            "capability_gaps": dispatched["capability_gaps"],
            "simulation_only": True,
            "robot_contacted": False,
            "memory_writes": False,
        }


def _intent(**overrides):
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


def run_default_scenarios(registry_path=DEFAULT_REGISTRY_PATH):
    ids = SequentialIdFactory()
    runner = YushiPerformanceDryRunner(registry_path, id_factory=ids)
    idle_pose = dict(ARM_IDLE_POSE)

    happy = runner.compile_plan(_intent(
        utterance_candidate="Good. The web and body expression are connected.",
        affective_tone="bright",
        expressive_intensity=0.82,
        desired_outlets=["text", "audio", "web_mood", "body"],
        body_expression_intent="delight",
    ), {
        "source": "main_chat",
        "execution_mode": "autonomous",
        "user_present": True,
        "robot_online": True,
        "audio_owner": "robot",
        "text_targets": ["main_chat"],
    })
    happy_result = runner.simulate(
        runner.dispatch(happy, current_arm_pose=idle_pose),
        current_arm_pose=idle_pose,
    )

    silent_glance = runner.compile_plan(_intent(
        affective_tone="quiet",
        expressive_intensity=0.4,
        desired_outlets=["gaze"],
        gaze_intent="glance",
    ), {
        "source": "hourly_arbitrator",
        "execution_mode": "autonomous",
        "user_present": False,
        "robot_online": True,
    })
    silent_result = runner.simulate(runner.dispatch(silent_glance))

    seek = runner.compile_plan(_intent(
        affective_tone="quiet",
        expressive_intensity=0.45,
        desired_outlets=["gaze", "observe"],
        gaze_intent="seek",
        observe_level="activity_once",
        after_result="decide",
    ), {
        "source": "hourly_arbitrator",
        "execution_mode": "supervised",
        "user_present": True,
        "robot_online": True,
    })
    seek_result = runner.simulate(
        runner.dispatch(seek),
        result_by_action={
            "seek_user": {
                "face_result": "face_found",
                "position_zone": "image_center",
                "confidence": 0.91,
            },
        },
    )
    seek_receipt = seek_result["receipts"][-1]
    visual_fixture = {
        "fixture_only": True,
        "person_present": True,
        "activity": "using_computer",
        "sensory_impression": (
            "I see screen light in front of her and her hand near the keyboard."
        ),
    }
    follow_up = runner.compile_plan(_intent(
        utterance_candidate="Still by the computer. I only glanced over for a moment.",
        affective_tone="warm",
        expressive_intensity=0.42,
        desired_outlets=["text", "audio", "web_mood"],
        after_result="silent",
    ), {
        "source": "hourly_arbitrator",
        "execution_mode": "autonomous",
        "user_present": True,
        "robot_online": True,
        "audio_owner": "robot",
        "text_targets": ["main_chat"],
        "parent_plan_id": seek_result["plan"]["plan_id"],
        "caused_by_receipt_id": seek_receipt["receipt_id"],
    })
    follow_up_result = runner.simulate(runner.dispatch(follow_up))

    return {
        "schema_version": "yushi-performance-dry-run-report/v1",
        "simulation_only": True,
        "robot_contacted": False,
        "memory_writes": False,
        "scenarios": {
            "happy_reply": happy_result,
            "silent_glance": silent_result,
            "observe_then_decide": {
                "seek_phase": seek_result,
                "visual_fixture": visual_fixture,
                "follow_up_phase": follow_up_result,
            },
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_default_scenarios(args.registry)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
