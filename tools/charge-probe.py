#!/usr/bin/python3
"""Fold 3: one-screen view of the whole charging path. Runs ON the device.

READ-ONLY by default. Everything it prints is measured, not inferred:

  input        VBYP and IIN from the fuel gauge -- the only way to see what
               voltage and current the charger is actually pulling, and what
               proves a 9 V negotiation later.
  pack         the gauge's own voltage/current/percent.
  per cell     both S2ASL01 limiters: branch voltage, branch current, and the
               hardware cap each one is enforcing. The two branch currents
               should sum to roughly the pack current; if one sits AT its cap
               while the other does not, that branch is in regulation and
               dissipating the difference.
  chip         what the charger is set to and what state it reports.

Scaling is from Samsung's drivers, not guessed:
  s2asl01_limiter.c  VBAT/VCHG = ((v1<<4)|(v2>>4)) * 1.25 mV
                     ICHG      = same packing * 1.5625 mA
                     CTRL4 cap = d<=4 ? d*75+50 : (d-4)*50+350   (rev 1/VER_6030)
  max77705_fuelgauge.c  VBYP = w * 0.427246 mV,  IIN = w * 0.125 mA
  max77705_charger.c    CNFG_02[5:0] = mA/50, CNFG_09[6:0] = mA/25 - 1,
                        CNFG_04[5:0] float = d<=4 ? d*50+4000 : (d-4)*10+4200

Usage:
  charge-probe.py                 one snapshot
  charge-probe.py --watch [SECS]  repeat until interrupted (default 5 s)
"""
import glob, os, subprocess, sys, time

CHG, FG, USBC = 0x69, 0x36, 0x25
MAIN_ADDR, SUB_ADDR = 0x38, 0x39
BAT = "/sys/class/power_supply/max170xx_battery/"
PSY = "/sys/class/power_supply/max77705-charger/"
BC = {0: "none", 1: "SDP", 2: "CDP", 3: "DCP"}
CHG_DTLS = {0x0: "prequal", 0x1: "fast-CC", 0x2: "fast-CV", 0x3: "top-off",
            0x4: "done", 0x5: "off(?)", 0x6: "off(?)", 0x7: "off(?)",
            0x8: "timer-fault", 0xa: "det-suspend", 0xb: "off"}
BAT_DTLS = {0: "no battery", 1: "prequal", 2: "dead", 3: "good",
            4: "low voltage", 5: "overvoltage", 6: "reserved"}


def rd(bus, addr, reg, word=False):
    out = subprocess.run(["i2cget", "-y", "-f", str(bus), hex(addr), hex(reg)]
                         + (["w"] if word else []),
                         capture_output=True, text=True)
    if out.returncode:
        return None
    return int(out.stdout.strip(), 16)


def pmic_bus():
    d = glob.glob("/sys/bus/i2c/devices/*-0066")
    return int(os.path.basename(d[0]).split("-")[0]) if d else None


def find_limiter(addr):
    """Bus numbers move; find the limiter by probing its ID register (0x29 reads
    0x90 on this unit: es 2, rev 1, VER_6030)."""
    for dev in sorted(glob.glob("/dev/i2c-*")):
        b = int(dev.rsplit("-", 1)[1])
        if rd(b, addr, 0x29) is not None:
            return b
    return None


def pack12(v1, v2):
    return ((v1 << 4) | (v2 >> 4)) & 0x0FFF


def fcc_cap(ctrl4):
    d = ctrl4 & 0x3F
    return d * 75 + 50 if d <= 4 else (d - 4) * 50 + 350


def sysfs(path, div=1):
    try:
        return int(open(path).read()) / div
    except OSError:
        return None
def pack_temps():
    """[(label, degC)] for the pack thermistors exposed as ADC7 IIO channels.

    Empty if the running DTB predates those channel nodes.
    """
    out = []
    for d in sorted(glob.glob("/sys/bus/iio/devices/iio:device*")):
        for f in sorted(glob.glob(d + "/in_temp_*_input")):
            label = f.rsplit("/", 1)[1][len("in_temp_"):-len("_input")]
            try:
                out.append((label, int(open(f).read()) / 1000))
            except (OSError, ValueError):
                pass
    return out


