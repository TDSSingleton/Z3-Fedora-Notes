import sys, struct
d = open(sys.argv[1], 'rb').read()
want = set(int(x) for x in sys.argv[2:])
typ = d[0]; ln = int.from_bytes(d[1:4], 'little')
print(f"file {len(d)} bytes, tlv type {typ}, len {ln}")
o = 4
while o + 12 <= len(d):
    tid, tlen, ptr, ex = struct.unpack_from('<HHII', d, o)
    o += 12
    data = d[o:o+tlen]; o += tlen
    if not want or tid in want:
        print(f"tag {tid:4d} len {tlen:4d} ex {ex:#x} @data {o-tlen:#x}: {data.hex(' ')}")
    else:
        print(f"tag {tid:4d} len {tlen:4d}")
