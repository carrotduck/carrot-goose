#!/usr/bin/env python3
"""Small, dependency-free DS18B20 reader for TonyPi.

The Linux 1-Wire driver exposes each probe as
``/sys/bus/w1/devices/28-*/w1_slave``.  This module only reads that
interface; it never changes GPIO configuration or writes to the robot.
"""

from __future__ import annotations

import re
import statistics
import time
from pathlib import Path


DEFAULT_W1_ROOT = Path("/sys/bus/w1/devices")
DS18B20_FAMILY_PREFIX = "28-"
POWER_ON_SENTINEL_MILLI_C = 85000
MIN_MILLI_C = -55000
MAX_MILLI_C = 125000


class TemperatureSensorError(RuntimeError):
    """Base error for a missing or unreadable temperature probe."""


class TemperatureSensorNotFound(TemperatureSensorError):
    pass


class TemperatureSensorAmbiguous(TemperatureSensorError):
    pass


class TemperatureReadingInvalid(TemperatureSensorError):
    pass


def parse_w1_slave(text: str) -> float:
    """Parse and validate one Linux ``w1_slave`` response."""

    lines = str(text or "").strip().splitlines()
    if len(lines) < 2 or not lines[0].strip().endswith("YES"):
        raise TemperatureReadingInvalid("ds18b20_crc_not_ready")

    match = re.search(r"(?:^|\s)t=(-?\d+)(?:\s|$)", lines[1])
    if match is None:
        raise TemperatureReadingInvalid("ds18b20_temperature_missing")

    milli_c = int(match.group(1))
    if milli_c == POWER_ON_SENTINEL_MILLI_C:
        raise TemperatureReadingInvalid("ds18b20_power_on_sentinel")
    if not MIN_MILLI_C <= milli_c <= MAX_MILLI_C:
        raise TemperatureReadingInvalid("ds18b20_temperature_out_of_range")
    return round(milli_c / 1000.0, 3)


def discover_ds18b20(root=DEFAULT_W1_ROOT):
    """Return sorted DS18B20 ROM ids that expose a readable sysfs file."""

    root_path = Path(root)
    if not root_path.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root_path.iterdir()
        if entry.is_dir()
        and entry.name.startswith(DS18B20_FAMILY_PREFIX)
        and (entry / "w1_slave").is_file()
    )


class DS18B20Reader:
    """Resolve one probe and return bounded, median-filtered readings."""

    def __init__(
        self,
        sensor_id=None,
        root=DEFAULT_W1_ROOT,
        sample_count=3,
        retry_count=3,
        retry_delay=0.2,
        sleep=time.sleep,
        wall_clock=time.time,
    ):
        self.sensor_id = str(sensor_id or "").strip() or None
        self.root = Path(root)
        self.sample_count = max(1, int(sample_count))
        self.retry_count = max(1, int(retry_count))
        self.retry_delay = max(0.0, float(retry_delay))
        self._sleep = sleep
        self._wall_clock = wall_clock

    def resolve_sensor_id(self):
        sensor_ids = discover_ds18b20(self.root)
        if self.sensor_id:
            if self.sensor_id not in sensor_ids:
                raise TemperatureSensorNotFound(
                    f"configured_ds18b20_not_found:{self.sensor_id}"
                )
            return self.sensor_id
        if not sensor_ids:
            raise TemperatureSensorNotFound("ds18b20_not_found")
        if len(sensor_ids) > 1:
            raise TemperatureSensorAmbiguous(
                "multiple_ds18b20_probes:" + ",".join(sensor_ids)
            )
        self.sensor_id = sensor_ids[0]
        return self.sensor_id

    def _read_once(self, sensor_id):
        path = self.root / sensor_id / "w1_slave"
        try:
            return parse_w1_slave(path.read_text(encoding="ascii"))
        except OSError as error:
            raise TemperatureReadingInvalid(
                f"ds18b20_read_failed:{type(error).__name__}"
            ) from error

    def _read_with_retry(self, sensor_id):
        last_error = None
        for attempt in range(self.retry_count):
            try:
                return self._read_once(sensor_id)
            except TemperatureReadingInvalid as error:
                last_error = error
                if attempt + 1 < self.retry_count:
                    self._sleep(self.retry_delay)
        raise last_error or TemperatureReadingInvalid("ds18b20_read_failed")

    def read_celsius(self):
        sensor_id = self.resolve_sensor_id()
        samples = [self._read_with_retry(sensor_id) for _ in range(self.sample_count)]
        return round(float(statistics.median(samples)), 3)

    def snapshot(self):
        sensor_id = self.resolve_sensor_id()
        temperature_c = self.read_celsius()
        return {
            "sensor": "ds18b20",
            "sensor_id": sensor_id,
            "temperature_c": temperature_c,
            "sample_count": self.sample_count,
            "sampled_at_unix": round(float(self._wall_clock()), 3),
        }
