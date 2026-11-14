import sys, struct, os
d = open(sys.argv[1], 'rb').read()
magic = b'QCA-ATH11K-BOARD\0'
assert d.startswith(magic)
o = (len(magic) + 3) & ~3
out = sys.argv[2] if len(sys.argv) > 2 else None
want = sys.argv[3] if len(sys.argv) > 3 else None
n = 0
while o + 8 <= len(d):
    ie, ln = struct.unpack_from('<II', d, o); o += 8
    body = d[o:o+ln]; o += (ln + 3) & ~3
    p = 0; names = []; data = None
    while p + 8 <= len(body):
        t, l = struct.unpack_from('<II', body, p); p += 8
        v = body[p:p+l]; p += (l + 3) & ~3
        if t == 0: names.append(v.decode())
        elif t == 1: data = v
    n += 1
    for nm in names:
        if want is None:
            print(ie, len(data), data[:4].hex(), nm)
        elif nm == want and out:
            open(out, 'wb').write(data); print('wrote', out, len(data))
