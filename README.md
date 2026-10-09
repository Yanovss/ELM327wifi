**English** · [Русский](README.ru.md)

# K-Line on macOS: passive capture, analysis, and a CH340/CH341 workaround

The original project contained only an empty notebook.ipynb and a .venv; no
existing serial/K-Line/OBD Python code was present.

## Main result: making CH340/CH341 wake up a K-Line ECU

**The problem.** Cheap CH340/CH341 USB-UART adapters do not work with diagnostic
apps (OpenDiag and similar) over K-Line, while PL2303 and FTDI do — even though
the K-Line front end (a transistor stage or a driver such as the L9637D) is the
same. The cause was unclear for a long time.

**What was measured in this project** (all tests on real hardware, macOS, pyserial):

1. **Data transfer.** A loopback test (TX shorted to RX) showed that CH340
   transmits and receives bytes **without loss or corruption** at every baud
   rate, including the nonstandard 10400. So the problem is **not** the baud rate
   and **not** byte loss. See `tools/loopback_test.py`.

2. **BREAK.** K-Line fast init (ISO 14230 / KWP2000) begins with a wake-up
   pattern: the line held low for ~25 ms. This is normally produced with a UART
   BREAK. The test showed that **CH340 does not produce a BREAK at all** — with
   `break_condition=True`, the loopback receives no `0x00` byte for any duration.
   For contrast, **PL2303 does produce BREAK** — which is exactly why "PL2303
   works, CH340 doesn't". See `tools/break_test.py`.

3. **The workaround.** CH340 **can** form the same long low level **without
   BREAK**, by sending a `0x00` byte at a low baud rate. At 360 baud 8N1, one
   `0x00` byte = 1 start bit + 8 zero data bits = 9 low bit-times = **25.0 ms**.
   Loopback confirmed the chip really holds the line low that long.
   See `tools/lowbaud_test.py`.

4. **Verified on an ECU.** With this method (360 baud `0x00` → pause → 10400 baud
   → init frame) CH340 **woke a real ECU** (Lada Kalina climate unit, address B1)
   and read live data: a `61 01 ...` response to the `21 01` request. The method
   is built into `elm327_wifi.py` (`LiveTransport._init_once`).

**Conclusion.** It is neither the K-Line front end nor the baud rate; CH340/CH341
simply cannot produce a BREAK (a low level of nonstandard duration). This is
worked around in software, no soldering: BREAK is replaced with `0x00` @ 360 baud.

### Limitations of the method (important)

- The pulse duration was measured at the host (loopback), **not** with a scope on
  the K-Line itself. The ECU reply confirms the pulse indirectly, but the actual
  waveform on the wire was not measured here.
- The ~25 ms pulse only arises at 360 baud. A high stop bit follows the low level,
  so the ISO 14230 "high" phase is shortened; ECUs with tight tolerances may not
  accept it.
- Changing the port baud rate is not atomic: there are random OS/USB delays
  between the pulse and the frame, so retries (several init attempts) are needed.
- Only **fast init** is implemented. The slow **5-baud init** (ISO 9141) is not.
- Verified on **one** ECU and **one** CH340 unit on a single macOS driver version.
  Behavior may differ on other hardware/OS.
- Your K-Line front end may invert the signal — verify on your own adapter.

### Diagnostic utilities

To test your own adapter (short TX↔RX for the loopback/break/lowbaud tests):

```sh
python3 tools/loopback_test.py /dev/cu.usbserial-XXX   # does the chip drop bytes at 10400
python3 tools/break_test.py    /dev/cu.usbserial-XXX   # can the chip do BREAK (CH340 cannot)
python3 tools/lowbaud_test.py  /dev/cu.usbserial-XXX   # does 0x00@360 form a long low level
python3 tools/rts_dtr_test.py  /dev/cu.usbserial-XXX   # do RTS/DTR lines respond (alternative workaround)
```

Find the port name with `python3 -m serial.tools.list_ports`
(CH340 shows up as `USB2.0-Ser!`, VID:PID `1A86:7523`).

## Experimental ELM327 Wi-Fi bridge

`elm327_wifi.py` starts a TCP server that a diagnostic app can connect to as a
Wi-Fi ELM327. The bridge transparently forwards KWP requests to the ECU over the
USB-K-Line adapter, performing the wakeup above automatically. Details and
limitations are in `docs/ELM327_WIFI.md`.

```sh
python3 -m serial.tools.list_ports
python3 elm327_wifi.py --mode live --host 0.0.0.0 --tcp-port 35000 \
  --port /dev/cu.usbserial-XXX --baudrate 10400
```

Order of operations with an ECU: start the bridge → connect the app → **turn on
the ignition** (the ECU wakes at that moment and init catches the window). A
one-shot probe without TCP:
`python3 elm327_wifi.py --mode live --probe --port /dev/cu.usbserial-XXX --init-attempts 60`.

