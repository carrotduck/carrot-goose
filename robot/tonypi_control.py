#!/usr/bin/env python3

import json
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path


OWNER_FILE = Path("/home/pi/yushi/control_owner")
SERIAL_LOCK_FILE = Path("/tmp/tonypi-controller-serial.lock")
REGISTRY_FILE = Path("/home/pi/yushi/protocol/tonypi_action_registry.json")
REGISTRY_MODE_FILE = Path("/home/pi/yushi/registry_enforcement")
VALID_MODES = {"yushi", "studio", "original", "joystick", "multi_control"}
MANAGED_SERVICES = (
    "yushi-client.service",
    "joystick.service",
    "multi_control_client.service",
    "multi_control_server.service",
    "tonypi.service",
)
MODE_SERVICES = {
    "yushi": ("yushi-client.service",),
    "studio": (),
    "original": ("tonypi.service",),
    "joystick": ("joystick.service",),
    "multi_control": ("multi_control_client.service", "multi_control_server.service"),
}
PROCESS_MARKERS = (
    ("studio", "/home/pi/TonyPi_PC_Software/main.py"),
    ("original", "/home/pi/TonyPi/TonyPi.py"),
    ("joystick", "/home/pi/TonyPi/Joystick.py"),
    ("multi_control", "/home/pi/TonyPi/Extend/multi_control/"),
)


def read_owner():
    try:
        return OWNER_FILE.read_text(encoding="utf-8").strip().lower() or "locked"
    except OSError:
        return "locked"


def registry_status():
    try:
        raw = REGISTRY_FILE.read_bytes()
        registry = json.loads(raw)
        version = str(registry.get("registry_version") or "").strip() or None
        schema_version = str(registry.get("schema_version") or "").strip() or None
        if schema_version != "tonypi-action-registry/v1" or not version:
            raise ValueError("invalid registry metadata")
        digest = hashlib.sha256(raw).hexdigest()
        error = None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        version = None
        schema_version = None
        digest = None
        error = str(exc)

    try:
        enforcement = REGISTRY_MODE_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        enforcement = "monitor"
    if enforcement not in {"monitor", "enforce"}:
        enforcement = "monitor"

    return {
        "registry_schema_version": schema_version,
        "registry_version": version,
        "registry_sha256": digest,
        "registry_enforcement": enforcement,
        "registry_error": error,
    }


def running_controllers():
    found = []
    own_pid = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == own_pid:
            continue
        try:
            raw = Path(f"/proc/{entry}/cmdline").read_bytes()
        except OSError:
            continue
        parts = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
        if not parts or "python" not in os.path.basename(parts[0]).lower():
            continue
        command = " ".join(parts)
        for role, marker in PROCESS_MARKERS:
            if marker in command:
                found.append({"pid": int(entry), "role": role, "command": command})
                break
    return sorted(found, key=lambda item: item["pid"])


def service_state(service):
    active = subprocess.run(
        ["systemctl", "is-active", service],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    enabled = subprocess.run(
        ["systemctl", "is-enabled", service],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    return {"active": active or "unknown", "enabled": enabled or "unknown"}


def write_owner(mode):
    OWNER_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = OWNER_FILE.with_suffix(".tmp")
    temporary.write_text(mode + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, OWNER_FILE)
    SERIAL_LOCK_FILE.touch(exist_ok=True)
    os.chmod(SERIAL_LOCK_FILE, 0o666)


def run_systemctl(*args):
    result = subprocess.run(["systemctl", *args], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"systemctl {' '.join(args)} failed: {message}")


def set_mode(mode):
    if os.geteuid() != 0:
        raise PermissionError("mode changes require sudo")
    if mode not in VALID_MODES:
        raise ValueError(f"unsupported mode: {mode}")

    allowed_roles = {mode}
    current = running_controllers()
    interactive_conflicts = [
        item for item in current
        if item["role"] in {"studio", "original"} and item["role"] not in allowed_roles
    ]
    if interactive_conflicts:
        details = ", ".join(f"{item['role']} pid={item['pid']}" for item in interactive_conflicts)
        raise RuntimeError(f"close the interactive controller first: {details}")

    target_services = set(MODE_SERVICES[mode])
    for service in MANAGED_SERVICES:
        if service not in target_services:
            run_systemctl("disable", "--now", service)

    time.sleep(0.5)
    remaining = [item for item in running_controllers() if item["role"] not in allowed_roles]
    if remaining:
        details = ", ".join(f"{item['role']} pid={item['pid']}" for item in remaining)
        raise RuntimeError(f"external controllers are still active: {details}")

    write_owner(mode)
    for service in MODE_SERVICES[mode]:
        run_systemctl("enable", "--now", service)

    print(json.dumps(status_payload(), ensure_ascii=False, indent=2))


def status_payload():
    payload = {
        "owner": read_owner(),
        "controllers": running_controllers(),
        "services": {service: service_state(service) for service in MANAGED_SERVICES},
    }
    payload.update(registry_status())
    return payload


def main():
    command = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "status"
    if command == "status":
        print(json.dumps(status_payload(), ensure_ascii=False, indent=2))
        return
    set_mode(command)


if __name__ == "__main__":
    main()
