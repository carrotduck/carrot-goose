#!/usr/bin/env python3

import unittest
from itertools import product

from tonypi_motion_catalog import (
    ARM_IDLE_POSE,
    ARM_SERVO_IDS,
    BODY_ATOM_CONTRACTS,
    BODY_MOTION_PRIMITIVE_CONTRACTS,
    FULL_IDLE_POSE,
    HAPPY_GREETING_RETURN_APPROACH_POSE,
    HAPPY_WAVE_RETURN_APPROACH_DURATION,
    MOTION_PHRASE_CONTRACTS,
    MOTION_PHRASE_LEVEL_PROFILES,
    SUPPORT_SERVO_IDS,
    TRAJECTORY_MAX_FRAME_DELTA,
    TRAJECTORY_OFFLINE_MAX_COMMAND_SPEED,
    TRAJECTORY_OFFLINE_MAX_CURVE_ACCELERATION,
    TRAJECTORY_OFFLINE_MAX_CURVE_JERK,
    TRAJECTORY_OFFLINE_MAX_CURVE_SPEED,
    TRAJECTORY_OFFLINE_MIN_SAMPLE_INTERVAL,
    VERIFIED_HAPPY_WAVE_TEMPLATE,
    VERIFIED_HAPPY_WAVE_TEMPLATE_NAME,
    compile_body_sequence,
    compile_motion_phrase,
    compile_motion_phrase_level,
    validate_motion_catalog,
)


