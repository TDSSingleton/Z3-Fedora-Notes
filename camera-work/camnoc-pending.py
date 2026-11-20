#!/usr/bin/env python3
"""
Read the camera NoC's pending-slave-transaction sense bits.

The vendor's CPAS driver has an erratum workaround,
`camnoc_flush_slave_pending_trans`, which before powering the camera NoC down
polls camnoc `sbm_SenseIn0_Low` (offset 0x3900) until bits 17-19 read 0 --
i.e. it waits for outstanding camnoc slave transactions to drain. On Lahaina
(Titan 580) the register and its semantics are defined but the workaround is
left `.enable = false`.

That matters here because the open SM8350 bug is "an IFE GDSC that has
actually streamed can never be powered up again", and a stuck bus transaction
is the obvious candidate. If these bits are set after a capture, the IFE is
being collapsed with transactions still outstanding.

MUST be run while the camera NoC is clocked -- i.e. straight after a capture,
while CCI still holds camnoc_axi/cpas_ahb and titan_top is up. Reading it at
idle, with those clocks gated, will abort.

Offsets from the vendor's cam_cpas monitor code, camnoc base 0xac42000.
"""
import mmap
import os
import struct
import sys

CAMNOC = 0xAC42000
SPAN = 0x8000
SBM_SENSEIN0_LOW = 0x3900
PENDING_MASK = 0xE0000           # bits 17, 18, 19
FILL_LEVELS = [("ife0?", 0x0A20), ("ife1?", 0x1420), ("ife2?", 0x1A20),
               ("580_a", 0x7620), ("580_b", 0x7420)]

fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
m = mmap.mmap(fd, SPAN, mmap.MAP_SHARED, mmap.PROT_READ, offset=CAMNOC)
r = lambda o: struct.unpack("<I", m[o:o + 4])[0]

sense = r(SBM_SENSEIN0_LOW)
pend = sense & PENDING_MASK
print(f"  sbm_SenseIn0_Low (0x3900) = {sense:#010x}")
print(f"    pending-slave bits 17-19 = {pend >> 17:#05b}  "
      f"-> {'PENDING TRANSACTIONS' if pend else 'drained (vendor expects this)'}")
print("  camnoc fill levels:")
for name, off in FILL_LEVELS:
    print(f"    {off:#06x} ({name:<5}) = {r(off):#010x}")
sys.exit(1 if pend else 0)
