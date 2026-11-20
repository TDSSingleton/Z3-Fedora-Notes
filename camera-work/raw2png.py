#!/usr/bin/env python3
"""
Turn a camss RDI raw frame from the Fold 3's ultrawide into a viewable PNG.

    ./raw2png.py shot1.raw out.png [WxH] [decimate]

The frame is V4L2_PIX_FMT_SRGGB10P ('pRAA'): MIPI CSI-2 10-bit packing, so
every 5 bytes hold 4 pixels -- four bytes of high bits, then one byte carrying
the four 2-bit low parts. Lines are padded to the driver's bytesperline, which
for 4208 px is 5264 and not 5260, so the stride has to be honoured per line or
the image shears progressively.

There is no ISP in this path (mainline camss is a CSI receiver, not an image
pipeline), so this does the minimum by hand: unpack, 2x2 RGGB debayer,
grey-world white balance, percentile normalise, gamma. It is a sanity check
that the sensor is really imaging -- not a photo pipeline.

`decimate` (default 4) takes every Nth 2x2 Bayer cell, so the default output is
a 1052x780 preview. Pass 1 for the full 2104x1560. Pure stdlib on purpose: no
numpy on the build host.
"""
import struct
import sys
import zlib


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    w, h = (int(x) for x in (sys.argv[3] if len(sys.argv) > 3
                             else "4208x3120").split("x"))
    dec = int(sys.argv[4]) if len(sys.argv) > 4 else 4

    # The driver pads bytesperline up to a 16-byte multiple.
    stride = ((w * 5 + 3) // 4 + 15) & ~15
    buf = open(src, "rb").read()
    if len(buf) < stride * h:
        sys.exit(f"!! {src}: {len(buf)} bytes, need {stride * h} "
                 f"for {w}x{h} at stride {stride}")

    def row10(y):
        """Unpack one Bayer line to a list of 10-bit ints."""
        base = y * stride
        out = []
        ap = out.append
        for g in range(0, (w // 4) * 5, 5):
            o = base + g
            b0, b1, b2, b3, lo = buf[o], buf[o + 1], buf[o + 2], buf[o + 3], buf[o + 4]
            ap((b0 << 2) | (lo & 3))
            ap((b1 << 2) | ((lo >> 2) & 3))
            ap((b2 << 2) | ((lo >> 4) & 3))
            ap((b3 << 2) | ((lo >> 6) & 3))
        return out

    ow, oh = (w // 2) // dec, (h // 2) // dec
    px = []                                  # [(r,g,b)] row-major
    lo_v, hi_v, tot, n = 1 << 16, 0, 0, 0
    for oy in range(oh):
        y = oy * dec * 2
        top, bot = row10(y), row10(y + 1)
        rowpx = []
        for ox in range(ow):
            x = ox * dec * 2
            r = top[x]
            g = (top[x + 1] + bot[x]) >> 1
            b = bot[x + 1]
            rowpx.append([r, g, b])
            lo_v = min(lo_v, r, g, b)
            hi_v = max(hi_v, r, g, b)
            tot += r + g + b
            n += 3
        px.append(rowpx)
    print(f"unpacked {w}x{h} -> {ow}x{oh} preview; "
          f"10-bit range {lo_v}..{hi_v}, mean {tot / max(n, 1):.1f}")

    # grey-world white balance
    sums = [0, 0, 0]
    for row in px:
        for p in row:
            for c in range(3):
                sums[c] += p[c]
    grand = sum(sums) / 3.0
    gain = [grand / s if s else 1.0 for s in sums]

    # normalise on a high percentile so a few hot pixels don't crush the rest
    flat = sorted(p[c] * gain[c] for row in px for p in row for c in range(3))
    hi = flat[int(len(flat) * 0.995)] or 1.0

    inv = 1.0 / 2.2
    rows = []
    for row in px:
        out = bytearray()
        for p in row:
            for c in range(3):
                v = p[c] * gain[c] / hi
                v = 0.0 if v < 0 else (1.0 if v > 1 else v)
                out.append(int((v ** inv) * 255))
        rows.append(bytes(out))

    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    with open(dst, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", ow, oh, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))
    print(f"wrote {dst}  ({ow}x{oh})")


if __name__ == "__main__":
    main()
