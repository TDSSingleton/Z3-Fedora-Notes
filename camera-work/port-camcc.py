#!/usr/bin/env python3
"""
Port Qualcomm's downstream camcc-lahaina.c (SM8350) to a mainline
camcc-sm8350.c, plus its dt-bindings header.

Why generate from the VENDOR file rather than patch a mainline sibling:
camcc-sm8250.c is the closest mainline relative (102 of 119 clock names
shared) but SM8350 adds a third IFE, two PLLs and a split SBI, and drops the
FD block and mclk6 -- and every register offset, frequency table and parent
map would still have to be substituted. Taking the vendor file as the source
of truth means no mainline leftover can survive by accident. What this script
does instead is strip the downstream-only scaffolding and replace the
boilerplate tail with mainline idioms.

Transforms applied (each one asserted or counted, so a silent no-op fails):
  1. mainline include block + dt-bindings header name
  2. drop DEFINE_VDD_REGULATORS / the regulators array / vdd-level.h
  3. drop every .vdd_data = {...} / .clkr.vdd_data = {...} block
  4. drop .enable_safe_config and the RCG-level .flags = HW_CLK_CTRL_MODE
     (the .flags = CLK_SET_RATE_PARENT inside clk_init_data is KEPT)
  5. CLK_ALPHA_PLL_TYPE_{LUCID,ZONDA}_5LPE -> the plain types; mainline has no
     5LPE *type* enum and expresses 5LPE purely through vco table + ops, the
     way gpucc-sm8350.c does. zonda_5lpe_ops -> zonda_ops: the two sequences
     are equivalent and mainline's is stricter (explicit 1 us between
     de-bypass and reset de-assert); the FSM-vote fast path only applies to
     voted PLLs, which camcc's are not.
  6. drop the redundant .name inside clk_parent_data (mainline uses .fw_name
     alone); the .name in clk_init_data is KEPT
  7. cam_cc_lahaina -> cam_cc_sm8350 symbol rename
  8. replace the vendor tail (clk list, regmap config, match table, fixup,
     probe, driver) with a mainline tail, and add the GDSCs, which downstream
     keeps in DT (qcom,gdsc@ad0.....) rather than in the driver

Usage: port-camcc.py <camcc-lahaina.c> <out.c> <out-bindings.h>
"""
import re, sys, collections

src_path, out_c, out_h = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(src_path, errors="replace").read()
orig_len = len(src)

def brace_block(txt, start):
    """Return (begin, end) of the {...} block whose '{' first appears at/after start."""
    i = txt.index("{", start)
    d, j = 0, i
    while j < len(txt):
        if txt[j] == "{": d += 1
        elif txt[j] == "}":
            d -= 1
            if d == 0: return i, j
        j += 1
    raise ValueError("unbalanced")

# ---------- 1. include block ----------
head_new = '''// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) 2019-2020, The Linux Foundation. All rights reserved.
 * Copyright (c) 2026, mainline port for SM8350 (Samsung Galaxy Z Fold 3).
 *
 * Generated from Qualcomm's downstream camcc-lahaina.c by
 * camera-work/port-camcc.py -- every register offset, frequency table and
 * parent map comes from that file unchanged.
 */

#include <linux/clk-provider.h>
#include <linux/err.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>

#include <dt-bindings/clock/qcom,sm8350-camcc.h>

#include "clk-alpha-pll.h"
#include "clk-branch.h"
#include "clk-rcg.h"
#include "clk-regmap.h"
#include "clk-regmap-divider.h"
#include "clk-regmap-mux.h"
#include "common.h"
#include "gdsc.h"
'''
m = re.search(r'^// SPDX.*?(?=^static DEFINE_VDD_REGULATORS)', src, re.S | re.M)
assert m, "could not find the vendor include block"
src = src[:m.start()] + head_new + "\n" + src[m.end():]

# ---------- 2. vdd scaffolding ----------
src, n = re.subn(r'^static DEFINE_VDD_REGULATORS\([^\n]*\n', '', src, flags=re.M)
assert n == 2, f"expected 2 DEFINE_VDD_REGULATORS, removed {n}"
m = re.search(r'^static struct clk_vdd_class \*cam_cc_lahaina_regulators\[\]', src, re.M)
assert m, "regulators array not found"
b, e = brace_block(src, m.start())
src = src[:m.start()] + src[e + 3:]           # drop "};\n"

