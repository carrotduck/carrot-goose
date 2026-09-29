#!/usr/bin/env python3

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path


REGISTRY_SCHEMA_VERSION = "tonypi-action-registry/v1"
COMMAND_SCHEMA_VERSION = "tonypi-command/v1"
MONITOR_HARD_ERRORS = {
    "command_type_unsupported",
    "action_not_registered",
    "action_not_remote",
    "parameters_invalid",
    "supervision_required",
    "action_blocked",
    "command_expired",
    "expires_at_invalid",
    "command_contains_brain_fields",
    "resource_claims_mismatch",
    "expected_final_pose_mismatch",
    "return_policy_mismatch",
    "timeout_invalid",
    "performance_phase_invalid",
    "caused_by_receipt_requires_parent_plan",
}
FORBIDDEN_DEVICE_FIELDS = {
    "affective_tone",
    "audio_owner",
    "expressive_intensity",
    "interpersonal_target",
    "mood",
    "text_targets",
    "utterance",
    "visual_observation",
}
VALID_PERFORMANCE_PHASES = {
    "expression",
    "seek",
    "observe",
    "follow_up",
    "recovery",
    "safety",
}


def _parse_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _schema_type_matches(value, expected):
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _matches_parameter_schema(value, schema):
    if not isinstance(schema, dict):
        return False

    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_schema_type_matches(value, item) for item in expected_types):
            return False

    if "enum" in schema and value not in schema["enum"]:
        return False

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return False
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False

    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            return False
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            return False

    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            return False
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            return False
        item_schema = schema.get("items")
        if item_schema is not None and not all(
            _matches_parameter_schema(item, item_schema) for item in value
        ):
            return False

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        if any(field not in value for field in required):
            return False
        if schema.get("additionalProperties") is False:
            if set(value) - set(properties):
                return False
        for field, field_value in value.items():
            field_schema = properties.get(field)
            if field_schema is not None and not _matches_parameter_schema(
                field_value,
                field_schema,
            ):
                return False

    return True


