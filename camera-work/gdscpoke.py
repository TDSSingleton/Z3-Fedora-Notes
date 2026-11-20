#!/usr/bin/env python3
"""
Read, and optionally drive, a camcc GDSC straight through /dev/mem.

    ./gdscpoke.py                 # dump all camcc GDSCs
    ./gdscpoke.py ife_0 on        # clear SW_COLLAPSE, poll PWR_ON
    ./gdscpoke.py ife_0 off       # set SW_COLLAPSE, poll !PWR_ON
    ./gdscpoke.py ife_0 cycle N   # N off/on cycles, reporting each

Purpose: decide whether "an IFE GDSC powers up only once per boot" is a
property of the GDSC itself or of what camss does around it. Driving the
hardware with nothing but these two register writes removes camss, genpd,
device links and the clock framework from the picture.

CAUTION: this writes registers that gdsc.c also owns through a regmap, so it
can desync the kernel's view. Use it on a domain camss is not currently
using, and reboot afterwards. Reading is always safe.

Register layout (drivers/clk/qcom/gdsc.c):
  GDSCR      bit31 PWR_ON, bit2 SW_OVERRIDE, bit1 HW_CONTROL, bit0 SW_COLLAPSE
  CFG_GDSCR  = GDSCR + 4; bit16 POWER_UP_COMPLETE, bit15 POWER_DOWN_COMPLETE,
               bit11 RETAIN_FF_ENABLE
"""
import mmap
import os
import struct
import sys
import time

BASE = 0xAD00000
SPAN = 0x10000
REGS = {"bps": 0x7004, "ipe_0": 0x8004, "sbi": 0x9004, "ife_0": 0xA004,
        "ife_1": 0xB004, "ife_2": 0xB070, "titan_top": 0xC120}

PWR_ON = 1 << 31
SW_COLLAPSE = 1 << 0
UP_DONE = 1 << 16
DOWN_DONE = 1 << 15
RETAIN_FF = 1 << 11
POLL_US = 2000          # gdsc.c STATUS_POLL_TIMEOUT_US


def decode(g, c):
    return (f"GDSCR={g:#010x} CFG={c:#010x}  "
            f"PWR_ON={int(bool(g & PWR_ON))} SW_COLLAPSE={int(bool(g & SW_COLLAPSE))} "
            f"| UP={int(bool(c & UP_DONE))} DOWN={int(bool(c & DOWN_DONE))} "
            f"RETAIN_FF={int(bool(c & RETAIN_FF))}")


class Cam:
    def __init__(self, write=False):
        flags = os.O_RDWR if write else os.O_RDONLY
        self.fd = os.open("/dev/mem", flags | os.O_SYNC)
        prot = mmap.PROT_READ | (mmap.PROT_WRITE if write else 0)
        self.m = mmap.mmap(self.fd, SPAN, mmap.MAP_SHARED, prot, offset=BASE)

    def r(self, o):
        return struct.unpack("<I", self.m[o:o + 4])[0]

    def w(self, o, v):
        self.m[o:o + 4] = struct.pack("<I", v)

    def show(self, name):
        off = REGS[name]
        return decode(self.r(off), self.r(off + 4))

    def wait(self, name, want_on):
        """Poll like gdsc_poll_status(). Returns (ok, elapsed_us)."""
        off = REGS[name]
        t0 = time.monotonic()
        while (time.monotonic() - t0) * 1e6 < POLL_US:
            g = self.r(off)
            if bool(g & PWR_ON) == want_on:
                return True, (time.monotonic() - t0) * 1e6
        return False, (time.monotonic() - t0) * 1e6

    def set_on(self, name, on):
        off = REGS[name]
        g = self.r(off)
        self.w(off, g & ~SW_COLLAPSE if on else g | SW_COLLAPSE)
        ok, us = self.wait(name, on)
        print(f"  {name} -> {'ON ' if on else 'OFF'}: "
              f"{'ok' if ok else 'TIMEOUT'} after {us:.0f} us   {self.show(name)}")
        return ok


def main():
    if len(sys.argv) == 1:
        c = Cam()
        for n in REGS:
            print(f"  {n:<11} {c.show(n)}")
        return 0

    name, action = sys.argv[1], sys.argv[2]
    if name not in REGS:
        sys.exit(f"!! unknown gdsc {name}; one of {', '.join(REGS)}")
    c = Cam(write=True)
    print(f"  before     {c.show(name)}")

    if action in ("on", "off"):
        return 0 if c.set_on(name, action == "on") else 1

    if action == "cycle":
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        for i in range(n):
            print(f"-- cycle {i + 1}")
            if not c.set_on(name, False):
                print("   (off failed; continuing anyway)")
            if not c.set_on(name, True):
                print(f"   !! power-up FAILED on cycle {i + 1}")
                return 1
        print(f"  all {n} cycles powered up fine")
        return 0

    sys.exit(f"!! unknown action {action}")


if __name__ == "__main__":
    sys.exit(main())
