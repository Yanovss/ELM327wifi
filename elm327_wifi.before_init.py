#!/usr/bin/env python3
"""Experimental ELM-compatible TCP endpoint for Kalina climate KWP2000.

Default mode is synthetic demo. Live mode requires an already initialized ECU.
Not a complete ELM327 implementation; unsupported AT commands return '?'.
"""
import argparse
import logging
import re
import socketserver
import time

from kline_sniffer import positive_int

LOG = logging.getLogger('elm')


def kwp_frame(header, payload):
    if not 1 <= len(payload) <= 63:
        raise ValueError('payload must contain 1..63 bytes')
    body = bytes([(header[0] & 0xC0) | len(payload)]) + header[1:] + payload
    return body + bytes([sum(body) & 255])


def extract_frames(buffer):
    """Consume checksum-valid, three-byte, physically addressed KWP frames."""
    frames = []
    while buffer:
        found = False
        for offset in range(len(buffer)):
            first = buffer[offset]
            if first & 0xC0 != 0x80 or not first & 63:
                continue
            size = (first & 63) + 4
            if offset + size > len(buffer):
                continue
            frame = bytes(buffer[offset:offset + size])
            if sum(frame[:-1]) & 255 == frame[-1]:
                del buffer[:offset + size]
                frames.append(frame)
                found = True
                break
        if not found:
            # Keep enough tail for the largest supported incomplete frame.
            if len(buffer) > 67:
                del buffer[:-67]
            break
    return frames


class DemoTransport:
    """Fixed example payloads from capture, never represented as live measurements."""
    def exchange(self, header, payload, timeout):
        examples = {
            b'\x21\x01': bytes.fromhex('61 01 90 D2 BF 93 94 B0 FB 04 00'),
            bytes.fromhex('18 00 80 00'): bytes.fromhex(
                '58 06 13 89 00 13 28 00 13 75 00 13 89 20 13 28 20 13 75 20'),
        }
        if header[1:] != bytes.fromhex('B1 F1') or payload not in examples:
            return None
        return kwp_frame(bytes([0x80, header[2], header[1]]), examples[payload])


class LiveTransport:
    def __init__(self, port):
        self.port = port

    def exchange(self, header, payload, timeout):
        # Only known read services are forwarded by this experimental bridge.
        if payload not in (bytes.fromhex('21 01'), bytes.fromhex('18 00 80 00'),
                           bytes.fromhex('1A 80')):
            return None
        request = kwp_frame(header, payload)
        self.port.reset_input_buffer()
        LOG.info('TX %s', request.hex(' ').upper())
        self.port.write(request)
        deadline = time.monotonic() + timeout
        buffer = bytearray()
        while time.monotonic() < deadline:
            buffer.extend(self.port.read(1))
            for frame in extract_frames(buffer):
                LOG.info('RX %s', frame.hex(' ').upper())
                if frame == request:  # single-wire adapter echo
                    continue
                if frame[1:3] != bytes([header[2], header[1]]):
                    continue
                data = frame[3:-1]
                if data[:2] == bytes([0x7F, payload[0]]):
                    if len(data) >= 3 and data[2] == 0x78:
                        continue  # bounded by the original timeout
                    return frame
                if data[0] == (payload[0] + 0x40) & 255:
                    if payload[0] in (0x21, 0x1A) and data[1:2] != payload[1:2]:
                        continue
                    return frame
        return None


