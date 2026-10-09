#!/usr/bin/env python3
"""Passive binary serial capture; timestamps describe host receipt, not wire timing."""
import argparse
from contextlib import ExitStack
import errno
import json
import math
from pathlib import Path
import sys
import time


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be finite and greater than zero')
    return number


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be greater than zero')
    return number


class Capture:
    def __init__(self, output, raw=None):
        self.output, self.raw = output, raw
        self.data = bytearray()
        self.start = self.end = self.last = None
        self.count = 0

    def feed(self, data, wall, mono):
        if not self.data:
            self.start = wall
        self.data.extend(data)
        self.end, self.last = wall, mono
        if self.raw is not None:
            self.raw.write(data)
            self.raw.flush()

    def finish(self, reason):
        if not self.data:
            return
        hex_data = self.data.hex(' ').upper()
        record = dict(ts=self.start, ts_end=self.end, data=hex_data,
                      length=len(self.data), reason=reason)
        self.output.write(json.dumps(record) + '\n')
        self.output.flush()
        ascii_data = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in self.data)
        self.data.clear()
        self.count += 1
        print(f'{record["ts"]:.6f}  len={record["length"]:4d}  '
              f'{hex_data}  |{ascii_data}|  [{reason}]', flush=True)


def capture_loop(port, capture, gap, verbose=False, wall_clock=time.time,
                 mono_clock=time.monotonic):
    previous = None
    reason = 'error'
    try:
        while True:
            data = port.read(1)
            mono, wall = mono_clock(), wall_clock()
            if capture.data and mono - capture.last > gap:
                capture.finish('gap')
            if data:
                capture.feed(data, wall, mono)
                if verbose:
                    delta = 'n/a' if previous is None else f'{(mono - previous) * 1000:.3f} ms'
                    print(f'BYTE {wall:.6f}  {data.hex(" ").upper()}  dt={delta}',
                          file=sys.stderr, flush=True)
                previous = mono
    except KeyboardInterrupt:
        reason = 'interrupted'
        raise
    finally:
        capture.finish(reason)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/cu.usbserial-1110')
    parser.add_argument('--baudrate', type=positive_int, default=10400)
    parser.add_argument('--frame-gap-ms', type=positive_float, default=20.0)
    parser.add_argument('--output', type=Path, default=Path('captures/kline.jsonl'))
    parser.add_argument('--raw', action='store_true', help='also save OUTPUT.bin')
    parser.add_argument('--verbose', action='store_true', help='log each byte and host receipt interval')
    args = parser.parse_args(argv)
    try:
        import serial
    except ImportError:
        print('Install dependency: python3 -m pip install pyserial', file=sys.stderr)
        return 1
    raw_path = Path(str(args.output) + '.bin')
    gap = args.frame_gap_ms / 1000
    print(f'port={args.port} baudrate={args.baudrate} format=8N1 '
          f'frame_gap_ms={args.frame_gap_ms:g} output={args.output} '
          f'raw={raw_path if args.raw else "off"} verbose={args.verbose}', flush=True)
    print('Passive read; timing is measured at host receipt. Ctrl+C to stop.', flush=True)
    try:
        with ExitStack() as stack:
            # Configure control lines before opening. No write/break/init commands.
            port = serial.Serial(port=None, baudrate=args.baudrate,
                                 timeout=min(gap / 4, 0.005),
                                 xonxoff=False, rtscts=False, dsrdtr=False,
                                 exclusive=True)
            stack.callback(port.close)
            port.dtr = False
            port.rts = False
            port.port = args.port
            # Refuse overwrite before opening hardware or creating output.
            if args.output.exists() or (args.raw and raw_path.exists()):
                raise FileExistsError('Capture output already exists; choose a new --output')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            output = stack.enter_context(args.output.open('x', encoding='utf-8'))
            raw = stack.enter_context(raw_path.open('xb')) if args.raw else None
            capture = Capture(output, raw)
            port.open()
            try:
                capture_loop(port, capture, gap, args.verbose)
            except KeyboardInterrupt:
                print(f'Capture stopped. Saved frames: {capture.count}', file=sys.stderr)
                return 0
    except PermissionError as exc:
        print(f'Permission denied (serial port or output): {exc}', file=sys.stderr)
        return 1
    except serial.SerialException as exc:
        if getattr(exc, 'errno', None) in (errno.EACCES, errno.EPERM):
            message = 'Permission denied opening serial port'
        elif getattr(exc, 'errno', None) == errno.ENOENT:
            message = 'Serial port not found'
        else:
            message = 'Serial error: port unavailable, disconnected, busy, or unsupported baudrate'
        print(f'{message}: {exc}', file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f'Capture failed: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Stopped.', file=sys.stderr)
        return 0


if __name__ == '__main__':
    sys.exit(main())
