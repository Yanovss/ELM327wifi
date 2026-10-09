#!/usr/bin/env python3
"""Эмулятор K-Line ЭБУ (блок B1) на CH340.

Мак через CH340 прикидывается блоком: слушает fast-init и запросы от тестера
(OpenDiag/PL2303 на телефоне) и отвечает, как реальный ЭБУ климата Kalina.

Ответы взяты из реального захвата:
  init  81 B1 F1 81 A4  -> 83 F1 B1 C1 D9 8F 4E
  21 01 82 B1 F1 21 01  -> 8B F1 B1 61 01 92 C2 81 9A 94 B0 00 00 00 ..

Запуск:  python3 ecu_emulator.py --port /dev/cu.usbserial-110 --baudrate 10400
"""
import argparse
import time
from kline_sniffer import positive_int
from elm327_wifi import extract_frames


def checksum(frame):
    return sum(frame) & 0xFF


def with_cs(body):
    return body + bytes([checksum(body)])


# Готовые ответы блока на известные запросы тестера (payload -> ответный кадр).
# Ответ адресуется source-тестеру динамически, поэтому собираем в рантайме.
RESPONSES = {
    # StartCommunication: C1 + два ключевых байта D9 8F
    bytes([0x81]): lambda tgt, src: with_cs(bytes([0x83, src, tgt, 0xC1, 0xD9, 0x8F])),
    # ReadDataByLocalId 21 01: 61 01 + 9 байт параметров (из реального захвата)
    bytes([0x21, 0x01]): lambda tgt, src: with_cs(
        bytes([0x80, src, tgt, 0x61, 0x01, 0x92, 0xC2, 0x81, 0x9A, 0x94, 0xB0, 0x00, 0x00, 0x00])),
    # ReadDTC 18 00 80 00
    bytes([0x18, 0x00, 0x80, 0x00]): lambda tgt, src: with_cs(
        bytes([0x80, src, tgt, 0x58, 0x06, 0x13, 0x89, 0x00, 0x13, 0x28, 0x00,
               0x13, 0x75, 0x00, 0x13, 0x89, 0x20, 0x13, 0x28, 0x20, 0x13, 0x75, 0x20])),
}

MY_ADDR = 0xB1  # адрес эмулируемого блока


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', default='/dev/cu.usbserial-110')
    ap.add_argument('--baudrate', type=positive_int, default=10400)
    ap.add_argument('--addr', type=lambda x: int(x, 16), default=MY_ADDR,
                    help='адрес блока в hex (по умолчанию B1)')
    args = ap.parse_args()

    import serial
    port = serial.Serial(port=None, baudrate=args.baudrate, timeout=0.01,
                         write_timeout=1, exclusive=True,
                         xonxoff=False, rtscts=False, dsrdtr=False)
    port.dtr = port.rts = False
    port.port = args.port
    port.open()

    print(f'ЭБУ-эмулятор на {args.port} @ {args.baudrate}, адрес блока {args.addr:02X}', flush=True)
    print('Слушаю запросы тестера (OpenDiag/PL2303). Ctrl+C для выхода.', flush=True)
    print('-' * 60, flush=True)

    buffer = bytearray()
    try:
        while True:
            data = port.read(64)
            if data:
                buffer.extend(data)
                # покажем всё, что реально приходит на линию (для диагностики)
                print(f'{time.strftime("%H:%M:%S")}  raw bytes: {data.hex(" ").upper()}', flush=True)
            for frame in extract_frames(buffer):
                fmt, target, source = frame[0], frame[1], frame[2]
                payload = frame[3:-1]
                # Нас спрашивают, только если target == наш адрес
                if target != args.addr:
                    continue
                ts = time.strftime('%H:%M:%S')
                print(f'{ts}  RX запрос: {frame.hex(" ").upper()}  (payload {payload.hex(" ").upper()})')
                responder = RESPONSES.get(bytes(payload))
                if responder is None:
                    # Негативный ответ 7F <sid> 11 (serviceNotSupported)
                    neg = with_cs(bytes([0x83, source, args.addr, 0x7F, payload[0] if payload else 0, 0x11]))
                    port.write(neg); port.flush()
                    print(f'          TX negative: {neg.hex(" ").upper()}')
                    continue
                reply = responder(args.addr, source)
                # небольшая пауза, как реальный блок (~45 мс)
                time.sleep(0.045)
                port.write(reply); port.flush()
                print(f'          TX ответ:   {reply.hex(" ").upper()}')
    except KeyboardInterrupt:
        print('\nОстановлено.')
    finally:
        port.close()


if __name__ == '__main__':
    main()
