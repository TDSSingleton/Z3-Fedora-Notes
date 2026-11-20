#!/usr/bin/env python3
"""
Cover-camera (IMX374, cam-sensor11/13) bring-up probe, v2.

Runs ON THE DEVICE, with camcc-mclk-test.ko already loaded (MCLK3 @ 24 MHz +
titan_top_gdsc on).

IMPORTANT, learned the hard way: the module reset VT10M2_RST_N is expander
gpio 21 on the PCAL6524 at 0x22, and that chip has the pca953x driver bound
with a regmap CACHE. v1 of this probe "restored" the line by writing 0x0e/0x06
directly with i2cset. That desynced the driver's cache, after which gpiolib's
own direction write was skipped as redundant and every later reset release
silently did nothing -- the pin stayed an input, reset stayed asserted, and
three probe runs measured nothing at all.

So: the reset line is driven ONLY through the gpio chardev here, and released
only by closing the fd. Expander registers are READ (harmless) to verify the
pin, never written. The S2MPB02 at i2c-0 is different -- that bus is
deliberately driverless, so i2cset there is the project's normal method.
"""
import os, fcntl, struct, subprocess, time

CHIP, LINE, PMIC = "/dev/gpiochip3", 21, "0x59"
RAILS = [("cam_vio  ldo7", "0x24", "0xb0"),
         ("cam_vana ldo13", "0x2a", "0xd8"),
         ("cam_vdig ldo3", "0x20", "0xa4")]

def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout.strip()

def pin():
    i = sh("i2cget", "-f", "-y", "3", "0x22", "0x02")
    c = sh("i2cget", "-f", "-y", "3", "0x22", "0x0e")
    if not i or not c:
        return "unreadable"
    lvl = (int(i, 16) >> 5) & 1
    direction = "in" if (int(c, 16) >> 5) & 1 else "OUT"
    return "level=%d dir=%s" % (lvl, direction)

REQ = 592
IOC_GET = (3 << 30) | (REQ << 16) | (0xB4 << 8) | 0x07
IOC_SETV = (3 << 30) | (16 << 16) | (0xB4 << 8) | 0x0F
FLAG_OUTPUT = 1 << 3

def req(val):
    fd = os.open(CHIP, os.O_RDWR)
    r = struct.pack("<64I", *([LINE] + [0] * 63)) + b"cover-probe".ljust(32, b"\0")
    r += (struct.pack("<QI", FLAG_OUTPUT, 1) + b"\0" * 20
          + struct.pack("<IIQ", 2, 0, 1 if val else 0) + struct.pack("<Q", 1)
          + b"\0" * (24 * 9))
    r += struct.pack("<II", 1, 0) + b"\0" * 20 + struct.pack("<i", -1)
    out = fcntl.ioctl(fd, IOC_GET, r)
    return fd, struct.unpack("<i", out[-4:])[0]

def setv(lfd, val):
    fcntl.ioctl(lfd, IOC_SETV, struct.pack("<QQ", 1 if val else 0, 1))

def probe(addr="0x51"):
    t = time.monotonic()
    rc = subprocess.run(["i2cget", "-y", "6", addr, "0x00"],
                        capture_output=True).returncode
    return "%.3fs rc=%d" % (time.monotonic() - t, rc)

def main():
    mclk = sh("grep", "-E", "cam_cc_mclk3_clk ", "/sys/kernel/debug/clk/clk_summary")
    print("mclk3:", " ".join(mclk.split()[:4]) if mclk else "NOT FOUND")
    saved = [(r, sh("i2cget", "-f", "-y", "0", PMIC, r)) for _, r, _ in RAILS]
    chipfd = linefd = None
    try:
        print("at rest            :", pin())
        for n, r, v in RAILS:
            sh("i2cset", "-f", "-y", "0", PMIC, r, v)
            time.sleep(0.001)
        time.sleep(0.02)
        print("rails up, in reset :", pin(), "| 0x51", probe())

        chipfd, linefd = req(0)
        time.sleep(0.005)
        print("reset asserted     :", pin())
        setv(linefd, 1)
        time.sleep(0.050)
        print("reset RELEASED     :", pin(), "| 0x51", probe())
        if "dir=in" in pin():
            print("\n!! pin is still an INPUT -- the pca953x cache is desynced again.")
            print("   Reboot and do not write 0x22's registers.")
        print()
        for a in ("0x51", "0x50", "0x11", "0x13", "0x1a", "0x20", "0x34", "0x42"):
            print("   %-5s %s" % (a, probe(a)))
        print("\n16-bit read at 0x51:",
              sh("i2ctransfer", "-y", "6", "w2@0x51", "0x00", "0x00", "r4") or "(no reply)")
        print("\nfull scan:")
        print(sh("i2cdetect", "-y", "-r", "6"))
    finally:
        if linefd is not None and linefd >= 0:
            os.close(linefd)
        if chipfd is not None:
            os.close(chipfd)
        for r, v in saved:
            if v:
                sh("i2cset", "-f", "-y", "0", PMIC, r, v)
        print("restored rails:",
              " ".join(sh("i2cget", "-f", "-y", "0", PMIC, r) for r, _ in saved),
              "| pin:", pin())

main()
