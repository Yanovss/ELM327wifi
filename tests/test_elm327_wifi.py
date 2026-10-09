import socket
import threading
import unittest
from elm327_wifi import DemoTransport, ElmSession, Handler, Server, extract_frames, kwp_frame


class ElmTests(unittest.TestCase):
    def test_frame_checksum_and_stream(self):
        request = kwp_frame(bytes.fromhex('80 B1 F1'), bytes.fromhex('21 01'))
        self.assertEqual(request.hex(), '82b1f1210146')
        buffer = bytearray(b'\x00' + request[:3])
        self.assertEqual(extract_frames(buffer), [])
        buffer.extend(request[3:] + request)
        self.assertEqual(extract_frames(buffer), [request, request])
        self.assertEqual(buffer, b'')

    def test_demo_and_formatting(self):
        session = ElmSession(DemoTransport())
        self.assertEqual(session.execute('21 01'), 'UNABLE TO CONNECT')
        self.assertEqual(session.execute('AT SP 5'), 'OK')
        self.assertEqual(session.execute('21 01'), '61 01 90 D2 BF 93 94 B0 FB 04 00')
        session.execute('ATH1')
        self.assertEqual(session.execute('21 01'), '8B F1 B1 61 01 90 D2 BF 93 94 B0 FB 04 00 86')
        session.execute('ATS0')
        self.assertEqual(session.execute('21 01'), '8BF1B1610190D2BF9394B0FB040086')
        self.assertEqual(session.execute('010C'), 'NO DATA')
        self.assertEqual(session.execute('ATFI'), '?')
        self.assertEqual(session.execute('ATRV'), '12.3V')
        # Harmless setup commands are accepted so apps finish initialization.
        self.assertEqual(session.execute('ATAT1'), 'OK')
        self.assertEqual(session.execute('ATCRA'), 'OK')
        self.assertEqual(session.execute('ATCAF0'), 'OK')

    def test_live_echo_and_checksum_validation(self):
        from elm327_wifi import LiveTransport
        header = bytes.fromhex('80 B1 F1')
        request = kwp_frame(header, bytes.fromhex('21 01'))
        response = bytes.fromhex('8B F1 B1 61 01 90 D2 BF 93 94 B0 FB 04 00 86')
        class Port:
            def reset_input_buffer(self):
                pass
            def write(self, data):
                self.sent = data
                self.incoming = bytearray(data + response[:-1] + b'\x00' + response)
                return len(data)
            def read(self, size):
                b = bytes(self.incoming[:size])
                del self.incoming[:size]
                return b
        port = Port()
        self.assertEqual(LiveTransport(port, already_active=True).exchange(header, bytes.fromhex('21 01'), .1), response)
        self.assertEqual(port.sent, request)

    def test_tcp_fragmented_and_multiple_commands(self):
        with Server(('127.0.0.1', 0), Handler) as server:
            server.transport = DemoTransport()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with socket.create_connection(server.server_address, timeout=2) as client:
                    self.assertEqual(client.recv(20), b'\r>')
                    client.sendall(b'AT')
                    client.sendall(b'E0\r\nATSP5\r2101\r')
                    data = b''
                    while data.count(b'>') < 3:
                        data += client.recv(1024)
                    self.assertEqual(data, b'ATE0\rOK\r>OK\r>61 01 90 D2 BF 93 94 B0 FB 04 00\r>')
            finally:
                server.shutdown()
                thread.join()
