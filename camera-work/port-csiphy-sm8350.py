#!/usr/bin/env python3
"""
Generate mainline camss `lane_regs_sm8350[]` from Qualcomm's CSIPHY v1.2.3
register tables, and PROVE the transform by regenerating the table mainline
already ships for SM8250 (CSIPHY v1.2.1) and diffing it byte-for-byte.

Why this is needed
------------------
SM8350 (Lahaina) CSIPHY is "qcom,csiphy-v1.2.3"; SM8250 (Kona) is
"qcom,csiphy-v1.2.1".  Those are *different* register sequences in the vendor
driver (cam_csiphy_soc.c selects a different csiphy_2ph_* table per version),
so camss cannot simply reuse `lane_regs_sm8250` for SM8350.

Mainline's `lane_regs_sm8250[]` is exactly the vendor's
`csiphy_2ph_v1_2_1_reg[MAX_LANES][MAX_SETTINGS_PER_LANE]` flattened lane by
lane, dropping the unused trailing slots.  That is a mechanical transform, so
this script applies the same transform to `csiphy_2ph_v1_2_3_reg` -- and
validates itself by replaying it on v1.2.1 and comparing against the in-tree
mainline array.  A self-check that reproduces 100/100 known-good entries is
what makes the 95 generated ones trustworthy.

2PH (D-PHY) only: mainline camss implements D-PHY, not C-PHY, and the sensors
on this board are D-PHY.

Usage:
    ./camera-work/port-csiphy-sm8350.py            # verify + write out/
    ./camera-work/port-csiphy-sm8350.py --check    # verify only, no write
"""

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = (ROOT / "SM-F926B/Kernel/techpack/camera/drivers"
                 "/cam_sensor_module/cam_csiphy/include")
# mainline tree carrying camss; the reference copy of lane_regs_sm8250
MAINLINE_CANDIDATES = [
    ROOT / "linux-fedora/drivers/media/platform/qcom/camss/camss-csiphy-3ph-1-0.c",
    ROOT / "linux/drivers/media/platform/qcom/camss/camss-csiphy-3ph-1-0.c",
]
OUT = ROOT / "camera-work/out"

# {0x0030, 0x00, 0x00, CSIPHY_DEFAULT_PARAMS},
ENTRY = re.compile(
    r"\{\s*(0[xX][0-9a-fA-F]+|\d+)\s*,"      # reg_addr
    r"\s*(0[xX][0-9a-fA-F]+|\d+)\s*,"        # reg_data
    r"\s*(0[xX][0-9a-fA-F]+|\d+)\s*,"        # delay
    r"\s*([A-Z0-9_]+)\s*\}"                  # csiphy_param_type
)


def extract_array(text, symbol):
    """Return the [lane][setting] lists for `symbol` in a vendor hwreg header.

    The vendor declares
        struct csiphy_reg_t <symbol>[MAX_LANES][MAX_SETTINGS_PER_LANE] = {
            { {..}, {..}, ... },   /* lane 0 */
            ...
        };
    Only the entries actually written are present; the rest of each row is
    implicitly zero and must NOT be emitted.
    """
    m = re.search(re.escape(symbol) + r"\s*\[[^\]]*\]\s*\[[^\]]*\]\s*=\s*\{", text)
    if not m:
        raise SystemExit(f"!! {symbol}: declaration not found")

    # Walk braces from the opening one to find the initialiser's exact extent.
    start = m.end() - 1
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                body = text[start + 1:i]
                break
    else:
        raise SystemExit(f"!! {symbol}: unbalanced braces")

    # Split the body into per-lane groups at depth 1.
    lanes, depth, cur = [], 0, []
    for ch in body:
        if ch == "{":
            depth += 1
            if depth == 1:
                cur = []
                continue
        elif ch == "}":
            depth -= 1
            if depth == 0:
                lanes.append("".join(cur))
                continue
        if depth >= 1:
            cur.append(ch)

    out = []
    for lane in lanes:
        rows = [(int(a, 0), int(d, 0), int(dl, 0), p)
                for a, d, dl, p in ENTRY.findall(lane)]
        out.append(rows)
    if not out:
        raise SystemExit(f"!! {symbol}: parsed zero lanes")
    return out


