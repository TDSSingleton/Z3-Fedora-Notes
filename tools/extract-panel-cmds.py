#!/usr/bin/env python3
"""
Decode Samsung/Qualcomm DSI panel command sequences out of a decompiled Samsung
board DTS, for porting to a mainline DRM panel driver.

Qualcomm's MDSS command-stream format is a 7-byte header per command:

    dtype, last, vc, ack, wait_ms, dlen_hi, dlen_lo, <dlen payload bytes>

DTS carries these either as a bytestring  [29 01 00 00 00 00 03 f0 5a 5a]
or as 32-bit cells                        <0x29010000 0x3f0 ...>  (big-endian).

Usage:
    extract-panel-cmds.py <board.dts> <panel-node-label> [--c] [--prop NAME]

    --c         emit a C command table instead of an annotated decode
    --prop      only this property (default: all command-like properties)
"""
import sys, re, argparse

# MIPI DSI data types we expect to see in a panel init sequence.
DTYPE = {
    0x05: "DCS_SHORT_WRITE",      0x15: "DCS_SHORT_WRITE_PARAM",
    0x06: "DCS_READ",             0x29: "GENERIC_LONG_WRITE",
    0x39: "DCS_LONG_WRITE",       0x37: "SET_MAX_RETURN_SIZE",
    0x03: "GENERIC_SHORT_WRITE_0",0x13: "GENERIC_SHORT_WRITE_1",
    0x23: "GENERIC_SHORT_WRITE_2",0x07: "COMPRESSION_MODE",
    0x0A: "PPS_LONG_WRITE",
}

# Standard DCS command bytes. Samsung's manufacturer commands (0xF0, 0xFC, 0x9F,
# 0xB0, 0xCB, 0xF6, 0xF7, 0x60, 0x68 ...) are vendor-specific and NOT in this map:
# those are the ones that need the panel datasheet or careful transcription.
DCS = {
    0x00:"nop", 0x01:"soft_reset", 0x10:"enter_sleep_mode", 0x11:"exit_sleep_mode",
    0x12:"enter_partial_mode", 0x13:"enter_normal_mode", 0x20:"exit_invert_mode",
    0x21:"enter_invert_mode", 0x28:"set_display_off", 0x29:"set_display_on",
    0x2A:"set_column_address", 0x2B:"set_page_address", 0x2C:"write_memory_start",
    0x30:"set_partial_rows", 0x33:"set_scroll_area", 0x34:"set_tear_off",
    0x35:"set_tear_on", 0x36:"set_address_mode", 0x3C:"write_memory_continue",
    0x39:"set_gamma_curve", 0x44:"set_tear_scanline", 0x51:"set_display_brightness",
    0x53:"write_control_display", 0x55:"write_power_save", 0x5E:"set_cabc_min_brightness",
    0x9D:"set_compression_mode", 0x03:"get_power_mode(rd)",
}

