#!/usr/bin/env python3
"""
Does leaving VFE_BUS_WM_CGC_OVERRIDE set wedge the IFE GDSC?

camss-vfe-480.c writes WM_CGC_OVERRIDE_ALL (0x3FFFFFF) to the bus write-master
clock-gating override in vfe_wm_start(), and NEVER clears it -- vfe_wm_stop()
only zeroes WM_CFG. So after any stream all 26 write-master clock gates are
forced open, and camss then collapses the IFE power domain in that state.

Everything else has been eliminated by this method already: clocks alone are
harmless, the VFE global reset is harmless (with register access verified),
and the data path is irrelevant (the CSID's internal TPG with zero frames
captured still wedges it).

    titan_top on -> ife_0 on -> clocks on -> write CGC override
                 -> clocks off -> ife_0 off -> ife_0 ON AGAIN

Run on a FRESH BOOT; ife_0 must start pristine (GDSCR ...f001).
"""
import mmap, os, struct, sys, time

CAMCC, VFE0 = 0xAD00000, 0xACB4000
TITAN, IFE0 = 0xC120, 0xA004
PWR_ON, SWC, CLK_EN = 1 << 31, 1, 1 << 0
IFE0_CLKS = [0xA028, 0xA084, 0xA088, 0xA030, 0xA058, 0xA080]
AHB_CLKS = [0xC0D0, 0xC0F0, 0xC12C]
BUS_REG_BASE = 0xAA00
VFE_BUS_WM_CGC_OVERRIDE = BUS_REG_BASE + 0x08
WM_CGC_OVERRIDE_ALL = 0x3FFFFFF

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
cc = mmap.mmap(fd, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=CAMCC)
vf = mmap.mmap(fd, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=VFE0)
rc_ = lambda o: struct.unpack("<I", cc[o:o+4])[0]
wc_ = lambda o, v: cc.__setitem__(slice(o, o+4), struct.pack("<I", v))
rv_ = lambda o: struct.unpack("<I", vf[o:o+4])[0]
wv_ = lambda o, v: vf.__setitem__(slice(o, o+4), struct.pack("<I", v))


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


clear_after = "--clear" in sys.argv

print(f"start: ife_0 {rc_(IFE0):#010x}")
gdsc(TITAN, True, "titan_top")
if not gdsc(IFE0, True, "ife_0 #1"):
    sys.exit("!! not a pristine boot?")
clocks(True)
wv_(VFE_BUS_WM_CGC_OVERRIDE, WM_CGC_OVERRIDE_ALL)
time.sleep(0.005)
got = rv_(VFE_BUS_WM_CGC_OVERRIDE)
print(f"  wrote CGC override {WM_CGC_OVERRIDE_ALL:#x}, reads {got:#x}")
if got == 0:
    sys.exit("!! register write did not land -- test meaningless")
if clear_after:
    wv_(VFE_BUS_WM_CGC_OVERRIDE, 0)
    time.sleep(0.005)
    print(f"  cleared it again, reads {rv_(VFE_BUS_WM_CGC_OVERRIDE):#x}")
clocks(False)
gdsc(IFE0, False, "ife_0 #1")
print("--- the test ---")
ok = gdsc(IFE0, True, "ife_0 #2")
print()
if clear_after:
    print("VERDICT(with clear): " + ("re-powers fine" if ok else "still wedged"))
else:
    print("VERDICT: CGC OVERRIDE WEDGES THE GDSC" if not ok
          else "VERDICT: CGC override is harmless")
sys.exit(0 if ok else 1)
