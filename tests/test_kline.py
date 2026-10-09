import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

from kline_sniffer import Capture, capture_loop
from kline_analyze import load_frames, main


class Port:
    def __init__(self, events, failure=KeyboardInterrupt):
        self.events = iter(events)
        self.now = 0
        self.failure = failure

    def read(self, size):
        assert size == 1
        try:
            self.now, data = next(self.events)
            return data
        except StopIteration:
            raise self.failure()


class CaptureTests(unittest.TestCase):
    def run_capture(self, events, failure=KeyboardInterrupt):
        output, raw = io.StringIO(), io.BytesIO()
        port = Port(events, failure)
        with redirect_stdout(io.StringIO()), self.assertRaises(failure):
            capture_loop(port, Capture(output, raw), .020,
                         wall_clock=lambda: 1000 + port.now,
                         mono_clock=lambda: port.now)
        return [json.loads(s) for s in output.getvalue().splitlines()], raw.getvalue()

    def test_gap_and_shutdown_binary_preserved(self):
        rows, raw = self.run_capture([(0, b'\x81'), (.001, b'\xff'),
                                     (.025, b''), (.030, b'\x00')])
        self.assertEqual([r['data'] for r in rows], ['81 FF', '00'])
        self.assertEqual([r['reason'] for r in rows], ['gap', 'interrupted'])
        self.assertEqual(rows[0]['ts'], 1000)
        self.assertEqual(raw, b'\x81\xff\x00')

    def test_gap_detected_when_next_read_has_data(self):
        rows, _ = self.run_capture([(0, b'A'), (.021, b'B')])
        self.assertEqual(len(rows), 2)

    def test_exact_threshold_does_not_split(self):
        rows, _ = self.run_capture([(0, b'A'), (.020, b'B')])
        self.assertEqual(rows[0]['data'], '41 42')

    def test_disconnect_flushes_partial(self):
        rows, _ = self.run_capture([(0, b'\x81')], OSError)
        self.assertEqual(rows[0]['reason'], 'error')

    def test_empty_stop(self):
        self.assertEqual(self.run_capture([]), ([], b''))

    def test_analyzer_minimal_and_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'capture.jsonl'
            row = {'ts': 1, 'data': '81 FF', 'length': 2}
            path.write_text(json.dumps(row) + '\n' + json.dumps(dict(row, ts=1.1)))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([str(path)]), 0)
            self.assertIn('100.000', output.getvalue())
            self.assertIn('count=2', output.getvalue())
            path.write_text(json.dumps(dict(row, length=3)))
            with self.assertRaisesRegex(ValueError, ':1:'):
                load_frames(path)


if __name__ == '__main__':
    unittest.main()
