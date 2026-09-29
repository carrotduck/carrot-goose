#!/usr/bin/env python3

import unittest

from tonypi_perception import classify_hand_landmarks


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def hand_with_extended(*extended_names):
    points = [Point(0.5, 0.75) for _ in range(21)]
    points[0] = Point(0.5, 0.9)
    joints = {
        "index": (5, 6, 7, 8, 0.35),
        "middle": (9, 10, 11, 12, 0.45),
        "ring": (13, 14, 15, 16, 0.55),
        "pinky": (17, 18, 19, 20, 0.65),
    }
    extended = set(extended_names)
    for name, (mcp, pip, dip, tip, x) in joints.items():
        points[mcp] = Point(x, 0.65)
        if name in extended:
            points[pip] = Point(x, 0.48)
            points[dip] = Point(x, 0.34)
            points[tip] = Point(x, 0.20)
        else:
            points[pip] = Point(x, 0.55)
            points[dip] = Point(x + 0.04, 0.60)
            points[tip] = Point(x + 0.08, 0.68)
    return points


class GestureClassifierTests(unittest.TestCase):
    def test_open_palm(self):
        result = classify_hand_landmarks(
            hand_with_extended("index", "middle", "ring", "pinky")
        )
        self.assertEqual(result["gesture"], "open_palm")
        self.assertEqual(len(result["extended_fingers"]), 4)

    def test_pointing(self):
        result = classify_hand_landmarks(hand_with_extended("index"))
        self.assertEqual(result["gesture"], "pointing")
        self.assertEqual(result["extended_fingers"], ["index"])

    def test_closed_fist(self):
        result = classify_hand_landmarks(hand_with_extended())
        self.assertEqual(result["gesture"], "closed_fist")
        self.assertEqual(result["extended_fingers"], [])

    def test_unmapped_gesture_stays_unknown(self):
        result = classify_hand_landmarks(hand_with_extended("index", "middle"))
        self.assertEqual(result["gesture"], "unknown")

    def test_invalid_landmark_count_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "21 hand landmarks"):
            classify_hand_landmarks([Point(0.0, 0.0)] * 20)


if __name__ == "__main__":
    unittest.main()
