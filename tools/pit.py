#!/usr/bin/env python3
"""
Parse (and later build) Samsung PIT files.

Why bother: heimdall can `flash --repartition --pit <file>`, which makes the
BOOTLOADER rewrite the GPT from the PIT. That is far safer than hand-editing
the GPT with sgdisk, because the device writes a layout it already agrees with
rather than one we invented behind its back.

Format (from heimdall's PitData):
  header  28 bytes   magic 0x12349876, entry count, then 6 u16 fields
  entry  132 bytes   see FIELDS below

Validate against a real device PIT before trusting the writer:
    heimdall download-pit --pit stock.pit
    python3 -I tools/pit.py stock.pit
"""
import struct, sys

MAGIC = 0x12349876
HDR   = 28
ENT   = 132

def parse(path):
    d = open(path, "rb").read()
    magic, count = struct.unpack_from("<II", d, 0)
    if magic != MAGIC:
        sys.exit(f"!! bad magic 0x{magic:08x} (want 0x{MAGIC:08x}) -- not a PIT?")
    print(f"  magic       0x{magic:08x}")
    print(f"  entries     {count}")
    print(f"  file size   {len(d)} bytes  (header {HDR} + {count} x {ENT} = {HDR+count*ENT})")
    if len(d) < HDR + count*ENT:
        print("  !! file shorter than the entry count implies")
    print()
    print(f"  {'#':>3} {'name':<22} {'blk start':>10} {'blk count':>10} {'size':>12}  {'flash file':<20}")
    print(f"  {'-'*3} {'-'*22} {'-'*10} {'-'*10} {'-'*12}  {'-'*20}")
    rows=[]
    for i in range(count):
        o = HDR + i*ENT
        (bin_t, dev_t, ident, attr, upd,
         blk_off, blk_cnt, f_off, f_size) = struct.unpack_from("<9I", d, o)
        name  = d[o+36:o+68].split(b"\0")[0].decode("ascii","replace")
        fname = d[o+68:o+100].split(b"\0")[0].decode("ascii","replace")
        rows.append((i,name,blk_off,blk_cnt,fname,dev_t,ident,attr))
        print(f"  {i:>3} {name:<22} {blk_off:>10} {blk_cnt:>10} {blk_cnt*4096/2**20:>10.1f}M  {fname:<20}")
    print()
    tot = sum(r[3] for r in rows)
    print(f"  total blocks {tot}  ({tot*4096/2**30:.2f} GiB at 512 B/blk)")
    big = sorted(rows, key=lambda r: -r[3])[:5]
    print("\n  five largest (resize candidates):")
    for i,name,off,cnt,_,_,_,_ in big:
        print(f"    {name:<22} {cnt*4096/2**30:8.2f} GiB   blocks {off}..{off+cnt}")
    return rows

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: pit.py <file.pit>")
    parse(sys.argv[1])