def flatten(lanes):
    return [row for lane in lanes for row in lane]


def render(rows, symbol, comment):
    """Emit the rows in mainline's exact source style."""
    lines = [f"/* {comment} */", "static const struct",
             f"csiphy_lane_regs {symbol}[] = {{"]
    for addr, data, delay, ptype in rows:
        lines.append(f"\t{{0x{addr:04X}, 0x{data:02X}, "
                     f"0x{delay:02X}, {ptype}}},")
    lines.append("};")
    return "\n".join(lines) + "\n"


def parse_mainline(path, symbol):
    """Parse mainline's own flat lane_regs_* array for comparison."""
    text = path.read_text()
    m = re.search(r"csiphy_lane_regs\s+" + re.escape(symbol) + r"\s*\[\s*\]\s*=\s*\{", text)
    if not m:
        raise SystemExit(f"!! {symbol} not found in {path}")
    start = m.end() - 1
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                body = text[start + 1:i]
                break
    return [(int(a, 0), int(d, 0), int(dl, 0), p)
            for a, d, dl, p in ENTRY.findall(body)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="run the self-check only; do not write out/")
    args = ap.parse_args()

    h121 = VENDOR / "cam_csiphy_1_2_1_hwreg.h"
    h123 = VENDOR / "cam_csiphy_1_2_3_hwreg.h"
    for p in (h121, h123):
        if not p.is_file():
            raise SystemExit(f"!! missing vendor header {p}\n"
                             "   (Samsung GPL drop; see tools/setup-sources.sh)")

    mainline = next((p for p in MAINLINE_CANDIDATES if p.is_file()), None)
    if mainline is None:
        raise SystemExit("!! no mainline camss-csiphy-3ph-1-0.c found")

    # ---- self-check: v1.2.1 must reproduce mainline's lane_regs_sm8250 ----
    got = flatten(extract_array(h121.read_text(), "csiphy_2ph_v1_2_1_reg"))
    want = parse_mainline(mainline, "lane_regs_sm8250")

    print(f"self-check against {mainline.relative_to(ROOT)}")
    print(f"  vendor v1.2.1 flattened : {len(got)} entries")
    print(f"  mainline lane_regs_sm8250: {len(want)} entries")
    if got != want:
        print("  MISMATCH -- the transform is not what mainline did:")
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                print(f"    [{i}] generated {g}  !=  mainline {w}")
        if len(got) != len(want):
            print(f"    length differs: {len(got)} vs {len(want)}")
        return 1
    print(f"  IDENTICAL -- {len(got)}/{len(want)} entries match exactly\n")

    # ---- the actual port: v1.2.3 -> lane_regs_sm8350 ----
    lanes = extract_array(h123.read_text(), "csiphy_2ph_v1_2_3_reg")
    rows = flatten(lanes)
    print("generating lane_regs_sm8350 from vendor v1.2.3")
    for i, lane in enumerate(lanes):
        print(f"  lane {i}: {len(lane)} entries")
    print(f"  total  : {len(rows)} entries")

    ptypes = sorted({r[3] for r in rows})
    print(f"  param types used: {', '.join(ptypes)}")
    # Every param type we emit must already be understood by mainline.
    known = set(re.findall(r"#define\s+(CSIPHY_[A-Z0-9_]+)",
                           mainline.read_text()))
    unknown = [p for p in ptypes if p not in known]
    if unknown:
        print(f"  !! param types mainline does not define: {unknown}")
        return 1
    print("  all param types are defined by mainline camss")

    src = render(rows, "lane_regs_sm8350", "GEN2 1.2.3 2PH")
    if args.check:
        print("\n--check: not writing")
        return 0
    OUT.mkdir(exist_ok=True)
    dst = OUT / "lane_regs_sm8350.c.inc"
    dst.write_text(src)
    print(f"\nwrote {dst.relative_to(ROOT)}  ({len(src.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
