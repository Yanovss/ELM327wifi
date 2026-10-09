import unittest
from elm327_wifi import LiveTransport

class FakePort:
    break_condition = False
    def __init__(self, answer=True):
        self.writes=[]
        self.incoming=bytearray()
        self.answer=answer
    def reset_input_buffer(self):
        self.incoming.clear()
    def write(self, data):
        self.writes.append(data)
        self.incoming.extend(data)
        if self.answer:
            self.incoming.extend(bytes.fromhex('83 F1 B1 C1 D9 8F 4E' if data[3]==0x81 else '8B F1 B1 61 01 92 C2 81 94 94 B0 00 00 00 3C'))
        return len(data)
    def read(self, n):
        out=bytes(self.incoming[:n]);del self.incoming[:n];return out

class InitTests(unittest.TestCase):
    def test_initialize_then_read_and_reuse(self):
        p=FakePort(); waits=[]; t=LiveTransport(p,sleep=waits.append)
        h=bytes.fromhex('80 B1 F1'); q=bytes.fromhex('21 01')
        self.assertEqual(t.exchange(h,q,.1)[3:5],bytes.fromhex('61 01'))
        self.assertEqual([v[3] for v in p.writes],[0x81,0x21])
        self.assertEqual(waits[:3],[.3,.025,.025]);self.assertFalse(p.break_condition)
        t.exchange(h,q,.1)
        self.assertEqual([v[3] for v in p.writes],[0x81,0x21,0x21])
    def test_failed_init_does_not_read(self):
        p=FakePort(False);t=LiveTransport(p,sleep=lambda _:None)
        self.assertIsNone(t.exchange(bytes.fromhex('80 B1 F1'),bytes.fromhex('21 01'),.1))
        self.assertEqual(len(p.writes),1);self.assertFalse(t.active)
    def test_break_released_on_interrupt(self):
        p=FakePort()
        def sleep(seconds):
            if p.break_condition:raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            LiveTransport(p,sleep=sleep).initialize(bytes.fromhex('80 B1 F1'))
        self.assertFalse(p.break_condition)
