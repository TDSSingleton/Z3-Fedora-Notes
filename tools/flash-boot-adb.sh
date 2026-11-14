#!/usr/bin/env bash
# Flash a boot image to the phone's `boot` partition from TWRP, over adb.
#
#   ./tools/flash-boot-adb.sh [path-to-boot.img] [--reboot]
#
# This replaces the serial self-flash (tools/selfflash.py) whenever the phone
# is already in TWRP: it is a direct binary pipe at ~37 MiB/s instead of
# base64 over a 2.3 MiB/s console, and it does not depend on our own kernel
# having booted far enough to flash itself.
#
# Guards, for the same reason as install-rootfs.sh: a raw write to the wrong
# index on this device is an unrecoverable brick. The live GPT is re-read and
# entry 19 must be exactly `boot`, at the start and end LBA we recorded. The
# image must also fit, because dd would otherwise spill into `recovery` --
# which is TWRP, our only way back in.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMG="${1:-$ROOT/images/q2q-stage1-boot.img}"
[ "${1:-}" = "--reboot" ] && IMG="$ROOT/images/q2q-stage1-boot.img"

WANT_IDX=19
WANT_NAME="boot"
WANT_START=99824
WANT_END=124399
BS=4096
MAX_BYTES=$(( (WANT_END - WANT_START + 1) * BS ))

die() { echo "!! $*" >&2; exit 1; }

[ -s "$IMG" ] || die "no boot image at $IMG"
sz=$(stat -c%s "$IMG")
[ "$sz" -le "$MAX_BYTES" ] || die "image is $sz bytes, partition holds $MAX_BYTES -- REFUSING"

state=$(adb get-state 2>/dev/null)
[ "$state" = "recovery" ] || die "phone is in '$state', need TWRP (recovery)"

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
adb exec-out 'dd if=/dev/block/sda bs=4096 count=16 2>/dev/null' > "$TMP/gpt.bin"
read -r gname gstart gend < <(python3 -I - "$TMP/gpt.bin" "$WANT_IDX" <<'PY'
import struct, sys
d = open(sys.argv[1], 'rb').read(); idx = int(sys.argv[2]); BS = 4096
assert d[BS:BS+8] == b'EFI PART', 'no EFI PART signature'
ents_lba, n, esz = struct.unpack_from('<QII', d, BS+72)
off = ents_lba*BS + (idx-1)*esz
start, end = struct.unpack_from('<QQ', d, off+32)
name = d[off+56:off+128].decode('utf-16-le').split('\x00')[0]
print(name, start, end)
PY
) || die "could not parse the GPT"

printf "  entry %d: name=%-10s start=%-8s end=%s\n" "$WANT_IDX" "$gname" "$gstart" "$gend"
[ "$gname"  = "$WANT_NAME"  ] || die "entry $WANT_IDX is '$gname', not '$WANT_NAME' -- REFUSING"
[ "$gstart" = "$WANT_START" ] || die "start is $gstart, expected $WANT_START -- REFUSING"
[ "$gend"   = "$WANT_END"   ] || die "end is $gend, expected $WANT_END -- REFUSING"

# bs=4096, and nothing else, for two reasons that each cost a wasted flash:
#
#  1. bs=1M LOSES THE FINAL PARTIAL BLOCK. The boot image is 46370816 bytes =
#     44.22 MiB, and a bs=1M write landed exactly 44 MiB -- 44 whole blocks --
#     leaving the last 233472 bytes as whatever was there before. Verification
#     caught it, but a 46%-correct kernel image is exactly the kind of thing
#     that would otherwise look like a mysterious boot failure. 4096 divides
#     this image exactly, and is also the disk's logical block size (4Kn).
#
#  2. NO iflag=. The device's dd is toybox 0.8.4, which rejects
#     `iflag=fullblock` with "bad iflag=fullblock" and exits 1 having written
#     nothing. `adb exec-in` is one-way and DISCARDS the command's stderr, so
#     that failure is completely silent -- two "flashes" in a row changed
#     nothing at all and only the hash check revealed it.
[ $(( sz % 4096 )) -eq 0 ] || die "image is $sz bytes, not a multiple of 4096 -- pad it first"
BLKS=$(( sz / 4096 ))

printf "flashing %s (%s bytes, %s blocks) to sda%d (%s) ...\n" "$(basename "$IMG")" "$sz" "$BLKS" "$WANT_IDX" "$WANT_NAME"
adb exec-in "dd of=/dev/block/sda$WANT_IDX bs=4096 conv=notrunc 2>/dev/null" < "$IMG" || die "transfer failed"
adb shell 'sync' >/dev/null 2>&1

L=$(sha256sum "$IMG" | cut -d' ' -f1)
R=$(adb shell "dd if=/dev/block/sda$WANT_IDX bs=4096 count=$BLKS 2>/dev/null | sha256sum" | tr -d '\r' | cut -d' ' -f1)
[ "$L" = "$R" ] || die "MISMATCH after write"
echo "  verified: $L"

if [ "${2:-}" = "--reboot" ] || [ "${1:-}" = "--reboot" ]; then
	echo "rebooting into it ..."
	adb reboot
fi
