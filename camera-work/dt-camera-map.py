#!/usr/bin/env python3
"""
Build the Fold 3's camera rail / bus / power-sequence map from the LIVE stock
device tree, pulled as a filesystem from /sys/firmware/devicetree/base.

Why this and not a .dts parse: /proc/device-tree is one file per property, so
phandle -> node resolution is exact. An earlier attempt parsed the decompiled
merged .dts with naive brace tracking and silently mapped two distinct
phandles to the same regulator, which produced a wrong rail table that was
then acted on. There is no text parsing here at all.
"""
import os, struct, sys, pathlib

ROOT = pathlib.Path(sys.argv[1])          # .../x/base

def be32(b, i=0):
    return struct.unpack_from(">I", b, i*4)[0]

def raw(p):
    try: return p.read_bytes()
    except Exception: return b""

def strs(b):
    return [s.decode("utf-8", "replace") for s in b.split(b"\x00") if s]

# ---- exact phandle -> path map, straight off the filesystem ----
ph = {}
for d, _, files in os.walk(ROOT):
    if "phandle" in files:
        b = raw(pathlib.Path(d) / "phandle")
        if len(b) >= 4:
            ph[be32(b)] = os.path.relpath(d, ROOT)

def nodename(path):
    return os.path.basename(path) or "/"

# ---- find the camera nodes ----
cams = []
for d, _, files in os.walk(ROOT):
    n = os.path.basename(d)
    if n.startswith(("qcom,cam-sensor", "qcom,eeprom", "qcom,ois", "qcom,actuator",
                     "qcom,camera-flash")):
        cams.append(pathlib.Path(d))

def cell(p, name):
    b = raw(p / name)
    return be32(b) if len(b) >= 4 else None

print("=" * 78)
print("Fold 3 (SM-F926B / q2q) camera topology -- from the LIVE stock device tree")
print("=" * 78)

for p in sorted(cams, key=lambda x: (os.path.basename(x))):
    parent = os.path.relpath(p.parent, ROOT)
    name = os.path.basename(p)
    ci = cell(p, "cell-index")
    sd = cell(p, "csiphy-sd-index")
    cm = cell(p, "cci-master")
    sa = cell(p, "slave-addr")
    rg = cell(p, "reg")
    print(f"\n### {name}")
    print(f"  parent bus      : {parent}")
    if ci is not None: print(f"  cell-index      : {ci}")
    if sd is not None: print(f"  csiphy-sd-index : {sd}")
    if cm is not None: print(f"  cci-master      : {cm}")
    if sa is not None: print(f"  slave-addr      : 0x{sa:02x}  (7-bit 0x{sa>>1:02x})")
    elif rg is not None: print(f"  reg             : 0x{rg:02x}")

    names = strs(raw(p / "regulator-names"))
    mins  = raw(p / "rgltr-min-voltage")
    maxs  = raw(p / "rgltr-max-voltage")
    loads = raw(p / "rgltr-load-current")
    if names:
        print("  rails:")
        for i, rn in enumerate(names):
            sup = raw(p / f"{rn}-supply")
            tgt = ph.get(be32(sup), "?") if len(sup) >= 4 else "(none)"
            mn = be32(mins, i) if len(mins) >= (i+1)*4 else None
            mx = be32(maxs, i) if len(maxs) >= (i+1)*4 else None
            ld = be32(loads, i) if len(loads) >= (i+1)*4 else None
            v = ""
            if mn is not None:
                v = f"{mn/1e6:.3f} V" if mn == mx else f"{mn/1e6:.3f}-{mx/1e6:.3f} V"
                if mn == 0: v = "(clock, not a rail)"
            print(f"    {rn:16s} -> {nodename(tgt):22s} {v:22s}"
                  + (f" {ld} uA" if ld else ""))

    seq = strs(raw(p / "qcom,cam-power-seq-type"))
    if seq:
        cfg = raw(p / "qcom,cam-power-seq-cfg-val")
        dly = raw(p / "qcom,cam-power-seq-delay")
        print("  power sequence (in order):")
        for i, s in enumerate(seq):
            c = be32(cfg, i) if len(cfg) >= (i+1)*4 else "?"
            dd = be32(dly, i) if len(dly) >= (i+1)*4 else "?"
            print(f"    {i+1}. {s:16s} val={c} delay={dd} ms")

    cr = raw(p / "clock-rates")
    if len(cr) >= 4:
        rates = [be32(cr, i) for i in range(len(cr)//4)]
        print(f"  mclk rates      : {', '.join(f'{r/1e6:g} MHz' for r in rates if r)}")
