#!/usr/bin/env bash
# Write an experimental boot image to the RECOVERY slot and reboot into it.
#
# Why recovery and not boot: `boot` keeps the working rooted Android, so you
# always have adb to write the next attempt. A failed experiment costs a power
# cycle, not a Download Mode rescue session.
#
#   ./tools/flash-experiment.sh images/boot-q2q.img          # write + reboot to recovery
#   ./tools/flash-experiment.sh images/boot-q2q.img --no-go   # write only
#   ./tools/flash-experiment.sh --restore                     # put stock recovery back
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Which slot to experiment in. Default is now `boot`:
#   - header v3, so no recovery_dtbo/dtb fields to get wrong
#   - every Samsung mainline port flashes boot
#   - TWRP lives in `recovery`, so a bad boot is recoverable with
#     Vol-Up+Power -> TWRP -> adb -> dd. No Download Mode needed.
# Override with SLOT=recovery ./tools/flash-experiment.sh ...
SLOT="${SLOT:-boot}"
STOCK="$ROOT/rescue/boot-stock-magisk.img"
[ "$SLOT" = recovery ] && STOCK="$ROOT/rescue/recovery-stock.img"

die(){ printf '\n!! %s\n' "$*" >&2; exit 1; }

# Works from Android (needs su) OR from TWRP (adb shell is already uid 0).
# TWRP is arguably the better place to do this: root with no su, and no Android
# adb-server flakiness. Writing `boot` is valid either way -- it is not in use.
if [ "$(timeout 10 adb shell 'id -u' 2>/dev/null | tr -d '\r')" = "0" ]; then
	SU=""
elif [ "$(timeout 10 adb shell 'su -c id -u' 2>/dev/null | tr -d '\r')" = "0" ]; then
	SU="su -c "
else
	die "need root: a rooted Android, or TWRP"
fi

node="$(timeout 15 adb shell "${SU}readlink -f /dev/block/by-name/$SLOT" | tr -d '\r')"
[ -n "$node" ] || die "could not resolve /dev/block/by-name/$SLOT"
psize="$(timeout 15 adb shell "${SU}blockdev --getsize64 $node" | tr -d '\r')"

if [ "${1:-}" = "--restore" ]; then
	IMG="$STOCK"; echo "restoring STOCK recovery from $IMG"
else
	IMG="${1:-}"; [ -f "$IMG" ] || die "usage: $0 <image> [--no-go] | --restore"
fi

sz=$(stat -c%s "$IMG")
[ "$sz" -le "$psize" ] || die "image is $sz bytes but $SLOT is only $psize"
want="$(sha256sum "$IMG" | awk '{print $1}')"
printf 'image   %s\n        %s bytes (%.1f MiB of %.0f MiB slot)\n        sha256 %s\n' \
	"$(basename "$IMG")" "$sz" "$(echo "scale=1;$sz/1048576"|bc)" "$(echo "$psize/1048576"|bc)" "${want:0:32}..."
echo "target  $SLOT -> $node"

t0=$(date +%s.%N)
# TWRP has no /data mounted; /tmp always exists in both environments
TMP=/tmp/exp.img
[ -n "$SU" ] && TMP=/data/local/tmp/exp.img
adb push "$IMG" "$TMP" >/dev/null
dev="$(timeout 120 adb shell "${SU}sha256sum $TMP" | tr -d '\r' | awk '{print $1}')"
[ "$dev" = "$want" ] || die "transfer corrupted (device sees $dev)"
timeout 240 adb shell "${SU}dd if=$TMP of=$node bs=4096 && ${SU}sync" >/dev/null 2>&1
# Read back BLOCKS then truncate to the image's real byte count. Partitions are
# block-granular but images usually are not, so hashing the rounded-up read
# includes trailing partition bytes and always mismatches. (Learned the hard
# way: the first Stage-1 image was exactly block-aligned, which hid this.)
blocks=$(( (sz + 4095) / 4096 ))
back="$(timeout 240 adb exec-out "${SU}dd if=$node bs=4096 count=$blocks 2>/dev/null" 2>/dev/null | head -c "$sz" | sha256sum | awk '{print $1}')"
[ "$back" = "$want" ] || die "read-back MISMATCH ($back) -- NOT rebooting"
timeout 20 adb shell "${SU}rm -f $TMP" >/dev/null 2>&1
t1=$(date +%s.%N)
printf 'written and read-back verified in %.1fs\n' "$(echo "$t1-$t0"|bc)"

[ "${2:-}" = "--no-go" ] && { echo "not rebooting (--no-go)."; exit 0; }
[ "${1:-}" = "--restore" ] && { echo "stock recovery restored. not rebooting."; exit 0; }

cat <<'EOF'

rebooting. What to watch for on the INNER screen:
  text appearing          -> uniLoader ran; load addresses are right
  unverified-firmware
    prompt then nothing   -> ABL accepted it, uniLoader stalled (TEXT_BASE/PAYLOAD_ENTRY)
  straight back to Android-> ABL rejected the image (header / mkbootimg args)
  black, no backlight     -> power-cycle; `boot` is untouched so Android still works

RECOVERY PATH if it does not boot:
  hold Power ~10s to force off, then Vol-Up + Power -> TWRP -> then from here:
     ./rescue/restore-boot.sh
  TWRP gives root adb with dd, so this needs no Download Mode and no heimdall.
EOF
if [ "$SLOT" = recovery ]; then adb reboot recovery; else adb reboot; fi
