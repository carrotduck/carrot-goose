#!/usr/bin/env python3

import unittest

import tonypi_control


class TonyPiControlModeTests(unittest.TestCase):
    def test_yushi_service_only_runs_in_yushi_mode(self):
        self.assertIn("yushi-client.service", tonypi_control.MANAGED_SERVICES)
        self.assertEqual(tonypi_control.MODE_SERVICES["yushi"], ("yushi-client.service",))
        for mode in tonypi_control.VALID_MODES - {"yushi"}:
            self.assertNotIn("yushi-client.service", tonypi_control.MODE_SERVICES[mode])

    def test_every_mode_has_a_service_policy(self):
        self.assertEqual(set(tonypi_control.MODE_SERVICES), tonypi_control.VALID_MODES)


if __name__ == "__main__":
    unittest.main()
