#!/usr/bin/env python3
"""
Shrink userdata and append a linux partition, on a 4Kn GPT.

Everything happens on local files. Nothing touches the device. sgdisk assumes
512-byte sectors and silently misreads this table, so the edit is done here.
"""
import struct, sys, uuid, zlib, binascii

BS = 4096
SRC_P, SRC_B = "rescue/gpt/gpt-primary.bin", "rescue/gpt/gpt-backup.bin"
OUT_P, OUT_B = "rescue/gpt/new-primary.bin", "rescue/gpt/new-backup.bin"
UD_GIB = float(sys.argv[1]) if len(sys.argv) > 1 else 32.0
LINUX_TYPE = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")  # Linux filesystem

prim = bytearray(open(SRC_P, "rb").read())
hdr  = bytearray(prim[BS:BS*2])
first_usable, last_usable = struct.unpack_from("<QQ", hdr, 40)
pt_lba, nent, entsz = struct.unpack_from("<QII", hdr, 72)
ents = bytearray(prim[pt_lba*BS : pt_lba*BS + nent*entsz])

def ent(i): return ents[i*entsz:(i+1)*entsz]
def name(i):
    return bytes(ent(i)[56:128]).decode("utf-16-le").split("\0")[0]

ud = next(i for i in range(nent) if name(i) == "userdata")
ud_start, ud_end = struct.unpack_from("<QQ", ents, ud*entsz + 32)
free = next(i for i in range(nent) if ents[i*entsz:i*entsz+16] == b"\0"*16)

new_ud_end = ud_start + int(UD_GIB * 2**30 // BS) - 1
lx_start   = ((new_ud_end + 1 + 2047) // 2048) * 2048       # 8 MiB alignment
lx_end     = last_usable

print(f"  userdata  was  {ud_start:>9} .. {ud_end:>9}   {(ud_end-ud_start+1)*BS/2**30:7.2f} GiB")
print(f"  userdata  now  {ud_start:>9} .. {new_ud_end:>9}   {(new_ud_end-ud_start+1)*BS/2**30:7.2f} GiB")
print(f"  linux     new  {lx_start:>9} .. {lx_end:>9}   {(lx_end-lx_start+1)*BS/2**30:7.2f} GiB")
print(f"  free entry slot: #{free+1} of {nent}")
assert lx_start < lx_end <= last_usable and new_ud_end < lx_start

# shrink userdata
struct.pack_into("<Q", ents, ud*entsz + 40, new_ud_end)
# build the linux entry: copy userdata's shape, then override
e = bytearray(entsz)
e[0:16]  = LINUX_TYPE.bytes_le
e[16:32] = uuid.uuid4().bytes_le
struct.pack_into("<QQQ", e, 32, lx_start, lx_end, 0)
e[56:128] = "linux".encode("utf-16-le").ljust(72, b"\0")
ents[free*entsz:(free+1)*entsz] = e

def build(header_src, is_backup):
    h = bytearray(header_src)
    my  = (len(prim)//BS if False else None)
    if is_backup:
        my_lba, alt_lba, p_lba = last_usable+5, 1, last_usable+1
    else:
        my_lba, alt_lba, p_lba = 1, last_usable+5, 2
    struct.pack_into("<QQ", h, 24, my_lba, alt_lba)
    struct.pack_into("<Q", h, 72, p_lba)
    struct.pack_into("<I", h, 88, binascii.crc32(bytes(ents)) & 0xffffffff)
    struct.pack_into("<I", h, 16, 0)
    hsz = struct.unpack_from("<I", h, 12)[0]
    struct.pack_into("<I", h, 16, binascii.crc32(bytes(h[:hsz])) & 0xffffffff)
    return h

# primary image: LBA0 mbr, LBA1 header, LBA2.. entries
np = bytearray(prim)
np[BS:BS*2] = build(hdr, False)
np[2*BS:2*BS+len(ents)] = ents
open(OUT_P, "wb").write(np)

# backup image: entries first, then header last
nb = bytearray(open(SRC_B, "rb").read())
nb[0:len(ents)] = ents
nb[len(nb)-BS:] = build(hdr, True)
open(OUT_B, "wb").write(nb)
print(f"\n  wrote {OUT_P} ({len(np)} B) and {OUT_B} ({len(nb)} B)")
