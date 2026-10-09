#!/usr/bin/env python3
"""CH34x low-baud wakeup test: form a long low pulse via a 0x00 byte at 300 baud
instead of BREAK. TX must be shorted to RX.

At 300 baud 8N1, one bit = 3.33 ms; a 0x00 byte = 1 start + 8 low bits = 9 low
bit-times ~= 30 ms of low level (close to the ~25 ms a K-Line fast-init wakeup
needs). If the chip really drives the line low that long, the loopback should
return a 0x00 and the measured transfer time should match. This tests whether
CH34x can make the nonstandard-length low pulse this way, unlike BREAK.
"""
import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/cu.usbserial-110'


def test(baud, bytesize, parity, label, nbytes=1):
    bits = 1 + bytesize + (0 if parity == serial.PARITY_NONE else 1) + 1  # start+data+parity+stop
    low_bits = 1 + bytesize + (1 if parity == serial.PARITY_SPACE else 0)  # start + data0 + space-parity0
    bit_ms = 1000 / baud
    p = serial.Serial(port=None, baudrate=baud, bytesize=bytesize, parity=parity,
                      stopbits=serial.STOPBITS_ONE, timeout=1.0,
                      xonxoff=False, rtscts=False, dsrdtr=False, exclusive=True)
    p.dtr = p.rts = False
    p.port = PORT
    p.open()
    try:
        p.reset_input_buffer()
        start = time.monotonic()
        p.write(b'\x00' * nbytes)
        p.flush()
        got = bytearray()
        end = time.monotonic() + 0.5
        while time.monotonic() < end and len(got) < nbytes:
            got.extend(p.read(nbytes - len(got)))
        elapsed = (time.monotonic() - start) * 1000
        print(f'{label:>22}: baud={baud} frame_bits={bits} '
              f'est_low={low_bits*bit_ms:.1f}ms  sent={nbytes} '
              f'got={got.hex(" ").upper() or "(nothing)"} elapsed={elapsed:.1f}ms')
        return bytes(got)
    finally:
        p.close()


print(f'PORT={PORT}  (TX shorted to RX)')
# 0x00 8N1 at various baud rates to find one whose low pulse ~= 25 ms.
# low = (1 start + 8 data0) bit-times = 9 / baud.
# 360 baud -> 25.0 ms; 300 -> 30.0 ms; 400 -> 22.5 ms.
test(300, serial.EIGHTBITS, serial.PARITY_NONE, '300 8N1 0x00')
test(360, serial.EIGHTBITS, serial.PARITY_NONE, '360 8N1 0x00')
test(400, serial.EIGHTBITS, serial.PARITY_NONE, '400 8N1 0x00')
# For contrast: 0x00 at 10400 (old approach) ~0.86 ms low -- too short for WUP.
test(10400, serial.EIGHTBITS, serial.PARITY_NONE, '10400 8N1 0x00')
