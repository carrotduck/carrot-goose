#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

from tonypi_temperature import (
    DS18B20Reader,
    TemperatureReadingInvalid,
    TemperatureSensorAmbiguous,
    TemperatureSensorNotFound,
    discover_ds18b20,
    parse_w1_slave,
)


def w1_payload(milli_c=32750, crc="YES"):
    return (
        f"9e 01 4b 46 7f ff 02 10 56 : crc=56 {crc}\n"
        f"9e 01 4b 46 7f ff 02 10 56 t={milli_c}\n"
    )


class DS18B20Tests(unittest.TestCase):
    def test_parse_valid_reading(self):
        self.assertEqual(parse_w1_slave(w1_payload()), 32.75)

    def test_parse_rejects_crc_and_power_on_sentinel(self):
        with self.assertRaisesRegex(TemperatureReadingInvalid, "crc_not_ready"):
            parse_w1_slave(w1_payload(crc="NO"))
        with self.assertRaisesRegex(TemperatureReadingInvalid, "power_on_sentinel"):
            parse_w1_slave(w1_payload(milli_c=85000))

    def test_discovery_and_median_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sensor = root / "28-000000000001"
            sensor.mkdir()
            (sensor / "w1_slave").write_text(w1_payload(), encoding="ascii")
            self.assertEqual(discover_ds18b20(root), [sensor.name])

            reader = DS18B20Reader(
                root=root,
                sample_count=3,
                retry_delay=0,
                sleep=lambda _seconds: None,
                wall_clock=lambda: 123.0,
            )
            self.assertEqual(reader.read_celsius(), 32.75)
            self.assertEqual(reader.snapshot()["sampled_at_unix"], 123.0)

    def test_missing_and_multiple_sensors_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = DS18B20Reader(root=directory, sample_count=1)
            with self.assertRaisesRegex(TemperatureSensorNotFound, "not_found"):
                reader.read_celsius()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix in ("1", "2"):
                sensor = root / f"28-00000000000{suffix}"
                sensor.mkdir()
                (sensor / "w1_slave").write_text(w1_payload(), encoding="ascii")
            reader = DS18B20Reader(root=root, sample_count=1)
            with self.assertRaisesRegex(TemperatureSensorAmbiguous, "multiple"):
                reader.read_celsius()

    def test_explicit_sensor_id_selects_one_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix, temp in (("1", 30000), ("2", 41000)):
                sensor = root / f"28-00000000000{suffix}"
                sensor.mkdir()
                (sensor / "w1_slave").write_text(
                    w1_payload(milli_c=temp), encoding="ascii"
                )
            reader = DS18B20Reader(
                sensor_id="28-000000000002",
                root=root,
                sample_count=1,
            )
            self.assertEqual(reader.read_celsius(), 41.0)


if __name__ == "__main__":
    unittest.main()
