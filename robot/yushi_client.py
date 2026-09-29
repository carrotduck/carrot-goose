#!/usr/bin/env python3
# yushi_client.py - 喻拾机器人客户端 v2（keepalive + robot 合并轮询）

import os
import sys
import json
import uuid
import requests
import time
import subprocess
import threading
import queue
import math
import statistics
import hashlib
import atexit
from collections import OrderedDict
from datetime import datetime

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows development fallback
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - Linux production path
    msvcrt = None

MEMORY_SERVER = os.environ.get("MEMORY_SERVER", "https://example.invalid")
ROBOT_POLL_INTERVAL = 1.0
KEEPALIVE_POLL_INTERVAL = 5.0
ROBOT_HTTP_TIMEOUT = (2.0, 3.0)
VISUAL_OBSERVATION_HTTP_TIMEOUT = (3.0, 20.0)
KEEPALIVE_HTTP_TIMEOUT = (3.0, 8.0)
BATTERY_POLL_INTERVAL = 2.0
POLL_INTERVAL = KEEPALIVE_POLL_INTERVAL
TTS_FILE = "/tmp/yushi_tts.mp3"
TTS_AUDIO_DEVICE = os.environ.get("TTS_AUDIO_DEVICE", "plughw:2,0")
TONYPI_ROOT = "/home/pi/TonyPi"
ACTION_BASE = f"{TONYPI_ROOT}/ActionGroups"
CONTROL_OWNER_FILE = os.environ.get("TONYPI_CONTROL_OWNER_FILE", "/home/pi/yushi/control_owner")
EXTERNAL_CONTROLLER_MARKERS = (
    ("studio", "/home/pi/TonyPi_PC_Software/main.py"),
    ("original", "/home/pi/TonyPi/TonyPi.py"),
    ("joystick", "/home/pi/TonyPi/Joystick.py"),
    ("multi_control", "/home/pi/TonyPi/Extend/multi_control/"),
)
for _p in (TONYPI_ROOT, f"{TONYPI_ROOT}/HiwonderSDK"):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import hiwonder.ActionGroupControl as AGC
from tonypi_seek import FaceCameraError, SeekStopped, run_local_seek, run_local_track
from tonypi_perception import (
    PerceptionCameraError,
    PerceptionStopped,
    observe_gesture_once,
)
from tonypi_motion_catalog import (
    ARM_IDLE_POSE,
    BODY_ATOM_CONTRACTS,
    FULL_IDLE_POSE,
    RIGHT_ARM_IDLE_POSE,
    atom_positions,
    compile_body_sequence,
    compile_motion_phrase_level,
    validate_expression_intensity,
)
from tonypi_registry import TonyPiRegistryGate
from tonypi_temperature import DS18B20Reader, TemperatureSensorError
from tonypi_vision import capture_ephemeral_jpeg, observe_activity_once

ROBOT_HTTP_SESSION = requests.Session()
KEEPALIVE_HTTP_SESSION = requests.Session()

BODY_MOTION_LOCK = threading.Lock()
GAZE_MOTION_LOCK = threading.Lock()
CAMERA_PERCEPTION_LOCK = threading.Lock()
BOARD_WRITE_LOCK = threading.RLock()
ACTIVE_MOTION_LOCK = threading.Lock()
ACTIVE_MOTIONS = {}
EMERGENCY_STOP_EVENT = threading.Event()
BATTERY_STATE_LOCK = threading.Lock()
LAST_BATTERY_MV = None
LAST_BATTERY_AT = None
TEMPERATURE_STATE_LOCK = threading.Lock()
LAST_TEMPERATURE_C = None
LAST_TEMPERATURE_SENSOR_ID = None
LAST_TEMPERATURE_AT = None
LAST_TEMPERATURE_ERROR = None
LOW_BATTERY_MV = 10200
AUTONOMY_BODY_MIN_BATTERY_MV = 10200
AUTONOMY_BODY_CAUTION_BATTERY_MV = 10600
AUTONOMY_BODY_CAUTION_MAX_TIMEOUT_MS = 6000
AUTONOMY_IMU_SAMPLE_SECONDS = 0.45
BATTERY_STALE_SECONDS = 15.0
STARTUP_RECOVERY_GRACE_SECONDS = 5.0
STARTUP_AUTO_FULL_BODY_RECOVERY = os.environ.get(
    "TONYPI_STARTUP_FULL_BODY_RECOVERY",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}
STARTUP_IMU_SAMPLE_SECONDS = 1.2
STARTUP_IMU_MIN_SAMPLES = 20
STARTUP_UPRIGHT_AX_RANGE = (-1.15, -0.85)
STARTUP_UPRIGHT_AY_ABS_MAX = 0.30
STARTUP_UPRIGHT_AZ_ABS_MAX = 0.35
STARTUP_ACCEL_MAG_RANGE = (0.80, 1.20)
STARTUP_ACCEL_STDEV_MAX = 0.04
STARTUP_GYRO_STDEV_MAX = 0.75
ACTION_COOLDOWN_LOCK = threading.Lock()
ACTION_LAST_STARTED = {}
COMMAND_LEDGER_LOCK = threading.RLock()
COMMAND_LEDGER = OrderedDict()
COMMAND_LEDGER_LIMIT = 256
RECEIPT_OUTBOX = OrderedDict()
COMMAND_PERSISTENCE_LOADED = False
COMMAND_SESSION_ID = str(uuid.uuid4())
INSTANCE_LOCK_HANDLE = None
KEEPALIVE_DELIVERY_LOCK = threading.RLock()
KEEPALIVE_DELIVERY_STATE = {
    "version": 1,
    "owner_id": "",
    "updated_at": "",
    "deliveries": {},
}
KEEPALIVE_DELIVERY_STATE_LOADED = False
KEEPALIVE_DELIVERY_SESSION_ID = "session:" + str(uuid.uuid4())
KEEPALIVE_DELIVERY_LIMIT = 256
_ORIGINAL_BOARD_BUF_WRITE = AGC.board.buf_write


class MotionStopped(RuntimeError):
    pass


class StartupRecoveryRejected(RuntimeError):
    def __init__(self, error_code, details=None):
        super().__init__(error_code)
        self.error_code = str(error_code)
        self.details = dict(details or {})


class VisualObservationServerError(RuntimeError):
    pass

def _locked_board_buf_write(func, data):
    with BOARD_WRITE_LOCK:
        return _ORIGINAL_BOARD_BUF_WRITE(func, data)

AGC.board.buf_write = _locked_board_buf_write

ACTION_ALIASES = {
    "happy_wave": "wave!!",
    "happy_twist": "twist",
    "body_sway": "twist",
}

D6A_FINAL_POSES = {
    "wave!!": "return_idle",
}

def _read_control_owner():
    try:
        with open(CONTROL_OWNER_FILE, encoding="utf-8") as owner_file:
            return owner_file.read().strip().lower() or "locked"
    except OSError:
        return "locked"

def _external_motion_controllers():
    controllers = []
    own_pid = os.getpid()
    try:
        proc_entries = os.listdir("/proc")
    except OSError:
        return ["proc_unavailable"]
    for entry in proc_entries:
        if not entry.isdigit() or int(entry) == own_pid:
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as cmdline_file:
                parts = [part.decode("utf-8", errors="replace") for part in cmdline_file.read().split(b"\0") if part]
        except OSError:
            continue
        if not parts or "python" not in os.path.basename(parts[0]).lower():
            continue
        command = " ".join(parts)
        for role, marker in EXTERNAL_CONTROLLER_MARKERS:
            if marker in command and role not in controllers:
                controllers.append(role)
    return controllers

def _motion_interlock_reason():
    owner = _read_control_owner()
    if owner != "yushi":
        return f"control_owner_{owner}"
    controllers = _external_motion_controllers()
    if controllers:
        return "external_controller_" + "+".join(sorted(controllers))
    return ""

def _set_active_motion(resource, action, command_id, implementation):
    with ACTIVE_MOTION_LOCK:
        ACTIVE_MOTIONS[resource] = {
            "resource": resource,
            "action": action,
            "command_id": str(command_id or ""),
            "implementation": implementation,
        }

def _clear_active_motion(resource):
    with ACTIVE_MOTION_LOCK:
        ACTIVE_MOTIONS.pop(resource, None)

def _active_motion_snapshot():
    with ACTIVE_MOTION_LOCK:
        return {resource: dict(state) for resource, state in ACTIVE_MOTIONS.items()}

def _is_robot_queue_item(item):
    if not isinstance(item, dict):
        return False
    command_type = str(item.get("command_type") or "action").strip()
    return bool(item.get("action")) or command_type == "stop"

def _enable_board_reception():
    try:
        AGC.board.enable_reception(True)
        print("[telemetry] board reception enabled", flush=True)
        return True
    except Exception as e:
        print(f"[telemetry] board reception failed: {e}", flush=True)
        return False

def _battery_snapshot():
    with BATTERY_STATE_LOCK:
        battery_mv = LAST_BATTERY_MV
        sampled_at = LAST_BATTERY_AT
    age_seconds = None if sampled_at is None else max(0.0, time.monotonic() - sampled_at)
    stale = age_seconds is None or age_seconds > BATTERY_STALE_SECONDS
    return {
        "battery_mv": battery_mv,
        "battery_voltage": None if battery_mv is None else round(battery_mv / 1000.0, 3),
        "battery_age_ms": None if age_seconds is None else int(age_seconds * 1000),
        "battery_stale": stale,
    }

def _battery_monitor():
    global LAST_BATTERY_MV, LAST_BATTERY_AT
    while True:
        try:
            value = AGC.board.get_battery()
            if value is not None:
                battery_mv = int(value)
                if 6000 <= battery_mv <= 15000:
                    with BATTERY_STATE_LOCK:
                        LAST_BATTERY_MV = battery_mv
                        LAST_BATTERY_AT = time.monotonic()
        except Exception as e:
            print(f"[battery] read failed: {e}", flush=True)
        time.sleep(BATTERY_POLL_INTERVAL)

def _temperature_snapshot():
    with TEMPERATURE_STATE_LOCK:
        temperature_c = LAST_TEMPERATURE_C
        sensor_id = LAST_TEMPERATURE_SENSOR_ID
        sampled_at = LAST_TEMPERATURE_AT
        error_code = LAST_TEMPERATURE_ERROR
    age_seconds = None if sampled_at is None else max(0.0, time.monotonic() - sampled_at)
    stale = age_seconds is None or age_seconds > TEMPERATURE_STALE_SECONDS
    return {
        "temperature_enabled": TONYPI_TEMPERATURE_ENABLED,
        "temperature_available": bool(
            TONYPI_TEMPERATURE_ENABLED
            and temperature_c is not None
            and sensor_id
            and not stale
        ),
        "temperature_c": temperature_c,
        "temperature_sensor_id": sensor_id,
        "temperature_age_ms": None if age_seconds is None else int(age_seconds * 1000),
        "temperature_stale": stale,
        "temperature_error": error_code,
    }

def _temperature_receipt_value():
    snapshot = _temperature_snapshot()
    if not snapshot["temperature_available"]:
        return None
    return {
        "sensor": "ds18b20",
        "sensor_id": snapshot["temperature_sensor_id"],
        "temperature_c": snapshot["temperature_c"],
        "age_ms": snapshot["temperature_age_ms"],
        "calibrated": False,
        "safety_enforced": False,
    }

def _temperature_monitor():
    global LAST_TEMPERATURE_C, LAST_TEMPERATURE_SENSOR_ID
    global LAST_TEMPERATURE_AT, LAST_TEMPERATURE_ERROR
    if not TONYPI_TEMPERATURE_ENABLED:
        print("[temperature] ds18b20 monitor disabled", flush=True)
        return

    reader = DS18B20Reader(
        sensor_id=TONYPI_DS18B20_ID,
        sample_count=TONYPI_TEMPERATURE_SAMPLE_COUNT,
    )
    previous_state = None
    while True:
        try:
            reading = reader.snapshot()
            with TEMPERATURE_STATE_LOCK:
                LAST_TEMPERATURE_C = reading["temperature_c"]
                LAST_TEMPERATURE_SENSOR_ID = reading["sensor_id"]
                LAST_TEMPERATURE_AT = time.monotonic()
                LAST_TEMPERATURE_ERROR = None
            current_state = ("available", reading["sensor_id"])
            if current_state != previous_state:
                print(
                    f"[temperature] sensor={reading['sensor_id']} available "
                    f"temperature_c={reading['temperature_c']}",
                    flush=True,
                )
        except TemperatureSensorError as error:
            error_code = str(error) or type(error).__name__
            with TEMPERATURE_STATE_LOCK:
                LAST_TEMPERATURE_ERROR = error_code
            current_state = ("unavailable", error_code)
            if current_state != previous_state:
                print(f"[temperature] unavailable error={error_code}", flush=True)
        except Exception as error:
            error_code = f"ds18b20_unexpected:{type(error).__name__}"
            with TEMPERATURE_STATE_LOCK:
                LAST_TEMPERATURE_ERROR = error_code
            current_state = ("unavailable", error_code)
            if current_state != previous_state:
                print(f"[temperature] unavailable error={error_code}", flush=True)
        previous_state = current_state
        time.sleep(TEMPERATURE_POLL_INTERVAL)

