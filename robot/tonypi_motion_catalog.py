#!/usr/bin/env python3

"""Deterministic, physically bounded TonyPi body motion primitives."""

import math


BUS_SERVO_MIN = 100
BUS_SERVO_MAX = 900
BUS_SERVO_IDS = frozenset(range(1, 19))
RIGHT_ARM_SERVO_IDS = frozenset({6, 7, 8})
LEFT_ARM_SERVO_IDS = frozenset({14, 15, 16})
ARM_SERVO_IDS = RIGHT_ARM_SERVO_IDS | LEFT_ARM_SERVO_IDS
LEFT_ARM_FORWARD_SERVO_ID = 16
HAPPY_WAVE_SWAY_SERVO_IDS = frozenset({8, 16})
SUPPORT_SERVO_IDS = BUS_SERVO_IDS - ARM_SERVO_IDS
EXPRESSION_INTENSITY_MIN = 0.35
EXPRESSION_INTENSITY_MAX = 1.0
MOTION_AMPLITUDE_MIN = 0.1
MOTION_AMPLITUDE_MAX = 1.0
TRAJECTORY_FRAME_INTERVAL = 0.05
TRAJECTORY_COMMAND_HORIZON = 0.085
TRAJECTORY_FINAL_SETTLE = 0.16
TRAJECTORY_MAX_FRAME_DELTA = 105
TRAJECTORY_OFFLINE_MIN_SAMPLE_INTERVAL = 0.03
TRAJECTORY_OFFLINE_MAX_CURVE_SPEED = 2600.0
TRAJECTORY_OFFLINE_MAX_CURVE_ACCELERATION = 50000.0
TRAJECTORY_OFFLINE_MAX_CURVE_JERK = 900000.0
TRAJECTORY_OFFLINE_MAX_COMMAND_SPEED = 1100.0
HARDWARE_SEGMENT_MAX_COMMAND_SPEED = 900.0
MOTION_TEMPO_MIN = 0.8
MOTION_TEMPO_MAX = 1.2
MOTION_CYCLES_MIN = 1
MOTION_CYCLES_MAX = 2
MOTION_HOLD_MS_MIN = 0
MOTION_HOLD_MS_MAX = 800
HAPPY_WAVE_MIN_CLEARANCE_SCALE = 0.45
HAPPY_WAVE_MIN_LEFT_CLEARANCE_SCALE = 0.55
HAPPY_WAVE_RETURN_APPROACH_DURATION = 0.28
HAPPY_GREETING_VERIFIED_LANDING_LEFT_FORWARD_PULSES = (433, 497)
HAPPY_GREETING_VERIFIED_LANDING_TEMPO = 0.87

ARM_IDLE_POSE = [[6, 535], [7, 803], [8, 690], [14, 425], [15, 200], [16, 275]]
FULL_IDLE_POSE = [
    [1, 500], [2, 395], [3, 500], [4, 593], [5, 500], [6, 535],
    [7, 803], [8, 690], [9, 500], [10, 605], [11, 500], [12, 406],
    [13, 500], [14, 425], [15, 200], [16, 275], [17, 500], [18, 500],
]
RIGHT_ARM_IDLE_POSE = [[6, 535], [7, 803], [8, 690]]
HANDS_READY_POSE = [[6, 575], [7, 725], [8, 724], [14, 425], [15, 275], [16, 275]]
HAPPY_WAVE_READY_POSE = [[6, 575], [7, 725], [8, 690], [14, 425], [15, 275], [16, 275]]
HAPPY_WAVE_OPEN_POSE = [[6, 650], [7, 875], [8, 336], [14, 350], [15, 125], [16, 796]]
HAPPY_WAVE_SWAY_A_POSE = [[6, 650], [7, 875], [8, 264], [14, 350], [15, 125], [16, 530]]
HAPPY_WAVE_SWAY_B_POSE = [[6, 650], [7, 875], [8, 397], [14, 350], [15, 125], [16, 711]]
HAPPY_WIGGLE_RETURN_CLEAR_POSE = [[6, 575], [7, 850], [8, 420], [14, 405], [15, 160], [16, 430]]
HAPPY_WIGGLE_RETURN_APPROACH_POSE = [[6, 545], [7, 820], [8, 600], [14, 420], [15, 185], [16, 320]]
HAPPY_GREETING_RETURN_APPROACH_POSE = [[6, 545], [7, 820], [8, 600], [14, 415], [15, 175], [16, 365]]
WINGS_OPEN_HOLD_POSE = [[6, 500], [7, 500], [8, 500], [14, 500], [15, 500], [16, 500]]

# Extracted from the user-recorded and physically verified wave!!.d6a.
VERIFIED_HAPPY_WAVE_TEMPLATE_NAME = "wave!!.d6a"
VERIFIED_HAPPY_WAVE_TEMPLATE = (
    (0.150, ((6, 535), (7, 803), (8, 690), (14, 425), (15, 200), (16, 275))),
    (0.300, ((6, 575), (7, 725), (8, 690), (14, 425), (15, 275), (16, 275))),
    (0.250, ((6, 650), (7, 875), (8, 336), (14, 350), (15, 125), (16, 796))),
    (0.150, ((6, 650), (7, 875), (8, 264), (14, 350), (15, 125), (16, 530))),
    (0.150, ((6, 650), (7, 875), (8, 397), (14, 350), (15, 125), (16, 711))),
    (0.150, ((6, 650), (7, 875), (8, 264), (14, 350), (15, 125), (16, 530))),
    (0.150, ((6, 650), (7, 875), (8, 397), (14, 350), (15, 125), (16, 711))),
    (0.150, ((6, 650), (7, 875), (8, 264), (14, 350), (15, 125), (16, 530))),
    (0.150, ((6, 650), (7, 875), (8, 397), (14, 350), (15, 125), (16, 711))),
    (0.150, ((6, 535), (7, 803), (8, 690), (14, 425), (15, 200), (16, 275))),
)


