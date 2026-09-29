"""Bounded read-only Pi sampler. Import is offline; hardware requires --run.

Wire format checked against local SDK backups. No SDK/action module imported.
Only bus temperature (09) and voltage (07) queries can be transmitted.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
import subprocess
import time

IDS = (14, 15, 16, 6, 7, 8)
SERVICES = ('yushi-client.service', 'tonypi.service', 'joystick.service',
            'multi_control_client.service', 'multi_control_server.service')
OWNER = Path('/home/pi/yushi/control_owner')


class StopSampling(RuntimeError):
    pass


def crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8C if crc & 1 else 0)
    return crc


def request_packet(sid, command):
    if type(sid) is not int or sid not in IDS or command not in (0x09, 0x07):
        raise StopSampling('request_not_allowed')
    body = bytes((5, 2, command, sid))
    return b'\xaa\x55' + body + bytes((crc8(body),))


class Frames:
    def __init__(self, initial_sync=False, max_discard=512, max_gap_zeros=8):
        self.buffer = bytearray()
        self.synchronizing = initial_sync
        self.max_discard = max_discard
        self.discarded = bytearray()
        self.seen_frame = False
        self.gap_zeros = 0
        self.total_gap_zeros = 0
        self.total_header_overlaps = 0
        self.max_gap_zeros = max_gap_zeros

    def discard_one(self):
        if len(self.discarded) >= self.max_discard:
            raise StopSampling('initial_sync_byte_limit')
        self.discarded.append(self.buffer.pop(0))

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while self.buffer:
            # SDK waits for AA between complete frames, not only zero padding.
            # Live capture also contains 79 after a CRC-valid servo reply.
            # Bound skipped interframe bytes; never skip bytes inside a frame.
            if not self.synchronizing and self.seen_frame and self.buffer[0] != 0xAA:
                if self.gap_zeros >= self.max_gap_zeros:
                    raise StopSampling('interframe_byte_limit')
                if self.buffer[0] == 0:
                    self.total_gap_zeros += 1
                del self.buffer[0]
                self.gap_zeros += 1
                continue
            if len(self.buffer) < 2:
                break
            if self.buffer[:2] != b'\xaa\x55':
                if self.synchronizing:
                    self.discard_one()
                    continue
                # After a verified frame, AA AA is an overlapping candidate
                # header, not yet a malformed packet. Keep the latter AA and
                # require the complete next packet/CRC before yielding data.
                # Share the existing interframe skip budget; never scan inside
                # an accepted AA 55 header, payload or failed CRC.
                if self.seen_frame and self.buffer[:2] == b'\xaa\xaa':
                    if self.gap_zeros >= self.max_gap_zeros:
                        raise StopSampling('interframe_byte_limit')
                    del self.buffer[0]
                    self.gap_zeros += 1
                    self.total_header_overlaps += 1
                    continue
                raise StopSampling('stream_alignment_unknown')
            if len(self.buffer) < 4:
                break
            function, size = self.buffer[2:4]
            if function >= 12 or size > 128:
                if self.synchronizing:
                    self.discard_one()
                    continue
                raise StopSampling('invalid_frame_header')
            if len(self.buffer) < size + 5:
                break
            raw = bytes(self.buffer[:size + 5])
            if crc8(raw[2:-1]) != raw[-1]:
                if self.synchronizing:
                    self.discard_one()
                    continue
                raise StopSampling('crc_error')
            del self.buffer[:size + 5]
            self.synchronizing = False
            self.seen_frame = True
            self.gap_zeros = 0
            frames.append((function, raw[4:-1], raw.hex()))
        return frames


def decode_reply(payload, sid, command):
    expected = 4 if command == 9 else 5
    if len(payload) != expected:
        raise StopSampling('reply_length')
    rid, cmd, status = struct.unpack('<BBb', payload[:3])
    if (rid, cmd) != (sid, command):
        raise StopSampling('reply_identity_mismatch')
    if status != 0:
        raise StopSampling('device_error:' + str(status))
    return payload[3] if command == 9 else struct.unpack('<H', payload[3:])[0]


class ThermalGate:
    def __init__(self):
        self.baseline = {}

    def check(self, sid, value):
        if type(value) is not int or not 0 <= value <= 125:
            raise StopSampling('temperature_implausible')
        if sid not in self.baseline:
            if value >= 40:
                raise StopSampling('initial_temperature_at_least_40')
            self.baseline[sid] = value
        if value >= 45 or value - self.baseline[sid] >= 5:
            raise StopSampling('temperature_rise_or_limit')


def voltage_gate(value):
    if not 11000 <= value <= 12600:
        raise StopSampling('voltage_outside_diagnostic_range')


class Sampler:
    make_request = staticmethod(request_packet)
    parse_reply = staticmethod(decode_reply)

    def __init__(self, port, deadline, emit, ensure_owner, clock=time.monotonic, sleep=time.sleep):
        self.port, self.deadline, self.emit = port, deadline, emit
        self.ensure_owner, self.clock = ensure_owner, clock
        self.sleep = sleep
        self.frames, self.sequence = Frames(), 0
        self.battery = None
        self.rx_tail = bytearray()

    def battery_frame(self, payload, raw, received, buffered=False):
        if len(payload) != 3:
            raise StopSampling('battery_length')
        value = struct.unpack('<H', payload[1:])[0]
        self.emit(dict(kind='battery', value_mv=value, received=received,
                       raw=raw, buffered_before_request=buffered))
        voltage_gate(value)
        # Buffered bytes have unknown arrival time: never mark them fresh.
        if not buffered:
            self.battery = (value, received)

    def drain_before_request(self, until):
        """Remove pre-request telemetry; abort if an unsolicited bus reply exists."""
        drained = 0
        pending_at_start = self.port.in_waiting
        if pending_at_start > 32768:
            raise StopSampling('pre_request_backlog_limit')
        end = min(self.clock() + .25, until)
        # Drain only the initial backlog, completing its last partial frame.
        # New periodic telemetry must not keep this loop alive indefinitely.
        while drained < pending_at_start or self.frames.buffer:
            self.ensure_owner()
            if self.clock() >= end or drained >= 32768:
                raise StopSampling('pre_request_drain_limit')
            byte = self.port.read(1)
            if not byte:
                continue
            drained += len(byte)
            received = self.clock()
            for function, payload, raw in self.receive(byte, received):
                if function == 5:
                    self.emit(dict(kind='unexpected_bus_reply', raw=raw, received=received))
                    raise StopSampling('bus_reply_before_request')
                if function == 0 and payload[:1] == b'\x04':
                    self.battery_frame(payload, raw, received, buffered=True)
        if drained:
            self.emit(dict(kind='pre_request_drain', bytes=drained))

    def receive(self, byte, received):
        self.rx_tail.extend(byte)
        del self.rx_tail[:-256]
        try:
            return self.frames.feed(byte)
        except StopSampling as error:
            self.emit(dict(kind='receive_error', reason=str(error), received=received,
                           raw_tail=self.rx_tail.hex(),
                           discarded_prefix=self.frames.discarded.hex()))
            raise

    def synchronize(self):
        """Find a CRC-valid passive frame before sending any request, once only."""
        self.ensure_owner()
        until = min(self.clock() + 1, self.deadline)
        # Passive capture found the first valid frame at ~75ms. At 1Mbaud,
        # 512 bytes can be exhausted in milliseconds; retain the 1s deadline
        # and use a separate finite startup budget, never for interframe gaps.
        self.frames = Frames(initial_sync=True, max_discard=16384)
        while self.clock() < until:
            byte = self.port.read(1)
            received = self.clock()
            if received >= until:
                break
            if not byte:
                continue
            for function, payload, raw in self.receive(byte, received):
                if function == 5:
                    self.emit(dict(kind='unexpected_bus_reply', raw=raw, received=received))
                    raise StopSampling('bus_reply_before_request')
                self.emit(dict(kind='initial_sync_complete', received=received, raw=raw,
                               discarded_prefix=self.frames.discarded.hex(),
                               discarded_count=len(self.frames.discarded)))
                return
        self.emit(dict(kind='receive_error', reason='initial_sync_timeout',
                       raw_tail=self.rx_tail.hex(), discarded_prefix=self.frames.discarded.hex()))
        raise StopSampling('initial_sync_timeout')

    def read(self, sid, command, round_deadline):
        self.ensure_owner()
        started = self.clock()
        until = min(started + 1.0, self.deadline, round_deadline)
        if started >= until:
            raise StopSampling('deadline')
        self.drain_before_request(until)
        self.ensure_owner()
        started = self.clock()
        if started >= until:
            raise StopSampling('deadline')
        # No retry after failure. One in-flight query, entire session exclusive.
        self.sequence += 1
        packet = self.make_request(sid, command)
        if self.port.write(packet) != len(packet):
            raise StopSampling('short_write')
        while self.clock() < until:
            byte = self.port.read(1)
            if not byte:
                continue
            received = self.clock()
            if received >= until:
                raise StopSampling('late_reply')
            for function, payload, raw in self.receive(byte, received):
                if function == 0 and payload[:1] == b'\x04':
                    self.battery_frame(payload, raw, received)
                elif function == 5:
                    self.emit(dict(kind='reply', sequence=self.sequence, servo_id=sid,
                                   command=command, requested=started, received=received, raw=raw))
                    value = self.parse_reply(payload, sid, command)
                    self.emit(dict(kind='value', sequence=self.sequence, servo_id=sid,
                                   command=command, value=value, valid=True,
                                   requested=started, received=received))
                    return value
        self.emit(dict(kind='receive_error', reason='query_timeout',
                       sequence=self.sequence, raw_tail=self.rx_tail.hex()))
        raise StopSampling('query_timeout')

    def run(self):
        gate = ThermalGate()
        start = self.clock()
        for index in range(6):
            due = start + index * 10
            self.idle_until(min(due, self.deadline))
            if self.clock() >= self.deadline:
                raise StopSampling('total_deadline')
            round_end = min(self.clock() + 8, self.deadline)
            self.emit(dict(kind='round', index=index))
            for sid in IDS:
                value = self.read(sid, 9, round_end)
                gate.check(sid, value)
            for sid in (14, 15, 16):
                voltage_gate(self.read(sid, 7, round_end))
            if self.battery is None or self.clock() - self.battery[1] > 2:
                self.wait_fresh_battery(round_end)

    def idle_until(self, due):
        """Continue consuming telemetry between rounds instead of filling UART buffers."""
        while self.clock() < due:
            self.ensure_owner()
            byte = self.port.read(1)
            received = self.clock()
            if received >= self.deadline:
                raise StopSampling('total_deadline')
            if not byte:
                continue
            for function, payload, raw in self.receive(byte, received):
                if function == 5:
                    self.emit(dict(kind='unexpected_bus_reply', raw=raw, received=received))
                    raise StopSampling('bus_reply_between_rounds')
                if function == 0 and payload[:1] == b'\x04':
                    self.battery_frame(payload,raw,received)

    def wait_fresh_battery(self, round_deadline):
        """Allow the next periodic battery report to arrive without any query."""
        until = min(self.clock()+.5, round_deadline, self.deadline)
        self.drain_before_request(until)
        while self.clock() < until:
            self.ensure_owner()
            byte = self.port.read(1)
            received = self.clock()
            if received >= until:
                break
            if not byte:
                continue
            for function, payload, raw in self.receive(byte, received):
                if function == 5:
                    self.emit(dict(kind='unexpected_bus_reply', raw=raw, received=received))
                    raise StopSampling('bus_reply_while_waiting_battery')
                if function == 0 and payload[:1] == b'\x04':
                    self.battery_frame(payload,raw,received)
                    return
        raise StopSampling('battery_missing_or_stale')


def passive_link_check(port, deadline, emit, ensure, clock=time.monotonic):
    """Observe startup traffic for <=3 seconds, never transmit or accept temperatures.

