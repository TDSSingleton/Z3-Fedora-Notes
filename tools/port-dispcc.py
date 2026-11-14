#!/usr/bin/env python3
"""
Port a qcom display clock controller between SoCs, using a vendor driver's
register map as the authoritative source.

HISTORICAL NOTE: this was written to port dispcc-sm8250.c to SM8350. That turned
out to be UNNECESSARY -- upstream's dispcc-sm8250.c is a multi-SoC driver that
already claims "qcom,sm8350-dispcc" and applies the SM8350 deltas at runtime.
The script is kept because (a) it independently computed exactly the 27 register
deltas upstream applies, which validated both, and (b) the same approach works
for genuinely unsupported SoCs.

Why this is a script and not hand-editing: the two drivers describe the same ~60
clocks with the same names, and the port is a mechanical substitution of register
offsets plus a few structural edits. Doing it programmatically makes the result
auditable and lets us ASSERT afterwards that every offset came from the
downstream driver rather than being left over from sm8250.

Usage: port-dispcc.py <dispcc-sm8250.c> <dispcc-lahaina.c> <out.c>
"""
import re, sys, collections

up_path, dn_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
up = open(up_path, errors='replace').read()
dn = open(dn_path, errors='replace').read()

Blk = collections.namedtuple('Blk', 'kind name body start end')

def blocks(txt):
    """Find top-level clock struct definitions and the clock name inside each."""
    pats = [
        ('branch', r'static struct clk_branch (\w+) = \{'),
        ('rcg',    r'static struct clk_rcg2 (\w+) = \{'),
        ('div',    r'static struct clk_regmap_div (\w+) = \{'),
        ('pll',    r'static struct clk_alpha_pll (\w+) = \{'),
    ]
    out = []
    for kind, p in pats:
        for m in re.finditer(p, txt):
            # brace-match to the closing "};"
            i = txt.index('{', m.start()); d = 0; j = i
            while j < len(txt):
                if txt[j] == '{': d += 1
                elif txt[j] == '}':
                    d -= 1
                    if d == 0: break
                j += 1
            body = txt[i:j+1]
            nm = re.search(r'\.name = "([a-z0-9_]+)"', body)
            if nm:
                out.append(Blk(kind, nm.group(1), body, m.start(), j+1))
    return out

# ---- 1. harvest the authoritative register values from downstream ----
dn_regs = {}
for b in blocks(dn):
    v = {}
    for key, pat in (('halt',  r'\.halt_reg = (0x[0-9a-fA-F]+)'),
                     ('en',    r'\.enable_reg = (0x[0-9a-fA-F]+)'),
                     ('mask',  r'\.enable_mask = (BIT\(\d+\)|0x[0-9a-fA-F]+)'),
                     ('rcgr',  r'\.cmd_rcgr = (0x[0-9a-fA-F]+)'),
                     ('reg',   r'\.reg = (0x[0-9a-fA-F]+)'),
                     ('off',   r'\.offset = (0x[0-9a-fA-F]+)')):
        m = re.search(pat, b.body)
        if m: v[key] = m.group(1)
    dn_regs[b.name] = v

# ---- 2. rewrite each upstream block's offsets from downstream ----
report, missing, edits = [], [], 0
out = up
for b in sorted(blocks(up), key=lambda x: -x.start):   # back-to-front: offsets stay valid
    d = dn_regs.get(b.name)
    if not d:
        missing.append((b.kind, b.name)); continue
    nb = b.body
    for pat, newval, label in (
            (r'\.halt_reg = (0x[0-9a-fA-F]+)',   d.get('halt'), 'halt'),
            (r'\.enable_reg = (0x[0-9a-fA-F]+)', d.get('en'),   'en'),
            (r'\.enable_mask = (BIT\(\d+\))',    d.get('mask'), 'mask'),
            (r'\.cmd_rcgr = (0x[0-9a-fA-F]+)',   d.get('rcgr'), 'rcgr'),
            (r'\.reg = (0x[0-9a-fA-F]+)',        d.get('reg'),  'reg'),
            (r'\.offset = (0x[0-9a-fA-F]+)',     d.get('off'),  'off')):
        m = re.search(pat, nb)
        if m and newval and m.group(1) != newval:
            nb = nb[:m.start(1)] + newval + nb[m.end(1):]
            report.append(f"  {b.name:42} {label:5} {m.group(1):8} -> {newval}")
            edits += 1
    out = out[:b.start] + out[b.start:b.end].replace(b.body, nb) + out[b.end:]

open(out_path, 'w').write(out)

print(f"substituted {edits} register values from {dn_path.split('/')[-1]}")
print("\n".join(report[:200]))
if missing:
    print(f"\nupstream clocks with NO downstream counterpart ({len(missing)}):")
    for k, n in missing: print(f"  {k:7} {n}")
dn_only = sorted(set(dn_regs) - {b.name for b in blocks(up)})
if dn_only:
    print(f"\ndownstream-only clocks ({len(dn_only)}):")
    for n in dn_only: print(f"          {n}")