class ElmSession:
    def __init__(self, transport):
        self.transport = transport
        self.reset()

    def reset(self):
        self.echo = True
        self.linefeeds = False
        self.spaces = True
        self.headers = False
        self.protocol = None
        self.header = bytes.fromhex('80 B1 F1')
        self.timeout = 1.0
        self.previous = ''

    def execute(self, command):
        command = re.sub(r'\s+', '', command).upper()
        if not command:
            return '?'
        if command in ('ATZ', 'ATWS'):
            self.reset()
            return 'ELM327 v1.5'
        if command == 'ATI':
            return 'ELM327 v1.5'
        if command == 'AT@1':
            return 'Experimental Kalina TCP bridge'
        if command == 'ATD':
            self.reset()
            return 'OK'
        for prefix, attr in [('ATE', 'echo'), ('ATL', 'linefeeds'),
                             ('ATS', 'spaces'), ('ATH', 'headers')]:
            if command in (prefix + '0', prefix + '1'):
                setattr(self, attr, command[-1] == '1')
                return 'OK'
        if command == 'ATSP5':
            self.protocol = 5
            return 'OK'
        if command == 'ATDP':
            return 'ISO 14230-4 (KWP FAST)' if self.protocol == 5 else 'UNSELECTED'
        if command == 'ATDPN':
            return '5' if self.protocol == 5 else '?'
        if re.fullmatch(r'ATSH[0-9A-F]{6}', command):
            header = bytes.fromhex(command[4:])
            if header[0] & 0xC0 != 0x80:
                return '?'
            self.header = header
            return 'OK'
        if re.fullmatch(r'ATST[0-9A-F]{2}', command):
            ticks = int(command[4:], 16)
            self.timeout = (ticks or 0x32) * .004
            return 'OK'
        if command.startswith('AT'):
            return '?'
        if not re.fullmatch(r'(?:[0-9A-F]{2}){1,63}', command):
            return '?'
        if self.protocol != 5:
            return 'UNABLE TO CONNECT'
        response = self.transport.exchange(self.header, bytes.fromhex(command), self.timeout)
        if response is None:
            return 'NO DATA'
        data = response if self.headers else response[3:-1]
        return (data.hex(' ') if self.spaces else data.hex()).upper()

    def reply(self, command):
        if not command:
            command = self.previous
        else:
            self.previous = command
        echo = self.echo
        try:
            answer = self.execute(command)
        except (OSError, ValueError) as exc:
            LOG.error('Transport failure: %s', exc)
            answer = 'BUS ERROR'
        newline = '\r\n' if self.linefeeds else '\r'
        return ((command + newline if echo else '') + answer + newline + '>').encode('ascii')


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        LOG.info('Client connected: %s', self.client_address)
        session = ElmSession(self.server.transport)
        self.request.settimeout(60)
        pending = bytearray()
        try:
            self.request.sendall(b'\r>')
            while True:
                chunk = self.request.recv(1024)
                if not chunk:
                    return
                for byte in chunk:
                    if byte == 10:  # tolerate CRLF without repeating the command
                        continue
                    if byte == 13:
                        try:
                            command = pending.decode('ascii')
                        except UnicodeDecodeError:
                            self.request.sendall(b'?\r>')
                        else:
                            self.request.sendall(session.reply(command))
                        pending.clear()
                    else:
                        pending.append(byte)
                        if len(pending) > 512:
                            self.request.sendall(b'?\r>')
                            return
        except OSError as exc:
            LOG.info('Client disconnected: %s', exc)


class Server(socketserver.TCPServer):
    allow_reuse_address = True
    # Deliberately one client at a time: one serial bus, one request owner.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--tcp-port', type=positive_int, default=35000)
    parser.add_argument('--mode', choices=('demo', 'live'), default='demo')
    parser.add_argument('--port', default='/dev/cu.usbserial-1110')
    parser.add_argument('--baudrate', type=positive_int, default=10400)
    parser.add_argument('--session-already-active', action='store_true')
    args = parser.parse_args()
    if args.tcp_port > 65535:
        parser.error('--tcp-port must be <= 65535')
    if args.mode == 'live' and not args.session_already_active:
        parser.error('Live mode requires --session-already-active; ECU initialization is not implemented')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    port = None
    try:
        transport = DemoTransport()
        if args.mode == 'live':
            import serial
            port = serial.Serial(port=None, baudrate=args.baudrate, timeout=.01,
                                 write_timeout=1, exclusive=True,
                                 xonxoff=False, rtscts=False, dsrdtr=False)
            port.dtr = port.rts = False
            port.port = args.port
            port.open()
            transport = LiveTransport(port)
        with Server((args.host, args.tcp_port), Handler) as server:
            server.transport = transport
            LOG.warning('MODE=%s TCP=%s:%s; partial ELM emulation; no ECU initialization',
                        args.mode.upper(), args.host, args.tcp_port)
            if args.mode == 'demo':
                LOG.warning('SYNTHETIC DATA from fixed examples; serial port is not opened')
            server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    except (ImportError, OSError, ValueError) as exc:
        LOG.error('%s', exc)
        return 1
    finally:
        if port is not None:
            port.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
