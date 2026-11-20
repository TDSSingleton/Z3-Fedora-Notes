#!/bin/bash
# to-android.sh -- flash the rooted stock Android boot image, FROM mainline Linux.
# The mirror image of /root/fold3-restore/back-to-linux.sh, which comes back.
#
# Verifies the source hash before writing and reads the partition back after,
# and does NOT reboot: that stays an explicit, separate decision.
set -e

IMG=${1:-/root/fold3-restore/boot-stock-magisk.img}
WANT=2e56945e4e13be67db125dd0046dd6dfd55f9cce04e7fce465f022bd8d54cc42
SZ=100663296
T=/dev/sda19   # partlabel: boot, 96 MiB

echo "image : $IMG"
echo "target: $T ($(lsblk -no PARTLABEL $T), $(blockdev --getsize64 $T) bytes)"

[ -f "$IMG" ] || { echo "!! image missing"; exit 1; }
[ "$(stat -c%s "$IMG")" = "$SZ" ] || { echo "!! image size != $SZ"; exit 1; }
[ "$(blockdev --getsize64 $T)" = "$SZ" ] || { echo "!! partition size != image size"; exit 1; }
GOT=$(sha256sum "$IMG" | cut -d' ' -f1)
[ "$GOT" = "$WANT" ] || { echo "!! source hash mismatch ($GOT), aborting"; exit 1; }
echo "source hash verified"

# the return path must exist BEFORE we leave Linux
[ -x /root/fold3-restore/back-to-linux.sh ] || { echo "!! no return script, aborting"; exit 1; }
[ -f /root/fold3-restore/q2q-boot.img ] || { echo "!! no mainline image to return to, aborting"; exit 1; }
echo "return path present: back-to-linux.sh + q2q-boot.img"

dd if="$IMG" of=$T bs=4M conv=fsync status=none
sync
BACK=$(dd if=$T bs=4M count=$((SZ/4194304)) status=none | sha256sum | cut -d' ' -f1)
[ "$BACK" = "$WANT" ] || { echo "!! READBACK MISMATCH ($BACK) -- DO NOT REBOOT"; exit 1; }
echo "*** readback verified -- reboot for rooted Android ***"
echo "    return with:  (in Android, as root)"
echo "      mkdir -p /mnt/fed && mount -o ro /dev/block/sda37 /mnt/fed"
echo "      sh /mnt/fed/root/fold3-restore/back-to-linux.sh"