class TonyPiRegistryGate:
    def __init__(self, registry_path, mode_path=None):
        self.registry_path = Path(registry_path)
        self.mode_path = Path(mode_path) if mode_path else None
        raw = self.registry_path.read_bytes()
        registry = json.loads(raw)
        if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            raise ValueError("registry_schema_unsupported")
        version = str(registry.get("registry_version") or "").strip()
        if not version:
            raise ValueError("registry_version_missing")
        actions = registry.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError("registry_actions_missing")
        self.registry = registry
        self.registry_version = version
        self.registry_sha256 = hashlib.sha256(raw).hexdigest()
        self.actions = {}
        for action in actions:
            name = str(action.get("name") or "").strip()
            if not name or name in self.actions:
                raise ValueError("registry_action_name_invalid")
            self.actions[name] = action
        aliases = registry.get("legacy_aliases")
        self.aliases = aliases if isinstance(aliases, dict) else {}

    @property
    def enforcement(self):
        if self.mode_path is None:
            return "monitor"
        try:
            mode = self.mode_path.read_text(encoding="utf-8").strip().lower()
        except OSError:
            mode = "monitor"
        return mode if mode in {"monitor", "enforce"} else "monitor"

    def status(self):
        return {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "registry_version": self.registry_version,
            "registry_sha256": self.registry_sha256,
            "enforcement": self.enforcement,
            "action_count": len(self.actions),
        }

    def validate_command(self, command, now=None):
        if not isinstance(command, dict):
            return self._decision(False, "command_not_object", [], None)

        command_type = str(command.get("command_type") or "action").strip()
        warnings = []
        if command_type in {"stop", "status"}:
            if command.get("schema_version") not in {None, COMMAND_SCHEMA_VERSION}:
                warnings.append("schema_version_unsupported")
            return self._decision(True, None, warnings, None)
        if command_type != "action":
            return self._finish(["command_type_unsupported"], None)

        if not str(command.get("command_type") or "").strip():
            warnings.append("command_type_required")
        if command.get("schema_version") != COMMAND_SCHEMA_VERSION:
            warnings.append("schema_version_unsupported")
        if str(command.get("registry_version") or "") != self.registry_version:
            warnings.append("registry_version_mismatch")
        if str(command.get("registry_sha256") or "") != self.registry_sha256:
            warnings.append("registry_hash_mismatch")
        for field in ("plan_id", "command_id", "source", "issued_at", "expires_at"):
            if not str(command.get(field) or "").strip():
                warnings.append(f"{field}_required")

        if not isinstance(command.get("execution_context"), dict):
            warnings.append("execution_context_required")

        if set(command) & FORBIDDEN_DEVICE_FIELDS:
            warnings.append("command_contains_brain_fields")

        parent_plan_id = str(command.get("parent_plan_id") or "").strip()
        caused_by_receipt_id = str(command.get("caused_by_receipt_id") or "").strip()
        if command.get("parent_plan_id") is not None and not parent_plan_id:
            warnings.append("parent_plan_id_invalid")
        if command.get("caused_by_receipt_id") is not None and not caused_by_receipt_id:
            warnings.append("caused_by_receipt_id_invalid")
        if caused_by_receipt_id and not parent_plan_id:
            warnings.append("caused_by_receipt_requires_parent_plan")

        performance_phase = str(command.get("performance_phase") or "").strip()
        if performance_phase and performance_phase not in VALID_PERFORMANCE_PHASES:
            warnings.append("performance_phase_invalid")

        action_name = str(command.get("action") or "").strip()
        canonical_action = action_name
        if action_name in self.aliases:
            warnings.append("noncanonical_action")
            alias = self.aliases[action_name]
            if isinstance(alias, dict):
                canonical_action = str(alias.get("canonical") or "").strip()
            else:
                canonical_action = str(alias or "").strip()
            action = self.actions.get(canonical_action)
            if action is None:
                warnings.append("action_not_registered")
        else:
            action = self.actions.get(action_name)
            if action is None:
                warnings.append("action_not_registered")

        if action is not None:
            if action.get("exposure") != "remote":
                warnings.append("action_not_remote")
            parameters = command.get("parameters", {})
            schema = action.get("parameters_schema") or {}
            if not _matches_parameter_schema(parameters, schema):
                warnings.append("parameters_invalid")

            if "resource_claims" in command:
                claims = command.get("resource_claims")
                resources = action.get("resources") or []
                if not isinstance(claims, list) or claims != resources:
                    warnings.append("resource_claims_mismatch")
            if "expected_final_pose" in command:
                if str(command.get("expected_final_pose") or "") != str(action.get("final_pose") or ""):
                    warnings.append("expected_final_pose_mismatch")
            if "return_policy" in command:
                if str(command.get("return_policy") or "") != str(action.get("return_policy") or ""):
                    warnings.append("return_policy_mismatch")
            if "timeout_ms" in command:
                timeout_ms = command.get("timeout_ms")
                registry_timeout = action.get("timeout_ms")
                if (
                    isinstance(timeout_ms, bool)
                    or not isinstance(timeout_ms, int)
                    or timeout_ms <= 0
                    or not isinstance(registry_timeout, int)
                    or timeout_ms > registry_timeout
                ):
                    warnings.append("timeout_invalid")

            autonomy = action.get("autonomy")
            context = command.get("execution_context")
            context = context if isinstance(context, dict) else {}
            context_mode = str(context.get("mode") or "").strip()
            user_present = context.get("user_present") is True
            if autonomy == "supervised" and not (context_mode == "supervised" and user_present):
                warnings.append("supervision_required")
            elif autonomy == "blocked":
                warnings.append("action_blocked")
            elif autonomy == "allowed" and context_mode not in {"autonomous", "supervised"}:
                warnings.append("execution_context_invalid")

        expires_at = command.get("expires_at")
        if expires_at:
            try:
                expires = _parse_time(expires_at)
                current = now or datetime.now(timezone.utc)
                if current.tzinfo is None:
                    current = current.replace(tzinfo=timezone.utc)
                if expires <= current.astimezone(timezone.utc):
                    warnings.append("command_expired")
            except (TypeError, ValueError):
                warnings.append("expires_at_invalid")

        return self._finish(warnings, canonical_action if action is not None else None)

    def _finish(self, warnings, canonical_action):
        unique_warnings = list(dict.fromkeys(warnings))
        if self.enforcement == "monitor":
            hard_error = next(
                (warning for warning in unique_warnings if warning in MONITOR_HARD_ERRORS),
                None,
            )
            if hard_error:
                return self._decision(False, hard_error, unique_warnings, canonical_action)
            return self._decision(True, None, unique_warnings, canonical_action)
        error_code = unique_warnings[0] if unique_warnings else None
        return self._decision(not unique_warnings, error_code, unique_warnings, canonical_action)

    def _decision(self, allowed, error_code, warnings, canonical_action):
        return {
            "allowed": bool(allowed),
            "error_code": error_code,
            "warnings": list(warnings),
            "canonical_action": canonical_action,
            "registry_version": self.registry_version,
            "registry_sha256": self.registry_sha256,
            "enforcement": self.enforcement,
        }
