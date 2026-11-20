#!/usr/bin/env python3
"""
Turn a libcamera ABGR8888 frame (software-ISP output) into a PNG.

    ./abgr2png.py still.bin out.png [WxH] [decimate] [stride_bytes]

libcamera's software ISP hands back packed 32-bit pixels. The name is the
DRM/libcamera one, so the byte order in memory is B,G,R,A -- not A,B,G,R.

`decimate` (default 4) takes every Nth pixel; the default output for a
4200x3120 frame is 1050x780. Pure stdlib: there is no numpy on the build host.

`stride_bytes` is the OUTPUT buffer's bytes-per-line. It is NOT always w*4:
libcamera pads the software-ISP output, and a 4200-wide ABGR frame comes back
with a 16896-byte stride (4224 px, w rounded up to 64). Decoding such a buffer
as though it were tightly packed shears the picture diagonally -- which is
exactly what the 2026-11-15 "libcamera stride shear" sample was. Omit it and
the stride is derived from the file size when that divides cleanly, else w*4.
"""
import struct
import sys
import zlib


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    w, h = (int(x) for x in (sys.argv[3] if len(sys.argv) > 3
                             else "4200x3120").split("x"))
    dec = int(sys.argv[4]) if len(sys.argv) > 4 else 4

    buf = open(src, "rb").read()

    if len(sys.argv) > 5:
        stride = int(sys.argv[5])
    elif len(buf) % h == 0 and len(buf) // h >= w * 4:
        stride = len(buf) // h
    else:
        stride = w * 4
    if stride != w * 4:
        print(f"stride {stride} B = {stride // 4} px (packed would be "
              f"{w * 4}); decoding with the padded stride")

    need = stride * h
    if len(buf) < need:
        sys.exit(f"!! {src}: {len(buf)} bytes, need {need} for {w}x{h} ABGR "
                 f"at stride {stride}")

    ow, oh = w // dec, h // dec
    rows = []
    tot = 0
    for oy in range(oh):
        base = (oy * dec) * stride
        out = bytearray()
        for ox in range(ow):
            o = base + (ox * dec) * 4
            b, g, r = buf[o], buf[o + 1], buf[o + 2]
            out += bytes((r, g, b))
            tot += r + g + b
        rows.append(bytes(out))
    print(f"{w}x{h} ABGR -> {ow}x{oh} PNG, mean level {tot / (ow * oh * 3):.1f}")

    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    with open(dst, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", ow, oh, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
