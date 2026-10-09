#!/usr/bin/env python3
"""CH34x RTS/DTR control-line test.

BREAK is dead on this chip, so the proposed workaround is to form the K-Line
fast-init wakeup by toggling RTS (or DTR) via TIOCMSET instead. This test does
NOT need any loopback wiring: it just asserts/deasserts RTS and DTR for a set
of durations and measures how precisely the host can hold them. If TIOCMSET is
unsupported or laggy on CH34x/macOS, the workaround is not viable before any
soldering. This measures host call timing, not the actual pin voltage.
"""
import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/cu.usbserial-110'
DURATIONS_MS = [1, 5, 10, 25, 50]


def precise_hold(ms):
    deadline = time.monotonic() + ms / 1000
    if ms / 1000 > 0.010:
        time.sleep(ms / 1000 - 0.010)
    while time.monotonic() < deadline:
        pass


def measure(setter, ms):
    start = time.monotonic()
    setter(True)
    t_on = (time.monotonic() - start) * 1000      # cost of the set call itself
    precise_hold(ms)
    mid = time.monotonic()
    setter(False)
    t_off = (time.monotonic() - mid) * 1000
    held = (mid - start) * 1000
    return t_on, held, t_off


def run(line_name, setter):
    print(f'\n--- {line_name} ---')
    print(f'{"req_ms":>7} {"set_call_ms":>12} {"held_ms":>8} {"clear_call_ms":>14}')
    for ms in DURATIONS_MS:
        t_on, held, t_off = measure(setter, ms)
        print(f'{ms:>7} {t_on:>12.3f} {held:>8.3f} {t_off:>14.3f}')


def main():
    p = serial.Serial(port=None, baudrate=10400, timeout=0.2,
                      xonxoff=False, rtscts=False, dsrdtr=False, exclusive=True)
    p.port = PORT
    p.open()
    try:
        print(f'PORT={PORT}  control-line timing (host call cost, not pin voltage)')
        run('RTS', lambda v: setattr(p, 'rts', v))
        run('DTR', lambda v: setattr(p, 'dtr', v))
    finally:
        p.close()


if __name__ == '__main__':
    main()
