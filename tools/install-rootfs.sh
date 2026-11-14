#!/usr/bin/env bash
# Write the prepared Fedora rootfs onto the phone's `linux` partition.
#
#   ./tools/install-rootfs.sh            # verify, ask, write, verify again
#   FORCE=1 ./tools/install-rootfs.sh    # skip the prompt
#
# Run it with the phone in TWRP. TWRP's adbd gives us a root shell with the
# whole of /dev/block/sda visible, and `adb exec-in` is a clean binary pipe
# into it -- measured at ~37 MiB/s, so 9.28 GiB lands in about four minutes.
# That is the fastest channel we have by a wide margin: the same bytes over the
# USB serial console would take over an hour.
#
# THE DANGER, stated plainly: this is a raw write to a block device on a phone
# whose xbl/abl/tz partitions cannot be restored if they are damaged. There is
# no public Firehose programmer for Samsung's SM8350, so a wrong partition
# index here is an unrecoverable brick, not an inconvenience.
#
# So the target is not trusted from its name alone. Before writing we re-read
# the live GPT off the device and require the 37th entry to be exactly the
# partition we carved: right name, right start LBA, right end LBA. Any drift --
# a restored stock table, a --repartition that swallowed our carve, a different
# phone plugged in -- fails the check and nothing is written.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMG="$ROOT/rootfs-work/fedora-mobile/p3-root.btrfs"

# The carve, as recorded when it was made. 4096-byte LBAs: this disk is 4Kn.
WANT_IDX=37
WANT_NAME="linux"
WANT_START=12402688
WANT_END=62340090
WANT_BYTES=204543602688          # (END - START + 1) * 4096
IMG_BYTES=9965666304             # p3 of the Fedora image

die() { echo "!! $*" >&2; exit 1; }

[ -s "$IMG" ] || die "no prepared image at $IMG -- run ./tools/prep-rootfs.sh first"
got=$(stat -c%s "$IMG")
[ "$got" = "$IMG_BYTES" ] || die "image is $got bytes, expected $IMG_BYTES"

state=$(adb get-state 2>/dev/null)
[ "$state" = "recovery" ] || die "phone is in '$state', need TWRP (recovery)"

echo "re-reading the live GPT off the phone ..."
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
adb exec-out 'dd if=/dev/block/sda bs=4096 count=16 2>/dev/null' > "$TMP/gpt.bin"
[ "$(stat -c%s "$TMP/gpt.bin")" = "65536" ] || die "could not read the GPT"

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

printf "  entry %d: name=%-10s start=%-10s end=%s\n" "$WANT_IDX" "$gname" "$gstart" "$gend"
[ "$gname"  = "$WANT_NAME"  ] || die "entry $WANT_IDX is '$gname', expected '$WANT_NAME' -- REFUSING"
[ "$gstart" = "$WANT_START" ] || die "start is $gstart, expected $WANT_START -- REFUSING"
[ "$gend"   = "$WANT_END"   ] || die "end is $gend, expected $WANT_END -- REFUSING"

devsz=$(adb shell 'cat /sys/block/sda/sda37/size' | tr -d '\r')
[ "$(( devsz * 512 ))" = "$WANT_BYTES" ] || die "sda37 is $(( devsz * 512 )) bytes, expected $WANT_BYTES"
echo "  guards passed: sda37 is our 190.50 GiB carve"

if [ "${FORCE:-0}" != "1" ]; then
	echo
	echo "About to write $(( IMG_BYTES / 1024 / 1024 )) MiB to /dev/block/sda37 ($WANT_NAME)."
	printf "Type YES to proceed: "
	read -r a; [ "$a" = "YES" ] || die "aborted"
fi

# The block size MUST divide the image exactly. toybox dd on the device loses
# a final partial block: flashing boot.img with bs=1M silently left its last
# 233472 bytes stale. This image is 9504 MiB, an exact multiple of 4 MiB, so
# bs=4M is safe here -- but assert it rather than trust it.
# Also never pass iflag=: toybox 0.8.4 rejects it and exits having written
# nothing, and `adb exec-in` discards stderr so the failure is invisible.
BS=4194304
if [ $(( IMG_BYTES % BS )) -ne 0 ]; then BS=4096; fi
[ $(( IMG_BYTES % BS )) -eq 0 ] || die "image size $IMG_BYTES is not a multiple of $BS"

echo "writing (~5 min at ~32 MiB/s, bs=$BS) ..."
t0=$(date +%s)
adb exec-in "dd of=/dev/block/sda37 bs=$BS conv=notrunc 2>/dev/null" < "$IMG" || die "transfer failed"
adb shell 'sync' >/dev/null 2>&1
t1=$(date +%s)
printf "  wrote in %d s (%.1f MiB/s)\n" "$((t1-t0))" \
       "$(echo "scale=1; $IMG_BYTES/1048576/($t1-$t0)" | bc)"

echo "verifying -- hashing the first $IMG_BYTES bytes back off the phone ..."
L=$(sha256sum "$IMG" | cut -d' ' -f1)
R=$(adb shell "dd if=/dev/block/sda37 bs=$BS count=$(( IMG_BYTES / BS )) 2>/dev/null | sha256sum" | tr -d '\r' | cut -d' ' -f1)
echo "  local : $L"
echo "  device: $R"
[ "$L" = "$R" ] || die "MISMATCH -- the rootfs on the phone is not what we built"
echo
echo "=== rootfs installed and verified on sda37 ==="
echo "next: ./tools/build-busybox.sh --rootfs && ./tools/assemble-boot.sh && ./tools/flash-boot-adb.sh"