def _battery_safety_error(action_name):
    if action_name in {"stop", "gaze_center", "return_idle"}:
        return None, _battery_snapshot()
    snapshot = _battery_snapshot()
    battery_mv = snapshot["battery_mv"]
    if battery_mv is not None and battery_mv < LOW_BATTERY_MV:
        return "low_battery", snapshot
    if snapshot["battery_stale"] and REGISTRY_GATE is not None and REGISTRY_GATE.enforcement == "enforce":
        return "battery_unknown", snapshot
    return None, snapshot

def _collect_imu_samples(duration=STARTUP_IMU_SAMPLE_SECONDS):
    samples = []
    deadline = time.monotonic() + max(0.1, float(duration))
    while time.monotonic() < deadline:
        if EMERGENCY_STOP_EVENT.is_set():
            raise MotionStopped("stopped_by_emergency_command")
        value = AGC.board.get_imu()
        if value is not None and len(value) == 6:
            samples.append(tuple(float(item) for item in value))
        time.sleep(0.02)
    return samples

def _evaluate_imu_upright(samples):
    if len(samples) < STARTUP_IMU_MIN_SAMPLES:
        return {
            "upright": False,
            "stable": False,
            "error_code": "startup_imu_unavailable",
            "sample_count": len(samples),
        }

    axes = list(zip(*samples))
    means = [statistics.fmean(axis) for axis in axes]
    stdevs = [statistics.pstdev(axis) for axis in axes]
    ax, ay, az, _gx, _gy, _gz = means
    accel_mag = math.sqrt(ax * ax + ay * ay + az * az)
    upright = (
        STARTUP_UPRIGHT_AX_RANGE[0] <= ax <= STARTUP_UPRIGHT_AX_RANGE[1]
        and abs(ay) <= STARTUP_UPRIGHT_AY_ABS_MAX
        and abs(az) <= STARTUP_UPRIGHT_AZ_ABS_MAX
        and STARTUP_ACCEL_MAG_RANGE[0] <= accel_mag <= STARTUP_ACCEL_MAG_RANGE[1]
    )
    stable = (
        max(stdevs[:3]) <= STARTUP_ACCEL_STDEV_MAX
        and max(stdevs[3:]) <= STARTUP_GYRO_STDEV_MAX
    )
    error_code = None
    if not upright:
        error_code = "startup_not_upright"
    elif not stable:
        error_code = "startup_not_stable"
    return {
        "upright": upright,
        "stable": stable,
        "error_code": error_code,
        "sample_count": len(samples),
        "accel_mean": {
            "ax": round(ax, 5),
            "ay": round(ay, 5),
            "az": round(az, 5),
            "magnitude": round(accel_mag, 5),
        },
        "accel_stdev_max": round(max(stdevs[:3]), 5),
        "gyro_stdev_max": round(max(stdevs[3:]), 5),
    }

def _autonomous_body_preflight(action_name, item, battery=None):
    context = item.get("execution_context") if isinstance(item, dict) else {}
    context = context if isinstance(context, dict) else {}
    if str(context.get("mode") or "").strip() != "autonomous":
        return None, {}
    if action_name in {"stop", "gaze_center", "return_idle"}:
        return None, {}

    action = (REGISTRY_GATE.actions.get(action_name) or {}) if REGISTRY_GATE is not None else {}
    if "body" not in (action.get("resources") or []):
        return None, {}

    snapshot = dict(battery or _battery_snapshot())
    details = {
        "battery_mv": snapshot.get("battery_mv"),
        "battery_age_ms": snapshot.get("battery_age_ms"),
        "minimum_battery_mv": AUTONOMY_BODY_MIN_BATTERY_MV,
        "caution_battery_mv": AUTONOMY_BODY_CAUTION_BATTERY_MV,
    }
    if snapshot.get("battery_mv") is None or snapshot.get("battery_stale"):
        return "autonomy_battery_unknown", details
    if snapshot["battery_mv"] < AUTONOMY_BODY_MIN_BATTERY_MV:
        return "autonomy_low_battery", details

    details["battery_mode"] = (
        "caution"
        if snapshot["battery_mv"] < AUTONOMY_BODY_CAUTION_BATTERY_MV
        else "normal"
    )
    if details["battery_mode"] == "caution":
        uses = {str(value).strip() for value in (action.get("uses") or []) if str(value).strip()}
        timeout_ms = max(0, int(action.get("timeout_ms") or 0))
        blocked_reasons = []
        if action.get("verified") is not True:
            blocked_reasons.append("unverified")
        if str(action.get("safety_tier") or "") != "safe_desktop":
            blocked_reasons.append("not_safe_desktop")
        if "legs" in uses:
            blocked_reasons.append("uses_legs")
        if timeout_ms > AUTONOMY_BODY_CAUTION_MAX_TIMEOUT_MS:
            blocked_reasons.append("long_running")
        details.update({
            "uses": sorted(uses),
            "timeout_ms": timeout_ms,
            "maximum_caution_timeout_ms": AUTONOMY_BODY_CAUTION_MAX_TIMEOUT_MS,
        })
        if blocked_reasons:
            details["blocked_reasons"] = blocked_reasons
            return "autonomy_low_battery_high_load", details

    try:
        imu = _evaluate_imu_upright(
            _collect_imu_samples(duration=AUTONOMY_IMU_SAMPLE_SECONDS)
        )
    except MotionStopped:
        return "stopped_by_emergency_command", details
    except Exception as error:
        details["imu_error"] = type(error).__name__
        return "autonomy_imu_unavailable", details
    details["imu"] = imu
    if not imu.get("upright"):
        error_code = imu.get("error_code")
        if error_code == "startup_imu_unavailable":
            return "autonomy_imu_unavailable", details
        return "autonomy_not_upright", details
    if not imu.get("stable"):
        return "autonomy_not_stable", details
    return None, details

def _startup_recovery_preflight(allow_current_body=False):
    interlock_reason = _motion_interlock_reason()
    if interlock_reason:
        raise StartupRecoveryRejected(interlock_reason)

    battery = _battery_snapshot()
    if battery["battery_mv"] is None or battery["battery_stale"]:
        raise StartupRecoveryRejected("startup_battery_unknown", battery)
    if battery["battery_mv"] < LOW_BATTERY_MV:
        raise StartupRecoveryRejected("low_battery", battery)

    for resource, state in _active_motion_snapshot().items():
        is_current_body = (
            allow_current_body
            and resource == "body"
            and state.get("action") == "startup_recover"
        )
        if not is_current_body:
            raise StartupRecoveryRejected(
                "startup_motion_active",
                {"resource": resource, "action": state.get("action")},
            )

    imu = _evaluate_imu_upright(_collect_imu_samples())
    if imu.get("error_code"):
        raise StartupRecoveryRejected(imu["error_code"], imu)
    return {
        "battery_mv": battery["battery_mv"],
        "battery_age_ms": battery["battery_age_ms"],
        "imu": imu,
    }

def _cooldown_remaining_ms(action_name):
    if REGISTRY_GATE is None:
        return 0
    action = REGISTRY_GATE.actions.get(action_name) or {}
    cooldown_ms = max(0, int(action.get("cooldown_ms") or 0))
    if cooldown_ms == 0:
        return 0
    with ACTION_COOLDOWN_LOCK:
        last_started = ACTION_LAST_STARTED.get(action_name)
    if last_started is None:
        return 0
    elapsed_ms = int((time.monotonic() - last_started) * 1000)
    return max(0, cooldown_ms - elapsed_ms)

def _mark_action_started(action_name):
    with ACTION_COOLDOWN_LOCK:
        ACTION_LAST_STARTED[action_name] = time.monotonic()

def _fsync_directory_best_effort(directory):
    descriptor = None
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        os.fsync(descriptor)
    except (AttributeError, OSError):
        pass
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass

