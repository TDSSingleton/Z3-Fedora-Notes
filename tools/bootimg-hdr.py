#!/usr/bin/env python3
"""
Print an Android boot image's header fields, version-aware.

    bootimg-hdr.py <boot.img>            -> "hv os_version os_patch cmdline"
    bootimg-hdr.py <boot.img> --verbose  -> human readable

header_version lives at offset 40 in every version, but os_version and cmdline
MOVED between v2 and v3:

    v0-v2 : os_version @44, name @48, cmdline @64   (512 bytes)
    v3+   : os_version @16, cmdline @44             (1536 bytes)

Reading a v3 image's os_version at the v0 offset lands in reserved[] and decodes
to a nonsense month -- which is exactly how this bit us the first time.
"""
import struct
import sys

path = sys.argv[1]
verbose = '--verbose' in sys.argv
b = open(path, 'rb').read()

if b[:8] != b'ANDROID!':
    sys.exit(f"{path}: not an Android boot image (magic {b[:8]!r})")

hv = struct.unpack_from('<I', b, 40)[0]

if hv >= 3:
    kernel_size, ramdisk_size, osv, hdr_size = struct.unpack_from('<IIII', b, 8)
    cmd = b[44:44 + 1536].split(b'\0')[0].decode(errors='replace')
    extra = {}
else:
    kernel_size, _ka, ramdisk_size, _ra, _ss, _sa, _ta, _ps = \
        struct.unpack_from('<IIIIIIII', b, 8)
    osv = struct.unpack_from('<I', b, 44)[0]
    cmd = b[64:64 + 512].split(b'\0')[0].decode(errors='replace')
    extra = {}
    if hv >= 1:
        extra['recovery_dtbo_size'] = struct.unpack_from('<I', b, 1632)[0]
    if hv >= 2:
        extra['dtb_size'] = struct.unpack_from('<I', b, 1648)[0]

major = (osv >> 25) & 0x7f
minor = (osv >> 18) & 0x7f
patch = (osv >> 11) & 0x7f
year = ((osv >> 4) & 0x7f) + 2000
month = osv & 0xf

if not 0 < month <= 12:
    sys.exit(f"{path}: decoded month {month} out of range for v{hv} -- "
             f"wrong offset, refusing to guess")

if verbose:
    print(f"  header_version   {hv}")
    print(f"  kernel_size      {kernel_size}")
    print(f"  ramdisk_size     {ramdisk_size}")
    print(f"  os_version       {major}.{minor}.{patch}")
    print(f"  os_patch_level   {year}-{month:02d}")
    for k, v in extra.items():
        print(f"  {k:16} {v}")
    print(f"  cmdline          {cmd[:110]}{'...' if len(cmd) > 110 else ''}")
else:
    # space-separated for shell `read`; spaces in cmdline escaped as \x01
    print(hv, f"{major}.{minor}.{patch}", f"{year}-{month:02d}",
          cmd.replace(' ', '\x01'))