# ---------- 3. vdd_data blocks ----------
# 32 RCGs + 7 PLLs carry one each; clk_branch never does.
removed = 0
while True:
    m = re.search(r'\n[ \t]*\.(?:clkr\.)?vdd_data = ', src)
    if not m:
        break
    _, e = brace_block(src, m.start())      # e == index of the matching '}'
    after = re.match(r'\},[ \t]*\n', src[e:])
    assert after, f"vdd_data block not closed by '}},' at {e}: {src[e:e+20]!r}"
    src = src[:m.start()] + src[e + after.end():].rstrip("\n") if False else \
          src[:m.start()] + "\n" + src[e + after.end():]
    removed += 1
assert removed == 39, f"expected 39 vdd_data blocks (32 RCG + 7 PLL), removed {removed}"
assert "vdd_data" not in src and "vdd_class" not in src, "vdd scaffolding survived"
vdd_removed = removed

# ---------- 4. downstream-only struct fields ----------
src, n_esc = re.subn(r'^\t\.enable_safe_config = true,\n', '', src, flags=re.M)
src, n_hw = re.subn(r'^\t\.flags = HW_CLK_CTRL_MODE,\n', '', src, flags=re.M)

# ---------- 5. PLL types / ops ----------
src, n_l = re.subn(r'CLK_ALPHA_PLL_TYPE_LUCID_5LPE', 'CLK_ALPHA_PLL_TYPE_LUCID', src)
src, n_z = re.subn(r'CLK_ALPHA_PLL_TYPE_ZONDA_5LPE', 'CLK_ALPHA_PLL_TYPE_ZONDA', src)
src, n_zo = re.subn(r'clk_alpha_pll_zonda_5lpe_ops', 'clk_alpha_pll_zonda_ops', src)
src, n_zp = re.subn(r'clk_alpha_pll_postdiv_zonda_5lpe_ops',
                    'clk_alpha_pll_postdiv_zonda_ops', src)
assert n_l and n_z, "PLL type rename did nothing"

# ---------- 6. redundant .name in clk_parent_data ----------
src, n_pn = re.subn(r'(\.fw_name = "([a-z0-9_]+)",\n)\s*\.name = "\2",\n', r'\1', src)

# ---------- 6a. drop the core_bi_pll_test_se test clock ----------
# Mainline omits it entirely (camcc-sm8250.c has zero references) and no DT
# provides it, so leaving it in would give every RCG an unresolvable fw_name
# parent. It is the LAST entry of every parent_map and parent_data array, so
# removing it leaves all other parent indices untouched.
src, n_enum = re.subn(r'^\tP_CORE_BI_PLL_TEST_SE,\n', '', src, flags=re.M)
assert n_enum == 1, f"enum member: removed {n_enum}"
src, n_map = re.subn(r'^\t\{ P_CORE_BI_PLL_TEST_SE, \d+ \},\n', '', src, flags=re.M)
src, n_pd = re.subn(r'^\t\{ \.fw_name = "core_bi_pll_test_se"[^\n]*\n', '', src, flags=re.M)
assert n_map == 8 and n_pd == 8, f"maps {n_map}, parent_data {n_pd}"

def _dec(m):
    return (f'.parent_data = cam_cc_parent_data_{m.group(1)},{m.group(2)}'
            f'.num_parents = {int(m.group(3)) - 1},')
src, n_np = re.subn(
    # NB: a suffixed array exists too (cam_cc_parent_data_7_ao, bi_tcxo_ao); a
    # \d+-only pattern silently matched 32 of 33 and left that clock too high.
    r'\.parent_data = cam_cc_parent_data_(\d+(?:_[a-z]+)?),(\s*)\.num_parents = (\d+),',
    _dec, src)
assert n_np == 33, f"num_parents decremented on {n_np} clocks, expected 33"
assert "core_bi_pll_test_se" not in src and "P_CORE_BI_PLL_TEST_SE" not in src

# the array form of the redundant .name, which step 6 does not reach
src, n_an = re.subn(r'(\{ \.fw_name = "([a-z0-9_]+)"), \.name = "\2" \}', r'\1 }', src)
assert n_an >= 8, f"array-form .name removed {n_an}"

