#!/usr/bin/env python3
"""
Does merely enabling and disabling the IFE's clocks, with no camss and no
register programming, wedge its GDSC?

Background: on SM8350 an IFE GDSC that camss has used once can never be
powered up again, yet one that camss has never touched cycles off/on
indefinitely (camera-work/gdscpoke.py). Streaming from the CSID's internal
test pattern -- no sensor, no CSIPHY, zero frames captured -- still wedges it,
so the data path is not involved. What is left is the clock enable/disable and
the VFE/CSID register programming. This isolates the clocks.

Sequence, all through /dev/mem:
    titan_top on -> ife_0 on -> enable IFE clocks -> disable them
                 -> ife_0 off -> ife_0 ON AGAIN  <- does this time out?

Run on a FRESH BOOT, before anything has streamed, or the result is
meaningless -- the GDSC must start pristine (GDSCR ...f001, DOWN=1).
"""
import mmap, os, struct, sys, time

BASE, SPAN = 0xAD00000, 0x10000
TITAN, IFE0 = 0xC120, 0xA004
PWR_ON, SWC = 1 << 31, 1
CLK_EN = 1 << 0           # CBCR bit 0 = CLK_ENABLE
CLK_OFF = 1 << 31         # CBCR bit 31 = CLK_OFF (1 == halted)
IFE0_CLKS = {"ife_0": 0xA028, "ife_0_axi": 0xA084, "ife_0_ahb": 0xA088,
             "ife_0_areg": 0xA030, "ife_0_csid": 0xA058,
             "ife_0_cphy_rx": 0xA080}

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, SPAN, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)
r = lambda o: struct.unpack("<I", m[o:o + 4])[0]
w = lambda o, v: m.__setitem__(slice(o, o + 4), struct.pack("<I", v))


def gdsc(off, on, label):
    w(off, (r(off) & ~SWC) if on else (r(off) | SWC))
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1e6 < 2000:
        if bool(r(off) & PWR_ON) == on:
            print(f"  {label}: {'ON' if on else 'OFF'} ok "
                  f"({(time.monotonic()-t0)*1e6:.0f} us)  {r(off):#010x}")
            return True
    print(f"  {label}: {'ON' if on else 'OFF'} TIMEOUT  {r(off):#010x}")
    return False


def clocks(on):
    for name, off in IFE0_CLKS.items():
        w(off, (r(off) | CLK_EN) if on else (r(off) & ~CLK_EN))
    time.sleep(0.01)
    state = []
    for name, off in IFE0_CLKS.items():
        v = r(off)
        state.append(f"{name}={'run' if not (v & CLK_OFF) else 'halt'}")
    print(f"  clocks {'ENABLED ' if on else 'DISABLED'}: {' '.join(state)}")


print(f"start: ife_0 {r(IFE0):#010x} (pristine looks like 0x..f001, DOWN set)")
gdsc(TITAN, True, "titan_top")
if not gdsc(IFE0, True, "ife_0 #1"):
    sys.exit("!! could not power up at all -- not a pristine boot?")
clocks(True)
clocks(False)
gdsc(IFE0, False, "ife_0 #1")
print("--- the test: power it up a second time ---")
ok = gdsc(IFE0, True, "ife_0 #2")
print()
print("VERDICT: clocks alone WEDGE the GDSC" if not ok else
      "VERDICT: clocks alone are harmless -- the register writes are implicated")
sys.exit(0 if ok else 1)
