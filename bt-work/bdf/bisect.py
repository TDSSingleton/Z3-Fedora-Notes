#!/usr/bin/env python3
"""Find which regions of Samsung's BDF crash upstream amss: graft DONOR[lo:hi) onto BASE, test on the phone."""
import subprocess, sys, os, tempfile
BASE, DONOR = 'generic-17cb0108-c2-b255.elf', 'bdwlan.elf'
N = 58180; MIN = 48
log = open('bisect.log', 'a', buffering=1)
def test(ranges):
    f = tempfile.mktemp(suffix='.elf')
    subprocess.run([sys.executable, 'hybrid.py', f, BASE, DONOR] + [f'{a:#x}:{b:#x}' for a, b in ranges], check=True, env=dict(os.environ, PYTHONPATH='.'))
    label = '+'.join(f'{a:#x}-{b:#x}' for a, b in ranges)
    for attempt in range(2):
        out = subprocess.run(['./bdtest.sh', label, f], capture_output=True, text=True).stdout.strip()
        log.write(out + '\n'); print(out, flush=True)
        if 'RESULT crash' in out: return True
        if 'RESULT ok' in out: return False
    raise SystemExit('no result twice -- phone gone? stopping')
def find(lo, hi):
    if not test([(lo, hi)]): return []
    if hi - lo <= MIN: return [(lo, hi)]
    mid = (lo + hi) // 2 & ~1
    l = find(lo, mid); r = find(mid, hi)
    return (l + r) or [(lo, hi)]
bad = find(int(sys.argv[1], 0), int(sys.argv[2], 0))
log.write(f'BAD {bad}\n'); print('BAD', [(hex(a), hex(b)) for a, b in bad], flush=True)