def _atomic_write_json(pathname, value):
    directory = os.path.dirname(os.path.abspath(pathname)) or "."
    os.makedirs(directory, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    json.loads(raw)

    def replace_one(target):
        temporary = os.path.join(
            directory,
            f".{os.path.basename(target)}.{os.getpid()}.{uuid.uuid4().hex}.tmp",
        )
        try:
            with open(temporary, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            _fsync_directory_best_effort(directory)
        finally:
            try:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            except OSError:
                pass

    replace_one(pathname)
    replace_one(pathname + ".last-good")

def _read_strict_json(pathname, default, validator):
    if not os.path.exists(pathname):
        return json.loads(json.dumps(default))
    try:
        with open(pathname, encoding="utf-8") as handle:
            parsed = json.load(handle)
    except Exception as error:
        raise RuntimeError(
            f"{os.path.basename(pathname)} invalid_json: {error}"
        ) from error
    reason = validator(parsed)
    if reason:
        raise RuntimeError(f"{os.path.basename(pathname)} invalid_shape: {reason}")
    return parsed

def _validate_command_ledger_store(value):
    if not isinstance(value, dict):
        return "root_not_object"
    if value.get("version") != 1:
        return "version"
    commands = value.get("commands")
    if not isinstance(commands, dict):
        return "commands_not_object"
    if any(not isinstance(command_id, str) or not command_id or not isinstance(entry, dict)
           for command_id, entry in commands.items()):
        return "invalid_command_entry"
    return ""

def _validate_receipt_outbox_store(value):
    if not isinstance(value, dict):
        return "root_not_object"
    if value.get("version") != 1:
        return "version"
    items = value.get("items")
    if not isinstance(items, list):
        return "items_not_array"
    for item in items:
        if (
            not isinstance(item, dict)
            or not str(item.get("id") or "").strip()
            or not isinstance(item.get("payload"), dict)
        ):
            return "invalid_outbox_item"
    return ""

def _ensure_command_persistence_loaded():
    global COMMAND_PERSISTENCE_LOADED
    with COMMAND_LEDGER_LOCK:
        if COMMAND_PERSISTENCE_LOADED:
            return
        ledger_store = _read_strict_json(
            TONYPI_COMMAND_LEDGER_FILE,
            {"version": 1, "updated_at": "", "commands": {}},
            _validate_command_ledger_store,
        )
        outbox_store = _read_strict_json(
            TONYPI_RECEIPT_OUTBOX_FILE,
            {"version": 1, "updated_at": "", "items": []},
            _validate_receipt_outbox_store,
        )
        COMMAND_LEDGER.clear()
        for command_id, entry in ledger_store["commands"].items():
            COMMAND_LEDGER[command_id] = dict(entry)
        RECEIPT_OUTBOX.clear()
        for item in outbox_store["items"]:
            RECEIPT_OUTBOX[str(item["id"])] = dict(item)
        COMMAND_PERSISTENCE_LOADED = True

def _trim_command_ledger_locked():
    while len(COMMAND_LEDGER) > COMMAND_LEDGER_LIMIT:
        removable = next(
            (
                command_id
                for command_id, entry in COMMAND_LEDGER.items()
                if entry.get("terminal_confirmed") is True
            ),
            None,
        )
        if removable is None:
            # Never evict an unconfirmed command merely to satisfy a size target.
            break
        COMMAND_LEDGER.pop(removable, None)

def _persist_command_ledger_locked():
    _trim_command_ledger_locked()
    _atomic_write_json(
        TONYPI_COMMAND_LEDGER_FILE,
        {
            "version": 1,
            "updated_at": datetime.now().astimezone().isoformat(),
            "commands": dict(COMMAND_LEDGER),
        },
    )

def _persist_receipt_outbox_locked():
    _atomic_write_json(
        TONYPI_RECEIPT_OUTBOX_FILE,
        {
            "version": 1,
            "updated_at": datetime.now().astimezone().isoformat(),
            "items": list(RECEIPT_OUTBOX.values()),
        },
    )

def _valid_keepalive_delivery_identity(value):
    value = str(value or "")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
    return 8 <= len(value) <= 128 and all(char in allowed for char in value)

def _validate_keepalive_delivery_store(value):
    if not isinstance(value, dict):
        return "root_not_object"
    if value.get("version") != 1:
        return "version"
    if not _valid_keepalive_delivery_identity(value.get("owner_id")):
        return "owner_id"
    deliveries = value.get("deliveries")
    if not isinstance(deliveries, dict):
        return "deliveries_not_object"
    for delivery_id, item in deliveries.items():
        if (
            not _valid_keepalive_delivery_identity(delivery_id)
            or not isinstance(item, dict)
            or item.get("phase") not in {"processing", "processed", "acked"}
            or not isinstance(item.get("content_hash"), str)
            or len(item.get("content_hash")) != 64
        ):
            return "invalid_delivery_entry"
        for field in ("lease_token", "lease_session", "lease_expires_at", "updated_at"):
            if not isinstance(item.get(field, ""), str):
                return "invalid_delivery_" + field
    return ""

def _persist_keepalive_delivery_state_locked():
    KEEPALIVE_DELIVERY_STATE["updated_at"] = datetime.now().astimezone().isoformat()
    deliveries = KEEPALIVE_DELIVERY_STATE["deliveries"]
    acked = [
        (delivery_id, item)
        for delivery_id, item in deliveries.items()
        if item.get("phase") == "acked"
    ]
    while len(acked) > KEEPALIVE_DELIVERY_LIMIT:
        delivery_id, _item = acked.pop(0)
        deliveries.pop(delivery_id, None)
    _atomic_write_json(TONYPI_KEEPALIVE_DELIVERY_FILE, KEEPALIVE_DELIVERY_STATE)

def _ensure_keepalive_delivery_state_loaded():
    global KEEPALIVE_DELIVERY_STATE_LOADED
    with KEEPALIVE_DELIVERY_LOCK:
        if KEEPALIVE_DELIVERY_STATE_LOADED:
            return KEEPALIVE_DELIVERY_STATE
        exists = os.path.exists(TONYPI_KEEPALIVE_DELIVERY_FILE)
        default = {
            "version": 1,
            "owner_id": "tonypi:" + str(uuid.uuid4()),
            "updated_at": "",
            "deliveries": {},
        }
        state = _read_strict_json(
            TONYPI_KEEPALIVE_DELIVERY_FILE,
            default,
            _validate_keepalive_delivery_store,
        )
        if not exists:
            _atomic_write_json(TONYPI_KEEPALIVE_DELIVERY_FILE, state)
        KEEPALIVE_DELIVERY_STATE.clear()
        KEEPALIVE_DELIVERY_STATE.update(state)
        KEEPALIVE_DELIVERY_STATE_LOADED = True
        return KEEPALIVE_DELIVERY_STATE

def _keepalive_content_hash(message):
    canonical = json.dumps(
        {
            "id": str(message.get("id") or ""),
            "content": str(message.get("content") or ""),
            "source": str(message.get("source") or ""),
            "timestamp": str(message.get("timestamp") or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def _keepalive_delivery_metadata(message):
    delivery = message.get("_delivery")
    if not isinstance(delivery, dict):
        return None
    delivery_id = str(delivery.get("id") or "").strip()
    owner = str(delivery.get("owner") or "").strip()
    session = str(delivery.get("session") or "").strip()
    lease_token = str(delivery.get("lease_token") or "").strip()
    if (
        delivery.get("protocol") != "keepalive-lease/v1"
        or not _valid_keepalive_delivery_identity(delivery_id)
        or not _valid_keepalive_delivery_identity(owner)
        or not _valid_keepalive_delivery_identity(session)
        or len(lease_token) < 32
    ):
        return None
    return {
        "id": delivery_id,
        "owner": owner,
        "session": session,
        "lease_token": lease_token,
        "lease_expires_at": str(delivery.get("lease_expires_at") or ""),
    }

def _claim_keepalive_delivery(message):
    metadata = _keepalive_delivery_metadata(message)
    if metadata is None:
        return None, False
    content_hash = _keepalive_content_hash(message)
    with KEEPALIVE_DELIVERY_LOCK:
        state = _ensure_keepalive_delivery_state_loaded()
        if metadata["owner"] != state["owner_id"]:
            raise RuntimeError("keepalive delivery owner mismatch")
        existing = state["deliveries"].get(metadata["id"])
        if existing is not None and existing.get("content_hash") != content_hash:
            raise RuntimeError("keepalive delivery content conflict")
        should_process = existing is None
        phase = "processing" if should_process else (
            "processed" if existing.get("phase") == "processing" else existing.get("phase")
        )
        state["deliveries"][metadata["id"]] = {
            **(existing or {}),
            "phase": phase,
            "content_hash": content_hash,
            "lease_token": metadata["lease_token"],
            "lease_session": metadata["session"],
            "lease_expires_at": metadata["lease_expires_at"],
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        _persist_keepalive_delivery_state_locked()
    return metadata, should_process

def _mark_keepalive_delivery_processed(delivery_id):
    with KEEPALIVE_DELIVERY_LOCK:
        state = _ensure_keepalive_delivery_state_loaded()
        item = state["deliveries"].get(str(delivery_id or ""))
        if item is None:
            raise RuntimeError("keepalive delivery claim missing")
        item["phase"] = "processed"
        item["processed_at"] = datetime.now().astimezone().isoformat()
        item["updated_at"] = item["processed_at"]
        _persist_keepalive_delivery_state_locked()

def _forget_keepalive_delivery_claim(delivery_id):
    with KEEPALIVE_DELIVERY_LOCK:
        state = _ensure_keepalive_delivery_state_loaded()
        state["deliveries"].pop(str(delivery_id or ""), None)
        _persist_keepalive_delivery_state_locked()

def _claim_command(command_id, command=None):
    command_id = str(command_id or "").strip()
    if not command_id:
        return True
    with COMMAND_LEDGER_LOCK:
        _ensure_command_persistence_loaded()
        entry = COMMAND_LEDGER.get(command_id)
        if entry is not None:
            COMMAND_LEDGER.move_to_end(command_id)
            phase = str(entry.get("phase") or "claimed")
            if (
                entry.get("terminal_confirmed") is True
                or phase in {"started", "terminal_queued", "terminal_confirmed"}
                or entry.get("session_id") == COMMAND_SESSION_ID
            ):
                return False
            if phase not in {"claimed", "ack"}:
                return False
            now = datetime.now().astimezone().isoformat()
            entry["session_id"] = COMMAND_SESSION_ID
            entry["resumed_at"] = now
            entry["updated_at"] = now
            if command is not None:
                entry["command"] = json.loads(json.dumps(command))
            _persist_command_ledger_locked()
            return True
        now = datetime.now().astimezone().isoformat()
        COMMAND_LEDGER[command_id] = {
            "command": json.loads(json.dumps(command or {})),
            "phase": "claimed",
            "session_id": COMMAND_SESSION_ID,
            "claimed_at": now,
            "updated_at": now,
            "last_receipt": None,
            "terminal_status": "",
            "terminal_confirmed": False,
        }
        # Durable takeover must complete before an ack or a physical action.
        _persist_command_ledger_locked()
    return True

def _record_command_receipt(payload):
    command_id = str(payload.get("command_id") or "").strip()
    if not command_id:
        return
    status = str(payload.get("status") or "").strip().lower()
    with COMMAND_LEDGER_LOCK:
        _ensure_command_persistence_loaded()
        entry = COMMAND_LEDGER.get(command_id)
        if entry is None:
            entry = {
                "command": {},
                "claimed_at": payload.get("at"),
                "session_id": COMMAND_SESSION_ID,
                "terminal_confirmed": False,
            }
            COMMAND_LEDGER[command_id] = entry
        if status == "started":
            entry["phase"] = "started"
        elif status in TERMINAL_RECEIPT_STATUSES:
            entry["phase"] = "terminal_queued"
            entry["terminal_status"] = status
            entry["terminal_confirmed"] = False
        elif status == "ack":
            entry["phase"] = "ack"
        else:
            entry.setdefault("phase", "claimed")
        entry["last_receipt"] = dict(payload)
        entry["updated_at"] = datetime.now().astimezone().isoformat()
        COMMAND_LEDGER.move_to_end(command_id)
        _persist_command_ledger_locked()

def _stage_robot_receipt(payload):
    receipt_id = str(payload.get("receipt_id") or "").strip()
    if not receipt_id:
        raise RuntimeError("receipt_id_required")
    with COMMAND_LEDGER_LOCK:
        _ensure_command_persistence_loaded()
        existing = RECEIPT_OUTBOX.get(receipt_id)
        item = dict(existing or {})
        item.update(
            {
                "id": receipt_id,
                "payload": dict(payload),
                "attempts": max(0, int(item.get("attempts") or 0)),
                "next_attempt_at": min(
                    float(item.get("next_attempt_at") or 0),
                    time.time(),
                ),
                "created_at": item.get("created_at") or datetime.now().astimezone().isoformat(),
                "updated_at": datetime.now().astimezone().isoformat(),
            }
        )
        RECEIPT_OUTBOX[receipt_id] = item
        # Outbox first: a terminal receipt can be replayed even if power fails
        # before the ledger phase update.
        _persist_receipt_outbox_locked()
        _record_command_receipt(payload)
    ROBOT_RECEIPT_QUEUE.put_nowait(dict(payload))
    return item

def _replay_last_command_receipt(command_id):
    with COMMAND_LEDGER_LOCK:
        _ensure_command_persistence_loaded()
        entry = COMMAND_LEDGER.get(str(command_id or "").strip()) or {}
        payload = dict(entry.get("last_receipt") or {})
    if not payload:
        return False
    payload["at"] = datetime.now().astimezone().isoformat()
    payload["replayed"] = True
    _stage_robot_receipt(payload)
    return True

def _motion_watchdog():
    previous = None
    while True:
        owner = _read_control_owner()
        controllers = _external_motion_controllers()
        reason = _motion_interlock_reason() or "ready"
        state = (owner, tuple(controllers), reason)
        if state != previous:
            print(
                f"[safety] owner={owner} external={','.join(controllers) or 'none'} interlock={reason}",
                flush=True,
            )
            previous = state
        time.sleep(2)

def load_env_file(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)

load_env_file(os.path.join(os.path.dirname(__file__), "secrets.env"))
MEMORY_SERVER = os.environ.get("MEMORY_SERVER", "https://example.invalid")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
TONYPI_BRIDGE_TOKEN = os.environ.get("TONYPI_BRIDGE_TOKEN", "").strip()
TONYPI_STATE_DIR = os.environ.get(
    "TONYPI_STATE_DIR",
    "/home/pi/yushi" if os.name == "posix" else os.path.dirname(__file__),
).strip()
TONYPI_COMMAND_LEDGER_FILE = os.environ.get(
    "TONYPI_COMMAND_LEDGER_FILE",
    os.path.join(TONYPI_STATE_DIR, "command_ledger.json"),
).strip()
TONYPI_RECEIPT_OUTBOX_FILE = os.environ.get(
    "TONYPI_RECEIPT_OUTBOX_FILE",
    os.path.join(TONYPI_STATE_DIR, "receipt_outbox.json"),
).strip()
TONYPI_INSTANCE_LOCK_FILE = os.environ.get(
    "TONYPI_INSTANCE_LOCK_FILE",
    os.path.join(TONYPI_STATE_DIR, "yushi_client.lock"),
).strip()
TONYPI_OWNER_ID = os.environ.get("TONYPI_OWNER_ID", "tonypi-yushi").strip()
TONYPI_KEEPALIVE_DELIVERY_FILE = os.environ.get(
    "TONYPI_KEEPALIVE_DELIVERY_FILE",
    os.path.join(TONYPI_STATE_DIR, "keepalive_delivery_state.json"),
).strip()
TONYPI_TEMPERATURE_ENABLED = os.environ.get(
    "TONYPI_TEMPERATURE_ENABLED",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}
TONYPI_DS18B20_ID = os.environ.get("TONYPI_DS18B20_ID", "").strip() or None
try:
    TEMPERATURE_POLL_INTERVAL = max(
        5.0,
        float(os.environ.get("TONYPI_TEMPERATURE_POLL_SEC", "15")),
    )
except (TypeError, ValueError):
    TEMPERATURE_POLL_INTERVAL = 15.0
try:
    TONYPI_TEMPERATURE_SAMPLE_COUNT = max(
        1,
        min(5, int(os.environ.get("TONYPI_TEMPERATURE_SAMPLE_COUNT", "3"))),
    )
except (TypeError, ValueError):
    TONYPI_TEMPERATURE_SAMPLE_COUNT = 3
try:
    TEMPERATURE_STALE_SECONDS = max(
        TEMPERATURE_POLL_INTERVAL * 2.0,
        float(os.environ.get("TONYPI_TEMPERATURE_STALE_SEC", "90")),
    )
except (TypeError, ValueError):
    TEMPERATURE_STALE_SECONDS = max(TEMPERATURE_POLL_INTERVAL * 2.0, 90.0)
# Wake/replay compatibility queue only. Durability and backpressure live in the
# on-disk outbox, so a full in-memory queue can never drop a terminal receipt.
ROBOT_RECEIPT_QUEUE = queue.Queue()
TONYPI_REGISTRY_PATH = os.environ.get(
    "TONYPI_REGISTRY_PATH",
    "/home/pi/yushi/protocol/tonypi_action_registry.json",
)
TONYPI_REGISTRY_MODE_FILE = os.environ.get(
    "TONYPI_REGISTRY_MODE_FILE",
    "/home/pi/yushi/registry_enforcement",
)
REGISTRY_GATE = None
COMMAND_CONTEXT_LOCK = threading.Lock()
COMMAND_RECEIPT_CONTEXT = {}
TERMINAL_RECEIPT_STATUSES = {"completed", "failed", "skipped", "stopped"}

def _release_single_instance_lock():
    global INSTANCE_LOCK_HANDLE
    handle = INSTANCE_LOCK_HANDLE
    INSTANCE_LOCK_HANDLE = None
    if handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except (OSError, ValueError):
        pass
    try:
        handle.close()
    except (OSError, ValueError):
        pass

def _acquire_single_instance_lock(lock_path=None):
    global INSTANCE_LOCK_HANDLE
    if INSTANCE_LOCK_HANDLE is not None:
        return INSTANCE_LOCK_HANDLE
    target = str(lock_path or TONYPI_INSTANCE_LOCK_FILE).strip()
    if not target:
        raise RuntimeError("tonypi_instance_lock_path_required")
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    handle = open(target, "a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:
            handle.seek(0)
            if not handle.read(1):
                handle.seek(0)
                handle.write("0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            raise RuntimeError("tonypi_instance_lock_unsupported")
    except (OSError, RuntimeError) as error:
        handle.close()
        raise RuntimeError("tonypi_instance_already_running") from error
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps({
        "pid": os.getpid(),
        "owner_id": TONYPI_OWNER_ID,
        "session_id": COMMAND_SESSION_ID,
        "started_at": datetime.now().astimezone().isoformat(),
    }, ensure_ascii=False))
    handle.flush()
    try:
        os.fsync(handle.fileno())
    except OSError:
        pass
    INSTANCE_LOCK_HANDLE = handle
    return handle

atexit.register(_release_single_instance_lock)

def _init_registry_gate():
    global REGISTRY_GATE
    REGISTRY_GATE = TonyPiRegistryGate(TONYPI_REGISTRY_PATH, TONYPI_REGISTRY_MODE_FILE)
    status = REGISTRY_GATE.status()
    print(
        f"[registry] version={status['registry_version']} sha256={status['registry_sha256']} "
        f"mode={status['enforcement']} actions={status['action_count']}",
        flush=True,
    )
    return REGISTRY_GATE

def _remember_command_context(item):
    command_id = str(item.get("command_id") or "").strip()
    if not command_id:
        return
    context = {}
    for field in (
        "plan_id",
        "parent_plan_id",
        "caused_by_receipt_id",
        "performance_phase",
        "lease_owner_id",
        "lease_session_id",
    ):
        value = str(item.get(field) or "").strip()
        if value:
            context[field] = value
    with COMMAND_CONTEXT_LOCK:
        COMMAND_RECEIPT_CONTEXT[command_id] = context

def _command_receipt_context(command_id):
    with COMMAND_CONTEXT_LOCK:
        return dict(COMMAND_RECEIPT_CONTEXT.get(command_id, {}))

def _forget_command_context(command_id):
    with COMMAND_CONTEXT_LOCK:
        COMMAND_RECEIPT_CONTEXT.pop(command_id, None)

def _robot_headers(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    headers = {"Content-Type": "application/json"}
    if TONYPI_BRIDGE_TOKEN:
        headers["X-TonyPi-Token"] = TONYPI_BRIDGE_TOKEN
    headers["X-TonyPi-Owner-ID"] = str(
        payload.get("owner_id")
        or payload.get("lease_owner_id")
        or TONYPI_OWNER_ID
    )
    headers["X-TonyPi-Session-ID"] = str(
        payload.get("owner_session_id")
        or payload.get("lease_session_id")
        or COMMAND_SESSION_ID
    )
    return headers

def _keepalive_delivery_headers(session=None):
    with KEEPALIVE_DELIVERY_LOCK:
        state = _ensure_keepalive_delivery_state_loaded()
        owner = state["owner_id"]
    headers = _robot_headers()
    headers["X-Yushi-Delivery-Owner"] = owner
    headers["X-Yushi-Delivery-Session"] = str(
        session or KEEPALIVE_DELIVERY_SESSION_ID
    )
    return headers

def _post_keepalive_delivery_result(metadata, status="completed", error=""):
    headers = _keepalive_delivery_headers(metadata.get("session"))
    if headers["X-Yushi-Delivery-Owner"] != metadata.get("owner"):
        raise RuntimeError("keepalive delivery owner mismatch")
    payload = {
        "delivery_id": metadata.get("id"),
        "lease_token": metadata.get("lease_token"),
        "status": status,
    }
    if error:
        payload["error"] = str(error)[:240]
    try:
        response = KEEPALIVE_HTTP_SESSION.post(
            f"{MEMORY_SERVER}/keepalive/ack",
            headers=headers,
            json=payload,
            timeout=KEEPALIVE_HTTP_TIMEOUT,
        )
        body = response.json()
        if response.status_code == 200 and isinstance(body, dict) and body.get("ok") is True:
            return True, False
        if response.status_code in {404, 409}:
            return False, True
        print(
            f"[keepalive-ack] unexpected http={response.status_code}",
            flush=True,
        )
    except Exception as ack_error:
        print(f"[keepalive-ack] retained: {ack_error}", flush=True)
    return False, False

def _keepalive_record_metadata(delivery_id, item, owner):
    lease_token = str(item.get("lease_token") or "")
    lease_session = str(item.get("lease_session") or "")
    if len(lease_token) < 32 or not _valid_keepalive_delivery_identity(lease_session):
        return None
    return {
        "id": str(delivery_id),
        "owner": str(owner),
        "session": lease_session,
        "lease_token": lease_token,
    }

def _ack_keepalive_delivery_once(delivery_id):
    with KEEPALIVE_DELIVERY_LOCK:
        state = _ensure_keepalive_delivery_state_loaded()
        item = state["deliveries"].get(str(delivery_id or ""))
        if item is None:
            return False
        metadata = _keepalive_record_metadata(delivery_id, item, state["owner_id"])
    if metadata is None:
        return False
    success, stale = _post_keepalive_delivery_result(metadata, status="completed")
    with KEEPALIVE_DELIVERY_LOCK:
        state = _ensure_keepalive_delivery_state_loaded()
        current = state["deliveries"].get(str(delivery_id or ""))
        if current is None or current.get("lease_token") != metadata["lease_token"]:
            return success
        if success:
            current["phase"] = "acked"
            current["acked_at"] = datetime.now().astimezone().isoformat()
            current["lease_token"] = ""
            current["lease_expires_at"] = ""
        elif stale:
            # The server may already have re-leased the item. Wait for the next
            # fetch to attach a current lease instead of retrying a stale token.
            current["lease_token"] = ""
            current["lease_expires_at"] = ""
        current["updated_at"] = datetime.now().astimezone().isoformat()
        _persist_keepalive_delivery_state_locked()
    return success

def _flush_keepalive_ack_once():
    with KEEPALIVE_DELIVERY_LOCK:
        state = _ensure_keepalive_delivery_state_loaded()
        delivery_ids = [
            delivery_id
            for delivery_id, item in state["deliveries"].items()
            if item.get("phase") in {"processing", "processed", "acked"}
            and len(str(item.get("lease_token") or "")) >= 32
        ]
    confirmed = 0
    for delivery_id in delivery_ids[:8]:
        if _ack_keepalive_delivery_once(delivery_id):
            confirmed += 1
    return confirmed

def process_keepalive_delivery(message):
    metadata, should_process = _claim_keepalive_delivery(message)
    if metadata is None:
        print(
            "[keepalive] ignored message without durable lease metadata",
            flush=True,
        )
        return False
    if should_process:
        try:
            if on_keepalive_message(message) is not True:
                _forget_keepalive_delivery_claim(metadata["id"])
                _post_keepalive_delivery_result(
                    metadata,
                    status="retry",
                    error="keepalive_processing_failed",
                )
                return False
            _mark_keepalive_delivery_processed(metadata["id"])
        except Exception as error:
            _forget_keepalive_delivery_claim(metadata["id"])
            _post_keepalive_delivery_result(
                metadata,
                status="retry",
                error=error,
            )
            print(f"[keepalive] processing failed: {error}", flush=True)
            return False
    else:
        print(
            f"[keepalive] duplicate delivery suppressed id={metadata['id']}",
            flush=True,
        )
    _ack_keepalive_delivery_once(metadata["id"])
    return True

def _server_visual_observation_provider(jpeg, metadata, command_id=None):
    headers = _robot_headers()
    headers.update(
        {
            "Content-Type": "image/jpeg",
            "X-TonyPi-Command-ID": str(command_id or ""),
            "X-TonyPi-Frame-Schema": str(metadata.get("schema_version") or ""),
            "X-TonyPi-Image-Width": str(int(metadata.get("width") or 0)),
            "X-TonyPi-Image-Height": str(int(metadata.get("height") or 0)),
        }
    )
    response = ROBOT_HTTP_SESSION.post(
        f"{MEMORY_SERVER}/robot/vision/observe",
        headers=headers,
        data=jpeg,
        timeout=VISUAL_OBSERVATION_HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        raise VisualObservationServerError(
            f"visual_observation_http_{response.status_code}"
        )
    try:
        return response.json()
    except Exception as error:
        raise VisualObservationServerError("visual_observation_invalid_json") from error

def _resolve_action_implementation(canonical_action):
    if REGISTRY_GATE is not None:
        action = REGISTRY_GATE.actions.get(canonical_action)
        if action is not None:
            implementation = action.get("implementation") or {}
            target = str(implementation.get("target") or "").strip()
            if target:
                return target
    return ACTION_ALIASES.get(canonical_action, canonical_action)

def _enqueue_robot_receipt(command_id, status, action, **extra):
    command_id = str(command_id or "").strip()
    if not command_id:
        return
    payload = {
        "schema_version": "tonypi-receipt/v1",
        "receipt_id": f"receipt:{command_id}:{str(status or '').strip()}",
        "command_id": command_id,
        "status": str(status or "").strip(),
        "action": str(action or "").strip(),
        "at": datetime.now().astimezone().isoformat(),
    }
    if REGISTRY_GATE is not None:
        payload["registry_version"] = REGISTRY_GATE.registry_version
        payload["registry_sha256"] = REGISTRY_GATE.registry_sha256
    battery = _battery_snapshot()
    if battery["battery_mv"] is not None:
        payload["battery_mv"] = battery["battery_mv"]
        payload["battery_voltage"] = battery["battery_voltage"]
        payload["battery_age_ms"] = battery["battery_age_ms"]
    context = _command_receipt_context(command_id)
    payload.update(context)
    payload["owner_id"] = str(context.get("lease_owner_id") or TONYPI_OWNER_ID)
    payload["owner_session_id"] = str(
        context.get("lease_session_id") or COMMAND_SESSION_ID
    )
    payload.update({k: v for k, v in extra.items() if v is not None})
    if payload["status"] in TERMINAL_RECEIPT_STATUSES:
        body_temperature = _temperature_receipt_value()
        if body_temperature is not None:
            result = payload.get("result")
            result = dict(result) if isinstance(result, dict) else {}
            result["body_temperature"] = body_temperature
            payload["result"] = result
    _stage_robot_receipt(payload)

def _deliver_robot_receipt_once(now=None):
    now = time.time() if now is None else float(now)
    with COMMAND_LEDGER_LOCK:
        _ensure_command_persistence_loaded()
        item = next(iter(RECEIPT_OUTBOX.values()), None)
        if item is None or float(item.get("next_attempt_at") or 0) > now:
            return None
        receipt_id = str(item.get("id") or "")
        payload = dict(item.get("payload") or {})
    error_message = ""
    try:
        response = ROBOT_HTTP_SESSION.post(
            f"{MEMORY_SERVER}/robot/receipt",
            headers=_robot_headers(payload),
            json=payload,
            timeout=8,
        )
        response_body = response.json()
        if response.status_code != 200 or not isinstance(response_body, dict) or response_body.get("ok") is not True:
            detail = response_body.get("error") if isinstance(response_body, dict) else ""
            error_message = f"http_{response.status_code}" + (f":{detail}" if detail else "")
    except Exception as error:
        error_message = str(error)

    with COMMAND_LEDGER_LOCK:
        _ensure_command_persistence_loaded()
        current = RECEIPT_OUTBOX.get(receipt_id)
        if current is None:
            return True
        if error_message:
            attempts = max(0, int(current.get("attempts") or 0)) + 1
            current["attempts"] = attempts
            current["last_error"] = error_message[:240]
            current["next_attempt_at"] = time.time() + min(
                60.0,
                0.5 * (2 ** min(7, attempts - 1)),
            )
            current["updated_at"] = datetime.now().astimezone().isoformat()
            _persist_receipt_outbox_locked()
            print(
                f"[receipt] retained command_id={payload.get('command_id')} "
                f"status={payload.get('status')} attempt={attempts} error={error_message}",
                flush=True,
            )
            return False

        RECEIPT_OUTBOX.pop(receipt_id, None)
        _persist_receipt_outbox_locked()
        command_id = str(payload.get("command_id") or "").strip()
        status = str(payload.get("status") or "").strip().lower()
        if status in TERMINAL_RECEIPT_STATUSES:
            entry = COMMAND_LEDGER.get(command_id)
            if entry is not None:
                confirmed_at = datetime.now().astimezone().isoformat()
                entry["phase"] = "terminal_confirmed"
                entry["terminal_status"] = status
                entry["terminal_confirmed"] = True
                entry["confirmed_at"] = confirmed_at
                entry["updated_at"] = confirmed_at
                _persist_command_ledger_locked()
            _forget_command_context(command_id)
    print(
        f"[receipt] posted command_id={payload.get('command_id')} "
        f"status={payload.get('status')}",
        flush=True,
    )
    return True

def _robot_receipt_worker():
    _ensure_command_persistence_loaded()
    while True:
        try:
            ROBOT_RECEIPT_QUEUE.get(timeout=0.25)
            ROBOT_RECEIPT_QUEUE.task_done()
        except queue.Empty:
            pass
        _deliver_robot_receipt_once()

def _recover_command_delivery_after_restart():
    with COMMAND_LEDGER_LOCK:
        _ensure_command_persistence_loaded()
        interrupted = [
            (command_id, dict(entry))
            for command_id, entry in COMMAND_LEDGER.items()
            if (
                entry.get("session_id") != COMMAND_SESSION_ID
                and entry.get("phase") == "started"
                and entry.get("terminal_confirmed") is not True
            )
        ]
    for command_id, entry in interrupted:
        command = entry.get("command") if isinstance(entry.get("command"), dict) else {}
        last_receipt = entry.get("last_receipt") if isinstance(entry.get("last_receipt"), dict) else {}
        _remember_command_context(command)
        _enqueue_robot_receipt(
            command_id,
            "failed",
            command.get("action") or last_receipt.get("action") or "",
            error_code="device_restarted_during_execution",
            error_detail="device process restarted before terminal confirmation",
        )
    return len(interrupted)

def fetch_yushi_pending():
    """优先合并接口 /yushi/pending，兼容旧 /keepalive/pending + /robot/pending。"""
    try:
        res = requests.get(
            f"{MEMORY_SERVER}/yushi/pending",
            headers=_keepalive_delivery_headers(),
            timeout=10,
        )
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, dict):
                keepalive = [m for m in (data.get("keepalive") or []) if isinstance(m, dict)]
                robot = [m for m in (data.get("robot") or []) if _is_robot_queue_item(m)]
                return keepalive, robot
    except Exception as e:
        print(f"[yushi] /yushi/pending 失败，回退旧接口: {e}")
    keepalive = []
    robot = []
    try:
        res = requests.get(
            f"{MEMORY_SERVER}/keepalive/pending",
            headers=_keepalive_delivery_headers(),
            timeout=10,
        )
        if res.status_code == 200 and isinstance(res.json(), list):
            keepalive = [m for m in res.json() if isinstance(m, dict)]
    except Exception as e:
        print(f"[yushi] keepalive 轮询失败: {e}")
    try:
        res = requests.get(f"{MEMORY_SERVER}/robot/pending", headers=_robot_headers(), timeout=10)
        if res.status_code == 200 and isinstance(res.json(), list):
            robot = [m for m in res.json() if _is_robot_queue_item(m)]
    except Exception as e:
        print(f"[yushi] robot 轮询失败: {e}")
    return keepalive, robot

def fetch_robot_pending():
    """Fetch body commands without letting keepalive or TTS delay emergency stop."""
    try:
        res = ROBOT_HTTP_SESSION.get(
            f"{MEMORY_SERVER}/robot/pending",
            headers=_robot_headers(),
            timeout=ROBOT_HTTP_TIMEOUT,
        )
        if res.status_code == 200 and isinstance(res.json(), list):
            return [m for m in res.json() if _is_robot_queue_item(m)]
        print(f"[robot-poll] unexpected http={res.status_code}", flush=True)
    except Exception as e:
        print(f"[robot-poll] failed: {e}", flush=True)
    return []

def fetch_keepalive_pending():
    """Fetch spoken keepalives on a slower, independent channel."""
    try:
        res = KEEPALIVE_HTTP_SESSION.get(
            f"{MEMORY_SERVER}/keepalive/pending",
            headers=_keepalive_delivery_headers(),
            timeout=KEEPALIVE_HTTP_TIMEOUT,
        )
        if res.status_code == 200 and isinstance(res.json(), list):
            return [m for m in res.json() if isinstance(m, dict)]
        print(f"[keepalive-poll] unexpected http={res.status_code}", flush=True)
    except Exception as e:
        print(f"[keepalive-poll] failed: {e}", flush=True)
    return []

def poll_robot_commands_once():
    for item in fetch_robot_pending():
        try:
            on_robot_action(item)
        except Exception as e:
            print(f"[robot-poll] command failed: {e}", flush=True)

def _robot_command_loop():
    while True:
        poll_robot_commands_once()
        time.sleep(ROBOT_POLL_INTERVAL)

def _run_action_group_locked(action_name, command_id=None, receipt_action=None):
    reported_action = receipt_action or action_name
    started = time.monotonic()
    terminal_status = "failed"
    terminal_extra = {
        "resource": "body",
        "implementation": "d6a",
    }
    terminal_log = None
    _set_active_motion("body", reported_action, command_id, "d6a")
    try:
        _enqueue_robot_receipt(command_id, "started", reported_action, resource="body", implementation="d6a")
        print(f"[motion] started action={action_name} resource=body implementation=d6a", flush=True)
        _ensure_motion_allowed()
        AGC.runActionGroup(action_name, 1, True)
        _ensure_motion_allowed()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _set_body_pose(D6A_FINAL_POSES.get(action_name, f"d6a:{action_name}:end_unverified"))
        terminal_status = "completed"
        terminal_extra.update({
            "duration_ms": elapsed_ms,
            "final_pose": _final_pose_snapshot("body"),
        })
        terminal_log = f"[motion] completed action={action_name} resource=body duration_ms={elapsed_ms}"
    except MotionStopped:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _set_body_pose("stopped_hold_unverified")
        terminal_status = "stopped"
        terminal_extra.update({
            "duration_ms": elapsed_ms,
            "error_code": "stopped_by_emergency_command",
            "final_pose": _final_pose_snapshot("body"),
        })
        terminal_log = f"[motion] stopped action={action_name} resource=body duration_ms={elapsed_ms}"
    except Exception as e:
        terminal_extra["error"] = str(e)
        terminal_log = f"[motion] failed action={action_name} resource=body error={e}"
    finally:
        _clear_active_motion("body")
        BODY_MOTION_LOCK.release()
    _enqueue_robot_receipt(command_id, terminal_status, reported_action, **terminal_extra)
    if terminal_log:
        print(terminal_log, flush=True)

def do_action(action_name, command_id=None, receipt_action=None):
    reported_action = receipt_action or action_name
    if EMERGENCY_STOP_EVENT.is_set():
        _enqueue_robot_receipt(
            command_id,
            "skipped",
            reported_action,
            resource="body",
            implementation="d6a",
            error_code="emergency_stop_active",
            final_pose=_final_pose_snapshot("body"),
        )
        return False
    interlock_reason = _motion_interlock_reason()
    if interlock_reason:
        _enqueue_robot_receipt(
            command_id,
            "skipped",
            reported_action,
            resource="body",
            implementation="d6a",
            error=interlock_reason,
            final_pose=_final_pose_snapshot("body"),
        )
        print(f"[motion] skipped action={action_name} resource=body reason={interlock_reason}", flush=True)
        return False
    action_file = f"{ACTION_BASE}/{action_name}.d6a"
    if not os.path.isfile(action_file):
        _enqueue_robot_receipt(command_id, "failed", reported_action, resource="body", implementation="d6a", error="action_file_missing")
        print(f"[yushi] 动作文件不存在: {action_file}")
        return False
    if not BODY_MOTION_LOCK.acquire(blocking=False):
        _enqueue_robot_receipt(command_id, "skipped", reported_action, resource="body", implementation="d6a", error="resource_busy")
        print(f"[motion] skipped action={action_name} resource=body reason=busy", flush=True)
        return False
    try:
        threading.Thread(
            target=_run_action_group_locked,
            args=(action_name, command_id, reported_action),
            daemon=True,
        ).start()
        print(f"[yushi] 执行动作: {action_name}", flush=True)
        return True
    except Exception as e:
        BODY_MOTION_LOCK.release()
        print(f"[yushi] 动作失败: {e}", flush=True)
        return False

PHYSICAL_ACCEPTANCE_ACTIONS = {
    "quiet_acknowledge_low": ("quiet_acknowledge", "low"),
    "quiet_acknowledge_medium": ("quiet_acknowledge", "medium"),
    "quiet_acknowledge_high": ("quiet_acknowledge", "high"),
    "happy_greeting_low": ("happy_greeting", "low"),
    "happy_greeting_medium": ("happy_greeting", "medium"),
    "happy_greeting_high": ("happy_greeting", "high"),
}
CODE_ACTIONS = {
    "soft_hug", "shy_wave", "listen_idle", "wings_open", "return_idle",
    "startup_recover", "happy_wiggle", "hands_ready", "want_attention",
    "read_arm_positions", "gaze_center", "gaze_left", "gaze_right",
    "gaze_up", "gaze_down", "gaze_glance_left", "gaze_glance_right",
    "gaze_glance_up", "gaze_glance_down", "gaze_safe_cycle", "seek_user",
    "track_face_brief", "observe_gesture_once", "observe_user_once",
    *PHYSICAL_ACCEPTANCE_ACTIONS,
}

INTERNAL_BODY_ATOMS = {
    atom_name: atom_positions(atom_name)
    for atom_name in BODY_ATOM_CONTRACTS
}
GAZE_CENTER_PITCH = 1500
GAZE_CENTER_YAW = 1530
GAZE_YAW_OFFSET = 120
GAZE_PITCH_OFFSET = 100
GAZE_GLANCE_YAW_OFFSET = 72
GAZE_GLANCE_PITCH_OFFSET = 60
PARAMETRIC_EXPRESSION_ACTIONS = {
    "hands_ready",
    "happy_wiggle",
    "gaze_glance_left",
    "gaze_glance_right",
    "gaze_glance_up",
    "gaze_glance_down",
}
GAZE_YAW_LIMITS = (GAZE_CENTER_YAW - GAZE_YAW_OFFSET, GAZE_CENTER_YAW + GAZE_YAW_OFFSET)
GAZE_PITCH_LIMITS = (GAZE_CENTER_PITCH - GAZE_PITCH_OFFSET, GAZE_CENTER_PITCH + GAZE_PITCH_OFFSET)
GAZE_COORDINATE_FRAME = "tonypi_body"
CAMERA_COORDINATE_FRAME = "camera_image"
GAZE_POSES = {
    "center": {"pitch": 1500, "yaw": 1530},
    "left": {"pitch": 1500, "yaw": 1650},
    "right": {"pitch": 1500, "yaw": 1410},
    "up": {"pitch": 1600, "yaw": 1530},
    "down": {"pitch": 1400, "yaw": 1530},
}
BODY_FINAL_POSES = {
    "soft_hug": "return_idle",
    "shy_wave": "right_arm_idle",
    "listen_idle": "wings_open_hold",
    "wings_open": "wings_open_hold",
    "return_idle": "return_idle",
    "startup_recover": "full_idle",
    "happy_wiggle": "return_idle",
    "hands_ready": "hands_ready_hold",
    "want_attention": "right_arm_idle",
    "quiet_acknowledge_low": "return_idle",
    "quiet_acknowledge_medium": "return_idle",
    "quiet_acknowledge_high": "return_idle",
    "happy_greeting_low": "return_idle",
    "happy_greeting_medium": "return_idle",
    "happy_greeting_high": "return_idle",
}
MOTION_STATE_LOCK = threading.Lock()
CURRENT_GAZE_POSE = {
    "coordinate_frame": GAZE_COORDINATE_FRAME,
    "name": "unknown_after_process_start",
    "pitch": None,
    "yaw": None,
}
CURRENT_BODY_POSE = {"coordinate_frame": GAZE_COORDINATE_FRAME, "name": "unknown"}

def _gaze_pose_name(pitch, yaw):
    for name, pose in GAZE_POSES.items():
        if int(pose["pitch"]) == int(pitch) and int(pose["yaw"]) == int(yaw):
            return name
    return "custom"

def _set_body_pose(name):
    global CURRENT_BODY_POSE
    with MOTION_STATE_LOCK:
        CURRENT_BODY_POSE = {
            "coordinate_frame": GAZE_COORDINATE_FRAME,
            "name": str(name or "unknown"),
        }

def _final_pose_snapshot(resource_name):
    with MOTION_STATE_LOCK:
        if resource_name == "gaze":
            return {"gaze": dict(CURRENT_GAZE_POSE)}
        if resource_name == "camera":
            return {
                "body": dict(CURRENT_BODY_POSE),
                "gaze": dict(CURRENT_GAZE_POSE),
            }
        return {"body": dict(CURRENT_BODY_POSE)}

def _all_final_pose_snapshot():
    with MOTION_STATE_LOCK:
        return {
            "body": dict(CURRENT_BODY_POSE),
            "gaze": dict(CURRENT_GAZE_POSE),
        }

def _interruptible_sleep(duration, allow_during_stop=False):
    duration = max(0.0, float(duration))
    if allow_during_stop:
        time.sleep(duration)
        return
    if EMERGENCY_STOP_EVENT.wait(duration):
        raise MotionStopped("stopped_by_emergency_command")

def _ensure_motion_allowed(allow_during_stop=False):
    if EMERGENCY_STOP_EVENT.is_set() and not allow_during_stop:
        raise MotionStopped("stopped_by_emergency_command")

def _pulse(value):
    return max(100, min(900, int(value)))

def _expression_intensity(action_name, parameters=None):
    parameters = parameters or {}
    if not isinstance(parameters, dict):
        raise ValueError("parameters_invalid")
    if action_name not in PARAMETRIC_EXPRESSION_ACTIONS:
        if parameters:
            raise ValueError("parameters_invalid")
        return 1.0
    if set(parameters) - {"intensity"}:
        raise ValueError("parameters_invalid")
    value = parameters.get("intensity", 1.0)
    return validate_expression_intensity(value)

def _move_bus(duration, positions, allow_during_stop=False, wait_duration=None):
    _ensure_motion_allowed(allow_during_stop)
    safe_positions = [[int(sid), _pulse(pos)] for sid, pos in positions]
    AGC.board.bus_servo_set_position(float(duration), safe_positions)
    if wait_duration is None:
        wait_duration = float(duration) + 0.05
    _interruptible_sleep(float(wait_duration), allow_during_stop)

def _move_atom(duration, atom_name):
    _move_bus(duration, atom_positions(atom_name))

def _execute_compiled_body_motion(profile_name, compiled):
    for step in compiled["steps"]:
        if "wait_only" in step:
            _interruptible_sleep(float(step["wait_only"]))
            continue
        if "wait_duration" in step:
            _move_bus(
                step["duration"],
                step["positions"],
                wait_duration=step["wait_duration"],
            )
        else:
            _move_bus(step["duration"], step["positions"])
    execution_mode = compiled.get("execution_mode", "deterministic_steps")
    if execution_mode == "continuous_trajectory":
        motion_profile = f"continuous_{profile_name}_v2"
    elif execution_mode == "hardware_interpolated_segments":
        motion_profile = f"hardware_interpolated_{profile_name}_v2"
    else:
        motion_profile = f"deterministic_{profile_name}_v1"
    result = {
        "motion_contract_version": compiled.get(
            "motion_contract_version",
            "tonypi-motion-catalog/v1",
        ),
        "motion_profile": motion_profile,
        "step_count": len(compiled["steps"]),
        "sequence_atoms": compiled.get(
            "primitive_sequence",
            [step["atom"] for step in compiled["steps"]],
        ),
        "expected_final_pose": compiled["expected_final_pose"],
        "return_policy": compiled["return_policy"],
    }
    if "applied_parameters" in compiled:
        result["applied_parameters"] = compiled["applied_parameters"]
    if "applied_genome" in compiled:
        result["applied_genome"] = compiled["applied_genome"]
    if "acceptance_level" in compiled:
        result["acceptance_level"] = compiled["acceptance_level"]
    if "sway_steps" in compiled:
        result["sway_steps"] = compiled["sway_steps"]
    if execution_mode == "continuous_trajectory":
        result.update({
            "execution_mode": compiled["execution_mode"],
            "primitive_sequence": compiled["primitive_sequence"],
            "trajectory_frame_count": compiled["trajectory_frame_count"],
            "trajectory_duration": compiled["trajectory_duration"],
            "frame_interval": compiled["frame_interval"],
            "command_horizon": compiled["command_horizon"],
            "max_frame_delta": compiled["max_frame_delta"],
            "continuous_blending": compiled["continuous_blending"],
        })
    elif execution_mode == "hardware_interpolated_segments":
        result.update({
            "execution_mode": execution_mode,
            "primitive_sequence": compiled["primitive_sequence"],
            "hardware_command_count": compiled["hardware_command_count"],
            "segment_count": compiled["segment_count"],
            "total_duration": compiled["total_duration"],
            "max_frame_delta": compiled["max_frame_delta"],
            "hardware_interpolation": True,
        })
        for field in (
            "source_template",
            "source_template_frame_count",
            "template_frame_count",
            "template_duration",
            "amplitude_scale",
            "clearance_scale",
            "right_clearance_scale",
            "left_clearance_scale",
            "recovery_waypoint_count",
            "recovery_waypoint",
            "recovery_waypoint_duration",
            "collision_clearance_policy",
            "timing_scale",
            "preserves_frame_order",
            "preserves_frame_timing",
            "preserves_exact_source_timing",
            "preserves_relative_frame_timing",
            "preserves_cycle_boundary",
        ):
            if field in compiled:
                result[field] = compiled[field]
    return result

def _run_compiled_body_sequence(action_name, intensity=1.0):
    compiled = compile_body_sequence(action_name, intensity=intensity)
    return _execute_compiled_body_motion(action_name, compiled)

def _run_physical_acceptance_action(action_name):
    phrase_name, level = PHYSICAL_ACCEPTANCE_ACTIONS[action_name]
    compiled = compile_motion_phrase_level(phrase_name, level)
    return _execute_compiled_body_motion(action_name, compiled)

def _move_gaze(duration, pitch, yaw, allow_during_stop=False):
    global CURRENT_GAZE_POSE
    _ensure_motion_allowed(allow_during_stop)
    positions = [[1, int(pitch)], [2, int(yaw)]]
    AGC.board.pwm_servo_set_position(float(duration), positions)
    try:
        _interruptible_sleep(float(duration) + 0.05, allow_during_stop)
    finally:
        with MOTION_STATE_LOCK:
            CURRENT_GAZE_POSE = {
                "coordinate_frame": GAZE_COORDINATE_FRAME,
                "name": _gaze_pose_name(pitch, yaw),
                "pitch": int(pitch),
                "yaw": int(yaw),
            }

def _run_glance(label, pitch, yaw, intensity=1.0):
    target_pitch = round(GAZE_CENTER_PITCH + (int(pitch) - GAZE_CENTER_PITCH) * intensity)
    target_yaw = round(GAZE_CENTER_YAW + (int(yaw) - GAZE_CENTER_YAW) * intensity)
    outward_duration = 0.45 + (0.10 * intensity)
    hold_duration = 0.30 + (0.25 * intensity)
    try:
        _move_gaze(outward_duration, target_pitch, target_yaw)
        print(
            f"[gaze] glance {label} pitch={target_pitch} yaw={target_yaw} "
            f"intensity={intensity:.2f}",
            flush=True,
        )
        _interruptible_sleep(hold_duration)
    finally:
        _move_gaze(0.65, GAZE_CENTER_PITCH, GAZE_CENTER_YAW, allow_during_stop=True)
        print(f"[gaze] glance {label} returned-center", flush=True)
    return {
        "applied_parameters": {"intensity": round(intensity, 3)},
        "motion_profile": "bounded_gaze_glance_v1",
        "target_pitch": target_pitch,
        "target_yaw": target_yaw,
    }

def _seek_move_pose(pose_name, allow_during_stop=False):
    poses = {
        "center": (0.80, GAZE_CENTER_PITCH, GAZE_CENTER_YAW),
        "left": (0.90, GAZE_CENTER_PITCH, GAZE_CENTER_YAW + GAZE_YAW_OFFSET),
        "right": (0.90, GAZE_CENTER_PITCH, GAZE_CENTER_YAW - GAZE_YAW_OFFSET),
    }
    if pose_name not in poses:
        raise ValueError(f"unsupported seek pose: {pose_name}")
    duration, pitch, yaw = poses[pose_name]
    _move_gaze(duration, pitch, yaw, allow_during_stop=allow_during_stop)
    print(f"[seek] gaze {pose_name} pitch={pitch} yaw={yaw}", flush=True)

def _track_move_absolute(pitch, yaw, duration, allow_during_stop=False):
    safe_pitch = max(GAZE_PITCH_LIMITS[0], min(GAZE_PITCH_LIMITS[1], int(pitch)))
    safe_yaw = max(GAZE_YAW_LIMITS[0], min(GAZE_YAW_LIMITS[1], int(yaw)))
    _move_gaze(float(duration), safe_pitch, safe_yaw, allow_during_stop=allow_during_stop)
    print(f"[track] gaze pitch={safe_pitch} yaw={safe_yaw} duration={float(duration):.2f}", flush=True)

def _run_startup_auto_recovery_once():
    try:
        details = _startup_recovery_preflight()
    except StartupRecoveryRejected as e:
        print(f"[startup] recovery skipped reason={e.error_code} details={e.details}", flush=True)
        return {"status": "skipped", "error_code": e.error_code, "details": e.details}
    except MotionStopped:
        print("[startup] recovery skipped reason=emergency_stop_active", flush=True)
        return {"status": "skipped", "error_code": "emergency_stop_active"}

    if not BODY_MOTION_LOCK.acquire(blocking=False):
        return {"status": "skipped", "error_code": "resource_busy"}
    if not GAZE_MOTION_LOCK.acquire(blocking=False):
        BODY_MOTION_LOCK.release()
        return {"status": "skipped", "error_code": "resource_busy"}

    _set_active_motion("body", "startup_auto_recover", None, "startup")
    _set_active_motion("gaze", "startup_auto_recover", None, "startup")
    try:
        _move_gaze(0.80, GAZE_CENTER_PITCH, GAZE_CENTER_YAW)
        if STARTUP_AUTO_FULL_BODY_RECOVERY:
            _move_atom(1.40, "full_idle")
            _move_atom(0.40, "full_idle")
            _set_body_pose("full_idle")
            print(
                "[startup] head centered and full body restored to calibrated idle pose",
                flush=True,
            )
            return {
                "status": "recovered",
                "head_centered": True,
                "full_body_recovered": True,
                "servo_count": len(FULL_IDLE_POSE),
                **details,
            }
        print("[startup] head centered; automatic full body recovery disabled", flush=True)
        return {
            "status": "ready",
            "head_centered": True,
            "full_body_recovered": False,
            **details,
        }
    except MotionStopped:
        print("[startup] recovery stopped by emergency command", flush=True)
        return {"status": "stopped", "error_code": "stopped_by_emergency_command"}
    finally:
        _clear_active_motion("body")
        _clear_active_motion("gaze")
        GAZE_MOTION_LOCK.release()
        BODY_MOTION_LOCK.release()

def _startup_recovery_worker():
    time.sleep(STARTUP_RECOVERY_GRACE_SECONDS)
    _run_startup_auto_recovery_once()

def _run_code_action(action_name, preflight=None, parameters=None, command_id=None):
    intensity = _expression_intensity(action_name, parameters)
    if action_name == "soft_hug":
        _move_bus(0.45, [[16, 620], [15, 230], [14, 380], [8, 430], [7, 800], [6, 720]])
        _move_bus(0.65, [[16, 660], [15, 180], [14, 320], [8, 380], [7, 840], [6, 820]])
        _interruptible_sleep(0.8)
        _move_bus(0.80, ARM_IDLE_POSE)
        _move_bus(0.40, ARM_IDLE_POSE)
    elif action_name == "shy_wave":
        _move_bus(0.35, [[8, 700], [7, 780], [6, 570]])
        for pos in (420, 500, 420, 500):
            _move_bus(0.18, [[6, pos]])
        _move_bus(0.80, RIGHT_ARM_IDLE_POSE)
        _move_bus(0.40, RIGHT_ARM_IDLE_POSE)
    elif action_name in ("listen_idle", "wings_open"):
        return _run_compiled_body_sequence(action_name)
    elif action_name == "return_idle":
        return _run_compiled_body_sequence("return_idle")
    elif action_name == "startup_recover":
        details = dict(preflight or _startup_recovery_preflight(allow_current_body=True))
        if not GAZE_MOTION_LOCK.acquire(blocking=False):
            raise StartupRecoveryRejected("startup_gaze_busy")
        try:
            sequence_result = _run_compiled_body_sequence("startup_recover")
        finally:
            GAZE_MOTION_LOCK.release()
        return {
            "upright": True,
            "stable": True,
            "manual_clearance_confirmed": True,
            "base_pose_source": "wave!!.d6a:first_last",
            "servo_count": len(FULL_IDLE_POSE),
            **sequence_result,
            **details,
        }
    elif action_name == "hands_ready":
        return _run_compiled_body_sequence("hands_ready", intensity=intensity)
    elif action_name == "happy_wiggle":
        return _run_compiled_body_sequence("happy_wiggle", intensity=intensity)
    elif action_name in PHYSICAL_ACCEPTANCE_ACTIONS:
        return _run_physical_acceptance_action(action_name)
    elif action_name == "want_attention":
        for _ in range(2):
            _move_bus(0.22, [[8, 610], [7, 650], [6, 560]])
            _move_bus(0.22, [[8, 530], [7, 560], [6, 500]])
        _move_bus(0.80, RIGHT_ARM_IDLE_POSE)
        _move_bus(0.40, RIGHT_ARM_IDLE_POSE)
    elif action_name == "read_arm_positions":
        for sid in [6, 7, 8, 13, 14, 15, 16]:
            try:
                pos = AGC.board.bus_servo_read_position(sid)
                print(f"[pos] ID{sid}: {pos}", flush=True)
            except Exception as e:
                print(f"[pos] ID{sid}: error - {e}", flush=True)
    elif action_name == "gaze_center":
        _move_gaze(0.80, GAZE_CENTER_PITCH, GAZE_CENTER_YAW)
        print(f"[gaze] centered pitch={GAZE_CENTER_PITCH} yaw={GAZE_CENTER_YAW}", flush=True)
    elif action_name == "gaze_left":
        _move_gaze(0.90, GAZE_CENTER_PITCH, GAZE_CENTER_YAW + GAZE_YAW_OFFSET)
        print(f"[gaze] left pitch={GAZE_CENTER_PITCH} yaw={GAZE_CENTER_YAW + GAZE_YAW_OFFSET}", flush=True)
    elif action_name == "gaze_right":
        _move_gaze(0.90, GAZE_CENTER_PITCH, GAZE_CENTER_YAW - GAZE_YAW_OFFSET)
        print(f"[gaze] right pitch={GAZE_CENTER_PITCH} yaw={GAZE_CENTER_YAW - GAZE_YAW_OFFSET}", flush=True)
    elif action_name == "gaze_up":
        _move_gaze(0.90, GAZE_CENTER_PITCH + GAZE_PITCH_OFFSET, GAZE_CENTER_YAW)
        print(f"[gaze] up pitch={GAZE_CENTER_PITCH + GAZE_PITCH_OFFSET} yaw={GAZE_CENTER_YAW}", flush=True)
    elif action_name == "gaze_down":
        _move_gaze(0.90, GAZE_CENTER_PITCH - GAZE_PITCH_OFFSET, GAZE_CENTER_YAW)
        print(f"[gaze] down pitch={GAZE_CENTER_PITCH - GAZE_PITCH_OFFSET} yaw={GAZE_CENTER_YAW}", flush=True)
    elif action_name == "gaze_glance_left":
        return _run_glance(
            "left",
            GAZE_CENTER_PITCH,
            GAZE_CENTER_YAW + GAZE_GLANCE_YAW_OFFSET,
            intensity,
        )
    elif action_name == "gaze_glance_right":
        return _run_glance(
            "right",
            GAZE_CENTER_PITCH,
            GAZE_CENTER_YAW - GAZE_GLANCE_YAW_OFFSET,
            intensity,
        )
    elif action_name == "gaze_glance_up":
        return _run_glance(
            "up",
            GAZE_CENTER_PITCH + GAZE_GLANCE_PITCH_OFFSET,
            GAZE_CENTER_YAW,
            intensity,
        )
    elif action_name == "gaze_glance_down":
        return _run_glance(
            "down",
            GAZE_CENTER_PITCH - GAZE_GLANCE_PITCH_OFFSET,
            GAZE_CENTER_YAW,
            intensity,
        )
    elif action_name == "gaze_safe_cycle":
        poses = [
            ("center", GAZE_CENTER_PITCH, GAZE_CENTER_YAW),
            ("left", GAZE_CENTER_PITCH, GAZE_CENTER_YAW + GAZE_YAW_OFFSET),
            ("center", GAZE_CENTER_PITCH, GAZE_CENTER_YAW),
            ("right", GAZE_CENTER_PITCH, GAZE_CENTER_YAW - GAZE_YAW_OFFSET),
            ("center", GAZE_CENTER_PITCH, GAZE_CENTER_YAW),
            ("up", GAZE_CENTER_PITCH + GAZE_PITCH_OFFSET, GAZE_CENTER_YAW),
            ("center", GAZE_CENTER_PITCH, GAZE_CENTER_YAW),
            ("down", GAZE_CENTER_PITCH - GAZE_PITCH_OFFSET, GAZE_CENTER_YAW),
        ]
        try:
            for label, pitch, yaw in poses:
                _move_gaze(0.80 if label == "center" else 0.90, pitch, yaw)
                print(f"[gaze] cycle {label} pitch={pitch} yaw={yaw}", flush=True)
                _interruptible_sleep(0.35)
        finally:
            _move_gaze(0.80, GAZE_CENTER_PITCH, GAZE_CENTER_YAW, allow_during_stop=True)
            print(f"[gaze] cycle final-center pitch={GAZE_CENTER_PITCH} yaw={GAZE_CENTER_YAW}", flush=True)
    elif action_name == "seek_user":
        result = run_local_seek(
            _seek_move_pose,
            return_center=lambda: _seek_move_pose("center", allow_during_stop=True),
            should_stop=EMERGENCY_STOP_EVENT.is_set,
        )
        print(
            f"[seek] completed face_result={result.get('face_result')} "
            f"zone={result.get('position_zone')} alignment={result.get('alignment')} "
            f"limit_reached={result.get('limit_reached')}",
            flush=True,
        )
        return result
    elif action_name == "track_face_brief":
        result = run_local_track(
            _track_move_absolute,
            GAZE_CENTER_PITCH,
            GAZE_CENTER_YAW,
            GAZE_PITCH_LIMITS,
            GAZE_YAW_LIMITS,
            duration_seconds=8.0,
            return_center=lambda: _track_move_absolute(
                GAZE_CENTER_PITCH,
                GAZE_CENTER_YAW,
                0.65,
                allow_during_stop=True,
            ),
            should_stop=EMERGENCY_STOP_EVENT.is_set,
        )
        print(
            f"[track] completed face_result={result.get('face_result')} "
            f"alignment={result.get('alignment')} updates={result.get('track_updates')} "
            f"limit_reached={result.get('limit_reached')}",
            flush=True,
        )
        return result
    elif action_name == "observe_gesture_once":
        result = observe_gesture_once(
            duration_seconds=1.8,
            sample_interval=0.12,
            should_stop=EMERGENCY_STOP_EVENT.is_set,
        )
        print(
            f"[gesture] completed hand_result={result.get('hand_result')} "
            f"gesture={result.get('gesture')} confidence={result.get('confidence')}",
            flush=True,
        )
        return result
    elif action_name == "observe_user_once":
        result = observe_activity_once(
            lambda: capture_ephemeral_jpeg(
                resolution=(640, 480),
                max_width=640,
                jpeg_quality=75,
                timeout_seconds=2.5,
                should_stop=EMERGENCY_STOP_EVENT.is_set,
            ),
            lambda jpeg, metadata: _server_visual_observation_provider(
                jpeg,
                metadata,
                command_id=command_id,
            ),
        )
        print(
            f"[vision] completed person_present={result.get('person_present')} "
            f"activity={result.get('activity')} confidence={result.get('confidence')}",
            flush=True,
        )
        return result
    return None

def _motion_lock_for_code_action(action_name):
    if action_name.startswith("gaze_") or action_name in {"seek_user", "track_face_brief"}:
        return "gaze", GAZE_MOTION_LOCK
    if action_name in {"observe_gesture_once", "observe_user_once"}:
        return "camera", CAMERA_PERCEPTION_LOCK
    return "body", BODY_MOTION_LOCK

def _additional_motion_locks_for_code_action(action_name):
    if action_name in {"seek_user", "track_face_brief"}:
        return [CAMERA_PERCEPTION_LOCK]
    return []

def _implementation_for_code_action(action_name):
    return (
        "perception"
        if action_name in {"observe_gesture_once", "observe_user_once"}
        else "code"
    )

def _run_code_action_locked(
    action_name,
    resource_name,
    resource_locks,
    command_id=None,
    receipt_action=None,
    parameters=None,
):
    reported_action = receipt_action or action_name
    implementation = _implementation_for_code_action(action_name)
    started = time.monotonic()
    terminal_status = "failed"
    terminal_extra = {
        "resource": resource_name,
        "implementation": implementation,
    }
    terminal_log = None
    _set_active_motion(resource_name, reported_action, command_id, implementation)
    try:
        preflight = None
        if action_name == "startup_recover":
            preflight = _startup_recovery_preflight(allow_current_body=True)
        _enqueue_robot_receipt(command_id, "started", reported_action, resource=resource_name, implementation=implementation)
        print(f"[motion] started action={action_name} resource={resource_name} implementation={implementation}", flush=True)
        _ensure_motion_allowed()
        action_result = _run_code_action(
            action_name,
            preflight=preflight,
            parameters=parameters,
            command_id=command_id,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if resource_name == "body" and action_name in BODY_FINAL_POSES:
            _set_body_pose(BODY_FINAL_POSES[action_name])
        result_fields = {}
        if isinstance(action_result, dict):
            result_fields = {
                "result": action_result,
                "face_result": action_result.get("face_result"),
                "position_zone": action_result.get("position_zone"),
                "confidence": action_result.get("confidence"),
                "alignment": action_result.get("alignment"),
                "limit_reached": action_result.get("limit_reached"),
                "search_exhausted": action_result.get("search_exhausted"),
                "hand_result": action_result.get("hand_result"),
                "gesture": action_result.get("gesture"),
                "motion_requested": action_result.get("motion_requested"),
                "image_saved": action_result.get("image_saved"),
                "raw_landmarks_saved": action_result.get("raw_landmarks_saved"),
            }
            if action_result.get("schema_version") == "yushi-visual-observation/v2":
                result_fields["visual_observation"] = action_result
        terminal_status = "completed"
        terminal_extra.update({
            "duration_ms": elapsed_ms,
            "final_pose": _final_pose_snapshot(resource_name),
            **result_fields,
        })
        terminal_log = (
            f"[motion] completed action={action_name} resource={resource_name} "
            f"duration_ms={elapsed_ms}"
        )
    except StartupRecoveryRejected as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        terminal_status = "skipped"
        terminal_extra.update({
            "duration_ms": elapsed_ms,
            "error_code": e.error_code,
            "result": e.details or None,
            "final_pose": _final_pose_snapshot(resource_name),
        })
        terminal_log = (
            f"[startup] body recovery skipped error_code={e.error_code} "
            f"details={e.details}"
        )
    except (MotionStopped, SeekStopped, PerceptionStopped):
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if resource_name == "body":
            _set_body_pose("stopped_hold_unverified")
        terminal_status = "stopped"
        terminal_extra.update({
            "duration_ms": elapsed_ms,
            "error_code": "stopped_by_emergency_command",
            "final_pose": _final_pose_snapshot(resource_name),
        })
        terminal_log = (
            f"[motion] stopped action={action_name} resource={resource_name} "
            f"duration_ms={elapsed_ms}"
        )
    except (FaceCameraError, PerceptionCameraError) as e:
        terminal_extra.update({
            "error": str(e),
            "error_code": str(e),
            "final_pose": _final_pose_snapshot(resource_name),
        })
        terminal_log = f"[motion] failed action={action_name} resource={resource_name} error={e}"
    except Exception as e:
        terminal_extra.update({
            "error": str(e),
            "error_code": "execution_error",
            "final_pose": _final_pose_snapshot(resource_name),
        })
        terminal_log = f"[motion] failed action={action_name} resource={resource_name} error={e}"
    finally:
        _clear_active_motion(resource_name)
        for resource_lock in reversed(resource_locks):
            resource_lock.release()
    _enqueue_robot_receipt(command_id, terminal_status, reported_action, **terminal_extra)
    if terminal_log:
        print(terminal_log, flush=True)

def code_action(action_name, command_id=None, receipt_action=None, parameters=None):
    if action_name not in CODE_ACTIONS:
        return False
    reported_action = receipt_action or action_name
    resource_name, resource_lock = _motion_lock_for_code_action(action_name)
    implementation = _implementation_for_code_action(action_name)
    resource_locks = [resource_lock, *_additional_motion_locks_for_code_action(action_name)]
    if EMERGENCY_STOP_EVENT.is_set():
        _enqueue_robot_receipt(
            command_id,
            "skipped",
            reported_action,
            resource=resource_name,
            implementation=implementation,
            error_code="emergency_stop_active",
            final_pose=_final_pose_snapshot(resource_name),
        )
        return False
    interlock_reason = _motion_interlock_reason()
    if interlock_reason:
        _enqueue_robot_receipt(
            command_id,
            "skipped",
            reported_action,
            resource=resource_name,
            implementation=implementation,
            error=interlock_reason,
            final_pose=_final_pose_snapshot(resource_name),
        )
        print(
            f"[motion] skipped action={action_name} resource={resource_name} reason={interlock_reason}",
            flush=True,
        )
        return False
    acquired_locks = []
    for candidate_lock in resource_locks:
        if candidate_lock.acquire(blocking=False):
            acquired_locks.append(candidate_lock)
            continue
        for acquired_lock in reversed(acquired_locks):
            acquired_lock.release()
        _enqueue_robot_receipt(
            command_id,
            "skipped",
            reported_action,
            resource=resource_name,
            implementation=implementation,
            error="resource_busy",
            final_pose=_final_pose_snapshot(resource_name),
        )
        print(f"[motion] skipped action={action_name} resource={resource_name} reason=busy", flush=True)
        return False
    try:
        threading.Thread(
            target=_run_code_action_locked,
            args=(
                action_name,
                resource_name,
                acquired_locks,
                command_id,
                reported_action,
                dict(parameters or {}),
            ),
            daemon=True,
        ).start()
        print(f"[yushi] code action: {action_name}", flush=True)
        return True
    except Exception as e:
        for acquired_lock in reversed(acquired_locks):
            acquired_lock.release()
        print(f"[yushi] code action failed: {e}", flush=True)
        return False

def say(text):
    text = (text or "").strip()
    if not text:
        return False
    print(f"[yushi] 说: {text}")
    if not ELEVENLABS_API_KEY:
        print("[yushi] TTS跳过: 未配置 ELEVENLABS_API_KEY")
        return False
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.6, "similarity_boost": 0.8, "speed": 0.85},
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30)
        if res.status_code != 200:
            print(f"[yushi] TTS失败: HTTP {res.status_code} {res.text[:120]}")
            return False
        with open(TTS_FILE, "wb") as f:
            f.write(res.content)
        played = subprocess.run(
            ["mpg123", "-q", "-a", TTS_AUDIO_DEVICE, TTS_FILE],
            timeout=60,
            check=False,
        )
        return played.returncode == 0
    except Exception as e:
        print(f"[yushi] TTS失败: {e}")
        return False

def on_keepalive_message(msg):
    content = (msg.get("content") or msg.get("draft") or "").strip()
    if not content:
        return False
    print(f"[yushi] keepalive [{msg.get('source', '?')}]: {content}")
    print("[performance] keepalive body expression is handled by the robot command queue", flush=True)
    return say(content) is True

def _request_emergency_stop():
    EMERGENCY_STOP_EVENT.set()
    active = _active_motion_snapshot()
    body = active.get("body") or {}
    stop_errors = []
    if body.get("implementation") == "d6a":
        for stop_name in ("stopAction", "stopActionGroup"):
            try:
                getattr(AGC, stop_name)()
            except Exception as e:
                stop_errors.append(f"{stop_name}:{e}")
    return active, stop_errors

def _motion_is_quiescent():
    return (
        not BODY_MOTION_LOCK.locked()
        and not GAZE_MOTION_LOCK.locked()
        and not CAMERA_PERCEPTION_LOCK.locked()
    )

def _wait_for_motion_quiescence(timeout_seconds=5.0):
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while not _motion_is_quiescent() and time.monotonic() < deadline:
        time.sleep(0.05)
    return _motion_is_quiescent()

def _clear_stop_when_quiescent():
    while not _motion_is_quiescent():
        time.sleep(0.1)
    EMERGENCY_STOP_EVENT.clear()
    print("[safety] emergency stop cleared after delayed quiescence", flush=True)

def _handle_stop_command(item, decision):
    command_id = str(item.get("command_id") or "").strip()
    warnings = decision.get("warnings") or []
    _remember_command_context(item)
    _enqueue_robot_receipt(command_id, "ack", "stop", registry_warnings=warnings or None)
    _enqueue_robot_receipt(command_id, "started", "stop", scope="all", torque_released=False)
    active, stop_errors = _request_emergency_stop()
    quiescent = _wait_for_motion_quiescence()
    interrupted = list(active.values())
    if quiescent:
        EMERGENCY_STOP_EVENT.clear()
        _enqueue_robot_receipt(
            command_id,
            "completed",
            "stop",
            scope="all",
            interrupted_actions=interrupted,
            stop_errors=stop_errors or None,
            torque_released=False,
            final_pose=_all_final_pose_snapshot(),
        )
        print(f"[safety] stop completed interrupted={len(interrupted)}", flush=True)
        return
    threading.Thread(target=_clear_stop_when_quiescent, daemon=True).start()
    _enqueue_robot_receipt(
        command_id,
        "failed",
        "stop",
        scope="all",
        interrupted_actions=interrupted,
        stop_errors=stop_errors or None,
        torque_released=False,
        error_code="stop_timeout",
        final_pose=_all_final_pose_snapshot(),
    )
    print(f"[safety] stop timeout active={list(active)}", flush=True)

def on_robot_action(item):
    command_type = str(item.get("command_type") or "action").strip()
    gate = REGISTRY_GATE or _init_registry_gate()
    decision = gate.validate_command(item)
    command_id = str(item.get("command_id") or "").strip()
    if not _claim_command(command_id, item):
        replayed = _replay_last_command_receipt(command_id)
        print(
            f"[idempotency] duplicate command_id={command_id} replayed={str(replayed).lower()}",
            flush=True,
        )
        return
    if command_type == "stop":
        _handle_stop_command(item, decision)
        return

    requested_action = str(item.get("action") or "").strip()
    canonical_action = decision.get("canonical_action") or requested_action
    execution_action = _resolve_action_implementation(canonical_action)
    kw = item.get("keyword") or item.get("source") or "?"
    _remember_command_context(item)
    warnings = decision.get("warnings") or []
    if warnings:
        print(
            f"[registry] command_id={command_id or 'legacy'} mode={decision['enforcement']} "
            f"warnings={','.join(warnings)} requested={requested_action} canonical={canonical_action}",
            flush=True,
        )
    _enqueue_robot_receipt(
        command_id,
        "ack",
        canonical_action,
        registry_warnings=warnings or None,
    )
    if not decision["allowed"]:
        error_code = decision.get("error_code") or "registry_rejected"
        _enqueue_robot_receipt(
            command_id,
            "skipped",
            canonical_action,
            error_code=error_code,
            error_detail="rejected_by_device_registry_gate",
        )
        print(
            f"[registry] rejected command_id={command_id or 'legacy'} action={requested_action} "
            f"error_code={error_code}",
            flush=True,
        )
        return
    battery_error, battery = _battery_safety_error(canonical_action)
    if battery_error:
        _enqueue_robot_receipt(
            command_id,
            "skipped",
            canonical_action,
            error_code=battery_error,
            battery_mv=battery.get("battery_mv"),
            battery_age_ms=battery.get("battery_age_ms"),
            final_pose=_all_final_pose_snapshot(),
        )
        print(
            f"[battery] rejected action={canonical_action} error_code={battery_error} "
            f"battery_mv={battery.get('battery_mv')}",
            flush=True,
        )
        return
    if battery["battery_stale"]:
        print(f"[battery] monitor-only unknown/stale action={canonical_action}", flush=True)
    cooldown_remaining_ms = _cooldown_remaining_ms(canonical_action)
    if cooldown_remaining_ms > 0:
        _enqueue_robot_receipt(
            command_id,
            "skipped",
            canonical_action,
            error_code="cooldown_active",
            retry_after_ms=cooldown_remaining_ms,
            final_pose=_all_final_pose_snapshot(),
        )
        print(
            f"[safety] cooldown action={canonical_action} retry_after_ms={cooldown_remaining_ms}",
            flush=True,
        )
        return
    autonomy_error, autonomy_preflight = _autonomous_body_preflight(
        canonical_action,
        item,
        battery,
    )
    if autonomy_error:
        terminal_status = (
            "stopped"
            if autonomy_error == "stopped_by_emergency_command"
            else "skipped"
        )
        _enqueue_robot_receipt(
            command_id,
            terminal_status,
            canonical_action,
            error_code=autonomy_error,
            error_detail="rejected_by_device_autonomy_preflight",
            safety=autonomy_preflight,
            final_pose=_all_final_pose_snapshot(),
        )
        print(
            f"[safety] autonomous preflight rejected action={canonical_action} "
            f"error_code={autonomy_error}",
            flush=True,
        )
        return
    if autonomy_preflight:
        print(
            f"[safety] autonomous body preflight passed action={canonical_action} "
            f"battery_mv={autonomy_preflight.get('battery_mv')} "
            f"battery_mode={autonomy_preflight.get('battery_mode')}",
            flush=True,
        )
    print(
        f"[yushi] 聊天触发 [{kw}] → {canonical_action} "
        f"implementation={execution_action} command_id={command_id or 'legacy'}"
    )
    if execution_action in CODE_ACTIONS:
        launched = code_action(
            execution_action,
            command_id=command_id,
            receipt_action=canonical_action,
            parameters=item.get("parameters") or {},
        )
    else:
        launched = do_action(execution_action, command_id=command_id, receipt_action=canonical_action)
    if launched:
        _mark_action_started(canonical_action)

def main():
    _acquire_single_instance_lock()
    print(f"[yushi] 喻拾客户端 v2 启动 {datetime.now()}")
    print(f"[yushi] 服务器: {MEMORY_SERVER}  轮询间隔: {POLL_INTERVAL}s")
    print(
        f"[poll] robot={ROBOT_POLL_INTERVAL}s keepalive={KEEPALIVE_POLL_INTERVAL}s "
        f"battery={BATTERY_POLL_INTERVAL}s temperature={TEMPERATURE_POLL_INTERVAL}s",
        flush=True,
    )
    _init_registry_gate()
    _enable_board_reception()
    _ensure_command_persistence_loaded()
    try:
        _ensure_keepalive_delivery_state_loaded()
    except Exception as error:
        # Body commands remain independent; keepalive polling itself will stay
        # fail-closed until the corrupt local delivery state is repaired.
        print(f"[keepalive] durable state unavailable: {error}", flush=True)
    recovered_receipts = _recover_command_delivery_after_restart()
    if recovered_receipts:
        print(
            f"[receipt] recovered interrupted_commands={recovered_receipts}",
            flush=True,
        )
    threading.Thread(target=_robot_receipt_worker, daemon=True).start()
    threading.Thread(target=_battery_monitor, daemon=True).start()
    threading.Thread(target=_temperature_monitor, daemon=True).start()
    threading.Thread(target=_motion_watchdog, daemon=True).start()
    threading.Thread(target=_robot_command_loop, daemon=True).start()
    threading.Thread(target=_startup_recovery_worker, daemon=True).start()
    while True:
        try:
            _flush_keepalive_ack_once()
        except Exception as error:
            print(f"[keepalive-ack] durable state unavailable: {error}", flush=True)
        for msg in fetch_keepalive_pending():
            try:
                process_keepalive_delivery(msg)
            except Exception as error:
                print(f"[keepalive] delivery rejected: {error}", flush=True)
        time.sleep(KEEPALIVE_POLL_INTERVAL)

if __name__ == "__main__":
    main()
