#!/usr/bin/env python3
"""
Bisect what wedges the SM8350 IFE GDSC: is it the VFE global reset?

Established so far (all via /dev/mem, camss out of the loop):
  * an IFE GDSC camss never touched cycles off/on indefinitely
  * one camss has streamed through can never be powered up again
  * streaming from the CSID's internal TPG -- no sensor, no CSIPHY, zero
    frames -- still wedges it, so the data path is irrelevant
  * enabling and disabling all six IFE clocks is harmless

That leaves the register programming camss does while the block is powered.
This tries the most suspicious single write: the VFE global reset that
camss-vfe-480.c issues on every power-up.

    titan_top on -> ife_0 on -> clocks on -> VFE global reset
                 -> clocks off -> ife_0 off -> ife_0 ON AGAIN

Run on a FRESH BOOT; ife_0 must start pristine (GDSCR ...f001, DOWN set).
"""
import mmap, os, struct, sys, time

CAMCC, VFE0 = 0xAD00000, 0xACB4000
TITAN, IFE0 = 0xC120, 0xA004
PWR_ON, SWC, CLK_EN = 1 << 31, 1, 1 << 0
IFE0_CLKS = [0xA028, 0xA084, 0xA088, 0xA030, 0xA058, 0xA080]
# VFE register access needs the CPAS/AHB fabric, which lives in titan_top and
# NOT in ife_0. Without these the whole VFE window reads back 0 and writes are
# silently dropped -- which invalidated the first run of this test.
AHB_CLKS = [0xC0D0,   # cam_cc_cpas_ahb_clk
            0xC0F0,   # cam_cc_camnoc_axi_clk
            0xC12C]   # cam_cc_core_ahb_clk
VFE_IRQ_MASK0, VFE_GLOBAL_RESET_CMD = 0x3C, 0x1C
IRQ_MASK_0_RESET_ACK, GLOBAL_RESET_HW_AND_REG = 1 << 0, 1 << 0

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
cc = mmap.mmap(fd, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=CAMCC)
vfe = mmap.mmap(fd, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=VFE0)
rc_ = lambda o: struct.unpack("<I", cc[o:o+4])[0]
wc_ = lambda o, v: cc.__setitem__(slice(o, o+4), struct.pack("<I", v))
wv_ = lambda o, v: vfe.__setitem__(slice(o, o+4), struct.pack("<I", v))
rv_ = lambda o: struct.unpack("<I", vfe[o:o+4])[0]


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
# Prove register access works before trusting anything this test concludes.
# Only bit 0 of IRQ_MASK0 is implemented, so a 0x5 write reads back 0x1; what
# matters is that the write lands at all. With the AHB clocks gated the whole
# window reads 0 and writes vanish, which silently invalidated an earlier run.
wv_(VFE_IRQ_MASK0, 0x5)
time.sleep(0.005)
probe = rv_(VFE_IRQ_MASK0)
print(f"  register access check: wrote 0x5 to VFE IRQ_MASK0, read {probe:#x}")
if probe == 0:
    sys.exit("!! VFE registers are not accessible -- test would be meaningless")
wv_(VFE_IRQ_MASK0, IRQ_MASK_0_RESET_ACK)
wv_(VFE_GLOBAL_RESET_CMD, GLOBAL_RESET_HW_AND_REG)
time.sleep(0.05)
print("  VFE global reset issued")
clocks(False)
gdsc(IFE0, False, "ife_0 #1")
print("--- the test ---")
ok = gdsc(IFE0, True, "ife_0 #2")
print()
print("VERDICT: the VFE GLOBAL RESET wedges the GDSC" if not ok else
      "VERDICT: the global reset is harmless -- look at the other writes")
sys.exit(0 if ok else 1)
