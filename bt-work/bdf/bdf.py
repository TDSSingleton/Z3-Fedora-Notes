import struct, sys
def load(p):
    d = bytearray(open(p,'rb').read())
    phoff, = struct.unpack_from('<I', d, 28); off, va, pa, fsz = struct.unpack_from('<IIII', d, phoff+4)
    return d, off, fsz
def xor16(b):
    x = 0
    for i in range(0, len(b) & ~1, 2): x ^= b[i] | (b[i+1] << 8)
    return x
if __name__ == '__main__':
    for p in sys.argv[1:]:
        d, off, n = load(p); b = d[off:off+n]
        print(p, 'len', n, 'xor16 all = %04x' % xor16(b), 'hdr len field = %04x' % struct.unpack_from('<H', b, 8)[0], 'csum field = %04x' % struct.unpack_from('<H', b, 10)[0], 'xor16 over hdrlen = %04x' % xor16(b[:struct.unpack_from('<H', b, 8)[0]]))