def dts_prop_bytes(text):
    """Turn a DTS property value into a flat list of bytes."""
    text = text.strip().rstrip(';').strip()
    if text.startswith('['):                       # bytestring
        return [int(t, 16) for t in text[1:text.rindex(']')].split()]
    if text.startswith('<'):                       # 32-bit cells, big-endian
        out = []
        for t in text[1:text.rindex('>')].split():
            v = int(t, 16) if t.startswith('0x') else int(t)
            out += [(v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF]
        return out
    return []

def parse_stream(b):
    """Split a Qualcomm MDSS command stream into (dtype, wait_ms, payload)."""
    cmds, i = [], 0
    while i + 7 <= len(b):
        dtype, last, vc, ack, wait = b[i], b[i+1], b[i+2], b[i+3], b[i+4]
        dlen = (b[i+5] << 8) | b[i+6]
        i += 7
        if dtype == 0 and dlen == 0:               # cell padding at the tail
            continue
        payload = b[i:i+dlen]
        if len(payload) < dlen:
            cmds.append((dtype, wait, payload, "TRUNCATED")); break
        i += dlen
        cmds.append((dtype, wait, payload, None))
    return cmds

TIMING_KEYS = {
    'panel-width':'w','panel-height':'h','h-pulse-width':'hpw','h-back-porch':'hbp',
    'h-front-porch':'hfp','h-sync-skew':'skew','v-pulse-width':'vpw','v-back-porch':'vbp',
    'v-front-porch':'vfp','panel-framerate':'fps','panel-clockrate':'clk',
    't-clk-pre':'tpre','t-clk-post':'tpost',
}

def modes(lines, start, end):
    """Parse the timing nodes under qcom,mdss-dsi-display-timings.

    Samsung names them by content (qxga120hs, hd60phs, ...), not timing@N."""
    out, cur, name, depth_at = [], None, None, None
    in_timings, d = False, 0
    for i in range(start, end + 1):
        l = lines[i]
        if 'qcom,mdss-dsi-display-timings' in l and '{' in l:
            in_timings, d = True, 0
        if not in_timings:
            continue
        d += l.count('{') - l.count('}')
        m = re.match(r'\s+([a-z0-9_@]+) \{', l)
        if m and d == 2:
            if cur is not None:
                out.append((name, cur))
            name, cur = m.group(1), {}
        if cur is not None:
            k = re.match(r'\s*qcom,mdss-(?:dsi-|dsc-)?([a-z0-9-]+)\s*=\s*<(0x[0-9a-f]+|\d+)>', l)
            if k and k.group(1) in TIMING_KEYS:
                v = k.group(2)
                cur[TIMING_KEYS[k.group(1)]] = int(v, 16) if v.startswith('0x') else int(v)
            k = re.match(r'\s*qcom,mdss-dsc-slice-(height|width)\s*=\s*<(0x[0-9a-f]+|\d+)>', l)
            if k:
                v = k.group(2)
                cur['sh' if k.group(1) == 'height' else 'sw'] = int(v, 16) if v.startswith('0x') else int(v)
            k = re.match(r'\s*qcom,mdss-dsi-panel-phy-timings\s*=\s*\[([0-9a-f ]+)\]', l)
            if k:
                cur['phy'] = k.group(1).strip()
            k = re.match(r'\s*qcom,mdss-mdp-transfer-time-us\s*=\s*<(0x[0-9a-f]+|\d+)>', l)
            if k:
                v = k.group(1)
                cur['xfer'] = int(v, 16) if v.startswith('0x') else int(v)
        if d == 0 and in_timings:
            if cur is not None:
                out.append((name, cur))
            break
    return out

def find_node(lines, label):
    start = next((i for i, l in enumerate(lines) if label + ' {' in l), None)
    if start is None:
        sys.exit(f"node label {label!r} not found")
    d = 0
    for i in range(start, len(lines)):
        d += lines[i].count('{') - lines[i].count('}')
        if d == 0 and i > start:
            return start, i
    return start, len(lines) - 1

def props(lines, start, end, want=None):
    """Yield (line_no, name, raw_value) for command-like properties."""
    pat = re.compile(r'\s*((?:qcom|samsung),[a-z0-9_-]*(?:command|cmds)[a-z0-9_-]*)\s*=\s*(.*)')
    i = start
    while i <= end:
        m = pat.match(lines[i])
        if m:
            name, rest = m.group(1), m.group(2)
            j = i
            while ';' not in rest and j < end:
                j += 1; rest += lines[j]
            if (want is None or want in name) and rest.lstrip()[:1] in '[<':
                yield i + 1, name, rest
            i = j
        i += 1

def decode_pps(p):
    """Decode a DSC Picture Parameter Set (DSC 1.x byte layout)."""
    g = lambda i: p[i] if i < len(p) else 0
    be = lambda i: (g(i) << 8) | g(i + 1)
    bpp = be(4) & 0x03FF
    return [
        f"dsc_version        {g(0) >> 4}.{g(0) & 0xF}",
        f"bits_per_component {g(3) >> 4}",
        f"linebuf_depth      {g(3) & 0xF}",
        f"bits_per_pixel     {bpp / 16:g}  (raw {bpp}, 1/16 units)",
        f"pic_height         {be(6)}",
        f"pic_width          {be(8)}",
        f"slice_height       {be(10)}",
        f"slice_width        {be(12)}",
        f"chunk_size         {be(14)}",
        f"initial_xmit_delay {be(16) & 0x03FF}",
        f"initial_dec_delay  {be(18)}",
        f"block_pred_enable  {(g(4) >> 5) & 1}",
        f"convert_rgb        {(g(4) >> 4) & 1}",
        f"slices_per_line    {be(8) // be(12) if be(12) else '?'}",
    ]

def annotate(cmds):
    out, total_wait = [], 0
    for dtype, wait, p, err in cmds:
        total_wait += wait
        dt = DTYPE.get(dtype, f"0x{dtype:02X}?")
        if not p:
            out.append(f"    {dt:24} (empty)"); continue
        w = f"  wait {wait}ms" if wait else ""
        e = f"  !! {err}" if err else ""
        # 0x07 compression-mode and 0x0A PPS carry no DCS register in payload[0]
        if dtype in (0x07, 0x0A):
            if dtype == 0x07:
                out.append(f"    {dt:24} enable={p[0]}{w}{e}")
            else:
                out.append(f"    {dt:24} [{len(p):3}] DSC PPS{w}{e}")
                out += ["      " + l for l in decode_pps(p)]
            continue
        reg = p[0]
        name = DCS.get(reg, "")
        tag = f"  <- {name}" if name else ""
        args = ' '.join(f"{x:02x}" for x in p[1:])
        out.append(f"    {dt:24} {reg:#04x} [{len(p)-1:3}] {args[:60]}{'...' if len(args)>60 else ''}{tag}{w}{e}")
    return out, total_wait

def emit_c(name, cmds):
    ident = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    print(f"/* {name} -- {len(cmds)} commands */")
    print(f"static const struct panel_cmd {ident}[] = {{")
    for dtype, wait, p, _ in cmds:
        if not p: continue
        payload = ', '.join(f"0x{x:02x}" for x in p)
        print(f"\t{{ .wait_ms = {wait:3}, .len = {len(p):3}, .data = {{ {payload} }} }},")
    print("};\n")

def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('dts'); ap.add_argument('label')
    ap.add_argument('--c', action='store_true'); ap.add_argument('--prop')
    ap.add_argument('--modes', action='store_true')
    a = ap.parse_args()

    lines = open(a.dts, errors='replace').read().splitlines()
    s, e = find_node(lines, a.label)
    if not a.c:
        print(f"# {a.label}")
        print(f"# DTS lines {s+1}..{e+1}\n")

    if a.modes:
        ms = modes(lines, s, e)
        print(f"## mode table -- {len(ms)} timing nodes\n")
        print(f"  {'node':12} {'WxH':>12} {'fps':>4} {'h pw/bp/fp':>12} {'v pw/bp/fp':>14}"
              f" {'bitclk':>13} {'slice':>9} {'xfer us':>8}")
        for n, t in ms:
            g = lambda k: t.get(k, 0)
            print(f"  {n:12} {g('w'):>5}x{g('h'):<6} {g('fps'):>4}"
                  f" {g('hpw'):>3}/{g('hbp')}/{g('hfp'):<4}"
                  f" {g('vpw'):>4}/{g('vbp')}/{g('vfp'):<6}"
                  f" {g('clk'):>13,} {g('sw')}x{g('sh'):<5} {g('xfer'):>8}")
        print()
        phys = {}
        for n, t in ms:
            if 'phy' in t:
                phys.setdefault(t['phy'], []).append(n)
        print("  DSI PHY timings (qcom,mdss-dsi-panel-phy-timings):")
        for ph, ns in phys.items():
            print(f"    [{ph}]  <- {', '.join(ns)}")
        print()
        return

    seen = {}
    for ln, name, raw in props(lines, s, e, a.prop):
        b = dts_prop_bytes(raw)
        cmds = parse_stream(b)
        key = (name, tuple(b))
        if key in seen:
            if not a.c:
                print(f"## {name}  (line {ln}) -- IDENTICAL to line {seen[key]}\n")
            continue
        seen[key] = ln
        if a.c:
            emit_c(f"{name} @line {ln}", cmds)
        else:
            body, tw = annotate(cmds)
            print(f"## {name}  (line {ln})")
            print(f"   {len(b)} bytes -> {len(cmds)} commands, {tw}ms total delay")
            print('\n'.join(body)); print()

if __name__ == '__main__':
    main()