# ---------- 6b. PLL2: this SoC is a v2 part ----------
# The vendor probe calls cam_cc_lahaina_fixup(), which re-configures pll2 with
# cam_cc_pll2_config_lahaina_v2 when the compatible is "qcom,lahaina-camcc-v2".
# The Fold 3's DT says exactly that:
#     qcom,camcc@ad00000 { compatible = "qcom,lahaina-camcc-v2", "syscon"; }
# so v2 is correct here and v1 is dead code. They differ in config_ctl_val
# (0x08200920 -> 0x08200800), config_ctl_hi_val (0x05008011 -> 0x05028011) and
# config_ctl_hi1_val (0x0 -> 0x08000000), i.e. materially. Drop v1 so nothing
# can pick it up by accident.
m = re.search(r'^static const struct alpha_pll_config cam_cc_pll2_config = \{', src, re.M)
assert m, "pll2 v1 config not found"
_, e = brace_block(src, m.start())
after = re.match(r'\};\n+', src[e:])
assert after, "pll2 v1 config not closed"
src = src[:m.start()] + src[e + after.end():]
assert "cam_cc_pll2_config = {" not in src, "v1 pll2 config survived"

# ---------- 7. symbol rename ----------
src, n_sym = re.subn(r'cam_cc_lahaina', 'cam_cc_sm8350', src)

# ---------- 8. tail ----------
m = re.search(r'^static struct clk_regmap \*cam_cc_sm8350_clocks\[\]', src, re.M)
assert m, "vendor clk_regmap array not found"
body = src[:m.start()]

# discover clocks, in declaration order, so the dt-bindings indices are stable
Clk = collections.namedtuple("Clk", "sym name kind")
clocks = []
for mm in re.finditer(
        r'^static struct (clk_branch|clk_rcg2|clk_alpha_pll_postdiv|clk_alpha_pll|'
        r'clk_regmap_div|clk_regmap_mux) (\w+) = \{', body, re.M):
    kind, sym = mm.group(1), mm.group(2)
    b, e = brace_block(body, mm.start())
    nm = re.search(r'\.name = "([a-z0-9_]+)"', body[b:e])
    if nm:
        clocks.append(Clk(sym, nm.group(1), kind))

assert clocks, "no clocks discovered"
seen = set()
clocks = [c for c in clocks if not (c.name in seen or seen.add(c.name))]

def macro(name):
    return name.upper()

# GDSCs: offsets from the vendor DT's qcom,gdsc@ad0..... nodes (base 0xad00000).
# Identical to camcc-sm8250 except titan_top (0xc144 -> 0xc120) and the added
# ife_2. Verified against capture/facts-*/dt/q2q-merged-postabl.dts.
#
# FLAGS: taken from the vendor's own qcom,gdsc@ad0..... nodes in lahaina.dtsi,
# NOT from camcc-sm8250 by analogy. The downstream gdsc-regulator driver reads
# them as DT properties, which map to mainline's gdsc.c flags:
#
#   qcom,support-hw-trigger -> HW_CTRL
#   qcom,retain-regs        -> RETAIN_FF_ENABLE
#
# Per-GDSC, as extracted from lahaina.dtsi:
#
#   bps        support-hw-trigger, retain-regs
#   ipe_0      support-hw-trigger, retain-regs
#   sbi        retain-regs
#   ife_0/1/2  retain-regs
#   titan_top  retain-regs
#
# Two corrections to the first version of this port, which used
# "HW_CTRL | POLL_CFG_GDSCR" for every child and POLL_CFG_GDSCR for titan_top:
#
# 1. POLL_CFG_GDSCR is wrong here. NO vendor DT in the Samsung drop sets
#    qcom,poll-cfg-gdscr on anything -- it came from camcc-sm8250 by analogy.
#    It makes gdsc.c poll CFG_GDSCR's POWER_UP/DOWN_COMPLETE bits instead of
#    GDSCR's PWR_ON.
# 2. HW_CTRL must not be on the IFEs (or sbi). With it, the GDSC is handed to
#    hardware control on enable and software's later power-off never lands.
#
# Symptom that led here (measured 2026-11-15): the FIRST camss capture worked
# and tore down cleanly, then the second failed with
#
#   ife_0_gdsc status stuck at 'off'          (gdsc_enable)
#   qcom-camss ac6a000.isp: Failed to power up pipeline: -22
#   titan_top_gdsc status stuck at 'on'       (gdsc_disable, ~0.8s later)
#
# leaving genpd:0:ac6a000.isp in runtime-PM "error", after which every stream
# start returns -EINVAL from device_link_add() in vfe_pm_domain_on().
#
# This also lands on exactly camcc-sc8280xp.c's pattern, which is the same
# Titan generation as SM8350 -- HW_CTRL only on bps/ipe, RETAIN_FF_ENABLE
# everywhere, no POLL_CFG_GDSCR.
# CLK_DIS_WAIT: how long the GDSC waits for its clocks to halt before it
# collapses. gdsc.c defaults to 0x2 when a driver leaves clk_dis_wait_val
# unset, and that default is what SM8350's IFEs were running with.
#
# Every OTHER upstream camcc driver that sets this uses the maximum:
# camcc-qcs615.c and camcc-kaanapali.c both put .clk_dis_wait_val = 0xf on all
# their camera GDSCs, titan_top and the IFEs included. Downstream raises it
# too (lahaina.dtsi uses qcom,clk-dis-wait-val = <8> on the GPU GDSC).
#
# Tried against the "one capture per IFE GDSC per boot" bug (HANDBOOK 33.11),
# where an IFE that has actually streamed can never be powered up again. The
# shape of that bug fits a too-short halt window: an IFE GDSC that has NEVER
# had clocks running cycles off/on indefinitely, while one collapsed after
# real clock activity is corrupted by that first collapse.
CLK_DIS_WAIT = 0xf

