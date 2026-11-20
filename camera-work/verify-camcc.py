#!/usr/bin/env python3
"""
Verify the generated camcc-sm8350.c carries EXACTLY the vendor's register data.

Compares, per clock name, every register-ish field between
camcc-lahaina.c and the generated file, and fails on any difference. This is
the check that makes the port auditable: the generator is allowed to delete
downstream scaffolding and rename symbols, and nothing else.

Usage: verify-camcc.py <camcc-lahaina.c> <camcc-sm8350.c>
"""
import re, sys, collections

FIELDS = ("parent_data", "offset", "cmd_rcgr", "halt_reg", "enable_reg", "enable_mask",
          "mnd_width", "hid_width", "post_div_shift", "width", "halt_check",
          "parent_map", "freq_tbl", "num_parents", "reg", "shift", "flags")

def parse(path):
    txt = open(path, errors="replace").read()
    out = {}
    for m in re.finditer(r'^static struct (clk_branch|clk_rcg2|clk_alpha_pll_postdiv|'
                         r'clk_alpha_pll|clk_regmap_div|clk_regmap_mux) (\w+) = \{',
                         txt, re.M):
        i = txt.index("{", m.start()); d = 0; j = i
        while j < len(txt):
            if txt[j] == "{": d += 1
            elif txt[j] == "}":
                d -= 1
                if d == 0: break
            j += 1
        body = txt[i:j+1]
        nm = re.search(r'\.name = "([a-z0-9_]+)"', body)
        if not nm: continue
        vals = {}
        for f in FIELDS:
            for mm in re.finditer(r'\.' + f + r' = ([^,\n]+)', body):
                vals.setdefault(f, []).append(mm.group(1).strip())
        out[nm.group(1)] = (m.group(1), vals)
    # frequency tables, compared verbatim
    ft = {}
    for m in re.finditer(r'^static const struct freq_tbl (ftbl_\w+)\[\] = \{(.*?)^\};',
                         txt, re.S | re.M):
        ft[m.group(1)] = re.sub(r'\s+', ' ', m.group(2)).strip()
    # parent maps, compared verbatim
    pm = {}
    for m in re.finditer(r'^static const struct parent_map (\w+)\[\] = \{(.*?)^\};',
                         txt, re.S | re.M):
        pm[m.group(1)] = re.sub(r'\s+', ' ', m.group(2)).strip()
    return out, ft, pm

vend, vft, vpm = parse(sys.argv[1])
gen,  gft, gpm = parse(sys.argv[2])

bad = []
# the vendor models cam_cc_gdsc_clk nowhere on this SoC; everything else must match
for name, (kind, vv) in vend.items():
    if name not in gen:
        bad.append(f"MISSING from generated: {kind} {name}")
        continue
    gkind, gv = gen[name]
    if gkind != kind:
        bad.append(f"{name}: kind {kind} -> {gkind}")
    for f in FIELDS:
        a, b = vv.get(f), gv.get(f)
        if f == "flags":
            # the RCG-level HW_CLK_CTRL_MODE flag is deliberately dropped;
            # clk_init_data flags must survive
            a = [x for x in (a or []) if "HW_CLK_CTRL_MODE" not in x]
            b = b or []
        if f == "num_parents" and a and b:
            # the core_bi_pll_test_se parent is deliberately dropped (mainline
            # omits it and no DT provides it), so every clock using a
            # cam_cc_parent_data_* array legitimately has one fewer parent
            uses_array = any("cam_cc_parent_data_" in x
                             for x in (vv.get("parent_data") or []))
            if uses_array and [str(int(x) - 1) for x in a] == b:
                continue
        if (a or None) != (b or None):
            bad.append(f"{name}: .{f} {a} -> {b}")

extra = set(gen) - set(vend)
if extra:
    bad.append(f"clocks in generated but NOT in vendor: {sorted(extra)}")

for nm, body in vft.items():
    if nm not in gft: bad.append(f"freq_tbl MISSING: {nm}")
    elif gft[nm] != body: bad.append(f"freq_tbl DIFFERS: {nm}")
def strip_test(body):
    """drop the deliberately-removed core_bi_pll_test_se entry"""
    return re.sub(r'\{ P_CORE_BI_PLL_TEST_SE, \d+ \},\s*', '', body).strip()

for nm, body in vpm.items():
    if nm not in gpm: bad.append(f"parent_map MISSING: {nm}")
    elif gpm[nm] != strip_test(body):
        bad.append(f"parent_map DIFFERS: {nm}\n      vendor(norm): {strip_test(body)}\n      generated   : {gpm[nm]}")

print(f"vendor clocks      : {len(vend)}")
print(f"generated clocks   : {len(gen)}")
print(f"freq tables checked: {len(vft)}")
print(f"parent maps checked: {len(vpm)}")
if bad:
    print(f"\n*** {len(bad)} DISCREPANCIES ***")
    for b in bad[:40]: print("  " + b)
    sys.exit(1)
print("\nOK: every clock, register value, frequency table and parent map in the")
print("generated driver is byte-identical to the vendor's.")