The larger byte budget is diagnostic only; it does not relax Sampler gates.
"""
    started = clock()
    until = min(started + 3, deadline)
    count = zeros = valid = errors = 0
    first_nonzero = first_valid = None
    prefix, tail = bytearray(), bytearray()
    parser = Frames(initial_sync=True, max_discard=300000)
    functions = {}
    while clock() < until and count < 300000:
        ensure()
        data = port.read(min(256, 300000-count))
        now = clock()
        if now >= until:
            break
        count += len(data)
        zeros += data.count(0)
        prefix.extend(data[:max(0,64-len(prefix))])
        tail.extend(data)
        del tail[:-64]
        if first_nonzero is None and any(data):
            first_nonzero = now-started
        # Diagnostic recovery never grants permission to send a request.
        for byte in data:
            try:
                frames = parser.feed(bytes((byte,)))
            except StopSampling:
                errors += 1
                parser = Frames(initial_sync=True, max_discard=300000)
                frames = []
            for function, _, _ in frames:
                valid += 1
                functions[str(function)] = functions.get(str(function),0)+1
                if first_valid is None:
                    first_valid = now-started
    result = dict(kind='passive_link_summary', bytes=count, zero_bytes=zeros,
                  crc_valid_frames=valid, parser_errors=errors, functions=functions,
                  first_nonzero_seconds=first_nonzero, first_valid_seconds=first_valid,
                  prefix_hex=prefix.hex(), tail_hex=tail.hex(),
                  duration=clock()-started, byte_budget_reached=count>=300000,
                  queries_sent=0, temperature_validated=False)
    emit(result)
    return result


def ensure_owner():
    if OWNER.read_text().strip() != 'studio':
        raise StopSampling('owner_not_studio')


def check_services_and_port():
    ensure_owner()
    for name in SERVICES:
        result = subprocess.run(['systemctl', 'is-active', name], capture_output=True,
                                text=True, timeout=1)
        if result.stdout.strip() not in ('inactive', 'failed'):
            raise StopSampling('service_not_inactive:' + name)
    # Refuse other open users of this serial device; no process termination.
    target = os.path.realpath('/dev/ttyAMA0')
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    if os.path.realpath(fd) == target:
                        raise StopSampling('serial_port_in_use:' + process.name)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
        except PermissionError:
            raise StopSampling('cannot_verify_serial_ownership')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--link-check', action='store_true', help='Only observe serial traffic for <=3 seconds; zero transmitted bytes')
    parser.add_argument('--power-on-time', help='Optional actual user-observed ISO8601 time; never estimate from wall clock')
    args = parser.parse_args()
    if not args.run:
        parser.print_help()
        return 0
    observed = datetime.fromisoformat(args.power_on_time) if args.power_on_time else None
    if observed is not None and observed.tzinfo is None:
        parser.error('power-on time must include timezone')
    import signal
    import fcntl
    import serial
    start = time.monotonic()

    def emit(data):
        print(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(),
                              elapsed=round(time.monotonic()-start, 3), **data)), flush=True)

    def stop_signal(*_):
        raise StopSampling('signal_or_total_deadline')

    signal.signal(signal.SIGALRM, stop_signal)
    signal.signal(signal.SIGTERM, stop_signal)
    total_seconds = 10 if args.link_check else 60
    signal.setitimer(signal.ITIMER_REAL, total_seconds)
    code = 1
    try:
        boot_age = float(Path('/proc/uptime').read_text().split()[0])
        emit(dict(kind='start', power_on_time=observed.isoformat() if observed else None,
                  power_on_time_source='user_observed' if observed else 'unknown',
                  os_uptime_seconds=boot_age, no_motion=True,
                  mode='passive_link_check' if args.link_check else 'thermal_sample'))
        with ExitStack() as stack:
            for path in ('/home/pi/yushi/yushi_client.lock', '/tmp/tonypi-controller-serial.lock'):
                lock = stack.enter_context(open(path, 'a'))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            check_services_and_port()
            port = serial.Serial(None, 1000000, timeout=.05, write_timeout=.2, exclusive=True)
            stack.callback(port.close)
            port.rts = False
            port.dtr = False
            port.port = '/dev/ttyAMA0'
            port.open()
            emit(dict(kind='serial_settings', settings=port.get_settings(),
                      port=port.port, serial_module=serial.__file__,
                      exclusive=port.exclusive, rts=port.rts, dtr=port.dtr))
            import termios
            attributes = termios.tcgetattr(port.fileno())
            emit(dict(kind='kernel_serial_settings', input_flags=attributes[0],
                      output_flags=attributes[1], control_flags=attributes[2],
                      local_flags=attributes[3], input_speed_code=attributes[4],
                      output_speed_code=attributes[5]))
            if args.link_check:
                passive_link_check(port,start+total_seconds,emit,ensure_owner)
                emit(dict(kind='diagnostic_finished', queries_sent=0))
                return 0
            discarded = port.in_waiting
            port.reset_input_buffer()
            emit(dict(kind='initial_input_discarded', byte_count=discarded))
            sampler = Sampler(port, start + 60, emit, ensure_owner)
            sampler.synchronize()
            sampler.run()
            code = 0
            emit(dict(kind='completed', rounds=6))
    except (Exception, KeyboardInterrupt) as error:
        emit(dict(kind='stopped', error=type(error).__name__, reason=str(error)))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        emit(dict(kind='power_off_reminder', message='Support robot and switch power off; no torque commands sent.'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
