#!/usr/bin/env python3

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path


SERVO_COUNT = 18
ARM_IDS = {6, 7, 8, 14, 15, 16}
LEG_IDS = {1, 2, 3, 4, 5, 9, 10, 11, 12, 13}
CALIBRATED_IDLE_POSE = (
    500, 395, 500, 593, 500, 535, 803, 690, 500,
    605, 500, 406, 500, 425, 200, 275, 500, 500,
)
IDLE_TOLERANCE = 8
HARD_PULSE_MIN = 0
HARD_PULSE_MAX = 1000
AUTONOMY_SOFT_PULSE_MIN = 100
AUTONOMY_SOFT_PULSE_MAX = 900
MAX_ATOM_SOURCE_DURATION_MS = 6000


def _parse_idle_pose(raw):
    if raw is None:
        return CALIBRATED_IDLE_POSE
    values = tuple(int(value.strip()) for value in raw.split(",") if value.strip())
    if len(values) != SERVO_COUNT:
        raise argparse.ArgumentTypeError(
            f"idle pose must contain exactly {SERVO_COUNT} comma-separated values"
        )
    return values


def _pose_is_near(pose, reference, tolerance):
    return len(pose) == len(reference) and all(
        abs(int(value) - int(expected)) <= tolerance
        for value, expected in zip(pose, reference)
    )


def _pose_error(pose, reference):
    if len(pose) != len(reference):
        return None
    return max(abs(int(value) - int(expected)) for value, expected in zip(pose, reference))


def _kinematic_proxies(poses, durations_ms, idle_pose):
    previous_pose = tuple(idle_pose)
    previous_velocity = None
    previous_acceleration = None
    max_delta = 0
    max_delta_servo_id = None
    max_speed = 0.0
    max_speed_servo_id = None
    max_acceleration = 0.0
    max_acceleration_servo_id = None
    max_jerk = 0.0
    max_jerk_servo_id = None

    for pose, duration_ms in zip(poses, durations_ms):
        duration_seconds = max(int(duration_ms), 1) / 1000.0
        velocities = []
        for offset, (before, after) in enumerate(zip(previous_pose, pose)):
            servo_id = offset + 1
            delta = abs(int(after) - int(before))
            speed = delta / duration_seconds
            velocities.append((int(after) - int(before)) / duration_seconds)
            if delta > max_delta:
                max_delta = delta
                max_delta_servo_id = servo_id
            if speed > max_speed:
                max_speed = speed
                max_speed_servo_id = servo_id

        accelerations = None
        if previous_velocity is not None:
            accelerations = []
            for offset, (velocity, before_velocity) in enumerate(
                zip(velocities, previous_velocity)
            ):
                servo_id = offset + 1
                acceleration = (velocity - before_velocity) / duration_seconds
                accelerations.append(acceleration)
                if abs(acceleration) > max_acceleration:
                    max_acceleration = abs(acceleration)
                    max_acceleration_servo_id = servo_id

        if accelerations is not None and previous_acceleration is not None:
            for offset, (acceleration, before_acceleration) in enumerate(
                zip(accelerations, previous_acceleration)
            ):
                servo_id = offset + 1
                jerk = abs(acceleration - before_acceleration) / duration_seconds
                if jerk > max_jerk:
                    max_jerk = jerk
                    max_jerk_servo_id = servo_id

        previous_pose = tuple(pose)
        previous_velocity = velocities
        if accelerations is not None:
            previous_acceleration = accelerations

    return {
        "includes_idle_to_first_frame": True,
        "max_frame_delta": max_delta,
        "max_frame_delta_servo_id": max_delta_servo_id,
        "max_speed_pulse_per_second": round(max_speed, 3),
        "max_speed_servo_id": max_speed_servo_id,
        "max_acceleration_pulse_per_second2": round(max_acceleration, 3),
        "max_acceleration_servo_id": max_acceleration_servo_id,
        "max_jerk_pulse_per_second3": round(max_jerk, 3),
        "max_jerk_servo_id": max_jerk_servo_id,
    }


