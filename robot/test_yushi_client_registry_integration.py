#!/usr/bin/env python3

import importlib
import json
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tonypi_registry import TonyPiRegistryGate


ROOT = Path(__file__).resolve().parent
ACTIVE_REGISTRY = ROOT / "protocol" / "tonypi_action_registry.json"


def command_for(gate, action, **overrides):
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
        "source": "test",
        "issued_at": (now - timedelta(seconds=1)).isoformat(),
        "expires_at": (now + timedelta(seconds=30)).isoformat(),
    }
    command.update(overrides)
    return command


def import_client_with_fake_hardware():
    if "yushi_client" in sys.modules:
        return sys.modules["yushi_client"]

    package = types.ModuleType("hiwonder")
    package.__path__ = []
    action_group = types.ModuleType("hiwonder.ActionGroupControl")

    class FakeBoard:
        def __init__(self):
            self.reception_enabled = False
            self.bus_moves = []
            self.gaze_moves = []
            self.imu_values = []

        def buf_write(self, *_args, **_kwargs):
            return None

        def enable_reception(self, enabled=True):
            self.reception_enabled = bool(enabled)

        def bus_servo_set_position(self, duration, positions):
            self.bus_moves.append((duration, positions))

        def pwm_servo_set_position(self, duration, positions):
            self.gaze_moves.append((duration, positions))

        def get_imu(self):
            return self.imu_values.pop(0) if self.imu_values else None

    action_group.board = FakeBoard()
    action_group.runActionGroup = lambda *_args, **_kwargs: None
    action_group.stop_calls = []
    action_group.stopAction = lambda: action_group.stop_calls.append("stopAction")
    action_group.stopActionGroup = lambda: action_group.stop_calls.append("stopActionGroup")
    package.ActionGroupControl = action_group
    sys.modules["hiwonder"] = package
    sys.modules["hiwonder.ActionGroupControl"] = action_group
    requests = types.ModuleType("requests")
    requests.get = lambda *_args, **_kwargs: None
    requests.post = lambda *_args, **_kwargs: None

    class FakeSession:
        def get(self, *args, **kwargs):
            return requests.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            return requests.post(*args, **kwargs)

    requests.Session = FakeSession
    sys.modules["requests"] = requests
    return importlib.import_module("yushi_client")


class ClientRegistryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = import_client_with_fake_hardware()

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.mode_path = Path(self.tempdir.name) / "registry_enforcement"
        self.original_gate = self.client.REGISTRY_GATE
        self.original_do_action = self.client.do_action
        self.original_code_action = self.client.code_action
        self.original_enqueue = self.client._enqueue_robot_receipt
        self.original_say = self.client.say
        self.original_run_action_group = self.client.AGC.runActionGroup
        self.original_startup_preflight = self.client._startup_recovery_preflight
        self.original_collect_imu_samples = self.client._collect_imu_samples
        self.original_move_atom = self.client._move_atom
        self.original_move_gaze = self.client._move_gaze
        self.original_ledger_file = self.client.TONYPI_COMMAND_LEDGER_FILE
        self.original_outbox_file = self.client.TONYPI_RECEIPT_OUTBOX_FILE
        self.original_keepalive_delivery_file = (
            self.client.TONYPI_KEEPALIVE_DELIVERY_FILE
        )
        self.client.TONYPI_COMMAND_LEDGER_FILE = str(
            Path(self.tempdir.name) / "command_ledger.json"
        )
        self.client.TONYPI_RECEIPT_OUTBOX_FILE = str(
            Path(self.tempdir.name) / "receipt_outbox.json"
        )
        self.client.TONYPI_KEEPALIVE_DELIVERY_FILE = str(
            Path(self.tempdir.name) / "keepalive_delivery_state.json"
        )
        self.client.COMMAND_PERSISTENCE_LOADED = False
        self.client.KEEPALIVE_DELIVERY_STATE_LOADED = False
        with self.client.KEEPALIVE_DELIVERY_LOCK:
            self.client.KEEPALIVE_DELIVERY_STATE.clear()
            self.client.KEEPALIVE_DELIVERY_STATE.update(
                {
                    "version": 1,
                    "owner_id": "",
                    "updated_at": "",
                    "deliveries": {},
                }
            )
        with self.client.COMMAND_CONTEXT_LOCK:
            self.client.COMMAND_RECEIPT_CONTEXT.clear()
        with self.client.ACTIVE_MOTION_LOCK:
            self.client.ACTIVE_MOTIONS.clear()
        self.client.EMERGENCY_STOP_EVENT.clear()
        self.client.AGC.stop_calls.clear()
        self.client.AGC.board.bus_moves.clear()
        self.client.AGC.board.gaze_moves.clear()
        self.client.AGC.board.imu_values.clear()
        with self.client.BATTERY_STATE_LOCK:
            self.client.LAST_BATTERY_MV = 12000
            self.client.LAST_BATTERY_AT = time.monotonic()
        with self.client.ACTION_COOLDOWN_LOCK:
            self.client.ACTION_LAST_STARTED.clear()
        with self.client.COMMAND_LEDGER_LOCK:
            self.client.COMMAND_LEDGER.clear()
            self.client.RECEIPT_OUTBOX.clear()
        upright = (-0.965, -0.110, 0.177, 3.21, 0.0, 1.63)
        self.client._collect_imu_samples = lambda duration=0.45: [upright] * 25
        while True:
            try:
                self.client.ROBOT_RECEIPT_QUEUE.get_nowait()
                self.client.ROBOT_RECEIPT_QUEUE.task_done()
            except self.client.queue.Empty:
                break

    def tearDown(self):
        self.client.REGISTRY_GATE = self.original_gate
        self.client.do_action = self.original_do_action
        self.client.code_action = self.original_code_action
        self.client._enqueue_robot_receipt = self.original_enqueue
        self.client.say = self.original_say
        self.client.AGC.runActionGroup = self.original_run_action_group
        self.client._startup_recovery_preflight = self.original_startup_preflight
        self.client._collect_imu_samples = self.original_collect_imu_samples
        self.client._move_atom = self.original_move_atom
        self.client._move_gaze = self.original_move_gaze
        self.client.TONYPI_COMMAND_LEDGER_FILE = self.original_ledger_file
        self.client.TONYPI_RECEIPT_OUTBOX_FILE = self.original_outbox_file
        self.client.TONYPI_KEEPALIVE_DELIVERY_FILE = (
            self.original_keepalive_delivery_file
        )
        self.client.COMMAND_PERSISTENCE_LOADED = False
        self.client.KEEPALIVE_DELIVERY_STATE_LOADED = False
        with self.client.KEEPALIVE_DELIVERY_LOCK:
            self.client.KEEPALIVE_DELIVERY_STATE.clear()
            self.client.KEEPALIVE_DELIVERY_STATE.update(
                {
                    "version": 1,
                    "owner_id": "",
                    "updated_at": "",
                    "deliveries": {},
                }
            )
        with self.client.COMMAND_LEDGER_LOCK:
            self.client.COMMAND_LEDGER.clear()
            self.client.RECEIPT_OUTBOX.clear()
        self.client.EMERGENCY_STOP_EVENT.clear()
        with self.client.ACTIVE_MOTION_LOCK:
            self.client.ACTIVE_MOTIONS.clear()
        self.tempdir.cleanup()

    def install_gate(self, mode="enforce"):
        self.mode_path.write_text(mode, encoding="utf-8")
        gate = TonyPiRegistryGate(ACTIVE_REGISTRY, self.mode_path)
        self.client.REGISTRY_GATE = gate
        return gate

    def capture_routing(self):
        calls = []
        receipts = []

        def capture_d6a(action_name, **kwargs):
            calls.append(("d6a", action_name, kwargs))
            return True

        def capture_code(action_name, **kwargs):
            calls.append(("code", action_name, kwargs))
            return True

        self.client.do_action = capture_d6a
        self.client.code_action = capture_code
        self.client._enqueue_robot_receipt = lambda command_id, status, action, **extra: receipts.append(
            (command_id, status, action, extra)
        )
        return calls, receipts

    def test_canonical_action_routes_to_implementation_and_keeps_canonical_receipt(self):
        gate = self.install_gate()
        calls, receipts = self.capture_routing()
        self.client.on_robot_action(command_for(gate, "happy_wave"))
        self.assertEqual(calls, [("d6a", "wave!!", {
            "command_id": "command-test",
            "receipt_action": "happy_wave",
        })])
        self.assertEqual(receipts[0][1:3], ("ack", "happy_wave"))

    def test_monitor_mode_normalizes_legacy_alias_before_execution(self):
        gate = self.install_gate("monitor")
        calls, receipts = self.capture_routing()
        self.client.on_robot_action(command_for(gate, "wave!!"))
        self.assertEqual(calls[0][0:2], ("d6a", "wave!!"))
        self.assertEqual(calls[0][2]["receipt_action"], "happy_wave")
        self.assertEqual(receipts[0][2], "happy_wave")
        self.assertIn("noncanonical_action", receipts[0][3]["registry_warnings"])

    def test_enforce_mode_rejects_blocked_action_without_execution(self):
        gate = self.install_gate()
        calls, receipts = self.capture_routing()
        command = command_for(
            gate,
            "soft_hug",
            execution_context={"mode": "supervised", "user_present": True},
        )
        self.client.on_robot_action(command)
        self.assertEqual(calls, [])
        self.assertEqual([receipt[1] for receipt in receipts], ["ack", "skipped"])
        self.assertEqual(receipts[-1][3]["error_code"], "action_blocked")

    def test_monitor_mode_rejects_unknown_action_without_execution(self):
        gate = self.install_gate("monitor")
        calls, receipts = self.capture_routing()
        self.client.on_robot_action(command_for(gate, "not_a_real_action"))
        self.assertEqual(calls, [])
        self.assertEqual([receipt[1] for receipt in receipts], ["ack", "skipped"])
        self.assertEqual(receipts[-1][3]["error_code"], "action_not_registered")

    def test_receipt_includes_registry_and_plan_metadata(self):
        gate = self.install_gate()
        command = command_for(
            gate,
            "happy_wave",
            parent_plan_id="parent-plan",
            caused_by_receipt_id="receipt:seek-command:completed",
            performance_phase="follow_up",
        )
        self.client._remember_command_context(command)
        self.client._enqueue_robot_receipt(
            command["command_id"],
            "completed",
            "happy_wave",
        )
        payload = self.client.ROBOT_RECEIPT_QUEUE.get_nowait()
        self.client.ROBOT_RECEIPT_QUEUE.task_done()
        self.assertEqual(payload["schema_version"], "tonypi-receipt/v1")
        self.assertEqual(payload["registry_version"], gate.registry_version)
        self.assertEqual(payload["registry_sha256"], gate.registry_sha256)
        self.assertEqual(payload["plan_id"], "plan-test")
        self.assertEqual(payload["receipt_id"], "receipt:command-test:completed")
        self.assertEqual(payload["parent_plan_id"], "parent-plan")
        self.assertEqual(payload["caused_by_receipt_id"], "receipt:seek-command:completed")
        self.assertEqual(payload["performance_phase"], "follow_up")
        self.assertEqual(payload["battery_mv"], 12000)
        self.assertGreaterEqual(payload["battery_age_ms"], 0)
        self.assertLess(payload["battery_age_ms"], 1000)
        with self.client.COMMAND_CONTEXT_LOCK:
            self.assertIn(command["command_id"], self.client.COMMAND_RECEIPT_CONTEXT)

    def test_terminal_receipt_merges_fresh_temperature_into_existing_result(self):
        gate = self.install_gate()
        command = command_for(gate, "happy_wave", command_id="temperature-command")
        self.client._remember_command_context(command)
        temperature = {
            "temperature_enabled": True,
            "temperature_available": True,
            "temperature_c": 31.625,
            "temperature_sensor_id": "28-000000000001",
            "temperature_age_ms": 240,
            "temperature_stale": False,
            "temperature_error": None,
        }
        with patch.object(self.client, "_temperature_snapshot", return_value=temperature):
            self.client._enqueue_robot_receipt(
                command["command_id"],
                "completed",
                "happy_wave",
                result={"motion": "ok"},
            )
        payload = self.client.ROBOT_RECEIPT_QUEUE.get_nowait()
        self.client.ROBOT_RECEIPT_QUEUE.task_done()
        self.assertEqual(payload["result"]["motion"], "ok")
        self.assertEqual(
            payload["result"]["body_temperature"],
            {
                "sensor": "ds18b20",
                "sensor_id": "28-000000000001",
                "temperature_c": 31.625,
                "age_ms": 240,
                "calibrated": False,
                "safety_enforced": False,
            },
        )

    def test_missing_temperature_never_creates_fake_receipt_data(self):
        gate = self.install_gate()
        command = command_for(gate, "happy_wave", command_id="no-temperature-command")
        missing = {
            "temperature_enabled": True,
            "temperature_available": False,
            "temperature_c": None,
            "temperature_sensor_id": None,
            "temperature_age_ms": None,
            "temperature_stale": True,
            "temperature_error": "ds18b20_not_found",
        }
        with patch.object(self.client, "_temperature_snapshot", return_value=missing):
            self.client._enqueue_robot_receipt(
                command["command_id"],
                "completed",
                "happy_wave",
            )
        payload = self.client.ROBOT_RECEIPT_QUEUE.get_nowait()
        self.client.ROBOT_RECEIPT_QUEUE.task_done()
        self.assertNotIn("result", payload)

    def test_keepalive_speaks_without_bypassing_the_robot_queue(self):
        body_calls = []
        spoken = []
        self.client.do_action = lambda *args, **kwargs: body_calls.append((args, kwargs))
        self.client.say = spoken.append
        self.client.on_keepalive_message({"content": "抱抱，我在等你回来", "source": "test"})
        self.assertEqual(body_calls, [])
        self.assertEqual(spoken, ["抱抱，我在等你回来"])

    def test_robot_poll_uses_dedicated_fast_endpoint(self):
        calls = []

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return [{"command_type": "stop", "command_id": "stop-test"}]

        class Session:
            @staticmethod
            def get(url, **kwargs):
                calls.append((url, kwargs))
                return Response()

        original_session = self.client.ROBOT_HTTP_SESSION
        self.client.ROBOT_HTTP_SESSION = Session()
        try:
            items = self.client.fetch_robot_pending()
        finally:
            self.client.ROBOT_HTTP_SESSION = original_session

        self.assertEqual(len(items), 1)
        self.assertTrue(calls[0][0].endswith("/robot/pending"))
        self.assertEqual(calls[0][1]["timeout"], self.client.ROBOT_HTTP_TIMEOUT)
        self.assertLess(self.client.ROBOT_POLL_INTERVAL, self.client.KEEPALIVE_POLL_INTERVAL)

    def test_keepalive_poll_never_drains_robot_queue(self):
        calls = []

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return [{"content": "hello"}]

        class Session:
            @staticmethod
            def get(url, **kwargs):
                calls.append((url, kwargs))
                return Response()

        original_session = self.client.KEEPALIVE_HTTP_SESSION
        original_token = self.client.TONYPI_BRIDGE_TOKEN
        self.client.KEEPALIVE_HTTP_SESSION = Session()
        self.client.TONYPI_BRIDGE_TOKEN = "test-device-token"
        try:
            items = self.client.fetch_keepalive_pending()
        finally:
            self.client.KEEPALIVE_HTTP_SESSION = original_session
            self.client.TONYPI_BRIDGE_TOKEN = original_token

        self.assertEqual(items, [{"content": "hello"}])
        self.assertTrue(calls[0][0].endswith("/keepalive/pending"))
        self.assertNotIn("/yushi/pending", calls[0][0])
        self.assertEqual(
            calls[0][1]["headers"].get("X-TonyPi-Token"),
            "test-device-token",
        )
        self.assertTrue(
            calls[0][1]["headers"].get("X-Yushi-Delivery-Owner", "").startswith(
                "tonypi:"
            )
        )
        self.assertEqual(
            calls[0][1]["headers"].get("X-Yushi-Delivery-Session"),
            self.client.KEEPALIVE_DELIVERY_SESSION_ID,
        )

    def test_battery_poll_is_low_frequency(self):
        self.assertGreaterEqual(self.client.BATTERY_POLL_INTERVAL, 1.0)
        self.assertLess(self.client.BATTERY_POLL_INTERVAL, self.client.BATTERY_STALE_SECONDS)

    def test_board_reception_is_enabled_for_battery_telemetry(self):
        self.client.AGC.board.reception_enabled = False
        self.assertTrue(self.client._enable_board_reception())
        self.assertTrue(self.client.AGC.board.reception_enabled)

    def test_calibrated_upright_imu_is_accepted(self):
        samples = [(-0.965, -0.110, 0.177, 3.21, 0.0, 1.63)] * 25
        result = self.client._evaluate_imu_upright(samples)
        self.assertTrue(result["upright"])
        self.assertTrue(result["stable"])
        self.assertIsNone(result["error_code"])

    def test_lying_imu_is_rejected(self):
        samples = [(0.01, 0.02, -0.99, 3.21, 0.0, 1.63)] * 25
        result = self.client._evaluate_imu_upright(samples)
        self.assertFalse(result["upright"])
        self.assertEqual(result["error_code"], "startup_not_upright")

    def test_startup_recover_uses_verified_full_idle_pose(self):
        moves = []
        preflight = {
            "battery_mv": 12500,
            "battery_age_ms": 300,
            "imu": {"upright": True, "stable": True},
        }
        with patch.object(
            self.client,
            "_move_bus",
            side_effect=lambda duration, positions: moves.append((duration, positions)),
        ):
            result = self.client._run_code_action("startup_recover", preflight=preflight)
        self.assertEqual([duration for duration, _positions in moves], [1.40, 0.40])
        self.assertEqual(moves[0][1], self.client.FULL_IDLE_POSE)
        self.assertEqual(moves[1][1], self.client.FULL_IDLE_POSE)
        self.assertEqual(len(self.client.FULL_IDLE_POSE), 18)
        self.assertEqual(result["servo_count"], 18)
        self.assertTrue(result["manual_clearance_confirmed"])

    def test_startup_automatic_phase_recovers_head_and_full_body(self):
        gaze_moves = []
        body_moves = []
        self.client._startup_recovery_preflight = lambda **_kwargs: {
            "battery_mv": 12500,
            "battery_age_ms": 300,
            "imu": {"upright": True, "stable": True},
        }
        self.client._move_gaze = lambda duration, pitch, yaw: gaze_moves.append((duration, pitch, yaw))
        self.client._move_atom = lambda duration, name: body_moves.append((duration, name))
        result = self.client._run_startup_auto_recovery_once()
        self.assertEqual(result["status"], "recovered")
        self.assertEqual(gaze_moves, [(0.80, 1500, 1530)])
        self.assertEqual(body_moves, [(1.40, "full_idle"), (0.40, "full_idle")])
        self.assertTrue(result["head_centered"])
        self.assertTrue(result["full_body_recovered"])
        self.assertEqual(result["servo_count"], 18)

    def test_idle_stop_does_not_latch_original_d6a_stop_flags(self):
        gate = self.install_gate()
        _calls, receipts = self.capture_routing()
        command = command_for(gate, None, command_type="stop")
        self.client.on_robot_action(command)
        self.assertEqual(self.client.AGC.stop_calls, [])
        self.assertEqual([receipt[1] for receipt in receipts], ["ack", "started", "completed"])
        self.assertFalse(self.client.EMERGENCY_STOP_EVENT.is_set())

    def test_active_d6a_stop_calls_both_original_stop_flags(self):
        gate = self.install_gate()
        _calls, receipts = self.capture_routing()
        self.client._set_active_motion("body", "happy_wave", "running-command", "d6a")
        command = command_for(gate, None, command_type="stop")
        self.client.on_robot_action(command)
        self.assertEqual(self.client.AGC.stop_calls, ["stopAction", "stopActionGroup"])
        self.assertEqual([receipt[1] for receipt in receipts], ["ack", "started", "completed"])

    def test_interrupted_d6a_reports_stopped_not_completed(self):
        self.install_gate()
        _calls, receipts = self.capture_routing()

        def interrupted_action(*_args, **_kwargs):
            self.client.EMERGENCY_STOP_EVENT.set()

        self.client.AGC.runActionGroup = interrupted_action
        self.client.BODY_MOTION_LOCK.acquire()
        self.client._run_action_group_locked("wave!!", "running-command", "happy_wave")
        self.assertEqual([receipt[1] for receipt in receipts], ["started", "stopped"])
        self.assertFalse(self.client.BODY_MOTION_LOCK.locked())

    def test_low_battery_blocks_expression_but_keeps_center_recovery(self):
        gate = self.install_gate()
        calls, receipts = self.capture_routing()
        with self.client.BATTERY_STATE_LOCK:
            self.client.LAST_BATTERY_MV = 10199
            self.client.LAST_BATTERY_AT = time.monotonic()
        self.client.on_robot_action(command_for(gate, "happy_wave"))
        self.assertEqual(calls, [])
        self.assertEqual(receipts[-1][3]["error_code"], "low_battery")

        receipts.clear()
        self.client.on_robot_action(command_for(gate, "gaze_center", command_id="center-command"))
        self.assertEqual(calls[-1][0:2], ("code", "gaze_center"))

    def test_autonomous_body_uses_10_2v_battery_floor(self):
        gate = self.install_gate()
        calls, receipts = self.capture_routing()
        with self.client.BATTERY_STATE_LOCK:
            self.client.LAST_BATTERY_MV = 10199
            self.client.LAST_BATTERY_AT = time.monotonic()
        self.client.on_robot_action(command_for(gate, "happy_wave"))
        self.assertEqual(calls, [])
        self.assertEqual(receipts[-1][3]["error_code"], "low_battery")
        self.assertEqual(self.client.LOW_BATTERY_MV, 10200)
        self.assertEqual(self.client.AUTONOMY_BODY_MIN_BATTERY_MV, 10200)

    def test_autonomous_safe_desktop_action_is_allowed_at_10_2v(self):
        gate = self.install_gate()
        calls, receipts = self.capture_routing()
        with self.client.BATTERY_STATE_LOCK:
            self.client.LAST_BATTERY_MV = 10200
            self.client.LAST_BATTERY_AT = time.monotonic()
        self.client.on_robot_action(command_for(gate, "happy_wave"))
        self.assertEqual(calls[0][0:2], ("d6a", "wave!!"))
        self.assertEqual([receipt[1] for receipt in receipts], ["ack"])

    def test_autonomous_caution_zone_blocks_high_load_body_action(self):
        gate = self.install_gate()
        gate.actions["test_high_load"] = {
            "verified": True,
            "safety_tier": "safe_desktop",
            "uses": ["arms", "legs"],
            "resources": ["body"],
            "timeout_ms": 5000,
        }
        error_code, details = self.client._autonomous_body_preflight(
            "test_high_load",
            {"execution_context": {"mode": "autonomous"}},
            {
                "battery_mv": 10500,
                "battery_age_ms": 0,
                "battery_stale": False,
            },
        )
        self.assertEqual(error_code, "autonomy_low_battery_high_load")
        self.assertEqual(details["battery_mode"], "caution")
        self.assertIn("uses_legs", details["blocked_reasons"])

    def test_autonomous_caution_zone_allows_verified_light_action(self):
        gate = self.install_gate()
        error_code, details = self.client._autonomous_body_preflight(
            "happy_wave",
            {"execution_context": {"mode": "autonomous"}},
            {
                "battery_mv": 10500,
                "battery_age_ms": 0,
                "battery_stale": False,
            },
        )
        self.assertIsNone(error_code)
        self.assertEqual(details["battery_mode"], "caution")

    def test_autonomous_body_requires_upright_imu(self):
        gate = self.install_gate()
        calls, receipts = self.capture_routing()
        lying = (0.01, 0.02, -0.99, 3.21, 0.0, 1.63)
        self.client._collect_imu_samples = lambda duration=0.45: [lying] * 25
        self.client.on_robot_action(command_for(gate, "happy_wave"))
        self.assertEqual(calls, [])
        self.assertEqual(receipts[-1][1], "skipped")
        self.assertEqual(receipts[-1][3]["error_code"], "autonomy_not_upright")

    def test_gaze_does_not_wait_for_body_imu_preflight(self):
        gate = self.install_gate()
        calls, _receipts = self.capture_routing()
        self.client._collect_imu_samples = lambda **_kwargs: self.fail(
            "gaze must not sample body IMU"
        )
        self.client.on_robot_action(command_for(gate, "gaze_glance_left"))
        self.assertEqual(calls[0][0:2], ("code", "gaze_glance_left"))

    def test_physical_acceptance_actions_are_body_only_fixed_profiles(self):
        expected = {
            "quiet_acknowledge_low": ("quiet_acknowledge", "low"),
            "quiet_acknowledge_medium": ("quiet_acknowledge", "medium"),
            "quiet_acknowledge_high": ("quiet_acknowledge", "high"),
            "happy_greeting_low": ("happy_greeting", "low"),
            "happy_greeting_medium": ("happy_greeting", "medium"),
            "happy_greeting_high": ("happy_greeting", "high"),
        }
        self.assertEqual(self.client.PHYSICAL_ACCEPTANCE_ACTIONS, expected)
        for action_name in expected:
            self.assertIn(action_name, self.client.CODE_ACTIONS)
            resource_name, resource_lock = self.client._motion_lock_for_code_action(
                action_name
            )
            self.assertEqual(resource_name, "body")
            self.assertIs(resource_lock, self.client.BODY_MOTION_LOCK)

        with (
            patch.object(self.client, "_move_bus") as move_bus,
            patch.object(self.client, "_interruptible_sleep") as sleep,
        ):
            result = self.client._run_code_action("quiet_acknowledge_low")
        self.assertEqual(move_bus.call_count, 2)
        sleep.assert_called_once_with(0.35)
        self.assertEqual(result["acceptance_level"], "low")
        self.assertEqual(result["expected_final_pose"], "return_idle")
        self.assertEqual(result["return_policy"], "idle")
        self.assertEqual(
            result["execution_mode"],
            "hardware_interpolated_segments",
        )
        self.assertEqual(result["hardware_command_count"], 2)

        with patch.object(self.client, "_move_bus") as move_bus:
            result = self.client._run_code_action("happy_greeting_low")
        self.assertEqual(move_bus.call_count, 7)
        self.assertEqual(result["execution_mode"], "hardware_interpolated_segments")
        self.assertEqual(result["hardware_command_count"], 7)
        self.assertEqual(result["source_template"], "wave!!.d6a")
        self.assertEqual(result["source_template_frame_count"], 10)
        self.assertEqual(result["template_frame_count"], 6)
        self.assertEqual(result["template_duration"], 1.15)
        self.assertEqual(result["total_duration"], 1.6436)
        self.assertEqual(result["amplitude_scale"], 0.35)
        self.assertEqual(result["clearance_scale"], 0.55)
        self.assertEqual(result["right_clearance_scale"], 0.45)
        self.assertEqual(result["left_clearance_scale"], 0.55)
        self.assertEqual(result["recovery_waypoint_count"], 1)
        self.assertEqual(
            result["recovery_waypoint"],
            "happy_greeting_return_approach",
        )
        self.assertEqual(
            result["collision_clearance_policy"],
            "left_biased_clear_body_before_idle",
        )
        self.assertTrue(result["preserves_frame_order"])
        self.assertTrue(result["preserves_frame_timing"])
        self.assertTrue(result["preserves_cycle_boundary"])

    def test_brief_face_tracking_uses_gaze_resource(self):
        self.assertIn("track_face_brief", self.client.CODE_ACTIONS)
        resource_name, resource_lock = self.client._motion_lock_for_code_action("track_face_brief")
        self.assertEqual(resource_name, "gaze")
        self.assertIs(resource_lock, self.client.GAZE_MOTION_LOCK)
        self.assertEqual(
            self.client._additional_motion_locks_for_code_action("track_face_brief"),
            [self.client.CAMERA_PERCEPTION_LOCK],
        )

    def test_gesture_observation_uses_camera_only(self):
        self.assertIn("observe_gesture_once", self.client.CODE_ACTIONS)
        resource_name, resource_lock = self.client._motion_lock_for_code_action(
            "observe_gesture_once"
        )
        self.assertEqual(resource_name, "camera")
        self.assertIs(resource_lock, self.client.CAMERA_PERCEPTION_LOCK)
        self.assertEqual(
            self.client._additional_motion_locks_for_code_action("observe_gesture_once"),
            [],
        )
        self.assertEqual(
            self.client._implementation_for_code_action("observe_gesture_once"),
            "perception",
        )

    def test_user_visual_observation_is_hidden_camera_only_perception(self):
        self.assertIn("observe_user_once", self.client.CODE_ACTIONS)
        self.assertNotIn(
            "observe_user_once",
            TonyPiRegistryGate(ACTIVE_REGISTRY).actions,
        )
        resource_name, resource_lock = self.client._motion_lock_for_code_action(
            "observe_user_once"
        )
        self.assertEqual(resource_name, "camera")
        self.assertIs(resource_lock, self.client.CAMERA_PERCEPTION_LOCK)
        self.assertEqual(
            self.client._implementation_for_code_action("observe_user_once"),
            "perception",
        )

    def test_visual_provider_posts_jpeg_bytes_with_device_metadata(self):
        captured = {}

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"provider": "ok"}

        def post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return Response()

        metadata = {
            "schema_version": "tonypi-ephemeral-frame/v1",
            "width": 640,
            "height": 480,
        }
        jpeg = memoryview(bytearray(b"jpeg-in-memory"))
        with patch.object(self.client.ROBOT_HTTP_SESSION, "post", side_effect=post), patch.object(
            self.client,
            "TONYPI_BRIDGE_TOKEN",
            "device-token",
        ):
            result = self.client._server_visual_observation_provider(
                jpeg,
                metadata,
                command_id="vision-command",
            )

        self.assertEqual(captured["url"], f"{self.client.MEMORY_SERVER}/robot/vision/observe")
        self.assertEqual(bytes(captured["data"]), b"jpeg-in-memory")
        self.assertEqual(captured["headers"]["X-TonyPi-Token"], "device-token")
        self.assertEqual(captured["headers"]["X-TonyPi-Command-ID"], "vision-command")
        self.assertEqual(captured["headers"]["X-TonyPi-Image-Width"], "640")
        self.assertEqual(captured["headers"]["X-TonyPi-Image-Height"], "480")
        self.assertEqual(result, {"provider": "ok"})
        jpeg.release()

    def test_user_visual_observation_clears_frame_and_returns_only_v2_result(self):
        from tonypi_vision import EphemeralJpeg

        frame = EphemeralJpeg(b"single-frame", 640, 480)
        raw_result = {
            "person_present": True,
            "scene_summary": "桌前有人坐着，画面主要是电脑和桌面。",
            "grounded_observations": ["有人坐在电脑前。", "视线朝向屏幕。"],
            "activity": "using_computer",
            "attention_direction": "screen",
            "body_posture": "sitting",
            "embodied_glimpse": "我这一眼看见有人还在电脑前，像是在忙手头的东西。",
            "uncertainty": "看不清屏幕内容。",
            "confidence": 0.86,
        }
        with patch.object(
            self.client,
            "capture_ephemeral_jpeg",
            return_value=frame,
        ), patch.object(
            self.client,
            "_server_visual_observation_provider",
            return_value=raw_result,
        ):
            result = self.client._run_code_action(
                "observe_user_once",
                command_id="vision-command",
            )

        self.assertTrue(frame.cleared)
        self.assertTrue(frame.is_zeroed())
        self.assertEqual(result["schema_version"], "yushi-visual-observation/v2")
        self.assertNotIn("image", result)
        self.assertEqual(result["activity"], "using_computer")

    def test_hands_ready_intensity_blends_only_within_verified_pose(self):
        with patch.object(self.client, "_move_bus") as move_bus:
            result = self.client._run_code_action(
                "hands_ready",
                parameters={"intensity": 0.5},
            )
        positions = move_bus.call_args.args[1]
        self.assertEqual(
            positions,
            [[6, 555], [7, 764], [8, 707], [14, 425], [15, 238], [16, 275]],
        )
        self.assertEqual(result["applied_parameters"], {"intensity": 0.5})

    def test_happy_wiggle_intensity_controls_bounded_sway_steps(self):
        with patch.object(self.client, "_move_bus"):
            low = self.client._run_code_action(
                "happy_wiggle",
                parameters={"intensity": 0.35},
            )
            high = self.client._run_code_action(
                "happy_wiggle",
                parameters={"intensity": 1.0},
            )
        self.assertEqual(low["sway_steps"], 2)
        self.assertEqual(high["sway_steps"], 4)

    def test_gaze_glance_intensity_scales_offset_and_still_returns_center(self):
        with patch.object(self.client, "_move_gaze") as move_gaze, patch.object(
            self.client,
            "_interruptible_sleep",
        ):
            result = self.client._run_code_action(
                "gaze_glance_left",
                parameters={"intensity": 0.5},
            )
        first = move_gaze.call_args_list[0].args
        final = move_gaze.call_args_list[-1].args
        self.assertEqual(first[1:], (1500, 1566))
        self.assertEqual(final[1:], (1500, 1530))
        self.assertTrue(move_gaze.call_args_list[-1].kwargs["allow_during_stop"])
        self.assertEqual(result["applied_parameters"], {"intensity": 0.5})

    def test_expression_intensity_rejects_unbounded_or_unknown_values(self):
        for parameters in (
            {"intensity": 0.2},
            {"intensity": 1.1},
            {"intensity": "0.7"},
            {"intensity": True},
            {"speed": 0.5},
        ):
            with self.assertRaisesRegex(ValueError, "parameters_invalid"):
                self.client._run_code_action("hands_ready", parameters=parameters)

    def test_stop_quiescence_includes_camera_observation(self):
        self.client.CAMERA_PERCEPTION_LOCK.acquire()
        try:
            self.assertFalse(self.client._motion_is_quiescent())
        finally:
            self.client.CAMERA_PERCEPTION_LOCK.release()
        self.assertTrue(self.client._motion_is_quiescent())

    def test_busy_camera_releases_gaze_lock_before_rejecting_track(self):
        receipts = []
        self.client._enqueue_robot_receipt = (
            lambda command_id, status, action, **extra: receipts.append(
                (command_id, status, action, extra)
            )
        )
        self.client.CAMERA_PERCEPTION_LOCK.acquire()
        try:
            with patch.object(self.client, "_motion_interlock_reason", return_value=""):
                launched = self.client.code_action(
                    "track_face_brief",
                    command_id="busy-camera",
                )
        finally:
            self.client.CAMERA_PERCEPTION_LOCK.release()

        self.assertFalse(launched)
        self.assertFalse(self.client.GAZE_MOTION_LOCK.locked())
        self.assertEqual(receipts[-1][1], "skipped")
        self.assertEqual(receipts[-1][3]["error"], "resource_busy")

    def test_registry_cooldown_blocks_immediate_repeat(self):
        gate = self.install_gate()
        calls, receipts = self.capture_routing()
        first = command_for(gate, "happy_wave", command_id="first-command")
        second = command_for(gate, "happy_wave", command_id="second-command")
        self.client.on_robot_action(first)
        self.client.on_robot_action(second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(receipts[-1][1], "skipped")
        self.assertEqual(receipts[-1][3]["error_code"], "cooldown_active")
        self.assertGreater(receipts[-1][3]["retry_after_ms"], 0)

    def test_duplicate_command_replays_receipt_without_reexecution(self):
        gate = self.install_gate()
        calls = []

        def capture_d6a(action_name, **kwargs):
            calls.append((action_name, kwargs))
            return True

        self.client.do_action = capture_d6a
        self.client._enqueue_robot_receipt = self.original_enqueue
        command = command_for(gate, "happy_wave", command_id="duplicate-command")
        self.client.on_robot_action(command)
        self.client.on_robot_action(command)
        payloads = []
        while True:
            try:
                payloads.append(self.client.ROBOT_RECEIPT_QUEUE.get_nowait())
                self.client.ROBOT_RECEIPT_QUEUE.task_done()
            except self.client.queue.Empty:
                break
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["status"], "ack")
        self.assertTrue(payloads[1]["replayed"])

    def test_command_claim_is_durable_before_execution(self):
        command = {"command_id": "durable-claim", "action": "happy_wave"}
        self.assertTrue(self.client._claim_command(command["command_id"], command))
        stored = self.client.json.loads(
            Path(self.client.TONYPI_COMMAND_LEDGER_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(stored["commands"]["durable-claim"]["phase"], "claimed")
        self.assertEqual(
            stored["commands"]["durable-claim"]["command"]["action"],
            "happy_wave",
        )
        self.assertTrue(
            Path(self.client.TONYPI_COMMAND_LEDGER_FILE + ".last-good").exists()
        )

    def test_receipt_outbox_has_no_old_queue_size_drop_limit(self):
        for index in range(125):
            self.client._enqueue_robot_receipt(
                f"queue-pressure-{index}",
                "ack",
                "happy_wave",
            )
        self.assertEqual(len(self.client.RECEIPT_OUTBOX), 125)
        self.assertEqual(self.client.ROBOT_RECEIPT_QUEUE.qsize(), 125)
        stored = self.client.json.loads(
            Path(self.client.TONYPI_RECEIPT_OUTBOX_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(len(stored["items"]), 125)

    def test_receipt_network_failure_stays_in_durable_outbox(self):
        class FailingSession:
            @staticmethod
            def post(*_args, **_kwargs):
                raise RuntimeError("network_down")

        original_session = self.client.ROBOT_HTTP_SESSION
        self.client.ROBOT_HTTP_SESSION = FailingSession()
        try:
            self.client._enqueue_robot_receipt("network-failure", "ack", "happy_wave")
            self.assertFalse(self.client._deliver_robot_receipt_once())
        finally:
            self.client.ROBOT_HTTP_SESSION = original_session
        item = next(iter(self.client.RECEIPT_OUTBOX.values()))
        self.assertEqual(item["attempts"], 1)
        self.assertIn("network_down", item["last_error"])

    def test_receipt_http_200_ok_false_stays_in_durable_outbox(self):
        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"ok": False, "error": "receipt_write_failed"}

        class Session:
            @staticmethod
            def post(*_args, **_kwargs):
                return Response()

        original_session = self.client.ROBOT_HTTP_SESSION
        self.client.ROBOT_HTTP_SESSION = Session()
        try:
            self.client._enqueue_robot_receipt("server-non-ok", "ack", "happy_wave")
            self.assertFalse(self.client._deliver_robot_receipt_once())
        finally:
            self.client.ROBOT_HTTP_SESSION = original_session
        item = next(iter(self.client.RECEIPT_OUTBOX.values()))
        self.assertEqual(item["attempts"], 1)
        self.assertIn("receipt_write_failed", item["last_error"])

    def test_terminal_receipt_closes_only_after_server_ok_true(self):
        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"ok": True}

        class Session:
            @staticmethod
            def post(*_args, **_kwargs):
                return Response()

        command = {"command_id": "terminal-confirm", "action": "happy_wave"}
        self.assertTrue(self.client._claim_command(command["command_id"], command))
        self.client._remember_command_context(command)
        self.client._enqueue_robot_receipt(
            command["command_id"],
            "completed",
            command["action"],
        )
        self.assertEqual(
            self.client.COMMAND_LEDGER[command["command_id"]]["phase"],
            "terminal_queued",
        )
        original_session = self.client.ROBOT_HTTP_SESSION
        self.client.ROBOT_HTTP_SESSION = Session()
        try:
            self.assertTrue(self.client._deliver_robot_receipt_once())
        finally:
            self.client.ROBOT_HTTP_SESSION = original_session
        self.assertEqual(len(self.client.RECEIPT_OUTBOX), 0)
        entry = self.client.COMMAND_LEDGER[command["command_id"]]
        self.assertEqual(entry["phase"], "terminal_confirmed")
        self.assertTrue(entry["terminal_confirmed"])
        with self.client.COMMAND_CONTEXT_LOCK:
            self.assertNotIn(command["command_id"], self.client.COMMAND_RECEIPT_CONTEXT)

    def test_restart_converts_started_command_to_durable_failure(self):
        now = datetime.now(timezone.utc).isoformat()
        self.client._atomic_write_json(
            self.client.TONYPI_COMMAND_LEDGER_FILE,
            {
                "version": 1,
                "updated_at": now,
                "commands": {
                    "interrupted-command": {
                        "command": {
                            "command_id": "interrupted-command",
                            "action": "happy_wave",
                        },
                        "phase": "started",
                        "session_id": "previous-process",
                        "claimed_at": now,
                        "updated_at": now,
                        "last_receipt": {
                            "command_id": "interrupted-command",
                            "status": "started",
                            "action": "happy_wave",
                        },
                        "terminal_confirmed": False,
                    }
                },
            },
        )
        self.client.COMMAND_PERSISTENCE_LOADED = False
        self.assertEqual(self.client._recover_command_delivery_after_restart(), 1)
        entry = self.client.COMMAND_LEDGER["interrupted-command"]
        self.assertEqual(entry["phase"], "terminal_queued")
        self.assertFalse(
            self.client._claim_command(
                "interrupted-command",
                {"command_id": "interrupted-command", "action": "happy_wave"},
            )
        )
        payload = next(iter(self.client.RECEIPT_OUTBOX.values()))["payload"]
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error_code"], "device_restarted_during_execution")

    def test_corrupt_persistence_fails_closed(self):
        Path(self.client.TONYPI_COMMAND_LEDGER_FILE).write_text(
            "{not-json",
            encoding="utf-8",
        )
        self.client.COMMAND_PERSISTENCE_LOADED = False
        with self.assertRaisesRegex(RuntimeError, "invalid_json"):
            self.client._claim_command(
                "must-not-run",
                {"command_id": "must-not-run", "action": "happy_wave"},
            )

    def test_keepalive_response_loss_restart_and_duplicate_are_not_replayed(self):
        state = self.client._ensure_keepalive_delivery_state_loaded()
        owner = state["owner_id"]
        spoken = []
        posted = []

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"ok": True, "changed": True}

        class Session:
            def __init__(self):
                self.fail_once = True

            def post(self, url, **kwargs):
                posted.append((url, kwargs))
                if self.fail_once:
                    self.fail_once = False
                    raise RuntimeError("response_lost")
                return Response()

        session = Session()

        def leased_message(lease_session, lease_token):
            return {
                "id": "delivery-client-restart",
                "role": "assistant",
                "content": "榛榛，早上好。",
                "source": "keepalive",
                "timestamp": "2026-07-24T02:00:00.000Z",
                "_delivery": {
                    "protocol": "keepalive-lease/v1",
                    "id": "delivery-client-restart",
                    "owner": owner,
                    "session": lease_session,
                    "lease_token": lease_token,
                    "lease_expires_at": "2026-07-24T02:02:00.000Z",
                },
            }

        first = leased_message(
            self.client.KEEPALIVE_DELIVERY_SESSION_ID,
            "a" * 43,
        )
        with patch.object(self.client, "KEEPALIVE_HTTP_SESSION", session), patch.object(
            self.client,
            "on_keepalive_message",
            side_effect=lambda message: spoken.append(message["content"]) or True,
        ):
            self.assertTrue(self.client.process_keepalive_delivery(first))
            self.assertEqual(spoken, ["榛榛，早上好。"])
            persisted = json.loads(
                Path(self.client.TONYPI_KEEPALIVE_DELIVERY_FILE).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                persisted["deliveries"]["delivery-client-restart"]["phase"],
                "processed",
            )

            # Simulate a client process restart after TTS completed but before
            # the ack response arrived. Reloading the durable claim suppresses
            # a second TTS and attaches the server's fresh lease token.
            self.client.KEEPALIVE_DELIVERY_STATE_LOADED = False
            with self.client.KEEPALIVE_DELIVERY_LOCK:
                self.client.KEEPALIVE_DELIVERY_STATE.clear()
                self.client.KEEPALIVE_DELIVERY_STATE.update(
                    {
                        "version": 1,
                        "owner_id": "",
                        "updated_at": "",
                        "deliveries": {},
                    }
                )
            redelivered = leased_message("session:after-restart", "b" * 43)
            self.assertTrue(self.client.process_keepalive_delivery(redelivered))
            self.assertEqual(
                spoken,
                ["榛榛，早上好。"],
                "restart/redelivery must not speak the same message twice",
            )

            # A pathological duplicate after the successful ack remains
            # harmless and only sends an idempotent confirmation.
            duplicate = leased_message("session:after-restart", "c" * 43)
            self.assertTrue(self.client.process_keepalive_delivery(duplicate))
            self.assertEqual(spoken, ["榛榛，早上好。"])

        self.assertGreaterEqual(len(posted), 3)
        self.assertEqual(
            posted[-1][1]["headers"]["X-Yushi-Delivery-Session"],
            "session:after-restart",
        )

    def test_keepalive_delivery_state_corruption_fails_closed(self):
        Path(self.client.TONYPI_KEEPALIVE_DELIVERY_FILE).write_text(
            "{not-json",
            encoding="utf-8",
        )
        self.client.KEEPALIVE_DELIVERY_STATE_LOADED = False
        with self.assertRaisesRegex(RuntimeError, "invalid_json"):
            self.client._ensure_keepalive_delivery_state_loaded()
        self.assertEqual(
            Path(self.client.TONYPI_KEEPALIVE_DELIVERY_FILE).read_text(
                encoding="utf-8"
            ),
            "{not-json",
        )

    def test_code_action_releases_resources_before_terminal_receipt(self):
        observations = []

        def capture(_command_id, status, _action, **_extra):
            observations.append({
                "status": status,
                "body_locked": self.client.BODY_MOTION_LOCK.locked(),
                "active": self.client._active_motion_snapshot(),
            })

        self.client.BODY_MOTION_LOCK.acquire()
        try:
            with patch.object(self.client, "_enqueue_robot_receipt", side_effect=capture), patch.object(
                self.client,
                "_run_code_action",
                return_value={"ok": True},
            ):
                self.client._run_code_action_locked(
                    "hands_ready",
                    "body",
                    [self.client.BODY_MOTION_LOCK],
                    command_id="release-code-command",
                    receipt_action="hands_ready",
                    parameters={"intensity": 1.0},
                )
        finally:
            if self.client.BODY_MOTION_LOCK.locked():
                self.client.BODY_MOTION_LOCK.release()

        self.assertEqual([item["status"] for item in observations], ["started", "completed"])
        self.assertTrue(observations[0]["body_locked"])
        self.assertIn("body", observations[0]["active"])
        self.assertFalse(observations[-1]["body_locked"])
        self.assertNotIn("body", observations[-1]["active"])

    def test_d6a_releases_body_before_terminal_receipt(self):
        observations = []

        def capture(_command_id, status, _action, **_extra):
            observations.append({
                "status": status,
                "body_locked": self.client.BODY_MOTION_LOCK.locked(),
                "active": self.client._active_motion_snapshot(),
            })

        self.client.BODY_MOTION_LOCK.acquire()
        try:
            with patch.object(self.client, "_enqueue_robot_receipt", side_effect=capture), patch.object(
                self.client.AGC,
                "runActionGroup",
                return_value=None,
            ):
                self.client._run_action_group_locked(
                    "wave!!",
                    command_id="release-d6a-command",
                    receipt_action="happy_wave",
                )
        finally:
            if self.client.BODY_MOTION_LOCK.locked():
                self.client.BODY_MOTION_LOCK.release()

        self.assertEqual([item["status"] for item in observations], ["started", "completed"])
        self.assertTrue(observations[0]["body_locked"])
        self.assertIn("body", observations[0]["active"])
        self.assertFalse(observations[-1]["body_locked"])
        self.assertNotIn("body", observations[-1]["active"])


if __name__ == "__main__":
    unittest.main()
