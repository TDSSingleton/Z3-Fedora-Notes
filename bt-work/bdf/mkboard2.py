#!/usr/bin/env python3
"""mkboard2.py OUT BDF.elf [NAME]  -- wrap one BDF into an ath11k board-2.bin container."""
import sys, struct
NAME = 'bus=pci,vendor=17cb,device=1103,subsystem-vendor=17cb,subsystem-device=0108,qmi-chip-id=2,qmi-board-id=255'
def pad(b): return b + b'\0' * (-len(b) % 4)
def ie(t, v): return struct.pack('<II', t, len(v)) + pad(v)
out, bdf = sys.argv[1:3]; name = (sys.argv[3] if len(sys.argv) > 3 else NAME).encode()
body = ie(0, name) + ie(1, open(bdf, 'rb').read())
open(out, 'wb').write(pad(b'QCA-ATH11K-BOARD\0') + ie(0, body))
