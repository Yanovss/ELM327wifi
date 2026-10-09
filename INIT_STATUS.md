# LIVE initialization update

The bridge now performs experimental fast initialization on the first supported read, after 3 seconds without a response, or after an address change. It drives BREAK low for approximately 25 ms, releases it for approximately 25 ms, and sends `81 B1 F1 81 A4`. Only a checksum-valid C1 response with two key bytes establishes the session. Read requests are not sent if initialization fails. Echo is ignored. Failed reads invalidate the session. ATFI explicitly initializes; ATPC invalidates the local session state. No periodic keepalive is implemented.

Run from the project directory:

```sh
python3 elm327_wifi.py --mode live --host 0.0.0.0 --tcp-port 35000
```

No `--session-already-active` flag is needed. That legacy flag is only an experimental shortcut for a direct probe; ELM reset/new TCP session invalidates cached state.

A single hardware test, without TCP:

```sh
python3 elm327_wifi.py --mode live --probe
```

Every run saves a timestamped `captures/elm-*.log`, including TCP commands/responses, initialization attempts, transmitted frames, received bytes, discarded echo and timeouts. Use `--log PATH` to append to a chosen file. DEMO remains synthetic. Unsupported AT commands still return `?`.

## Hardware result, 2026-10-09

Two direct probes were made with only the Mac adapter connected according to the user. Both received request echo but no C1 response. First host pulse measurements were 30/30 ms; after compensating for scheduler overshoot, 26.088/25.005 ms. These measure software calls, not physical K-Line voltage. Actual BREAK propagation and TX wiring remain unverified. Hardware initialization is NOT yet working. No fake positive response is returned.

Next check: exact Mac adapter model and whether its transmitter, not only receiver, is connected to K-Line. A simultaneous independent capture or oscilloscope/logic analyzer measurement is needed to establish that the wakeup pulse reaches the ECU. Do not run another active diagnostic master during the test.
