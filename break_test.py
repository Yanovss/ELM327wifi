#!/usr/bin/env python3
"""CH34x BREAK test: TX must still be shorted to RX.

A UART BREAK holds the TX line low beyond one character frame. With TX looped
to RX, a sustained low is received as a run of 0x00 bytes (framing errors
deliver 0x00 in pyserial). By counting how many 0x00 arrive for a requested
BREAK duration we can estimate whether the chip actually held the line low for
the full nonstandard interval a K-Line fast-init wakeup (~25 ms) needs.

This is an indirect estimate at the host, not a wire measurement, but a chip
that cannot sustain BREAK will show far fewer 0x00 than expected (or none).
"""
import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/cu.usbserial-110'
BAUD = 10400
# At 10400 8N1 one byte frame ~0.962 ms. A 25 ms low ~= 26 byte-times of 0x00.
DURATIONS_MS = [1, 5, 10, 25, 50]


def expected_zeros(ms):
    frame_s = 10 / BAUD  # 8N1 -> 10 bit-times per byte
    return ms / 1000 / frame_s


def run(ms):
    p = serial.Serial(port=None, baudrate=BAUD, timeout=0.2,
                      xonxoff=False, rtscts=False, dsrdtr=False, exclusive=True)
    p.dtr = p.rts = False
    p.port = PORT
    p.open()
    try:
        p.reset_input_buffer()
        start = time.monotonic()
        p.break_condition = True
        # Busy-hold the requested interval as precisely as the host allows.
        deadline = start + ms / 1000
        if ms / 1000 > 0.010:
            time.sleep(ms / 1000 - 0.010)
        while time.monotonic() < deadline:
            pass
        p.break_condition = False
        held = (time.monotonic() - start) * 1000
        # Drain whatever the loopback delivered.
        time.sleep(0.1)
        got = bytearray()
        end = time.monotonic() + 0.3
        while time.monotonic() < end:
            chunk = p.read(256)
            if not chunk:
                break
            got.extend(chunk)
        return held, bytes(got)
    finally:
        p.close()


print(f'PORT={PORT} BAUD={BAUD}  (TX shorted to RX)')
print(f'{"req_ms":>7} {"held_ms":>8} {"exp_0x00":>9} {"got_bytes":>10} '
      f'{"zeros":>6} {"nonzero":>8}  received_hex')
for ms in DURATIONS_MS:
    try:
        held, got = run(ms)
    except OSError as exc:
        print(f'{ms:>7}  ERROR: {exc}')
        continue
    zeros = got.count(0)
    nonzero = len(got) - zeros
    exp = expected_zeros(ms)
    hexs = got.hex(' ').upper()
    if len(hexs) > 60:
        hexs = hexs[:60] + ' ...'
    print(f'{ms:>7} {held:>8.1f} {exp:>9.1f} {len(got):>10} '
          f'{zeros:>6} {nonzero:>8}  {hexs}')