Do not expose the TCP port to the internet: there is no authentication or encryption.

## Install

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Capture

```sh
python3 kline_sniffer.py \
  --port /dev/cu.usbserial-XXX \
  --baudrate 10400 \
  --frame-gap-ms 20 \
  --output captures/kline.jsonl
```

These are all default values. Files are never overwritten: choose a new name for
the next capture. The directory is created automatically. If the port fails to
open, empty capture files may remain; use another name or delete them manually.

Additional modes:

```sh
python3 kline_sniffer.py --output captures/session2.jsonl --raw --verbose
python3 kline_analyze.py captures/kline.jsonl --top 10 --header-bytes 4
```

`--raw` also saves every received byte to `captures/session2.jsonl.bin` with no
separators or metadata. `--verbose` prints each byte and its interval from the
previous one to stderr; these are application-receipt intervals, not exact
on-wire intervals. Heavy output can affect timing.

Example display (illustration, not a measurement):

```text
port=/dev/cu.usbserial-XXX baudrate=10400 format=8N1 frame_gap_ms=20 output=captures/kline.jsonl raw=off verbose=False
Passive read; timing is measured at host receipt. Ctrl+C to stop.
1791555792.123456  len=   5  81 11 F1 81 04  |.....|  [gap]
```

A JSONL line:

```json
{"ts": 1791555792.123456, "ts_end": 1791555792.127456, "data": "81 11 F1 81 04", "length": 5, "reason": "gap"}
```

`ts` is the Unix timestamp of the first byte, `ts_end` of the last, on the host
clock. Gaps are detected with a monotonic clock. `reason` is `gap`, `interrupted`,
or `error`; the latter two mark a potentially incomplete frame. The analyzer
accounts for every record, reports the termination reasons, and also reads the
minimal ts/data/length format. Without ts_end the interval from the frame end is
unknown. A malformed record aborts analysis with the line number. Large files
need memory: the analyzer loads the whole capture.

Reading is binary, one byte at a time, without decoding. The ASCII column on the
right shows only printable 0x20–0x7E characters; the rest become dots. A frame
ends on an observed gap strictly greater than the threshold. On Ctrl+C or a read
error, the accumulated frame is written before the files close. JSONL is flushed
after each frame, raw after each byte (this is not a guarantee against power
loss). If a disk write fails, full preservation is impossible.

## Hardware and timing limitations

The script uses 8N1, disables software/hardware flow control, and sets RTS/DTR to
False before opening. It does not call serial.write, break, or K-Line
initialization. However, the OS/driver may briefly toggle RTS/DTR on open;
electrical passivity is guaranteed by the adapter circuit, not by Python. Use an
interface suitable for listening to K-Line; a plain UART must not be connected
directly to an automotive K-Line. Fully passive listening requires a proper
receive path that does not drive the bus via TX.

10400 is a nonstandard baud rate: macOS/pyserial support nonstandard values, but a
specific adapter or driver may refuse. Details:
[pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).

USB and the driver buffer data. Even read(1) does not restore the original
inter-byte gaps; a USB packet may merge several frames, and application latency
may create a false split. The 20 ms threshold is a heuristic, not a protocol
spec. Accurate physical timing needs a hardware capture with timestamps. A single
receive channel alone does not determine the direction of exchange.

A missing port, denied access, a busy port, an unsupported baud rate, and USB
disconnection are reported to stderr with a nonzero exit code. If there is no
data, the program keeps waiting; silence alone does not mean a disconnect. Ctrl+C
is a normal exit. Close other programs using the port; check the connection and
permissions. Do not run as root without first understanding the error.

## Next steps for protocol identification

1. Record several sessions with known diagnostic-tool actions, including the start
   of a connection, while staying a passive observer. Without an active peer on
   the bus there may be silence.
2. Verify the baud rate and format with a physical measurement; compare results
   across frame-gap thresholds and confirm the boundaries are stable.
3. Compare repeated prefixes, lengths, request/response pairs, and last bytes.
   Test length-field and checksum hypotheses on many different frames, not a
   single example.
4. Match the init recording, addressing, message structure, and timing against
   ISO 9141-2 and ISO 14230/KWP2000 and the specific ECU documentation. The baud
   rate 10400 and a shared prefix alone do not uniquely identify the protocol.
   Init at a different rate/pulse may not be captured correctly by a UART fixed at
   10400; a logic analyzer with a proper K-Line path helps here.
5. If standard structures do not agree across several sessions, investigate a
   manufacturer-specific or proprietary protocol. The analyzer deliberately
   assigns no meaning to fields and does not auto-detect the protocol.

## Checks without hardware

```sh
python3 -m py_compile kline_sniffer.py kline_analyze.py
python3 -m unittest discover -s tests -v
```

The tests use a serial-port model, open no hardware, and do not require pyserial.
Real USB timing, 10400 support, and electrical passivity require separate hardware
verification.