BODY_ATOM_CONTRACTS = {
    "arms_idle": {
        "positions": ARM_IDLE_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "return_idle",
        "recovery_atom": "arms_idle",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
    },
    "full_idle": {
        "positions": FULL_IDLE_POSE,
        "changed_joint_ids": sorted(BUS_SERVO_IDS),
        "required_support_pose": "supervised_upright_clearance_confirmed",
        "expected_final_pose": "full_idle",
        "recovery_atom": None,
        "interruptible": True,
        "composable_with": [],
        "verified": True,
    },
    "hands_ready": {
        "positions": HANDS_READY_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "hands_ready_hold",
        "recovery_atom": "arms_idle",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
    },
    "happy_wave_ready": {
        "positions": HAPPY_WAVE_READY_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "happy_wave_ready",
        "recovery_atom": "arms_idle",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
    },
    "happy_wave_open": {
        "positions": HAPPY_WAVE_OPEN_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "happy_wave_open",
        "recovery_atom": "happy_wiggle_return_clear",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
    },
    "happy_wave_sway_a": {
        "positions": HAPPY_WAVE_SWAY_A_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "happy_wave_sway_a",
        "recovery_atom": "happy_wiggle_return_clear",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
    },
    "happy_wave_sway_b": {
        "positions": HAPPY_WAVE_SWAY_B_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "happy_wave_sway_b",
        "recovery_atom": "happy_wiggle_return_clear",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
    },
    "happy_wiggle_return_clear": {
        "positions": HAPPY_WIGGLE_RETURN_CLEAR_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "return_clear",
        "recovery_atom": "happy_wiggle_return_approach",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
    },
    "happy_wiggle_return_approach": {
        "positions": HAPPY_WIGGLE_RETURN_APPROACH_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "return_approach",
        "recovery_atom": "arms_idle",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
    },
    "happy_greeting_return_approach": {
        "positions": HAPPY_GREETING_RETURN_APPROACH_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "return_approach",
        "recovery_atom": "arms_idle",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
        "verification": "supervised_physical_acceptance_2026-07-25",
    },
    "wings_open_hold": {
        "positions": WINGS_OPEN_HOLD_POSE,
        "changed_joint_ids": sorted(ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "expected_final_pose": "wings_open_hold",
        "recovery_atom": "arms_idle",
        "interruptible": True,
        "composable_with": ["gaze"],
        "verified": True,
    },
}


# A pose atom is a calibrated point. A motion primitive is a continuous journey
# between points. Only primitives backed by verified anchors are used at runtime;
# the single-arm entries remain offline candidates until physical acceptance.
BODY_MOTION_PRIMITIVE_CONTRACTS = {
    "raise_both_arms": {
        "kind": "transition",
        "active_joint_ids": sorted(ARM_SERVO_IDS),
        "start_anchor": "arms_idle",
        "end_anchor": "hands_ready",
        "required_support_pose": "calibrated_upright_hold",
        "composable_with": ["gaze"],
        "verification": "verified_anchors_transition_candidate",
    },
    "open_both_arms": {
        "kind": "transition",
        "active_joint_ids": sorted(ARM_SERVO_IDS),
        "start_anchor": "hands_ready",
        "end_anchor": "happy_wave_open",
        "required_support_pose": "calibrated_upright_hold",
        "composable_with": ["gaze"],
        "verification": "verified_anchors_transition_candidate",
    },
    "raise_and_open_both_arms": {
        "kind": "transition",
        "active_joint_ids": sorted(ARM_SERVO_IDS),
        "start_anchor": "arms_idle",
        "end_anchor": "happy_wave_open",
        "required_support_pose": "calibrated_upright_hold",
        "composable_with": ["gaze"],
        "verification": "verified_anchors_transition_candidate",
    },
    "sway_both_hands": {
        "kind": "oscillation",
        "active_joint_ids": sorted(HAPPY_WAVE_SWAY_SERVO_IDS),
        "anchors": ["happy_wave_sway_a", "happy_wave_sway_b"],
        "required_support_pose": "calibrated_upright_hold",
        "composable_with": ["gaze"],
        "verification": "verified_anchors_transition_candidate",
    },
    "lower_both_arms": {
        "kind": "transition",
        "active_joint_ids": sorted(ARM_SERVO_IDS),
        "anchors": [
            "happy_wiggle_return_clear",
            "happy_wiggle_return_approach",
            "arms_idle",
        ],
        "required_support_pose": "calibrated_upright_hold",
        "composable_with": ["gaze"],
        "verification": "verified_anchors_transition_candidate",
    },
    "raise_left_arm": {
        "kind": "transition",
        "active_joint_ids": sorted(LEFT_ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "composable_with": ["gaze", "right_arm"],
        "verification": "offline_candidate",
    },
    "raise_right_arm": {
        "kind": "transition",
        "active_joint_ids": sorted(RIGHT_ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "composable_with": ["gaze", "left_arm"],
        "verification": "offline_candidate",
    },
    "wave_left_hand": {
        "kind": "oscillation",
        "active_joint_ids": sorted(LEFT_ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "composable_with": ["gaze", "right_arm"],
        "verification": "offline_candidate",
    },
    "wave_right_hand": {
        "kind": "oscillation",
        "active_joint_ids": sorted(RIGHT_ARM_SERVO_IDS),
        "required_support_pose": "calibrated_upright_hold",
        "composable_with": ["gaze", "left_arm"],
        "verification": "offline_candidate",
    },
}


MOTION_PHRASE_CONTRACTS = {
    "happy_greeting": {
        "body_sequence": "happy_wiggle",
        "parameters": {
            "expressive_intensity": [EXPRESSION_INTENSITY_MIN, EXPRESSION_INTENSITY_MAX],
            "openness": [EXPRESSION_INTENSITY_MIN, EXPRESSION_INTENSITY_MAX],
            "tempo": [MOTION_TEMPO_MIN, MOTION_TEMPO_MAX],
            "cycles": [MOTION_CYCLES_MIN, MOTION_CYCLES_MAX],
        },
        "expected_final_pose": "return_idle",
        "return_policy": "idle",
        "resources": ["body"],
        "compatible_resources": ["gaze"],
        "verification": "offline_candidate_uses_verified_anchors",
    },
    "quiet_acknowledge": {
        "body_sequence": "quiet_acknowledge",
        "parameters": {
            "expressive_intensity": [EXPRESSION_INTENSITY_MIN, EXPRESSION_INTENSITY_MAX],
            "amplitude": [MOTION_AMPLITUDE_MIN, MOTION_AMPLITUDE_MAX],
            "tempo": [MOTION_TEMPO_MIN, MOTION_TEMPO_MAX],
            "hold_ms": [MOTION_HOLD_MS_MIN, MOTION_HOLD_MS_MAX],
        },
        "expected_final_pose": "return_idle",
        "return_policy": "idle",
        "resources": ["body"],
        "compatible_resources": ["gaze"],
        "verification": "offline_candidate_uses_verified_anchors",
    },
}


MOTION_PHRASE_LEVEL_PROFILES = {
    "quiet_acknowledge": {
        "low": {
            "expressive_intensity": 0.35,
            "amplitude": 0.12,
            "tempo": 0.85,
            "hold_ms": 350,
        },
        "medium": {
            "expressive_intensity": 0.62,
            "amplitude": 0.4,
            "tempo": 1.0,
            "hold_ms": 250,
        },
        "high": {
            "expressive_intensity": 0.88,
            "amplitude": 0.88,
            "tempo": 1.15,
            "hold_ms": 180,
        },
    },
    "happy_greeting": {
        "low": {
            "expressive_intensity": 0.35,
            "tempo": 0.87,
            "openness": 0.35,
            "cycles": 1,
        },
        "medium": {
            "expressive_intensity": 0.55,
            "tempo": 1.0,
            "openness": 0.55,
            "cycles": 2,
        },
        "high": {
            "expressive_intensity": 0.75,
            "tempo": 1.0,
            "openness": 0.75,
            "cycles": 2,
        },
    },
}


BODY_SEQUENCE_CONTRACTS = {
    "hands_ready": {
        "required_start_poses": ["return_idle", "hands_ready_hold"],
        "expected_final_pose": "hands_ready_hold",
        "return_policy": "hold",
        "resources": ["body"],
        "compatible_resources": ["gaze"],
        "parameter_names": ["intensity"],
    },
    "happy_wiggle": {
        "required_start_poses": ["return_idle"],
        "expected_final_pose": "return_idle",
        "return_policy": "idle",
        "resources": ["body"],
        "compatible_resources": ["gaze"],
        "parameter_names": ["intensity"],
    },
    "return_idle": {
        "required_start_poses": ["any_verified_arm_pose"],
        "expected_final_pose": "return_idle",
        "return_policy": "idle",
        "resources": ["body"],
        "compatible_resources": ["gaze"],
        "parameter_names": [],
    },
    "wings_open": {
        "required_start_poses": ["return_idle"],
        "expected_final_pose": "wings_open_hold",
        "return_policy": "hold",
        "resources": ["body"],
        "compatible_resources": ["gaze"],
        "parameter_names": [],
    },
    "listen_idle": {
        "required_start_poses": ["return_idle"],
        "expected_final_pose": "wings_open_hold",
        "return_policy": "hold",
        "resources": ["body"],
        "compatible_resources": ["gaze"],
        "parameter_names": [],
    },
    "startup_recover": {
        "required_start_poses": ["supervised_upright_clearance_confirmed"],
        "expected_final_pose": "full_idle",
        "return_policy": "idle",
        "resources": ["body", "gaze"],
        "compatible_resources": [],
        "parameter_names": [],
    },
}


def _pulse(value):
    return max(BUS_SERVO_MIN, min(BUS_SERVO_MAX, int(value)))


def validate_expression_intensity(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("parameters_invalid")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("parameters_invalid")
    if not EXPRESSION_INTENSITY_MIN <= value <= EXPRESSION_INTENSITY_MAX:
        raise ValueError("parameters_invalid")
    return value


def validate_motion_amplitude(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("parameters_invalid")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("parameters_invalid")
    if not MOTION_AMPLITUDE_MIN <= value <= MOTION_AMPLITUDE_MAX:
        raise ValueError("parameters_invalid")
    return value


def _bounded_number(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("motion_genome_invalid")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("motion_genome_invalid")
    return value


def validate_motion_genome(phrase_name, genome=None):
    contract = MOTION_PHRASE_CONTRACTS.get(phrase_name)
    if contract is None:
        raise ValueError(f"unknown_motion_phrase:{phrase_name}")
    if genome is None:
        genome = {}
    if not isinstance(genome, dict):
        raise ValueError("motion_genome_invalid")
    allowed = set(contract["parameters"])
    if set(genome) - allowed:
        raise ValueError("motion_genome_invalid")

    intensity = _bounded_number(
        genome.get("expressive_intensity", 0.65),
        EXPRESSION_INTENSITY_MIN,
        EXPRESSION_INTENSITY_MAX,
    )
    tempo = _bounded_number(
        genome.get("tempo", 1.0),
        MOTION_TEMPO_MIN,
        MOTION_TEMPO_MAX,
    )
    normalized = {
        "expressive_intensity": round(intensity, 3),
        "tempo": round(tempo, 3),
    }

    if phrase_name == "happy_greeting":
        openness = _bounded_number(
            genome.get("openness", intensity),
            EXPRESSION_INTENSITY_MIN,
            EXPRESSION_INTENSITY_MAX,
        )
        default_cycles = 1 if intensity < 0.5 else 2
        cycles = genome.get("cycles", default_cycles)
        if isinstance(cycles, bool) or not isinstance(cycles, int):
            raise ValueError("motion_genome_invalid")
        if not MOTION_CYCLES_MIN <= cycles <= MOTION_CYCLES_MAX:
            raise ValueError("motion_genome_invalid")
        normalized.update({
            "openness": round(openness, 3),
            "cycles": int(cycles),
        })
    elif phrase_name == "quiet_acknowledge":
        amplitude = _bounded_number(
            genome.get("amplitude", intensity),
            MOTION_AMPLITUDE_MIN,
            MOTION_AMPLITUDE_MAX,
        )
        hold_ms = genome.get("hold_ms", 250)
        if isinstance(hold_ms, bool) or not isinstance(hold_ms, int):
            raise ValueError("motion_genome_invalid")
        if not MOTION_HOLD_MS_MIN <= hold_ms <= MOTION_HOLD_MS_MAX:
            raise ValueError("motion_genome_invalid")
        normalized.update({
            "amplitude": round(amplitude, 3),
            "hold_ms": int(hold_ms),
        })
    return normalized


def atom_positions(atom_name, intensity=None):
    atom = BODY_ATOM_CONTRACTS.get(atom_name)
    if atom is None:
        raise ValueError(f"unknown_body_atom:{atom_name}")
    target = atom["positions"]
    if intensity is None:
        return [[int(sid), int(position)] for sid, position in target]

    intensity = validate_motion_amplitude(intensity)
    base_by_id = {int(sid): int(position) for sid, position in ARM_IDLE_POSE}
    positions = []
    for sid, target_position in target:
        sid = int(sid)
        if sid not in base_by_id:
            raise ValueError(f"atom_not_expression_blendable:{atom_name}:{sid}")
        base = base_by_id[sid]
        position = round(base + (int(target_position) - base) * intensity)
        positions.append([sid, _pulse(position)])
    return positions


def _step(atom_name, duration, intensity=None):
    return {
        "atom": atom_name,
        "duration": round(float(duration), 4),
        "positions": atom_positions(atom_name, intensity=intensity),
    }


def _pchip_endpoint_slope(h0, h1, delta0, delta1):
    slope = ((2.0 * h0 + h1) * delta0 - h0 * delta1) / (h0 + h1)
    if slope * delta0 <= 0.0:
        return 0.0
    if delta0 * delta1 < 0.0 and abs(slope) > abs(3.0 * delta0):
        return 3.0 * delta0
    return slope


def _pchip_slopes(times, values):
    count = len(times)
    if count != len(values) or count < 2:
        raise ValueError("invalid_trajectory_keyframes")
    intervals = [times[index + 1] - times[index] for index in range(count - 1)]
    if any(interval <= 0.0 for interval in intervals):
        raise ValueError("invalid_trajectory_timing")
    secants = [
        (values[index + 1] - values[index]) / intervals[index]
        for index in range(count - 1)
    ]
    if count == 2:
        return [secants[0], secants[0]]

    slopes = [0.0] * count
    slopes[0] = _pchip_endpoint_slope(
        intervals[0], intervals[1], secants[0], secants[1]
    )
    slopes[-1] = _pchip_endpoint_slope(
        intervals[-1], intervals[-2], secants[-1], secants[-2]
    )
    for index in range(1, count - 1):
        before = secants[index - 1]
        after = secants[index]
        if before == 0.0 or after == 0.0 or before * after <= 0.0:
            slopes[index] = 0.0
            continue
        weight_before = 2.0 * intervals[index] + intervals[index - 1]
        weight_after = intervals[index] + 2.0 * intervals[index - 1]
        slopes[index] = (weight_before + weight_after) / (
            weight_before / before + weight_after / after
        )
    return slopes


def _hermite_value(time_value, time_start, time_end, value_start, value_end, slope_start, slope_end):
    interval = time_end - time_start
    normalized = (time_value - time_start) / interval
    normalized_sq = normalized * normalized
    normalized_cube = normalized_sq * normalized
    basis_start = (2.0 * normalized_cube) - (3.0 * normalized_sq) + 1.0
    basis_start_slope = normalized_cube - (2.0 * normalized_sq) + normalized
    basis_end = (-2.0 * normalized_cube) + (3.0 * normalized_sq)
    basis_end_slope = normalized_cube - normalized_sq
    return (
        basis_start * value_start
        + basis_start_slope * interval * slope_start
        + basis_end * value_end
        + basis_end_slope * interval * slope_end
    )


def _trajectory_sample_times(keyframes, frame_interval):
    if frame_interval <= 0.0:
        raise ValueError("invalid_trajectory_frame_interval")
    sample_times = []
    for index in range(len(keyframes) - 1):
        start = float(keyframes[index]["time"])
        end = float(keyframes[index + 1]["time"])
        duration = end - start
        if duration <= 0.0:
            raise ValueError("invalid_trajectory_timing")
        step_count = max(1, math.ceil(duration / frame_interval))
        step_duration = duration / step_count
        for step_index in range(1, step_count + 1):
            sample_times.append(round(start + (step_duration * step_index), 6))
    return sample_times


def _trajectory_kinematic_audit(frames, initial_positions):
    if not frames:
        raise ValueError("empty_trajectory")
    previous_positions = {
        int(sid): int(position) for sid, position in initial_positions
    }
    joint_ids = sorted(previous_positions)
    previous_time = 0.0
    previous_velocity = None
    previous_acceleration = None
    minimum_interval = math.inf
    maximum_interval = 0.0
    max_frame_delta = 0
    max_frame_delta_servo_id = None
    max_curve_speed = 0.0
    max_curve_speed_servo_id = None
    max_curve_acceleration = 0.0
    max_curve_acceleration_servo_id = None
    max_curve_jerk = 0.0
    max_curve_jerk_servo_id = None
    max_command_speed = 0.0
    max_command_speed_servo_id = None

    for frame in frames:
        current_time = float(frame["time"])
        sample_interval = current_time - previous_time
        if sample_interval <= 0.0:
            raise ValueError("non_monotonic_trajectory_frames")
        minimum_interval = min(minimum_interval, sample_interval)
        maximum_interval = max(maximum_interval, sample_interval)
        current_positions = {
            int(sid): int(position) for sid, position in frame["positions"]
        }
        if sorted(current_positions) != joint_ids:
            raise ValueError("trajectory_frame_joint_set_mismatch")

        velocity = {}
        acceleration = None
        for sid in joint_ids:
            signed_delta = current_positions[sid] - previous_positions[sid]
            frame_delta = abs(signed_delta)
            curve_speed = frame_delta / sample_interval
            command_speed = frame_delta / float(frame["duration"])
            velocity[sid] = signed_delta / sample_interval
            if frame_delta > max_frame_delta:
                max_frame_delta = frame_delta
                max_frame_delta_servo_id = sid
            if curve_speed > max_curve_speed:
                max_curve_speed = curve_speed
                max_curve_speed_servo_id = sid
            if command_speed > max_command_speed:
                max_command_speed = command_speed
                max_command_speed_servo_id = sid

        if previous_velocity is not None:
            acceleration = {}
            for sid in joint_ids:
                value = (velocity[sid] - previous_velocity[sid]) / sample_interval
                acceleration[sid] = value
                if abs(value) > max_curve_acceleration:
                    max_curve_acceleration = abs(value)
                    max_curve_acceleration_servo_id = sid

        if acceleration is not None and previous_acceleration is not None:
            for sid in joint_ids:
                value = abs(
                    (acceleration[sid] - previous_acceleration[sid])
                    / sample_interval
                )
                if value > max_curve_jerk:
                    max_curve_jerk = value
                    max_curve_jerk_servo_id = sid

        previous_positions = current_positions
        previous_velocity = velocity
        if acceleration is not None:
            previous_acceleration = acceleration
        previous_time = current_time

    violations = []
    if minimum_interval < TRAJECTORY_OFFLINE_MIN_SAMPLE_INTERVAL:
        violations.append("sample_interval_too_short")
    if max_frame_delta > TRAJECTORY_MAX_FRAME_DELTA:
        violations.append("frame_delta_exceeded")
    if max_curve_speed > TRAJECTORY_OFFLINE_MAX_CURVE_SPEED:
        violations.append("curve_speed_exceeded")
    if max_curve_acceleration > TRAJECTORY_OFFLINE_MAX_CURVE_ACCELERATION:
        violations.append("curve_acceleration_exceeded")
    if max_curve_jerk > TRAJECTORY_OFFLINE_MAX_CURVE_JERK:
        violations.append("curve_jerk_exceeded")
    if max_command_speed > TRAJECTORY_OFFLINE_MAX_COMMAND_SPEED:
        violations.append("command_speed_exceeded")

    return {
        "kind": "offline_regression_guard_not_physical_verification",
        "passed": not violations,
        "violations": violations,
        "min_sample_interval": round(minimum_interval, 6),
        "max_sample_interval": round(maximum_interval, 6),
        "max_frame_delta": max_frame_delta,
        "max_frame_delta_servo_id": max_frame_delta_servo_id,
        "max_curve_speed_pulse_per_second": round(max_curve_speed, 3),
        "max_curve_speed_servo_id": max_curve_speed_servo_id,
        "max_curve_acceleration_pulse_per_second2": round(
            max_curve_acceleration, 3
        ),
        "max_curve_acceleration_servo_id": max_curve_acceleration_servo_id,
        "max_curve_jerk_pulse_per_second3": round(max_curve_jerk, 3),
        "max_curve_jerk_servo_id": max_curve_jerk_servo_id,
        "max_command_speed_pulse_per_second": round(max_command_speed, 3),
        "max_command_speed_servo_id": max_command_speed_servo_id,
        "limits": {
            "min_sample_interval": TRAJECTORY_OFFLINE_MIN_SAMPLE_INTERVAL,
            "max_frame_delta": TRAJECTORY_MAX_FRAME_DELTA,
            "max_curve_speed_pulse_per_second": TRAJECTORY_OFFLINE_MAX_CURVE_SPEED,
            "max_curve_acceleration_pulse_per_second2": (
                TRAJECTORY_OFFLINE_MAX_CURVE_ACCELERATION
            ),
            "max_curve_jerk_pulse_per_second3": TRAJECTORY_OFFLINE_MAX_CURVE_JERK,
            "max_command_speed_pulse_per_second": (
                TRAJECTORY_OFFLINE_MAX_COMMAND_SPEED
            ),
        },
    }


def _compile_shape_preserving_trajectory(keyframes, frame_interval=TRAJECTORY_FRAME_INTERVAL):
    if len(keyframes) < 2 or float(keyframes[0]["time"]) != 0.0:
        raise ValueError("invalid_trajectory_keyframes")

    times = [float(keyframe["time"]) for keyframe in keyframes]
    position_maps = [
        {int(sid): int(position) for sid, position in keyframe["positions"]}
        for keyframe in keyframes
    ]
    joint_ids = sorted(position_maps[0])
    if not joint_ids or any(sorted(position_map) != joint_ids for position_map in position_maps):
        raise ValueError("trajectory_joint_set_mismatch")

    values_by_joint = {
        sid: [position_map[sid] for position_map in position_maps]
        for sid in joint_ids
    }
    slopes_by_joint = {
        sid: _pchip_slopes(times, values)
        for sid, values in values_by_joint.items()
    }
    sample_times = _trajectory_sample_times(keyframes, frame_interval)
    frames = []
    previous_time = 0.0
    previous_positions = dict(position_maps[0])
    max_frame_delta = 0

    for sample_time in sample_times:
        segment = 0
        while segment + 1 < len(times) - 1 and sample_time > times[segment + 1]:
            segment += 1
        positions = []
        current_positions = {}
        for sid in joint_ids:
            values = values_by_joint[sid]
            slopes = slopes_by_joint[sid]
            value = _hermite_value(
                sample_time,
                times[segment],
                times[segment + 1],
                values[segment],
                values[segment + 1],
                slopes[segment],
                slopes[segment + 1],
            )
            # Shape-preserving interpolation should already stay bounded. This
            # clamp is a final guard against floating-point or future data drift.
            segment_min = min(values[segment], values[segment + 1])
            segment_max = max(values[segment], values[segment + 1])
            position = _pulse(round(max(segment_min, min(segment_max, value))))
            positions.append([sid, position])
            current_positions[sid] = position

        frame_delta = max(
            abs(current_positions[sid] - previous_positions[sid])
            for sid in joint_ids
        )
        max_frame_delta = max(max_frame_delta, frame_delta)
        if frame_delta > TRAJECTORY_MAX_FRAME_DELTA:
            raise ValueError(f"trajectory_frame_delta_exceeded:{frame_delta}")

        wait_duration = sample_time - previous_time
        is_final = sample_time == sample_times[-1]
        destination = keyframes[segment + 1]
        frames.append({
            "atom": destination["primitive"],
            "anchor_atom": destination["atom"],
            "time": round(sample_time, 4),
            "duration": TRAJECTORY_FINAL_SETTLE if is_final else TRAJECTORY_COMMAND_HORIZON,
            "wait_duration": round(
                TRAJECTORY_FINAL_SETTLE + 0.05 if is_final else wait_duration,
                4,
            ),
            "positions": positions,
        })
        previous_time = sample_time
        previous_positions = current_positions

    audit = _trajectory_kinematic_audit(
        frames,
        keyframes[0]["positions"],
    )
    if not audit["passed"]:
        raise ValueError(
            "trajectory_kinematic_audit_failed:"
            + ",".join(audit["violations"])
        )
    return frames, audit


def _happy_wiggle_trajectory(intensity, tempo=1.0, openness=None, cycles=None):
    openness = intensity if openness is None else openness
    gesture_scale = (0.55 * intensity) + (0.45 * openness)
    cycles = (1 if intensity < 0.5 else 2) if cycles is None else int(cycles)
    # One cycle is the complete A -> B journey. Runtime profiles use two
    # cycles so expression strength changes amplitude and tempo, not command
    # count.
    sway_steps = 2 * cycles
    lift_duration = (0.62 + (0.12 * (1.0 - intensity))) / tempo
    sway_duration = (0.28 + (0.08 * (1.0 - intensity))) / tempo
    return_duration = (0.68 + (0.10 * (1.0 - intensity))) / tempo
    current_time = 0.0
    keyframes = [{
        "time": current_time,
        "atom": "arms_idle",
        "primitive": "start",
        "positions": atom_positions("arms_idle"),
    }]

    def append_keyframe(atom_name, primitive_name, duration, blend_intensity=intensity):
        nonlocal current_time
        current_time += duration
        keyframes.append({
            "time": round(current_time, 6),
            "atom": atom_name,
            "primitive": primitive_name,
            "positions": atom_positions(
                atom_name,
                intensity=blend_intensity,
            ),
        })

    append_keyframe(
        "happy_wave_open",
        "raise_and_open_both_arms",
        lift_duration,
        blend_intensity=gesture_scale,
    )
    for index in range(sway_steps):
        append_keyframe(
            "happy_wave_sway_a" if index % 2 == 0 else "happy_wave_sway_b",
            "sway_both_hands",
            sway_duration,
            blend_intensity=gesture_scale,
        )
    append_keyframe(
        "arms_idle",
        "lower_both_arms",
        return_duration,
        blend_intensity=None,
    )

    frame_interval = TRAJECTORY_FRAME_INTERVAL / max(1.0, tempo)
    frames, kinematic_audit = _compile_shape_preserving_trajectory(
        keyframes,
        frame_interval=frame_interval,
    )
    return {
        "frames": frames,
        "keyframes": [
            {
                "time": keyframe["time"],
                "atom": keyframe["atom"],
                "primitive": keyframe["primitive"],
            }
            for keyframe in keyframes
        ],
        "primitive_sequence": [
            "raise_and_open_both_arms",
            "sway_both_hands",
            "lower_both_arms",
        ],
        "sway_steps": sway_steps,
        "max_frame_delta": kinematic_audit["max_frame_delta"],
        "kinematic_audit": kinematic_audit,
        "trajectory_duration": round(float(keyframes[-1]["time"]), 4),
        "frame_interval": round(frame_interval, 6),
    }


def _quiet_acknowledge_trajectory(intensity, tempo=1.0, hold_ms=250, amplitude=None):
    amplitude = intensity if amplitude is None else amplitude
    raise_duration = (0.45 + (0.10 * (1.0 - intensity))) / tempo
    lower_duration = (0.44 + (0.08 * (1.0 - intensity))) / tempo
    current_time = 0.0
    keyframes = [{
        "time": current_time,
        "atom": "arms_idle",
        "primitive": "start",
        "positions": atom_positions("arms_idle"),
    }]
    current_time += raise_duration
    ready_positions = atom_positions("hands_ready", intensity=amplitude)
    keyframes.append({
        "time": round(current_time, 6),
        "atom": "hands_ready",
        "primitive": "raise_both_arms",
        "positions": ready_positions,
    })
    if hold_ms:
        current_time += hold_ms / 1000.0
        keyframes.append({
            "time": round(current_time, 6),
            "atom": "hands_ready",
            "primitive": "hold",
            "positions": ready_positions,
        })
    current_time += lower_duration
    keyframes.append({
        "time": round(current_time, 6),
        "atom": "arms_idle",
        "primitive": "lower_both_arms",
        "positions": atom_positions("arms_idle"),
    })
    frame_interval = TRAJECTORY_FRAME_INTERVAL / max(1.0, tempo)
    frames, kinematic_audit = _compile_shape_preserving_trajectory(
        keyframes,
        frame_interval=frame_interval,
    )
    primitive_sequence = ["raise_both_arms"]
    if hold_ms:
        primitive_sequence.append("hold")
    primitive_sequence.append("lower_both_arms")
    return {
        "frames": frames,
        "keyframes": [
            {
                "time": keyframe["time"],
                "atom": keyframe["atom"],
                "primitive": keyframe["primitive"],
            }
            for keyframe in keyframes
        ],
        "primitive_sequence": primitive_sequence,
        "max_frame_delta": kinematic_audit["max_frame_delta"],
        "kinematic_audit": kinematic_audit,
        "trajectory_duration": round(float(keyframes[-1]["time"]), 4),
        "frame_interval": round(frame_interval, 6),
    }


def _hardware_segment_audit(steps, initial_positions):
    previous = {int(sid): int(position) for sid, position in initial_positions}
    joint_ids = set(previous)
    violations = []
    command_count = 0
    max_frame_delta = 0
    max_frame_delta_servo_id = None
    max_command_speed = 0.0
    max_command_speed_servo_id = None

    for step in steps:
        if "wait_only" in step:
            wait_only = float(step["wait_only"])
            if not math.isfinite(wait_only) or wait_only < 0.0:
                violations.append("wait_duration_invalid")
            continue
        duration = float(step["duration"])
        current = {
            int(sid): int(position) for sid, position in step["positions"]
        }
        if not math.isfinite(duration) or duration <= 0.0:
            violations.append("segment_duration_invalid")
            continue
        if not current or not set(current) <= joint_ids:
            violations.append("segment_joint_set_mismatch")
            continue
        command_count += 1
        for sid, position in current.items():
            if not BUS_SERVO_MIN <= position <= BUS_SERVO_MAX:
                violations.append("segment_position_out_of_bounds")
            delta = abs(position - previous[sid])
            speed = delta / duration
            if delta > max_frame_delta:
                max_frame_delta = delta
                max_frame_delta_servo_id = sid
            if speed > max_command_speed:
                max_command_speed = speed
                max_command_speed_servo_id = sid
            previous[sid] = position

    if max_command_speed > HARDWARE_SEGMENT_MAX_COMMAND_SPEED:
        violations.append("command_speed_exceeded")
    return {
        "kind": "hardware_interpolation_contract_not_physical_verification",
        "passed": not violations,
        "violations": list(dict.fromkeys(violations)),
        "hardware_command_count": command_count,
        "max_frame_delta": max_frame_delta,
        "max_frame_delta_servo_id": max_frame_delta_servo_id,
        "max_command_speed_pulse_per_second": round(max_command_speed, 3),
        "max_command_speed_servo_id": max_command_speed_servo_id,
        "limits": {
            "pulse_min": BUS_SERVO_MIN,
            "pulse_max": BUS_SERVO_MAX,
            "max_command_speed_pulse_per_second": (
                HARDWARE_SEGMENT_MAX_COMMAND_SPEED
            ),
        },
    }


def _hardware_segment_result(steps):
    audit = _hardware_segment_audit(steps, atom_positions("arms_idle"))
    if not audit["passed"]:
        raise ValueError(
            "hardware_segment_kinematic_audit_failed:"
            + ",".join(audit["violations"])
        )
    return {
        "steps": steps,
        "hardware_command_count": audit["hardware_command_count"],
        "segment_count": len(steps),
        "total_duration": round(sum(
            float(step.get("wait_duration", step.get("wait_only", 0.0)))
            for step in steps
        ), 4),
        "max_frame_delta": audit["max_frame_delta"],
        "kinematic_audit": audit,
    }


def _quiet_acknowledge_hardware_segments(genome):
    """Let the bus servos interpolate each deliberate movement themselves."""
    intensity = genome["expressive_intensity"]
    amplitude = genome["amplitude"]
    tempo = genome["tempo"]
    hold_seconds = genome["hold_ms"] / 1000.0
    raise_duration = (0.45 + (0.10 * (1.0 - intensity))) / tempo
    lower_duration = (0.44 + (0.08 * (1.0 - intensity))) / tempo
    steps = [
            {
                "atom": "hands_ready",
                "primitive": "raise_both_arms",
                "duration": round(raise_duration, 4),
                "wait_duration": round(raise_duration + 0.04, 4),
                "positions": atom_positions("hands_ready", intensity=amplitude),
            },
            {
                "atom": "hands_ready",
                "primitive": "hold",
                "wait_only": round(hold_seconds, 4),
            },
            {
                "atom": "arms_idle",
                "primitive": "lower_both_arms",
                "duration": round(lower_duration, 4),
                "wait_duration": round(lower_duration + 0.08, 4),
                "positions": atom_positions("arms_idle"),
            },
        ]
    return _hardware_segment_result(steps)


def _verified_happy_wave_sway_center():
    sway_a = dict(VERIFIED_HAPPY_WAVE_TEMPLATE[3][1])
    sway_b = dict(VERIFIED_HAPPY_WAVE_TEMPLATE[4][1])
    return {
        sid: (sway_a[sid] + sway_b[sid]) / 2.0
        for sid in sorted(ARM_SERVO_IDS)
    }


def _scaled_verified_arm_pose(
    frame_index,
    source_positions,
    amplitude_scale,
    right_clearance_scale,
    left_clearance_scale,
):
    idle = {int(sid): int(position) for sid, position in ARM_IDLE_POSE}
    sway_center = _verified_happy_wave_sway_center()
    scaled = []
    for sid, source_position in source_positions:
        sid = int(sid)
        base = idle[sid]
        clearance_scale = (
            left_clearance_scale
            if sid in LEFT_ARM_SERVO_IDS
            else right_clearance_scale
        )
        if frame_index in {1, len(VERIFIED_HAPPY_WAVE_TEMPLATE)}:
            position = base
        elif 4 <= frame_index <= 9:
            center = sway_center[sid]
            position = round(
                base
                + (center - base) * clearance_scale
                + (int(source_position) - center) * amplitude_scale
            )
        else:
            position = round(
                base + (int(source_position) - base) * clearance_scale
            )
        scaled.append([sid, _pulse(position)])
    return scaled


def _verified_template_audit(
    steps,
    source_frames,
    amplitude_scale,
    right_clearance_scale,
    left_clearance_scale,
    landing_left_forward_pulses,
    landing_tempo,
    tempo,
):
    violations = []
    idle = {int(sid): int(position) for sid, position in ARM_IDLE_POSE}
    previous = dict(idle)
    source_previous = dict(idle)
    max_frame_delta = 0
    max_frame_delta_servo_id = None
    max_command_speed = 0.0
    max_command_speed_servo_id = None
    source_max_command_speed = 0.0

    if not MOTION_AMPLITUDE_MIN <= amplitude_scale <= MOTION_AMPLITUDE_MAX:
        violations.append("template_amplitude_out_of_bounds")
    if not amplitude_scale <= right_clearance_scale <= MOTION_AMPLITUDE_MAX:
        violations.append("template_right_clearance_out_of_bounds")
    if not amplitude_scale <= left_clearance_scale <= MOTION_AMPLITUDE_MAX:
        violations.append("template_left_clearance_out_of_bounds")
    for pulse in landing_left_forward_pulses or ():
        if not BUS_SERVO_MIN <= pulse <= BUS_SERVO_MAX:
            violations.append("template_landing_left_forward_out_of_bounds")
    if len(steps) != len(source_frames):
        violations.append("template_frame_count_changed")

    for step, (
        frame_index,
        (source_duration, source_positions),
    ) in zip(
        steps,
        source_frames,
    ):
        if step.get("source_frame") != frame_index:
            violations.append("template_frame_order_changed")
        duration = float(step["duration"])
        expected_duration = round(
            float(source_duration)
            / (
                float(landing_tempo)
                if (
                    landing_tempo is not None
                    and frame_index == source_frames[-1][0]
                )
                else float(tempo)
            ),
            4,
        )
        if not math.isclose(duration, expected_duration, abs_tol=1e-9):
            violations.append("template_frame_timing_changed")
        current = {
            int(sid): int(position) for sid, position in step["positions"]
        }
        source = {
            int(sid): int(position) for sid, position in source_positions
        }
        if set(current) != ARM_SERVO_IDS or set(source) != ARM_SERVO_IDS:
            violations.append("template_joint_set_changed")
            continue
        expected_positions = dict(_scaled_verified_arm_pose(
            frame_index,
            source_positions,
            amplitude_scale,
            right_clearance_scale,
            left_clearance_scale,
        ))
        landing_frame_indices = (
            (source_frames[-3][0], source_frames[-2][0])
            if landing_left_forward_pulses is not None
            else ()
        )
        if frame_index in landing_frame_indices:
            expected_positions[LEFT_ARM_FORWARD_SERVO_ID] = (
                landing_left_forward_pulses[
                    landing_frame_indices.index(frame_index)
                ]
            )
        for sid in sorted(ARM_SERVO_IDS):
            if current[sid] != expected_positions[sid]:
                violations.append("template_position_not_scaled")
            if not BUS_SERVO_MIN <= current[sid] <= BUS_SERVO_MAX:
                violations.append("template_position_out_of_bounds")
            lower_bound = min(idle[sid], source[sid])
            upper_bound = max(idle[sid], source[sid])
            if not lower_bound <= current[sid] <= upper_bound:
                violations.append("template_position_exceeded_source_envelope")
            delta = abs(current[sid] - previous[sid])
            source_delta = abs(source[sid] - source_previous[sid])
            speed = delta / duration
            source_speed = source_delta / duration
            if delta > source_delta + 1:
                violations.append("template_frame_delta_exceeded")
            if delta > max_frame_delta:
                max_frame_delta = delta
                max_frame_delta_servo_id = sid
            if speed > max_command_speed:
                max_command_speed = speed
                max_command_speed_servo_id = sid
            source_max_command_speed = max(
                source_max_command_speed,
                source_speed,
            )
        previous = current
        source_previous = source

    if steps:
        if steps[0]["positions"] != ARM_IDLE_POSE:
            violations.append("template_start_pose_changed")
        if steps[-1]["positions"] != ARM_IDLE_POSE:
            violations.append("template_final_pose_changed")
    if max_command_speed > source_max_command_speed + 1.0:
        violations.append("template_command_speed_exceeded")
    return {
        "kind": "scaled_physically_verified_template_contract",
        "passed": not violations,
        "violations": list(dict.fromkeys(violations)),
        "hardware_command_count": len(steps),
        "max_frame_delta": max_frame_delta,
        "max_frame_delta_servo_id": max_frame_delta_servo_id,
        "max_command_speed_pulse_per_second": round(max_command_speed, 3),
        "max_command_speed_servo_id": max_command_speed_servo_id,
        "verified_source_max_command_speed_pulse_per_second": round(
            source_max_command_speed,
            3,
        ),
        "limits": {
            "pulse_min": BUS_SERVO_MIN,
            "pulse_max": BUS_SERVO_MAX,
            "amplitude_scale_min": MOTION_AMPLITUDE_MIN,
            "amplitude_scale_max": MOTION_AMPLITUDE_MAX,
            "minimum_right_clearance_scale": HAPPY_WAVE_MIN_CLEARANCE_SCALE,
            "minimum_left_clearance_scale": (
                HAPPY_WAVE_MIN_LEFT_CLEARANCE_SCALE
            ),
            "verified_template": VERIFIED_HAPPY_WAVE_TEMPLATE_NAME,
        },
    }


def _verified_happy_wave_source_frames(cycles):
    source_indices = [1, 2, 3]
    for cycle_index in range(int(cycles)):
        source_indices.extend([
            4 + (cycle_index * 2),
            5 + (cycle_index * 2),
        ])
    source_indices.append(len(VERIFIED_HAPPY_WAVE_TEMPLATE))
    return [
        (frame_index, VERIFIED_HAPPY_WAVE_TEMPLATE[frame_index - 1])
        for frame_index in source_indices
    ]


def _happy_greeting_hardware_segments(genome):
    amplitude_scale = round(
        (genome["expressive_intensity"] + genome["openness"]) / 2.0,
        3,
    )
    right_clearance_scale = max(
        amplitude_scale,
        HAPPY_WAVE_MIN_CLEARANCE_SCALE,
    )
    left_clearance_scale = max(
        amplitude_scale,
        HAPPY_WAVE_MIN_LEFT_CLEARANCE_SCALE,
    )
    tempo = float(genome["tempo"])
    cycles = int(genome["cycles"])
    source_frames = _verified_happy_wave_source_frames(cycles)
    landing_frame_indices = (
        source_frames[-3][0],
        source_frames[-2][0],
    )
    landing_left_forward_pulses = (
        HAPPY_GREETING_VERIFIED_LANDING_LEFT_FORWARD_PULSES
        if amplitude_scale > 0.35
        else None
    )
    landing_tempo = (
        HAPPY_GREETING_VERIFIED_LANDING_TEMPO
        if amplitude_scale > 0.35
        else None
    )
    atoms_by_source_frame = {
        1: "arms_idle",
        2: "happy_wave_ready",
        3: "happy_wave_open",
        4: "happy_wave_sway_a",
        5: "happy_wave_sway_b",
        6: "happy_wave_sway_a",
        7: "happy_wave_sway_b",
        8: "happy_wave_sway_a",
        9: "happy_wave_sway_b",
        10: "arms_idle",
    }
    primitives_by_source_frame = {
        1: "settle_idle",
        2: "prepare_both_arms",
        3: "raise_and_open_both_arms",
        4: "sway_both_hands",
        5: "sway_both_hands",
        6: "sway_both_hands",
        7: "sway_both_hands",
        8: "sway_both_hands",
        9: "sway_both_hands",
        10: "lower_both_arms",
    }
    steps = []
    for frame_index, (duration, source_positions) in source_frames:
        atom_name = atoms_by_source_frame[frame_index]
        primitive_name = primitives_by_source_frame[frame_index]
        scaled_duration = round(
            float(duration)
            / (
                landing_tempo
                if (
                    landing_tempo is not None
                    and frame_index == source_frames[-1][0]
                )
                else tempo
            ),
            4,
        )
        positions = _scaled_verified_arm_pose(
            frame_index,
            source_positions,
            amplitude_scale,
            right_clearance_scale,
            left_clearance_scale,
        )
        if (
            frame_index in landing_frame_indices
            and landing_left_forward_pulses is not None
        ):
            landing_pulse = landing_left_forward_pulses[
                landing_frame_indices.index(frame_index)
            ]
            positions = [
                [
                    sid,
                    (
                        landing_pulse
                        if sid == LEFT_ARM_FORWARD_SERVO_ID
                        else position
                    ),
                ]
                for sid, position in positions
            ]
        steps.append({
            "atom": atom_name,
            "primitive": primitive_name,
            "source_frame": frame_index,
            "duration": scaled_duration,
            "wait_duration": scaled_duration,
            "positions": positions,
        })

    template_audit = _verified_template_audit(
        steps,
        source_frames,
        amplitude_scale,
        right_clearance_scale,
        left_clearance_scale,
        landing_left_forward_pulses,
        landing_tempo,
        tempo,
    )
    if not template_audit["passed"]:
        raise ValueError(
            "verified_template_audit_failed:"
            + ",".join(template_audit["violations"])
        )

    recovery_duration = round(
        HAPPY_WAVE_RETURN_APPROACH_DURATION / (
            landing_tempo if landing_tempo is not None else tempo
        ),
        4,
    )
    recovery_steps = [{
        "atom": "happy_greeting_return_approach",
        "primitive": "clear_body_before_idle",
        "source_frame": None,
        "derived_from_verified_atoms": [
            "happy_wiggle_return_clear",
            "happy_wiggle_return_approach",
        ],
        "duration": recovery_duration,
        "wait_duration": recovery_duration,
        "positions": atom_positions("happy_greeting_return_approach"),
    }]
    steps[-1:-1] = recovery_steps
    audit = _hardware_segment_audit(steps, ARM_IDLE_POSE)
    audit["violations"] = [
        violation for violation in audit["violations"]
        if violation != "command_speed_exceeded"
    ]
    verified_speed_limit = (
        template_audit[
            "verified_source_max_command_speed_pulse_per_second"
        ]
    )
    if (
        audit["max_command_speed_pulse_per_second"]
        > verified_speed_limit + 1.0
    ):
        audit["violations"].append("verified_template_command_speed_exceeded")
    audit["violations"] = list(dict.fromkeys(audit["violations"]))
    audit["passed"] = not audit["violations"]
    if not audit["passed"]:
        raise ValueError(
            "happy_wave_recovery_audit_failed:"
            + ",".join(audit["violations"])
        )
    audit["kind"] = "verified_template_with_physically_verified_recovery"
    audit["template_audit"] = template_audit
    audit["recovery_anchor_verified"] = True
    audit["recovery_anchor_bounded_by_verified_corridor"] = True
    audit["limits"]["max_command_speed_pulse_per_second"] = (
        verified_speed_limit
    )
    return {
        "steps": steps,
        "hardware_command_count": audit["hardware_command_count"],
        "segment_count": len(steps),
        "total_duration": round(sum(step["wait_duration"] for step in steps), 4),
        "max_frame_delta": audit["max_frame_delta"],
        "kinematic_audit": audit,
        "sway_steps": 2 * cycles,
        "primitive_sequence": [
            step["primitive"] for step in steps
        ],
        "source_template": VERIFIED_HAPPY_WAVE_TEMPLATE_NAME,
        "source_template_frame_count": len(VERIFIED_HAPPY_WAVE_TEMPLATE),
        "template_frame_count": len(source_frames),
        "template_duration": round(sum(
            frame[0] for _frame_index, frame in source_frames
        ), 4),
        "amplitude_scale": amplitude_scale,
        "clearance_scale": max(
            right_clearance_scale,
            left_clearance_scale,
        ),
        "right_clearance_scale": right_clearance_scale,
        "left_clearance_scale": left_clearance_scale,
        "landing_left_forward_pulses": landing_left_forward_pulses,
        "landing_tempo": landing_tempo,
        "recovery_waypoint_count": len(recovery_steps),
        "recovery_waypoints": [
            step["atom"] for step in recovery_steps
        ],
        "recovery_waypoint": recovery_steps[-1]["atom"],
        "recovery_waypoint_duration": round(
            sum(step["wait_duration"] for step in recovery_steps),
            4,
        ),
        "collision_clearance_policy": (
            "verified_low_landing_corridor_then_single_recovery"
            if landing_left_forward_pulses is not None
            else "left_biased_clear_body_before_idle"
        ),
        "timing_scale": round(1.0 / tempo, 4),
        "preserves_frame_order": True,
        "preserves_frame_timing": True,
        "preserves_exact_source_timing": math.isclose(tempo, 1.0),
        "preserves_relative_frame_timing": True,
        "preserves_cycle_boundary": True,
    }


def _compiled_phrase_result(phrase_name, genome, trajectory):
    contract = MOTION_PHRASE_CONTRACTS[phrase_name]
    return {
        "phrase": phrase_name,
        "body_sequence": contract["body_sequence"],
        "contract": {
            key: list(value) if isinstance(value, list) else value
            for key, value in contract.items()
        },
        "steps": trajectory["frames"],
        "expected_final_pose": contract["expected_final_pose"],
        "return_policy": contract["return_policy"],
        "execution_mode": "continuous_trajectory",
        "motion_contract_version": "tonypi-motion-catalog/v2",
        "primitive_sequence": trajectory["primitive_sequence"],
        "keyframes": trajectory["keyframes"],
        "trajectory_frame_count": len(trajectory["frames"]),
        "trajectory_duration": trajectory["trajectory_duration"],
        "frame_interval": trajectory["frame_interval"],
        "command_horizon": TRAJECTORY_COMMAND_HORIZON,
        "max_frame_delta": trajectory["max_frame_delta"],
        "kinematic_audit": dict(trajectory["kinematic_audit"]),
        "continuous_blending": True,
        "applied_genome": dict(genome),
    }


def compile_motion_phrase(phrase_name, genome=None):
    normalized = validate_motion_genome(phrase_name, genome)
    if phrase_name == "happy_greeting":
        trajectory = _happy_wiggle_trajectory(
            normalized["expressive_intensity"],
            tempo=normalized["tempo"],
            openness=normalized["openness"],
            cycles=normalized["cycles"],
        )
    elif phrase_name == "quiet_acknowledge":
        trajectory = _quiet_acknowledge_trajectory(
            normalized["expressive_intensity"],
            tempo=normalized["tempo"],
            hold_ms=normalized["hold_ms"],
            amplitude=normalized["amplitude"],
        )
    else:
        raise ValueError(f"motion_phrase_not_compiled:{phrase_name}")
    return _compiled_phrase_result(phrase_name, normalized, trajectory)


def compile_motion_phrase_level(phrase_name, level):
    profiles = MOTION_PHRASE_LEVEL_PROFILES.get(phrase_name)
    if profiles is None or level not in profiles:
        raise ValueError("motion_acceptance_profile_invalid")
    compiled = compile_motion_phrase(phrase_name, profiles[level])
    if phrase_name == "quiet_acknowledge":
        hardware = _quiet_acknowledge_hardware_segments(compiled["applied_genome"])
    else:
        hardware = _happy_greeting_hardware_segments(compiled["applied_genome"])
    if phrase_name in {"quiet_acknowledge", "happy_greeting"}:
        compiled["steps"] = hardware["steps"]
        compiled["execution_mode"] = "hardware_interpolated_segments"
        compiled["hardware_command_count"] = hardware["hardware_command_count"]
        compiled["segment_count"] = hardware["segment_count"]
        compiled["total_duration"] = hardware["total_duration"]
        compiled["max_frame_delta"] = hardware["max_frame_delta"]
        compiled["kinematic_audit"] = hardware["kinematic_audit"]
        if "sway_steps" in hardware:
            compiled["sway_steps"] = hardware["sway_steps"]
        if "primitive_sequence" in hardware:
            compiled["primitive_sequence"] = hardware["primitive_sequence"]
        for field in (
            "source_template",
            "source_template_frame_count",
            "template_frame_count",
            "template_duration",
            "amplitude_scale",
            "clearance_scale",
            "right_clearance_scale",
            "left_clearance_scale",
            "landing_left_forward_pulses",
            "landing_tempo",
            "recovery_waypoint_count",
            "recovery_waypoints",
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
            if field in hardware:
                compiled[field] = hardware[field]
        for field in (
            "trajectory_frame_count",
            "trajectory_duration",
            "frame_interval",
            "command_horizon",
            "continuous_blending",
        ):
            compiled.pop(field, None)
    compiled["acceptance_level"] = level
    return compiled


def compile_body_sequence(action_name, intensity=1.0):
    contract = BODY_SEQUENCE_CONTRACTS.get(action_name)
    if contract is None:
        raise ValueError(f"unknown_body_sequence:{action_name}")

    if contract["parameter_names"]:
        intensity = validate_expression_intensity(intensity)
    else:
        if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
            raise ValueError("parameters_invalid")
        if not math.isfinite(float(intensity)) or float(intensity) != 1.0:
            raise ValueError("parameters_invalid")

    sway_steps = None
    trajectory = None

    if action_name == "hands_ready":
        steps = [_step("hands_ready", 0.35 + (0.12 * (1.0 - intensity)), intensity)]
    elif action_name == "happy_wiggle":
        trajectory = _happy_wiggle_trajectory(intensity)
        steps = trajectory["frames"]
        sway_steps = trajectory["sway_steps"]
    elif action_name == "return_idle":
        steps = [_step("arms_idle", 0.80), _step("arms_idle", 0.40)]
    elif action_name in {"wings_open", "listen_idle"}:
        steps = [_step("wings_open_hold", 0.65)]
    elif action_name == "startup_recover":
        steps = [_step("full_idle", 1.40), _step("full_idle", 0.40)]
    else:
        raise ValueError(f"body_sequence_not_compiled:{action_name}")

    result = {
        "action": action_name,
        "contract": {key: list(value) if isinstance(value, list) else value for key, value in contract.items()},
        "steps": steps,
        "expected_final_pose": contract["expected_final_pose"],
        "return_policy": contract["return_policy"],
    }
    if action_name in {"hands_ready", "happy_wiggle"}:
        result["applied_parameters"] = {"intensity": round(float(intensity), 3)}
    if sway_steps is not None:
        result["sway_steps"] = sway_steps
    if trajectory is not None:
        result.update({
            "execution_mode": "continuous_trajectory",
            "motion_contract_version": "tonypi-motion-catalog/v2",
            "primitive_sequence": trajectory["primitive_sequence"],
            "keyframes": trajectory["keyframes"],
            "trajectory_frame_count": len(trajectory["frames"]),
            "trajectory_duration": trajectory["trajectory_duration"],
            "frame_interval": trajectory["frame_interval"],
            "command_horizon": TRAJECTORY_COMMAND_HORIZON,
            "max_frame_delta": trajectory["max_frame_delta"],
            "kinematic_audit": dict(trajectory["kinematic_audit"]),
            "continuous_blending": True,
        })
    return result


def validate_motion_catalog():
    for atom_name, atom in BODY_ATOM_CONTRACTS.items():
        positions = atom.get("positions") or []
        ids = [int(sid) for sid, _position in positions]
        if not positions or len(ids) != len(set(ids)):
            raise ValueError(f"invalid_atom_positions:{atom_name}")
        if any(sid not in BUS_SERVO_IDS for sid in ids):
            raise ValueError(f"invalid_atom_servo:{atom_name}")
        if any(not BUS_SERVO_MIN <= int(position) <= BUS_SERVO_MAX for _sid, position in positions):
            raise ValueError(f"invalid_atom_pulse:{atom_name}")
        declared = set(atom.get("changed_joint_ids") or [])
        if declared != set(ids):
            raise ValueError(f"atom_joint_contract_mismatch:{atom_name}")
        if atom["required_support_pose"] == "calibrated_upright_hold":
            if declared & SUPPORT_SERVO_IDS:
                raise ValueError(f"arm_atom_changes_support_joint:{atom_name}")
        recovery_atom = atom.get("recovery_atom")
        if recovery_atom is not None and recovery_atom not in BODY_ATOM_CONTRACTS:
            raise ValueError(f"atom_recovery_missing:{atom_name}")

    for primitive_name, primitive in BODY_MOTION_PRIMITIVE_CONTRACTS.items():
        active_joint_ids = set(primitive.get("active_joint_ids") or [])
        if not active_joint_ids or not active_joint_ids <= ARM_SERVO_IDS:
            raise ValueError(f"invalid_motion_primitive_joints:{primitive_name}")
        if primitive.get("required_support_pose") != "calibrated_upright_hold":
            raise ValueError(f"invalid_motion_primitive_support:{primitive_name}")
        for anchor_name in [
            primitive.get("start_anchor"),
            primitive.get("end_anchor"),
            *(primitive.get("anchors") or []),
        ]:
            if anchor_name is not None and anchor_name not in BODY_ATOM_CONTRACTS:
                raise ValueError(f"motion_primitive_anchor_missing:{primitive_name}:{anchor_name}")

    for phrase_name, phrase in MOTION_PHRASE_CONTRACTS.items():
        compiled_phrase = compile_motion_phrase(phrase_name)
        if compiled_phrase["expected_final_pose"] != phrase["expected_final_pose"]:
            raise ValueError(f"motion_phrase_final_pose_mismatch:{phrase_name}")
        if compiled_phrase["steps"][-1]["positions"] != ARM_IDLE_POSE:
            raise ValueError(f"motion_phrase_final_idle_mismatch:{phrase_name}")
        if compiled_phrase["max_frame_delta"] > TRAJECTORY_MAX_FRAME_DELTA:
            raise ValueError(f"motion_phrase_frame_delta_exceeded:{phrase_name}")
        if not compiled_phrase["kinematic_audit"]["passed"]:
            raise ValueError(f"motion_phrase_kinematic_audit_failed:{phrase_name}")
        if any(
            {int(sid) for sid, _position in frame["positions"]} - ARM_SERVO_IDS
            for frame in compiled_phrase["steps"]
        ):
            raise ValueError(f"motion_phrase_changes_support_joint:{phrase_name}")

    for sequence_name in BODY_SEQUENCE_CONTRACTS:
        compiled = compile_body_sequence(sequence_name)
        if not compiled["steps"]:
            raise ValueError(f"empty_body_sequence:{sequence_name}")
        if compiled["expected_final_pose"] != BODY_SEQUENCE_CONTRACTS[sequence_name]["expected_final_pose"]:
            raise ValueError(f"sequence_final_pose_mismatch:{sequence_name}")
        for step in compiled["steps"]:
            ids = {int(sid) for sid, _position in step["positions"]}
            if sequence_name != "startup_recover" and not ids <= ARM_SERVO_IDS:
                raise ValueError(f"body_sequence_changes_support_joint:{sequence_name}")
        if compiled.get("execution_mode") == "continuous_trajectory":
            if not compiled.get("continuous_blending"):
                raise ValueError(f"trajectory_blending_disabled:{sequence_name}")
            if compiled["max_frame_delta"] > TRAJECTORY_MAX_FRAME_DELTA:
                raise ValueError(f"trajectory_frame_delta_exceeded:{sequence_name}")
            if not compiled["kinematic_audit"]["passed"]:
                raise ValueError(f"trajectory_kinematic_audit_failed:{sequence_name}")
            if compiled["steps"][-1]["positions"] != ARM_IDLE_POSE:
                raise ValueError(f"trajectory_final_idle_mismatch:{sequence_name}")
    return True


validate_motion_catalog()
