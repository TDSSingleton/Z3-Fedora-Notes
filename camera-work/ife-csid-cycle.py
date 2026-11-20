#!/usr/bin/env python3
"""
Does running the CSID RDI path -- enable, resume, halt, disable -- wedge the
IFE GDSC? Continues the bisect in HANDBOOK 33.11.

Already eliminated by the same method (each from a fresh boot, with register
access asserted): the GDSC alone, the IFE clocks, the VFE global reset, and
the WM_CGC_OVERRIDE write. camss streaming from the CSID's own test generator
-- no sensor, no CSIPHY, zero frames -- still wedges it, so what remains is
camss starting and stopping the CSID and/or the VFE.

This isolates the CSID half. On gen2 the CSID lives inside the VFE register
window at +0x1200, so it shares the IFE power domain.

    titan_top on -> ife_0 on -> clocks on
      -> RDI_CFG0 |= ENABLE -> RDI_CTRL = RESUME -> RDI_CTRL = HALT
      -> RDI_CFG0 &= ~ENABLE
    -> clocks off -> ife_0 off -> ife_0 ON AGAIN

Run on a FRESH BOOT; ife_0 must start pristine (GDSCR 0x..f001).
"""
import mmap, os, struct, sys, time

CAMCC, VFE0 = 0xAD00000, 0xACB4000
CSID_OFF = 0x1200                  # VFE_480_CSID_OFFSET
TITAN, IFE0 = 0xC120, 0xA004
PWR_ON, SWC, CLK_EN = 1 << 31, 1, 1 << 0
IFE0_CLKS = [0xA028, 0xA084, 0xA088, 0xA030, 0xA058, 0xA080]
AHB_CLKS = [0xC0D0, 0xC0F0, 0xC12C]
RDI_CFG0, RDI_CTRL = 0x300, 0x308  # non-lite, rdi 0
RDI_CFG0_ENABLE = 1 << 31
HALT_AT_FRAME_BOUNDARY, RESUME_AT_FRAME_BOUNDARY = 0, 1

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
cc = mmap.mmap(fd, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=CAMCC)
vf = mmap.mmap(fd, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=VFE0)
rc_ = lambda o: struct.unpack("<I", cc[o:o+4])[0]
wc_ = lambda o, v: cc.__setitem__(slice(o, o+4), struct.pack("<I", v))
rs_ = lambda o: struct.unpack("<I", vf[CSID_OFF+o:CSID_OFF+o+4])[0]
ws_ = lambda o, v: vf.__setitem__(slice(CSID_OFF+o, CSID_OFF+o+4), struct.pack("<I", v))


def gdsc(off, on, label):
    wc_(off, (rc_(off) & ~SWC) if on else (rc_(off) | SWC))
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1e6 < 2000:
        if bool(rc_(off) & PWR_ON) == on:
            print(f"  {label}: {'ON' if on else 'OFF'} ok "
                  f"({(time.monotonic()-t0)*1e6:.0f} us)  {rc_(off):#010x}")
            return True
    print(f"  {label}: {'ON' if on else 'OFF'} TIMEOUT  {rc_(off):#010x}")
    return False


def clocks(on):
    for o in IFE0_CLKS + AHB_CLKS:
        wc_(o, (rc_(o) | CLK_EN) if on else (rc_(o) & ~CLK_EN))
    time.sleep(0.02)


print(f"start: ife_0 {rc_(IFE0):#010x}")
gdsc(TITAN, True, "titan_top")
if not gdsc(IFE0, True, "ife_0 #1"):
    sys.exit("!! not a pristine boot?")
clocks(True)

ws_(RDI_CTRL, 0)
time.sleep(0.005)
if rs_(RDI_CTRL) is None:
    sys.exit("!! unreadable")
ws_(RDI_CFG0, rs_(RDI_CFG0) | RDI_CFG0_ENABLE)
time.sleep(0.005)
cfg = rs_(RDI_CFG0)
print(f"  RDI_CFG0 after enable: {cfg:#010x} (bit31 {'set' if cfg & RDI_CFG0_ENABLE else 'NOT SET'})")
if not (cfg & RDI_CFG0_ENABLE):
    sys.exit("!! CSID register write did not land -- test meaningless")

ws_(RDI_CTRL, RESUME_AT_FRAME_BOUNDARY)
time.sleep(0.05)
print(f"  RDI running; RDI_CTRL reads {rs_(RDI_CTRL):#x}")
ws_(RDI_CTRL, HALT_AT_FRAME_BOUNDARY)
time.sleep(0.05)
ws_(RDI_CFG0, rs_(RDI_CFG0) & ~RDI_CFG0_ENABLE)
time.sleep(0.005)
print(f"  halted and disabled; RDI_CFG0 {rs_(RDI_CFG0):#010x}")

clocks(False)
gdsc(IFE0, False, "ife_0 #1")
print("--- the test ---")
ok = gdsc(IFE0, True, "ife_0 #2")
print()
print("VERDICT: running the CSID RDI WEDGES the GDSC" if not ok
      else "VERDICT: CSID RDI start/stop is harmless -- the VFE side is implicated")
sys.exit(0 if ok else 1)