def snapshot(bus, lim_buses):
    L = []
    # ---- input side, from the fuel gauge ----
    vbyp = rd(bus, FG, 0xB3, word=True)
    iin = rd(bus, FG, 0xD0, word=True)
    typ = rd(bus, USBC, 0x08)
    L.append("  input    VBYP %s   IIN %s   BC1.2 %s" % (
        "%.2f V" % (vbyp * 0.427246 / 1000) if vbyp is not None else "?",
        "%4d mA" % (iin * 0.125) if iin is not None else "?",
        BC.get(typ & 3, "?") if typ is not None else "?"))

    # ---- pack, from the gauge's own power_supply ----
    v = sysfs(BAT + "voltage_now", 1000)
    i = sysfs(BAT + "current_now", 1000)
    cap = sysfs(BAT + "capacity")
    # NOT the gauge's temp: its TEX bit is set, so that register is a frozen
    # host-written constant and nothing on mainline writes it. The real pack
    # thermistors are PM8350 GPIO2/GPIO3 read through PMK8350's ADC7, which
    # our DTS exposes as two IIO channels.
    therms = pack_temps()
    if therms:
        tstr = "   ".join("%s %.1f C" % (n, v2) for n, v2 in therms)
    else:
        t = sysfs(BAT + "temp", 10)
        tstr = "%.1f C (gauge, FROZEN -- no thermistor channel)" % (t or 0)
    L.append("  pack     %.3f V   %+5.0f mA   %s%%   %s" % (
        v / 1000 if v else 0, i or 0, int(cap) if cap is not None else "?",
        tstr))

    # ---- the two branches ----
    total = 0
    for label, addr in (("main", MAIN_ADDR), ("sub ", SUB_ADDR)):
        b = lim_buses.get(addr)
        if b is None:
            L.append("  %s     not found on any bus" % label)
            continue
        r = [rd(b, addr, x) for x in (0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C,
                                      0x0D, 0x0E, 0x12)]
        if any(x is None for x in r):
            L.append("  %s     read failed on bus %d" % (label, b))
            continue
        vchg = pack12(r[0], r[1]) * 1.25
        vbat = pack12(r[2], r[3]) * 1.25
        ichg = pack12(r[4], r[5]) * 1.5625
        idis = pack12(r[6], r[7]) * 1.5625
        cap_ma = fcc_cap(r[8])
        net = ichg - idis
        total += net
        at_cap = "  <-- AT CAP" if ichg >= cap_ma * 0.97 else ""
        L.append("  %s     in %.3f V  cell %.3f V  %+7.1f mA (chg %.0f / dis "
                 "%.0f)  cap %d mA%s"
                 % (label, vchg / 1000, vbat / 1000, net, ichg, idis,
                    cap_ma, at_cap))
    L.append("  branches net %+.0f mA (gauge says %+.0f mA)" % (total, i or 0))

    # ---- the charger chip ----
    ok, d0, d1 = rd(bus, CHG, 0xB2), rd(bus, CHG, 0xB3), rd(bus, CHG, 0xB4)
    cnfg02, cnfg04, cnfg09 = (rd(bus, CHG, 0xB9), rd(bus, CHG, 0xBB),
                              rd(bus, CHG, 0xC0))
    if None not in (ok, d1, cnfg02, cnfg04, cnfg09):
        cc = cnfg02 & 0x3F
        fl = cnfg04 & 0x3F
        L.append("  chip     charge %d mA   input %d mA   float %d mV   "
                 "chg_en %d" % (
                     100 if cc <= 2 else cc * 50,
                     ((cnfg09 & 0x7F) + 1) * 25,
                     fl * 50 + 4000 if fl <= 4 else (fl - 4) * 10 + 4200,
                     (cnfg09 >> 7) & 1))
        L.append("  state    %s / battery %s   CHGIN %s   AICL %s" % (
            CHG_DTLS.get(d1 & 0xF, hex(d1 & 0xF)),
            BAT_DTLS.get((d1 >> 4) & 7, "?"),
            "valid" if ok & 0x40 else "ABSENT",
            "limiting" if not ok & 0x80 else "idle"))

    # ---- driver, if bound ----
    if os.path.isdir(PSY):
        L.append("  driver   bound: %s, cc %d mA, ilim %d mA" % (
            open(PSY + "status").read().strip(),
            sysfs(PSY + "constant_charge_current", 1000) or 0,
            sysfs(PSY + "input_current_limit", 1000) or 0))
    else:
        L.append("  driver   NOT bound (no %s)" % PSY)
    return "\n".join(L)


def main():
    bus = pmic_bus()
    if bus is None:
        sys.exit("no max77705 found (looked for /sys/bus/i2c/devices/*-0066)")
    lim = {a: find_limiter(a) for a in (MAIN_ADDR, SUB_ADDR)}
    watch = "--watch" in sys.argv
    period = 5
    if watch:
        rest = sys.argv[sys.argv.index("--watch") + 1:]
        if rest and rest[0].isdigit():
            period = int(rest[0])
    print("max77705 on i2c-%d; limiters: main i2c-%s, sub i2c-%s"
          % (bus, lim[MAIN_ADDR], lim[SUB_ADDR]))
    while True:
        print(time.strftime("[%H:%M:%S]"))
        print(snapshot(bus, lim))
        if not watch:
            return
        time.sleep(period)


if __name__ == "__main__":
    main()
