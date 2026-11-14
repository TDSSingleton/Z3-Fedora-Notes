#!/usr/bin/python3
"""Bit-banged I2C to the Fold 3 digital hall (AKM, 0x10) on TLMM 104 (SDA) / 105 (SCL)
through /dev/mem. Prototype tool: the pins are in gpio-reserved-ranges, so no kernel bus exists.
  akm-bb.py id | status | setup | dump
"""
import mmap, os, struct, sys, time
BASE, SDA, SCL, ADDR = 0x0f100000, 104, 105, 0x10
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
M = {n: mmap.mmap(fd, 0x1000, offset=BASE + 0x1000 * n) for n in (SDA, SCL, 80)}
def cfg(n, oe):  # func 0 (gpio), 2 mA, no pull, output-enable as given; output latch stays 0
    M[n][0:4] = struct.pack("<I", (oe << 9))
def hi(n): cfg(n, 0)            # release: external pull-up takes it high
def lo(n): M[n][4:8] = struct.pack("<I", 0); cfg(n, 1)
def rd(n): return struct.unpack("<I", M[n][4:8])[0] & 1
D = 0.0002
def start(): hi(SDA); hi(SCL); time.sleep(D); lo(SDA); time.sleep(D); lo(SCL)
def stop(): lo(SDA); time.sleep(D); hi(SCL); time.sleep(D); hi(SDA); time.sleep(D)
def wbyte(b):
    for i in range(8):
        (hi if b & 0x80 else lo)(SDA); b <<= 1; time.sleep(D); hi(SCL); time.sleep(D); lo(SCL)
    hi(SDA); time.sleep(D); hi(SCL); time.sleep(D); nack = rd(SDA); lo(SCL)
    return not nack
def rbyte(ack):
    v = 0; hi(SDA)
    for i in range(8):
        time.sleep(D); hi(SCL); time.sleep(D); v = (v << 1) | rd(SDA); lo(SCL)
    (lo if ack else hi)(SDA); time.sleep(D); hi(SCL); time.sleep(D); lo(SCL); hi(SDA)
    return v
def read(reg, n):
    start()
    if not wbyte(ADDR << 1): stop(); raise IOError("no ACK on address")
    wbyte(reg); start(); wbyte((ADDR << 1) | 1)
    out = [rbyte(i < n - 1) for i in range(n)]; stop(); return out
def write(reg, data):
    start()
    if not wbyte(ADDR << 1): stop(); raise IOError("no ACK on address")
    ok = wbyte(reg) and all(wbyte(b) for b in data); stop(); return ok
def status():
    d = read(0x17, 7); s16 = lambda a, b: struct.unpack(">h", bytes([a, b]))[0]
    return f"st=0x{d[0]:02x} z={s16(d[1],d[2])} y={s16(d[3],d[4])} x={s16(d[5],d[6])} int(gpio80)={rd(80)}"
cmd = sys.argv[1]
print(f"idle lines: sda={rd(SDA)} scl={rd(SCL)}")
hi(SDA); hi(SCL); time.sleep(0.01)
print(f"released  : sda={rd(SDA)} scl={rd(SCL)}")
if cmd == "id": print("id", [hex(x) for x in read(0x00, 4)])
elif cmd == "status": print(status())
elif cmd == "dump":
    print("id", [hex(x) for x in read(0x00, 4)]); print("cntl1", [hex(x) for x in read(0x20, 2)], "cntl2", [hex(x) for x in read(0x21, 1)])
    for r, n in ((0x22, "thX"), (0x23, "thY"), (0x24, "thZ"), (0x25, "thV")): print(n, [hex(x) for x in read(r, 4)])
    print(status())
elif cmd == "setup":
    # vendor DT: pol = <0 1 0 0>, sw_en = <0 1 0 0>, err_en = 1, drdy_en = 0,
    # measurement_number = 5 (mode 0x0a), sdr = 1, threshold_y = <0x889 0x690>
    print("cntl1", write(0x20, [0x02, 0x24]), "thY", write(0x23, [0x08, 0x89, 0x06, 0x90]), "cntl2", write(0x21, [0x0a | (1 << 5)]))
    time.sleep(0.1); print(status())