HW_CTRL, RETAIN = "HW_CTRL", "RETAIN_FF_ENABLE"
gdscs = [("bps_gdsc",       0x7004, [HW_CTRL, RETAIN]),
         ("ipe_0_gdsc",     0x8004, [HW_CTRL, RETAIN]),
         ("sbi_gdsc",       0x9004, [RETAIN]),
         ("ife_0_gdsc",     0xa004, [RETAIN]),
         ("ife_1_gdsc",     0xb004, [RETAIN]),
         ("ife_2_gdsc",     0xb070, [RETAIN]),
         ("titan_top_gdsc", 0xc120, [RETAIN])]

gd = ["static struct gdsc titan_top_gdsc;\n"]
for nm, off, fl in gdscs:
    flags = " | ".join(fl)
    if nm == "titan_top_gdsc":
        gd.append(f"""
static struct gdsc {nm} = {{
\t.gdscr = {off:#x},
\t.pd = {{
\t\t.name = "{nm}",
\t}},
\t.pwrsts = PWRSTS_OFF_ON,
\t.flags = {flags},
\t.clk_dis_wait_val = {CLK_DIS_WAIT:#x},
}};
""")
    else:
        gd.append(f"""
static struct gdsc {nm} = {{
\t.gdscr = {off:#x},
\t.pd = {{
\t\t.name = "{nm}",
\t}},
\t.flags = {flags},
\t.parent = &titan_top_gdsc.pd,
\t.pwrsts = PWRSTS_OFF_ON,
\t.clk_dis_wait_val = {CLK_DIS_WAIT:#x},
}};
""")

clk_list = "\n".join(
    f"\t[{macro(c.name)}] = &{c.sym}.clkr," for c in clocks)
gdsc_list = "\n".join(f"\t[{nm.upper()}] = &{nm}," for nm, _, _fl in gdscs)

