#!/usr/bin/env python3
"""CH34x loopback test: TX must be physically shorted to RX.

Sends a known byte pattern at several baud rates, reads it back, and reports
lost/corrupted bytes. This isolates the USB-UART chip+driver from any K-Line
wiring or ECU. Pure hardware sanity check, no bus, no BREAK.
"""
import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/cu.usbserial-110'
BAUDS = [9600, 10000, 10400, 19200, 38400]
# A pattern that includes the exact K-Line init bytes plus a counter so a
# dropped or shifted byte is obvious.
PATTERN = bytes(range(256)) + bytes.fromhex('00 81 B1 F1 81 A4') * 20


def run(baud):
    p = serial.Serial(port=None, baudrate=baud, timeout=1.0,
                      xonxoff=False, rtscts=False, dsrdtr=False, exclusive=True)
    p.dtr = p.rts = False
    p.port = PORT
    p.open()
    try:
        p.reset_input_buffer()
        p.write(PATTERN)
        p.flush()
        deadline = time.monotonic() + 2.0
        got = bytearray()
        while len(got) < len(PATTERN) and time.monotonic() < deadline:
            got.extend(p.read(len(PATTERN) - len(got)))
        return bytes(got)
    finally:
        p.close()


def diff(sent, got):
    n = min(len(sent), len(got))
    mism = sum(1 for i in range(n) if sent[i] != got[i])
    return mism


print(f'PORT={PORT}  pattern={len(PATTERN)} bytes')
print(f'{"baud":>7} {"received":>9} {"missing":>8} {"mismatch@aligned":>17}  verdict')
for baud in BAUDS:
    try:
        got = run(baud)
    except OSError as exc:
        print(f'{baud:>7}  ERROR: {exc}')
        continue
    missing = len(PATTERN) - len(got)
    mism = diff(PATTERN, got)
    clean = (missing == 0 and mism == 0)
    verdict = 'CLEAN' if clean else 'LOSS/CORRUPTION'
    print(f'{baud:>7} {len(got):>9} {missing:>8} {mism:>17}  {verdict}')
    if not clean:
        # Show first divergence to make the failure concrete.
        n = min(len(PATTERN), len(got))
        for i in range(n):
            if PATTERN[i] != got[i]:
                lo = max(0, i - 3)
                print(f'          first diff at byte {i}: '
                      f'sent {PATTERN[lo:i+4].hex(" ").upper()} | '
                      f'got {got[lo:i+4].hex(" ").upper()}')
                break
