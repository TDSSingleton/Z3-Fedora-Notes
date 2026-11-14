#!/usr/bin/env python3
"""Parse a GPT dumped from a 4Kn disk. sgdisk assumes 512 B sectors and
cannot read this from a file, so do it directly."""
import struct, sys, uuid
BS = int(sys.argv[2]) if len(sys.argv) > 2 else 4096
d = open(sys.argv[1], "rb").read()
h = d[BS:BS*2]
if h[:8] != b"EFI PART": sys.exit("!! no EFI PART signature at LBA 1")
(sig, rev, hsz, crc, _r, cur, bak, first, last) = struct.unpack_from("<8sIIII QQQQ", h, 0)
pt_lba, nent, entsz, pcrc = struct.unpack_from("<QIII", h, 72)
disk_guid = uuid.UUID(bytes_le=h[56:72])
print(f"  disk GUID     {disk_guid}")
print(f"  this header   LBA {cur}      backup LBA {bak}")
print(f"  usable        LBA {first} .. {last}")
print(f"  entries       {nent} x {entsz} B at LBA {pt_lba}")
print(f"  disk size     {(last+1)*BS/2**30:.2f} GiB usable, {BS} B sectors")
print()
parts=[]
for i in range(nent):
    o = (pt_lba - 0)*BS + i*entsz
    if o+entsz > len(d): break
    tguid = d[o:o+16]
    if tguid == b"\0"*16: continue
    s_lba, e_lba, flags = struct.unpack_from("<QQQ", d, o+32)
    name = d[o+56:o+128].decode("utf-16-le").split("\0")[0]
    parts.append((i+1, name, s_lba, e_lba, (e_lba-s_lba+1)*BS))
print(f"  {'#':>3} {'name':<20} {'start LBA':>12} {'end LBA':>12} {'size':>12}")
print(f"  {'-'*3} {'-'*20} {'-'*12} {'-'*12} {'-'*12}")
for n,name,s,e,sz in parts:
    u = f"{sz/2**30:.2f}G" if sz >= 2**30 else f"{sz/2**20:.0f}M"
    print(f"  {n:>3} {name:<20} {s:>12} {e:>12} {u:>12}")
print()
print(f"  {len(parts)} partitions")
last_p = max(parts, key=lambda p: p[3])
print(f"  highest end LBA: {last_p[1]} ends at {last_p[3]} (usable last = {last})")
print(f"  slack after it : {(last - last_p[3])*BS/2**20:.1f} MiB")
big = sorted(parts, key=lambda p:-p[4])[:4]
print("\n  largest:")
for n,name,s,e,sz in big: print(f"    {name:<20} {sz/2**30:8.2f} GiB")