tail = f'''{''.join(gd)}
static struct clk_regmap *cam_cc_sm8350_clocks[] = {{
{clk_list}
}};

static struct gdsc *cam_cc_sm8350_gdscs[] = {{
{gdsc_list}
}};

static const struct regmap_config cam_cc_sm8350_regmap_config = {{
\t.reg_bits = 32,
\t.reg_stride = 4,
\t.val_bits = 32,
\t.max_register = 0xf008,
\t.fast_io = true,
}};

static const struct qcom_cc_desc cam_cc_sm8350_desc = {{
\t.config = &cam_cc_sm8350_regmap_config,
\t.clks = cam_cc_sm8350_clocks,
\t.num_clks = ARRAY_SIZE(cam_cc_sm8350_clocks),
\t.gdscs = cam_cc_sm8350_gdscs,
\t.num_gdscs = ARRAY_SIZE(cam_cc_sm8350_gdscs),
}};

static const struct of_device_id cam_cc_sm8350_match_table[] = {{
\t{{ .compatible = "qcom,sm8350-camcc" }},
\t{{ }}
}};
MODULE_DEVICE_TABLE(of, cam_cc_sm8350_match_table);

static int cam_cc_sm8350_probe(struct platform_device *pdev)
{{
\tstruct regmap *regmap;

\tregmap = qcom_cc_map(pdev, &cam_cc_sm8350_desc);
\tif (IS_ERR(regmap))
\t\treturn PTR_ERR(regmap);

\tclk_lucid_5lpe_pll_configure(&cam_cc_pll0, regmap, &cam_cc_pll0_config);
\tclk_lucid_5lpe_pll_configure(&cam_cc_pll1, regmap, &cam_cc_pll1_config);
\t/*
\t * pll2 takes the v2 config: the only compatible this driver claims is the
\t * v2 part (the vendor DT's "qcom,lahaina-camcc-v2"), whose fixup path
\t * configures pll2 with these values rather than the v1 ones.
\t */
\tclk_zonda_pll_configure(&cam_cc_pll2, regmap, &cam_cc_pll2_config_sm8350_v2);
\tclk_lucid_5lpe_pll_configure(&cam_cc_pll3, regmap, &cam_cc_pll3_config);
\tclk_lucid_5lpe_pll_configure(&cam_cc_pll4, regmap, &cam_cc_pll4_config);
\tclk_lucid_5lpe_pll_configure(&cam_cc_pll5, regmap, &cam_cc_pll5_config);
\tclk_lucid_5lpe_pll_configure(&cam_cc_pll6, regmap, &cam_cc_pll6_config);

\t/*
\t * Deliberately NOT done here, although the vendor driver does it:
\t *
\t *\tregmap_update_bits(regmap, 0xc148, BIT(0), BIT(0));
\t *
\t * That force-enables cam_cc_gdsc_clk, which sits inside titan_top_gdsc.
\t * Holding it on pins the domain: titan_top then never collapses, and
\t * because the write bypasses the clock framework nothing shows a
\t * non-zero enable_cnt to explain why. Measured 2026-11-15 -- the first
\t * camss capture worked, its teardown logged
\t *
\t *\ttitan_top_gdsc status stuck at 'on'
\t *\tWARNING: drivers/clk/qcom/gdsc.c:192 gdsc_toggle_logic
\t *
\t * and from then on ife_0_gdsc would not enable, leaving
\t * genpd:0:ac6a000.isp in runtime-PM "error" so every later stream start
\t * failed -EINVAL out of device_link_add() in vfe_pm_domain_on().
\t *
\t * Upstream camcc-sm8250 models cam_cc_gdsc_clk as an ordinary branch and
\t * never enables it, and its GDSCs cycle fine; the vendor can get away
\t * with the write because downstream manages these domains itself and
\t * never asks titan_top to collapse.
\t */

\treturn qcom_cc_really_probe(&pdev->dev, &cam_cc_sm8350_desc, regmap);
}}

static struct platform_driver cam_cc_sm8350_driver = {{
\t.probe = cam_cc_sm8350_probe,
\t.driver = {{
\t\t.name = "camcc-sm8350",
\t\t.of_match_table = cam_cc_sm8350_match_table,
\t}},
}};

module_platform_driver(cam_cc_sm8350_driver);

MODULE_DESCRIPTION("QTI CAMCC SM8350 Driver");
MODULE_LICENSE("GPL");
'''

open(out_c, "w").write(body + tail)

# ---------- bindings header ----------
hdr = ["/* SPDX-License-Identifier: GPL-2.0-only */",
       "/*",
       " * Copyright (c) 2019-2020, The Linux Foundation. All rights reserved.",
       " * Copyright (c) 2026, mainline port for SM8350.",
       " *",
       " * Indices generated from camcc-lahaina.c declaration order by",
       " * camera-work/port-camcc.py.",
       " */",
       "",
       "#ifndef _DT_BINDINGS_CLK_QCOM_CAM_CC_SM8350_H",
       "#define _DT_BINDINGS_CLK_QCOM_CAM_CC_SM8350_H",
       "",
       "/* CAM_CC clocks */"]
for i, c in enumerate(clocks):
    hdr.append(f"#define {macro(c.name):<42} {i}")
hdr += ["", "/* CAM_CC power domains */"]
for i, (nm, _, _fl) in enumerate(gdscs):
    hdr.append(f"#define {nm.upper():<42} {i}")
hdr += ["", "#endif", ""]
open(out_h, "w").write("\n".join(hdr))

print(f"source {orig_len} -> {len(body)+len(tail)} bytes")
print(f"  vdd_data blocks removed      : {vdd_removed}")
print(f"  enable_safe_config removed   : {n_esc}")
print(f"  HW_CLK_CTRL_MODE flags removed: {n_hw}")
print(f"  LUCID_5LPE -> LUCID          : {n_l}")
print(f"  ZONDA_5LPE -> ZONDA          : {n_z} (+{n_zo} ops, +{n_zp} postdiv ops)")
print(f"  redundant parent .name removed: {n_pn} standalone + {n_an} array")
print(f"  test-clock entries removed   : {n_map} maps, {n_pd} parent_data,"
      f" num_parents fixed on {n_np} clocks")
print(f"  symbol renames               : {n_sym}")
print(f"  clocks discovered            : {len(clocks)}")
print(f"  gdscs emitted                : {len(gdscs)}")
by = collections.Counter(c.kind for c in clocks)
for k, v in sorted(by.items()):
    print(f"    {k:26} {v}")
