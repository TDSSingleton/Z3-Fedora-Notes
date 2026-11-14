#!/usr/bin/env python3
"""hybrid.py OUT BASE DONOR lo:hi [lo:hi ...]  -- BASE with DONOR's BDF bytes in the given
ranges (offsets inside the BDF payload), checksum fixed (xor16 of payload == 0xffff, field at 0x0a)."""
import sys, struct
from bdf import load, xor16
out, base, donor = sys.argv[1:4]
b, bo, n = load(base); d, do, n2 = load(donor); assert n == n2
for r in sys.argv[4:]:
    lo, hi = (int(x, 0) for x in r.split(':'))
    b[bo+lo:bo+hi] = d[do+lo:do+hi]
b[bo+10:bo+12] = b'\0\0'
struct.pack_into('<H', b, bo+10, xor16(b[bo:bo+n]) ^ 0xffff)
assert xor16(b[bo:bo+n]) == 0xffff
open(out, 'wb').write(b)
