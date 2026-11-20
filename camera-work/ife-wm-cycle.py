#!/usr/bin/env python3
"""
Does enabling the VFE bus write master wedge the IFE GDSC?

The bisect (HANDBOOK 33.11) has eliminated, each from a fresh boot with the
register write verified: the GDSC alone, the IFE clocks, the VFE global reset,
the WM_CGC_OVERRIDE write, and running the CSID RDI path. camss streaming from
the CSID's own TPG -- no sensor, no CSIPHY, zero frames -- still wedges it,
so the VFE side is what is left.

The write master is the VFE's bus DMA engine: enabling it makes the IFE an
active master on the camera NoC. camss enables it in vfe_wm_start() and stops
it in vfe_wm_stop() with a bare `writel(0, WM_CFG)`.

RDI line 0 drives write master RDI_WM(0) = 23 on a non-lite VFE, so
VFE_BUS_WM_CFG(23) = 0xaa00 + 0x200 + 23*0x100 = 0xbd00.

    titan_top on -> ife_0 on -> clocks on
      -> WM_CFG = EN|MIPI_RAW -> REG_UPDATE -> WM_CFG = 0
    -> clocks off -> ife_0 off -> ife_0 ON AGAIN

Run on a FRESH BOOT; ife_0 must start pristine (GDSCR 0x..f001).
"""
import mmap, os, struct, sys, time

CAMCC, VFE0 = 0xAD00000, 0xACB4000
TITAN, IFE0 = 0xC120, 0xA004
PWR_ON, SWC, CLK_EN = 1 << 31, 1, 1 << 0
IFE0_CLKS = [0xA028, 0xA084, 0xA088, 0xA030, 0xA058, 0xA080]
AHB_CLKS = [0xC0D0, 0xC0F0, 0xC12C]
BUS_REG_BASE = 0xAA00
WM = 23                                        # RDI_WM(0) on a full VFE
WM_CFG = BUS_REG_BASE + 0x200 + WM * 0x100     # 0xbd00
WM_FRAME_INCR = BUS_REG_BASE + 0x208 + WM * 0x100
WM_IMAGE_CFG_0 = BUS_REG_BASE + 0x20c + WM * 0x100
WM_IMAGE_CFG_2 = BUS_REG_BASE + 0x214 + WM * 0x100
WM_CGC_OVERRIDE = BUS_REG_BASE + 0x08
WM_CGC_OVERRIDE_ALL = 0x3FFFFFF
VFE_REG_UPDATE_CMD = 0x34
REG_UPDATE_RDI0 = 1 << 1                       # BIT(1 + 0)
WM_CFG_START = (1 << 0) | (1 << 16)            # EN | MODE_MIPI_RAW

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


print(f"start: ife_0 {rc_(IFE0):#010x}")
gdsc(TITAN, True, "titan_top")
if not gdsc(IFE0, True, "ife_0 #1"):
    sys.exit("!! not a pristine boot?")
clocks(True)

wv_(WM_CGC_OVERRIDE, WM_CGC_OVERRIDE_ALL)
wv_(WM_FRAME_INCR, 5264 * 3120)
wv_(WM_IMAGE_CFG_0, 0xFFFF)
wv_(WM_IMAGE_CFG_2, 5264)
wv_(WM_CFG, WM_CFG_START)
time.sleep(0.005)
got = rv_(WM_CFG)
print(f"  WM{WM}_CFG written {WM_CFG_START:#x}, reads {got:#x}")
if got == 0:
    sys.exit("!! WM register write did not land -- test meaningless")
wv_(VFE_REG_UPDATE_CMD, REG_UPDATE_RDI0)
time.sleep(0.05)
print(f"  reg_update issued; WM still {rv_(WM_CFG):#x}")
wv_(WM_CFG, 0)
time.sleep(0.02)
print(f"  WM stopped (camss writes a bare 0 here); reads {rv_(WM_CFG):#x}")

clocks(False)
gdsc(IFE0, False, "ife_0 #1")
print("--- the test ---")
ok = gdsc(IFE0, True, "ife_0 #2")
print()
print("VERDICT: enabling the VFE WRITE MASTER WEDGES the GDSC" if not ok
      else "VERDICT: the write master is harmless too")
sys.exit(0 if ok else 1)
