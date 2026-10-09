import unittest
from elm327_wifi import LiveTransport

INIT = bytes.fromhex('81 B1 F1 81 A4')
C1 = bytes.fromhex('83 F1 B1 C1 D9 8F 4E')
READ = bytes.fromhex('8B F1 B1 61 01 92 C2 81 94 94 B0 00 00 00 3C')

class FakePort:
    break_condition = False
    def __init__(self, answer=True):
        self.writes=[]
        self.incoming=bytearray()
        self.answer=answer
        self.baudrate=10400
        self.bauds=[]
    def reset_input_buffer(self):
        self.incoming.clear()
    def flush(self):
        pass
    def write(self, data):
        self.writes.append((self.baudrate, bytes(data)))
        self.incoming.extend(data)
        # The init frame (0x81 service) replies with C1; a read frame (0x21)
        # replies with the parameter response. The low-baud 0x00 wakeup does not.
        if self.answer:
            if len(data) >= 4 and data[3] == 0x81:
                self.incoming.extend(C1)
            elif len(data) >= 4 and data[3] == 0x21:
                self.incoming.extend(READ)
        return len(data)
    def read(self, n):
        out=bytes(self.incoming[:n]);del self.incoming[:n];return out

class InitTests(unittest.TestCase):
    def test_initialize_then_read_and_reuse(self):
        p=FakePort(); waits=[]; t=LiveTransport(p,sleep=waits.append)
        h=bytes.fromhex('80 B1 F1'); q=bytes.fromhex('21 01')
        self.assertEqual(t.exchange(h,q,.1)[3:5],bytes.fromhex('61 01'))
        bauds=[b for b,_ in p.writes]; datas=[d for _,d in p.writes]
        # low-baud 0x00 wakeup, then init frame at diag baud, then the read.
        self.assertEqual(datas[0], b'\x00')
        self.assertEqual(bauds[0], LiveTransport.WAKEUP_BAUD)
        self.assertEqual(datas[1][:1], bytes([0x81]))
        self.assertEqual(bauds[1], LiveTransport.DIAG_BAUD)
        self.assertEqual(datas[2][3], 0x21)
        self.assertEqual(bauds[2], LiveTransport.DIAG_BAUD)
        # port must be restored to diag baud, not left at wakeup baud.
        self.assertEqual(p.baudrate, LiveTransport.DIAG_BAUD)
    def test_failed_init_retries_then_does_not_read(self):
        p=FakePort(False);t=LiveTransport(p,sleep=lambda _:None,init_attempts=3)
        self.assertIsNone(t.exchange(bytes.fromhex('80 B1 F1'),bytes.fromhex('21 01'),.1))
        datas=[d for _,d in p.writes]
        init_frames=[d for d in datas if len(d)>=4 and d[3]==0x81]
        self.assertEqual(len(init_frames), 3)
        self.assertEqual(datas.count(b'\x00'), 3)
        self.assertFalse(any(len(d)>=4 and d[3]==0x21 for d in datas))
        self.assertFalse(t.active)
    def test_init_succeeds_on_later_attempt(self):
        p=FakePort(False)
        orig=p.write
        def write_then_answer(data):
            n=orig(data)
            init_frames=[d for _,d in p.writes if len(d)>=4 and d[3]==0x81]
            if len(init_frames)>=2 and len(data)>=4 and data[3]==0x81:
                p.incoming.extend(C1)
            return n
        p.write=write_then_answer
        t=LiveTransport(p,sleep=lambda _:None,init_attempts=3)
        self.assertTrue(t.initialize(bytes.fromhex('80 B1 F1')))
        init_frames=[d for _,d in p.writes if len(d)>=4 and d[3]==0x81]
        self.assertEqual(len(init_frames), 2)

    def test_baud_restored_when_write_fails(self):
        p=FakePort()
        def boom(data):
            raise OSError('usb gone')
        p.write=boom
        t=LiveTransport(p,sleep=lambda _:None,init_attempts=1)
        with self.assertRaises(OSError):
            t.initialize(bytes.fromhex('80 B1 F1'))
        self.assertEqual(p.baudrate, LiveTransport.DIAG_BAUD)

    def test_atsh_four_hex_sets_target_and_tester(self):
        from elm327_wifi import ElmSession, DemoTransport
        s=ElmSession(DemoTransport())
        self.assertEqual(s.execute('ATSH10F1'),'OK')
        self.assertEqual(s.header, bytes.fromhex('80 10 F1'))