def _recommendation(
    *,
    servo_count,
    active_ids,
    active_leg_ids,
    held_non_idle_leg_ids,
    legs_stay_at_idle,
    starts_at_idle,
    returns_to_idle,
    duration_ms,
    invalid_duration_count,
    invalid_pulse_count,
    soft_limit_servo_ids,
):
    reasons = []
    if servo_count != SERVO_COUNT:
        reasons.append("unexpected_servo_count")
    if invalid_duration_count:
        reasons.append("nonpositive_frame_duration")
    if invalid_pulse_count:
        reasons.append("pulse_outside_hardware_range")
    if soft_limit_servo_ids:
        reasons.append("touches_autonomy_soft_pulse_limit")
    if active_leg_ids:
        reasons.append("moves_leg_servos")
    if held_non_idle_leg_ids:
        reasons.append("holds_leg_servos_away_from_calibrated_idle")
    if not starts_at_idle:
        reasons.append("requires_non_idle_start_pose")
    if not returns_to_idle:
        reasons.append("does_not_return_to_calibrated_idle")
    if duration_ms > MAX_ATOM_SOURCE_DURATION_MS:
        reasons.append("too_long_for_expression_atom_source")
    if not active_ids:
        reasons.append("no_motion_frames")
    unknown_active_ids = set(active_ids) - ARM_IDS - LEG_IDS
    if unknown_active_ids:
        reasons.append("moves_unclassified_servos")

    structurally_invalid = (
        servo_count != SERVO_COUNT
        or invalid_duration_count > 0
        or invalid_pulse_count > 0
    )
    arm_only_material = (
        bool(active_ids)
        and set(active_ids).issubset(ARM_IDS)
        and not active_leg_ids
        and legs_stay_at_idle
    )
    direct_atom_candidate = (
        arm_only_material
        and starts_at_idle
        and returns_to_idle
        and duration_ms <= MAX_ATOM_SOURCE_DURATION_MS
        and not soft_limit_servo_ids
    )

    if structurally_invalid:
        level = "reject"
    elif direct_atom_candidate:
        level = "offline_atom_candidate"
    elif arm_only_material:
        level = "reference_only"
    elif active_leg_ids or held_non_idle_leg_ids or not legs_stay_at_idle:
        level = "supervised_only"
    else:
        level = "reference_only"

    return {
        "level": level,
        "reasons": reasons,
        "candidate_atom_source": direct_atom_candidate,
        "candidate_atom_material": arm_only_material,
        "requires_supervision": level == "supervised_only",
    }


def inspect_action(path, idle_pose=CALIBRATED_IDLE_POSE, idle_tolerance=IDLE_TOLERANCE):
    path = Path(path)
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as database:
        rows = database.execute("SELECT * FROM ActionGroup ORDER BY [Index]").fetchall()
    if not rows:
        return None

    servo_count = len(rows[0]) - 2
    poses = [tuple(int(value) for value in row[2:]) for row in rows]
    durations_ms = [int(row[1]) for row in rows]
    active_ids = set()
    ranges = {}
    for offset in range(servo_count):
        servo_id = offset + 1
        values = [pose[offset] for pose in poses]
        low = min(values)
        high = max(values)
        ranges[str(servo_id)] = [low, high]
        if high != low:
            active_ids.add(servo_id)

    all_servo_ids = set(range(1, servo_count + 1))
    comparable_servo_ids = set(range(1, min(servo_count, len(idle_pose)) + 1))
    off_idle_ids = {
        servo_id
        for servo_id in comparable_servo_ids
        if any(
            abs(pose[servo_id - 1] - idle_pose[servo_id - 1]) > idle_tolerance
            for pose in poses
        )
    }
    held_non_idle_ids = off_idle_ids - active_ids
    active_arm_ids = sorted(active_ids & ARM_IDS)
    active_leg_ids = sorted(active_ids & LEG_IDS)
    held_non_idle_arm_ids = sorted(held_non_idle_ids & ARM_IDS)
    held_non_idle_leg_ids = sorted(held_non_idle_ids & LEG_IDS)
    unknown_active_ids = sorted(active_ids - ARM_IDS - LEG_IDS)

    invalid_pulse_entries = []
    soft_limit_servo_ids = set()
    for frame_index, pose in enumerate(poses, start=1):
        for offset, pulse in enumerate(pose):
            servo_id = offset + 1
            if pulse < HARD_PULSE_MIN or pulse > HARD_PULSE_MAX:
                invalid_pulse_entries.append(
                    {"frame": frame_index, "servo_id": servo_id, "pulse": pulse}
                )
            if pulse < AUTONOMY_SOFT_PULSE_MIN or pulse > AUTONOMY_SOFT_PULSE_MAX:
                soft_limit_servo_ids.add(servo_id)

    invalid_duration_frames = [
        index
        for index, duration in enumerate(durations_ms, start=1)
        if duration <= 0
    ]
    start_pose = poses[0]
    end_pose = poses[-1]
    starts_at_idle = _pose_is_near(start_pose, idle_pose, idle_tolerance)
    returns_to_idle = _pose_is_near(end_pose, idle_pose, idle_tolerance)
    legs_stay_at_idle = all(
        servo_id > servo_count
        or all(
            abs(pose[servo_id - 1] - idle_pose[servo_id - 1]) <= idle_tolerance
            for pose in poses
        )
        for servo_id in LEG_IDS
    )
    duration_ms = sum(max(duration, 0) for duration in durations_ms)
    recommendation = _recommendation(
        servo_count=servo_count,
        active_ids=active_ids,
        active_leg_ids=active_leg_ids,
        held_non_idle_leg_ids=held_non_idle_leg_ids,
        legs_stay_at_idle=legs_stay_at_idle,
        starts_at_idle=starts_at_idle,
        returns_to_idle=returns_to_idle,
        duration_ms=duration_ms,
        invalid_duration_count=len(invalid_duration_frames),
        invalid_pulse_count=len(invalid_pulse_entries),
        soft_limit_servo_ids=soft_limit_servo_ids,
    )

    if active_leg_ids or held_non_idle_leg_ids or not legs_stay_at_idle:
        motion_scope = "legs_or_whole_body"
    elif active_arm_ids and not unknown_active_ids:
        motion_scope = "arms_only"
    elif active_ids:
        motion_scope = "unclassified_motion"
    else:
        motion_scope = "static_or_unknown"

    return {
        "name": path.stem,
        "file": path.name,
        "frames": len(rows),
        "duration_ms": duration_ms,
        "servo_count": servo_count,
        "motion_scope": motion_scope,
        "active_servo_ids": sorted(active_ids),
        "active_arm_ids": active_arm_ids,
        "active_leg_ids": active_leg_ids,
        "unknown_active_ids": unknown_active_ids,
        "off_idle_servo_ids": sorted(off_idle_ids),
        "held_non_idle_servo_ids": sorted(held_non_idle_ids),
        "held_non_idle_arm_ids": held_non_idle_arm_ids,
        "held_non_idle_leg_ids": held_non_idle_leg_ids,
        "legs_stay_at_calibrated_idle": legs_stay_at_idle,
        "returns_to_start_exactly": start_pose == end_pose,
        "starts_at_calibrated_idle": starts_at_idle,
        "returns_to_calibrated_idle": returns_to_idle,
        "start_max_idle_error": _pose_error(start_pose, idle_pose),
        "end_max_idle_error": _pose_error(end_pose, idle_pose),
        "start_pose": list(start_pose),
        "end_pose": list(end_pose),
        "ranges": ranges,
        "timing": {
            "min_frame_duration_ms": min(durations_ms),
            "max_frame_duration_ms": max(durations_ms),
            "nonpositive_duration_frames": invalid_duration_frames,
        },
        "pulse_audit": {
            "hardware_range": [HARD_PULSE_MIN, HARD_PULSE_MAX],
            "autonomy_soft_range": [
                AUTONOMY_SOFT_PULSE_MIN,
                AUTONOMY_SOFT_PULSE_MAX,
            ],
            "invalid_entry_count": len(invalid_pulse_entries),
            "invalid_entries": invalid_pulse_entries[:20],
            "soft_limit_servo_ids": sorted(soft_limit_servo_ids),
        },
        "kinematic_proxies": _kinematic_proxies(poses, durations_ms, idle_pose),
        "recommendation": recommendation,
        "all_servo_ids": sorted(all_servo_ids),
    }


