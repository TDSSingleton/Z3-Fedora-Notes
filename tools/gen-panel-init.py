#!/usr/bin/env python3
"""Emit a mainline DRM panel init function from a Samsung DTS command sequence.

Uses the current upstream idiom: mipi_dsi_multi_context + *_multi() helpers,
so the generated code needs no per-call error handling.

Usage: gen-panel-init.py <board.dts> <panel-label> <func_name> [--prop on-command] [--variant N]
"""
import sys, argparse, importlib.util, os

spec = importlib.util.spec_from_file_location(
    "e", os.path.join(os.path.dirname(__file__), "extract-panel-cmds.py"))
e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e)

ap = argparse.ArgumentParser()
ap.add_argument('dts'); ap.add_argument('label'); ap.add_argument('func')
ap.add_argument('--prop', default='on-command'); ap.add_argument('--variant', type=int, default=0)
a = ap.parse_args()

lines = open(a.dts, errors='replace').read().splitlines()
s, en = e.find_node(lines, a.label)

uniq, order = {}, []
for ln, name, raw in e.props(lines, s, en, a.prop):
    if not name.endswith(a.prop):
        continue
    b = tuple(e.dts_prop_bytes(raw))
    if b not in uniq:
        uniq[b] = ln; order.append(b)
if not order:
    sys.exit(f"no {a.prop} found in {a.label}")
b = order[min(a.variant, len(order) - 1)]
cmds = e.parse_stream(list(b))

print(f"/* Generated from {os.path.basename(a.dts)}")
print(f" * {a.label}")
print(f" * {a.prop} variant {a.variant} of {len(order)} (DTS line {uniq[b]})")
print(f" * {len(b)} bytes -> {len(cmds)} commands")
print(f" */")
print(f"static void {a.func}(struct mipi_dsi_multi_context *ctx)")
print("{")
for dtype, wait, p, _ in cmds:
    if not p:
        continue
    if dtype == 0x07:
        print(f"\t/* DSC compression mode enable={p[0]} -- handled by msm DSI via drm_dsc_config */")
        continue
    if dtype == 0x0A:
        print(f"\t/* DSC PPS ({len(p)} bytes) -- emit with mipi_dsi_compression_mode_multi() +")
        print(f"\t * drm_dsc_pps_payload_pack() from the drm_dsc_config below, NOT as a raw blob */")
        continue
    args = ', '.join(f"0x{x:02x}" for x in p)
    print(f"\tmipi_dsi_dcs_write_seq_multi(ctx, {args});")
    if wait:
        print(f"\tmipi_dsi_msleep(ctx, {wait});")
print("}")