class MotionCatalogTests(unittest.TestCase):
    def test_catalog_self_validation_passes(self):
        self.assertTrue(validate_motion_catalog())

    def test_arm_atoms_never_write_support_joints(self):
        for atom_name, atom in BODY_ATOM_CONTRACTS.items():
            if atom["required_support_pose"] != "calibrated_upright_hold":
                continue
            ids = {sid for sid, _position in atom["positions"]}
            self.assertTrue(ids <= ARM_SERVO_IDS, atom_name)
            self.assertFalse(ids & SUPPORT_SERVO_IDS, atom_name)

    def test_happy_wiggle_compiles_verified_anchors_into_one_continuous_trajectory(self):
        compiled = compile_body_sequence("happy_wiggle", intensity=1.0)
        self.assertEqual(compiled["execution_mode"], "continuous_trajectory")
        self.assertTrue(compiled["continuous_blending"])
        self.assertEqual(compiled["primitive_sequence"], [
            "raise_and_open_both_arms",
            "sway_both_hands",
            "lower_both_arms",
        ])
        self.assertEqual(
            [keyframe["atom"] for keyframe in compiled["keyframes"][:3]],
            ["arms_idle", "happy_wave_open", "happy_wave_sway_a"],
        )
        self.assertGreater(compiled["trajectory_frame_count"], 40)
        self.assertEqual(compiled["steps"][-1]["positions"], ARM_IDLE_POSE)
        self.assertEqual(compiled["expected_final_pose"], "return_idle")
        self.assertEqual(compiled["return_policy"], "idle")
        self.assertEqual(compiled["sway_steps"], 4)

    def test_continuous_trajectory_is_bounded_deterministic_and_arm_only(self):
        first = compile_body_sequence("happy_wiggle", intensity=1.0)
        second = compile_body_sequence("happy_wiggle", intensity=1.0)
        self.assertEqual(first, second)
        self.assertLessEqual(first["max_frame_delta"], TRAJECTORY_MAX_FRAME_DELTA)
        for frame in first["steps"]:
            self.assertTrue({sid for sid, _position in frame["positions"]} <= ARM_SERVO_IDS)
            self.assertGreater(frame["duration"], frame["wait_duration"] if frame is not first["steps"][-1] else 0)
            for _sid, position in frame["positions"]:
                self.assertGreaterEqual(position, 100)
                self.assertLessEqual(position, 900)

    def test_continuous_trajectory_sends_each_verified_anchor_without_duplicate_hold_step(self):
        compiled = compile_body_sequence("happy_wiggle", intensity=1.0)
        anchor_frames = {
            (frame["anchor_atom"], frame["time"]): frame
            for frame in compiled["steps"]
        }
        for keyframe in compiled["keyframes"][1:]:
            self.assertIn((keyframe["atom"], keyframe["time"]), anchor_frames)
        self.assertNotEqual(
            compiled["steps"][-2]["positions"],
            compiled["steps"][-1]["positions"],
        )

    def test_continuous_trajectory_has_no_close_packed_frames_and_passes_kinematic_audit(self):
        compiled = compile_motion_phrase("happy_greeting", {
            "expressive_intensity": 1.0,
            "openness": 1.0,
            "tempo": 1.2,
            "cycles": 2,
        })
        audit = compiled["kinematic_audit"]
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["violations"], [])
        self.assertGreaterEqual(
            audit["min_sample_interval"],
            TRAJECTORY_OFFLINE_MIN_SAMPLE_INTERVAL,
        )
        self.assertLessEqual(
            audit["max_curve_speed_pulse_per_second"],
            TRAJECTORY_OFFLINE_MAX_CURVE_SPEED,
        )
        self.assertLessEqual(
            audit["max_curve_acceleration_pulse_per_second2"],
            TRAJECTORY_OFFLINE_MAX_CURVE_ACCELERATION,
        )
        self.assertLessEqual(
            audit["max_curve_jerk_pulse_per_second3"],
            TRAJECTORY_OFFLINE_MAX_CURVE_JERK,
        )
        self.assertLessEqual(
            audit["max_command_speed_pulse_per_second"],
            TRAJECTORY_OFFLINE_MAX_COMMAND_SPEED,
        )

    def test_unverified_single_arm_primitives_stay_explicit_offline_candidates(self):
        for primitive_name in (
            "raise_left_arm",
            "raise_right_arm",
            "wave_left_hand",
            "wave_right_hand",
        ):
            primitive = BODY_MOTION_PRIMITIVE_CONTRACTS[primitive_name]
            self.assertEqual(primitive["verification"], "offline_candidate")
            self.assertTrue(set(primitive["active_joint_ids"]) <= ARM_SERVO_IDS)

    def test_motion_phrases_accept_only_normalized_genome_parameters(self):
        compiled = compile_motion_phrase("happy_greeting", {
            "expressive_intensity": 0.8,
            "openness": 0.7,
            "tempo": 1.1,
            "cycles": 2,
        })
        self.assertEqual(compiled["applied_genome"], {
            "expressive_intensity": 0.8,
            "tempo": 1.1,
            "openness": 0.7,
            "cycles": 2,
        })
        self.assertEqual(compiled["primitive_sequence"], [
            "raise_and_open_both_arms",
            "sway_both_hands",
            "lower_both_arms",
        ])
        self.assertEqual(compiled["steps"][-1]["positions"], ARM_IDLE_POSE)

    def test_motion_phrase_rejects_raw_servo_or_unbounded_model_fields(self):
        invalid_genomes = (
            {"pwm": {"6": 700}},
            {"expressive_intensity": 1.2},
            {"tempo": 2.0},
            {"cycles": 3},
            {"cycles": 2.0},
            {"hold_ms": 100},
        )
        for genome in invalid_genomes:
            with self.assertRaisesRegex(ValueError, "motion_genome_invalid"):
                compile_motion_phrase("happy_greeting", genome)

    def test_quiet_acknowledge_is_a_small_continuous_round_trip(self):
        compiled = compile_motion_phrase("quiet_acknowledge", {
            "expressive_intensity": 0.45,
            "amplitude": 0.2,
            "tempo": 0.9,
            "hold_ms": 300,
        })
        self.assertEqual(compiled["primitive_sequence"], [
            "raise_both_arms",
            "hold",
            "lower_both_arms",
        ])
        self.assertEqual(compiled["expected_final_pose"], "return_idle")
        self.assertEqual(compiled["steps"][-1]["positions"], ARM_IDLE_POSE)
        self.assertLess(compiled["max_frame_delta"], 20)
        for frame in compiled["steps"]:
            self.assertTrue({sid for sid, _position in frame["positions"]} <= ARM_SERVO_IDS)

    def test_motion_phrase_catalog_remains_offline_until_physical_acceptance(self):
        self.assertEqual(set(MOTION_PHRASE_CONTRACTS), {
            "happy_greeting",
            "quiet_acknowledge",
        })
        for phrase in MOTION_PHRASE_CONTRACTS.values():
            self.assertEqual(
                phrase["verification"],
                "offline_candidate_uses_verified_anchors",
            )

    def test_supervised_acceptance_levels_are_fixed_bounded_round_trips(self):
        self.assertEqual(
            set(MOTION_PHRASE_LEVEL_PROFILES),
            {"happy_greeting", "quiet_acknowledge"},
        )
        for phrase_name, profiles in MOTION_PHRASE_LEVEL_PROFILES.items():
            self.assertEqual(set(profiles), {"low", "medium", "high"})
            for level, genome in profiles.items():
                compiled = compile_motion_phrase_level(phrase_name, level)
                self.assertEqual(compiled["acceptance_level"], level)
                self.assertEqual(compiled["applied_genome"], genome)
                self.assertTrue(compiled["kinematic_audit"]["passed"])
                self.assertEqual(compiled["steps"][-1]["positions"], ARM_IDLE_POSE)
                self.assertEqual(
                    compiled["execution_mode"],
                    "hardware_interpolated_segments",
                )
                if phrase_name == "quiet_acknowledge":
                    self.assertEqual(compiled["hardware_command_count"], 2)
                    self.assertEqual(
                        compiled["applied_genome"]["amplitude"],
                        genome["amplitude"],
                    )
                    self.assertEqual(compiled["steps"][1]["primitive"], "hold")
                    self.assertIn("wait_only", compiled["steps"][1])
                    self.assertNotIn("positions", compiled["steps"][1])
                else:
                    expected_commands = 7 if level == "low" else 9
                    expected_sway_steps = 2 if level == "low" else 4
                    expected_duration = 1.15 if level == "low" else 1.45
                    self.assertEqual(
                        compiled["hardware_command_count"],
                        expected_commands,
                    )
                    self.assertEqual(
                        compiled["sway_steps"],
                        expected_sway_steps,
                    )
                    self.assertEqual(
                        compiled["source_template"],
                        VERIFIED_HAPPY_WAVE_TEMPLATE_NAME,
                    )
                    self.assertEqual(compiled["source_template_frame_count"], 10)
                    self.assertEqual(
                        compiled["template_frame_count"],
                        6 if level == "low" else 8,
                    )
                    self.assertEqual(
                        compiled["template_duration"],
                        expected_duration,
                    )
                    self.assertGreaterEqual(
                        compiled["clearance_scale"],
                        compiled["amplitude_scale"],
                    )
                    self.assertGreaterEqual(
                        compiled["right_clearance_scale"],
                        compiled["amplitude_scale"],
                    )
                    self.assertGreaterEqual(
                        compiled["left_clearance_scale"],
                        compiled["right_clearance_scale"],
                    )
                    self.assertTrue(compiled["preserves_frame_order"])
                    self.assertTrue(compiled["preserves_frame_timing"])
                    self.assertTrue(compiled["preserves_cycle_boundary"])
                    self.assertEqual(compiled["recovery_waypoint_count"], 1)
                    self.assertEqual(
                        compiled["recovery_waypoints"],
                        ["happy_greeting_return_approach"],
                    )
                    self.assertEqual(
                        compiled["recovery_waypoint"],
                        "happy_greeting_return_approach",
                    )
                    self.assertEqual(
                        compiled["collision_clearance_policy"],
                        (
                            "verified_low_landing_corridor_then_single_recovery"
                            if level != "low"
                            else "left_biased_clear_body_before_idle"
                        ),
                    )
                    self.assertEqual(
                        compiled["landing_left_forward_pulses"],
                        None if level == "low" else (433, 497),
                    )
                    self.assertEqual(
                        compiled["landing_tempo"],
                        None if level == "low" else 0.87,
                    )
                    self.assertTrue(all(
                        "positions" in step for step in compiled["steps"]
                    ))
                    for step in compiled["steps"]:
                        self.assertEqual(
                            {sid for sid, _position in step["positions"]},
                            ARM_SERVO_IDS,
                        )

        with self.assertRaisesRegex(ValueError, "motion_acceptance_profile_invalid"):
            compile_motion_phrase_level("happy_greeting", "extreme")

    def test_happy_greeting_preserves_verified_wave_order_and_timing(self):
        atoms_by_source_frame = {
            1: "arms_idle",
            2: "happy_wave_ready",
            3: "happy_wave_open",
            4: "happy_wave_sway_a",
            5: "happy_wave_sway_b",
            6: "happy_wave_sway_a",
            7: "happy_wave_sway_b",
            10: "arms_idle",
        }
        idle = dict(ARM_IDLE_POSE)
        maximum_offsets = []
        for level in ("low", "medium", "high"):
            compiled = compile_motion_phrase_level("happy_greeting", level)
            source_indices = (
                [1, 2, 3, 4, 5, 10]
                if level == "low"
                else [1, 2, 3, 4, 5, 6, 7, 10]
            )
            recovery_atoms = ["happy_greeting_return_approach"]
            execution_sources = [
                *source_indices[:-1],
                *([None] * len(recovery_atoms)),
                source_indices[-1],
            ]
            expected_sway_steps = 2 if level == "low" else 4
            self.assertEqual(compiled["sway_steps"], expected_sway_steps)
            sway_steps = [
                step for step in compiled["steps"]
                if step["primitive"] == "sway_both_hands"
            ]
            self.assertEqual(len(sway_steps), expected_sway_steps)
            self.assertEqual(sway_steps[-1]["atom"], "happy_wave_sway_b")
            self.assertEqual(
                [step["atom"] for step in compiled["steps"]],
                [
                    *[
                        atoms_by_source_frame[index]
                        for index in source_indices[:-1]
                    ],
                    *recovery_atoms,
                    "arms_idle",
                ],
            )
            expected_durations = [
                round(
                    VERIFIED_HAPPY_WAVE_TEMPLATE[index - 1][0]
                    / (
                        0.87
                        if level != "low" and index == source_indices[-1]
                        else MOTION_PHRASE_LEVEL_PROFILES[
                            "happy_greeting"
                        ][level]["tempo"]
                    ),
                    4,
                )
                for index in source_indices
            ]
            expected_durations = expected_durations[:-1]
            recovery_duration = round(
                HAPPY_WAVE_RETURN_APPROACH_DURATION
                / (
                    0.87
                    if level != "low"
                    else MOTION_PHRASE_LEVEL_PROFILES[
                        "happy_greeting"
                    ][level]["tempo"]
                ),
                4,
            )
            expected_durations.extend([
                *([recovery_duration] * len(recovery_atoms)),
                round(
                    VERIFIED_HAPPY_WAVE_TEMPLATE[
                        source_indices[-1] - 1
                    ][0]
                    / (
                        0.87
                        if level != "low"
                        else MOTION_PHRASE_LEVEL_PROFILES[
                            "happy_greeting"
                        ][level]["tempo"]
                    ),
                    4,
                ),
            ])
            self.assertEqual(
                [step["duration"] for step in compiled["steps"]],
                expected_durations,
            )
            self.assertEqual(
                [step["wait_duration"] for step in compiled["steps"]],
                expected_durations,
            )
            self.assertEqual(
                [step["source_frame"] for step in compiled["steps"]],
                execution_sources,
            )
            recovery_index = 0
            for step, source_index in zip(
                compiled["steps"],
                execution_sources,
            ):
                if source_index is None:
                    recovery_atom = recovery_atoms[recovery_index]
                    recovery_index += 1
                    self.assertEqual(
                        step["positions"],
                        HAPPY_GREETING_RETURN_APPROACH_POSE,
                    )
                    self.assertEqual(
                        step["derived_from_verified_atoms"],
                        [
                            "happy_wiggle_return_clear",
                            "happy_wiggle_return_approach",
                        ],
                    )
                    continue
                _duration, source_positions = (
                    VERIFIED_HAPPY_WAVE_TEMPLATE[source_index - 1]
                )
                actual = dict(step["positions"])
                for sid, source_position in source_positions:
                    self.assertGreaterEqual(
                        actual[sid],
                        min(idle[sid], source_position),
                    )
                    self.assertLessEqual(
                        actual[sid],
                        max(idle[sid], source_position),
                    )
            self.assertEqual(compiled["steps"][0]["positions"], ARM_IDLE_POSE)
            self.assertEqual(compiled["steps"][-1]["positions"], ARM_IDLE_POSE)
            maximum_offsets.append(max(
                abs(position - idle[sid])
                for step in compiled["steps"]
                for sid, position in step["positions"]
            ))
        self.assertEqual(maximum_offsets, sorted(maximum_offsets))
        self.assertGreater(maximum_offsets[-1], maximum_offsets[0])

    def test_happy_greeting_low_applies_slow_tempo_to_real_hardware_segments(self):
        compiled = compile_motion_phrase_level("happy_greeting", "low")
        self.assertEqual(compiled["applied_genome"]["tempo"], 0.87)
        self.assertEqual(compiled["timing_scale"], round(1.0 / 0.87, 4))
        self.assertGreater(compiled["total_duration"], 1.43)
        self.assertTrue(compiled["preserves_relative_frame_timing"])
        self.assertFalse(compiled["preserves_exact_source_timing"])
        self.assertTrue(
            BODY_ATOM_CONTRACTS[
                "happy_greeting_return_approach"
            ]["verified"]
        )
        self.assertTrue(
            compiled["kinematic_audit"]["recovery_anchor_verified"]
        )

    def test_every_motion_genome_boundary_combination_stays_compilable_and_bounded(self):
        compiled_results = []
        for values in product((0.35, 1.0), (0.35, 1.0), (0.8, 1.2), (1, 2)):
            compiled_results.append(compile_motion_phrase("happy_greeting", dict(zip(
                ("expressive_intensity", "openness", "tempo", "cycles"),
                values,
            ))))
        for values in product((0.35, 1.0), (0.1, 1.0), (0.8, 1.2), (0, 800)):
            compiled_results.append(compile_motion_phrase("quiet_acknowledge", dict(zip(
                ("expressive_intensity", "amplitude", "tempo", "hold_ms"),
                values,
            ))))
        self.assertEqual(len(compiled_results), 32)
        for compiled in compiled_results:
            self.assertLessEqual(compiled["max_frame_delta"], TRAJECTORY_MAX_FRAME_DELTA)
            self.assertTrue(compiled["kinematic_audit"]["passed"])
            self.assertEqual(compiled["steps"][-1]["positions"], ARM_IDLE_POSE)

    def test_happy_wiggle_intensity_changes_only_bounded_arm_steps(self):
        compiled = compile_body_sequence("happy_wiggle", intensity=0.35)
        self.assertEqual(compiled["sway_steps"], 2)
        for step in compiled["steps"]:
            self.assertTrue({sid for sid, _position in step["positions"]} <= ARM_SERVO_IDS)
            for _sid, position in step["positions"]:
                self.assertGreaterEqual(position, 100)
                self.assertLessEqual(position, 900)

    def test_startup_recovery_is_the_only_full_body_sequence(self):
        compiled = compile_body_sequence("startup_recover")
        self.assertEqual([step["duration"] for step in compiled["steps"]], [1.4, 0.4])
        self.assertEqual(compiled["steps"][0]["positions"], FULL_IDLE_POSE)
        self.assertEqual(compiled["steps"][1]["positions"], FULL_IDLE_POSE)
        self.assertEqual(compiled["contract"]["resources"], ["body", "gaze"])
        self.assertEqual(compiled["contract"]["compatible_resources"], [])

    def test_invalid_intensity_never_reaches_sequence_compilation(self):
        for value in (0.2, 1.1, "0.7", True, float("nan")):
            with self.assertRaisesRegex(ValueError, "parameters_invalid"):
                compile_body_sequence("hands_ready", intensity=value)


if __name__ == "__main__":
    unittest.main()
