#!/usr/bin/env python3
"""Turn Fedora's EFI zboot vmlinuz into the plain arm64 Image that
kexec_file_load needs.

    ./tools/unzboot.py /usr/lib/modules/<rel>/vmlinuz -o Image

Fedora ships aarch64 kernels as `Linux kernel ARM64 EFI executable zstd
compressed zboot Image`: a PE/COFF wrapper whose payload is the compressed
Image plus a decompressor stub. arm64 `kexec_file_load` only accepts a bare
Image (ARMd magic at 0x38), so the chainloader cannot take vmlinuz as it is.

Layout, from drivers/firmware/efi/libstub/zboot-header.S:

    0x00  u32    IMAGE_DOS_SIGNATURE ("MZ\0\0")
    0x04  char[4] "zimg"
    0x08  u32    payload offset, from the start of the file
    0x0c  u32    payload size
    0x10  u32[2] reserved
    0x18  asciz  compression type ("zstd", "gzip", ...)
    0x38  u32    LINUX_PE_MAGIC

Note the "zimg" tag sits at 0x04, NOT 0x08: the struct in
include/linux/efi.h starts with msdos_magic + reserved0, but the assembly
that actually emits the header uses a single .long for the DOS signature.
Trust zboot-header.S. Decompression is delegated to the matching CLI tool,
so this needs no third-party Python modules on either host or phone.
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile

# compression type in the header -> (argv to decompress stdin->stdout)
DECOMP = {
    "gzip": ["gzip", "-dc"],
    "lzma": ["xz", "-dc", "--format=lzma"],
    "xzkern": ["xz", "-dc", "--single-stream"],
    "lzo": ["lzop", "-dc"],
    "lz4": ["lz4", "-dc"],
    "zstd22": ["zstd", "-dc"],
    "zstd": ["zstd", "-dc"],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vmlinuz")
    ap.add_argument("-o", "--output", help="default: ./Image")
    ap.add_argument("-n", "--dry-run", action="store_true",
                    help="print what the header says and stop")
    args = ap.parse_args()

    with open(args.vmlinuz, "rb") as f:
        head = f.read(0x40)
        if len(head) < 0x40:
            sys.exit(f"!! {args.vmlinuz}: too short to be a zboot image")
        if head[0:2] != b"MZ":
            sys.exit(f"!! {args.vmlinuz}: no MZ signature -- not a PE image. "
                     "A plain Image needs no extraction; check for 'ARMd' at 0x38.")
        if head[4:8] != b"zimg":
            # A bare arm64 Image also opens with "MZ" (it carries an EFI stub
            # header), so the zimg tag is the real discriminator.
            if head[0x38:0x3c] == b"ARMd":
                sys.exit(f"!! {args.vmlinuz} is already a plain arm64 Image "
                         "-- copy it, do not extract it")
            sys.exit(f"!! {args.vmlinuz}: PE image but not zboot "
                     f"(got {head[4:8]!r} at 0x04, want b'zimg')")
        poff, psize = struct.unpack_from("<II", head, 8)
        comp = head[0x18:0x38].split(b"\0")[0].decode("ascii", "replace")

        size = os.fstat(f.fileno()).st_size
        if poff + psize > size:
            sys.exit(f"!! payload runs past EOF: offset {poff} + size {psize} > {size}")
        argv = DECOMP.get(comp)
        print(f"zboot: {comp} payload at {poff}, {psize} bytes, of {size} total")
        if args.dry_run:
            return
        if argv is None:
            sys.exit(f"!! unknown compression type {comp!r}; known: "
                     + " ".join(sorted(DECOMP)))

        f.seek(poff)
        payload = f.read(psize)

    out = args.output or "Image"
    # Decompress to a temporary file in the destination directory and rename
    # only on success: a half-written Image inside /boot/fold3/entries/<e>/
    # would be a kernel the chainloader tries to boot.
    dest = os.path.dirname(os.path.abspath(out))
    try:
        proc = subprocess.run(argv, input=payload, stdout=subprocess.PIPE)
    except FileNotFoundError:
        sys.exit(f"!! {argv[0]} not found; needed to decompress a {comp} payload")
    if proc.returncode != 0:
        sys.exit(f"!! {' '.join(argv)} failed with {proc.returncode}")
    image = proc.stdout
    if image[0x38:0x3c] != b"ARMd":
        sys.exit(f"!! decompressed {len(image)} bytes but no 'ARMd' magic at 0x38 "
                 f"(got {image[0x38:0x3c]!r}) -- this is not an arm64 Image")

    fd, tmp = tempfile.mkstemp(prefix=".unzboot-", dir=dest)
    try:
        with os.fdopen(fd, "wb") as g:
            g.write(image)
        os.replace(tmp, out)
    except BaseException:
        os.unlink(tmp)
        raise
    print(f"wrote {out}: {len(image)} bytes, arm64 Image")


if __name__ == "__main__":
    main()