def build_inventory(action_dir, idle_pose=CALIBRATED_IDLE_POSE, idle_tolerance=IDLE_TOLERANCE):
    action_dir = Path(action_dir)
    actions = []
    failures = []
    for path in sorted(action_dir.glob("*.d6a")):
        try:
            result = inspect_action(path, idle_pose=idle_pose, idle_tolerance=idle_tolerance)
            if result is not None:
                actions.append(result)
        except (OSError, sqlite3.Error, ValueError, IndexError) as exc:
            failures.append({"file": path.name, "error": str(exc)})

    recommendation_counts = Counter(
        action["recommendation"]["level"] for action in actions
    )
    return {
        "schema_version": "tonypi-source-action-inventory/v2",
        "analysis_kind": "offline_static_audit_not_physical_verification",
        "action_count": len(actions),
        "failure_count": len(failures),
        "calibrated_idle_pose": list(idle_pose),
        "idle_tolerance": idle_tolerance,
        "summary": {
            "recommendation_counts": dict(sorted(recommendation_counts.items())),
            "offline_atom_candidate_names": [
                action["name"]
                for action in actions
                if action["recommendation"]["candidate_atom_source"]
            ],
            "candidate_atom_material_names": [
                action["name"]
                for action in actions
                if action["recommendation"]["candidate_atom_material"]
            ],
            "supervised_only_names": [
                action["name"]
                for action in actions
                if action["recommendation"]["level"] == "supervised_only"
            ],
        },
        "actions": actions,
        "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--idle-pose",
        type=_parse_idle_pose,
        default=CALIBRATED_IDLE_POSE,
        help="18 comma-separated calibrated idle pulses",
    )
    parser.add_argument("--idle-tolerance", type=int, default=IDLE_TOLERANCE)
    args = parser.parse_args()

    if args.idle_tolerance < 0:
        parser.error("--idle-tolerance must be non-negative")
    payload = build_inventory(
        args.action_dir,
        idle_pose=args.idle_pose,
        idle_tolerance=args.idle_tolerance,
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
