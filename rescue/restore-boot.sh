#!/usr/bin/env bash
# Put the known-good boot image back. Two routes, tried in order.
#
#   ./rescue/restore-boot.sh            # auto: adb if Android is up, else tell you what to do
#   ./rescue/restore-boot.sh heimdall   # force the Download Mode route
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IMG="$HERE/boot-stock-magisk.img"
TAR="$HERE/boot-stock-magisk.tar"
WANT="2e56945e4e13be67db125dd0046dd6dfd55f9cce04e7fce465f022bd8d54cc42"

[ -f "$IMG" ] || { echo "!! missing $IMG"; exit 1; }
got="$(sha256sum "$IMG" | awk '{print $1}')"
[ "$got" = "$WANT" ] || { echo "!! rescue image hash mismatch -- do NOT flash this"; echo "   want $WANT"; echo "   got  $got"; exit 1; }
echo "rescue image verified: ${got:0:16}..."

route="${1:-auto}"

# Works from Android (needs su) OR from TWRP (adb shell is already uid 0).
amroot() {
	[ "$(timeout 10 adb shell 'id -u' 2>/dev/null | tr -d '\r')" = "0" ] && { SU=""; return 0; }
	[ "$(timeout 10 adb shell 'su -c id -u' 2>/dev/null | tr -d '\r')" = "0" ] && { SU="su -c "; return 0; }
	return 1
}
if [ "$route" != heimdall ] && amroot; then
	echo "Android is up with root -- using the adb route."
	node="$(timeout 15 adb shell "${SU}readlink -f /dev/block/by-name/boot" | tr -d '\r')"
	echo "  boot -> $node"
	adb push "$IMG" /data/local/tmp/rescue-boot.img
	dev="$(timeout 60 adb shell "${SU}sha256sum /data/local/tmp/rescue-boot.img" | tr -d '\r' | awk '{print $1}')"
	[ "$dev" = "$WANT" ] || { echo "!! transfer corrupted (device sees $dev) -- aborting"; exit 1; }
	echo "  transfer verified"
	timeout 240 adb shell "${SU}dd if=/data/local/tmp/rescue-boot.img of=$node bs=4096 && ${SU}sync"
	# block-granular read, truncated to the image's real size -- see the note in
	# tools/flash-experiment.sh about why the rounded read always mismatches.
	isz=$(stat -c%s "$IMG"); iblk=$(( (isz + 4095) / 4096 ))
	back="$(timeout 240 adb exec-out "su -c 'dd if=$node bs=4096 count=$iblk 2>/dev/null'" 2>/dev/null | head -c "$isz" | sha256sum | awk '{print $1}')"
	if [ "$back" = "$WANT" ]; then
		echo "  read-back verified. rebooting."
		adb shell 'su -c "rm -f /data/local/tmp/rescue-boot.img"'
		adb reboot
	else
		echo "!! read-back MISMATCH ($back) -- do not reboot; investigate"
		exit 1
	fi
	exit 0
fi

echo
echo "Android is not reachable (or heimdall was requested). Download Mode route:"
echo
echo "  1. Power the device off completely."
echo "  2. Hold Volume-Up + Volume-Down, then plug in USB. You want the blue"
echo "     'Downloading...' screen, NOT the warning screen."
echo "  3. Then:"
echo
if command -v heimdall >/dev/null; then
	echo "     heimdall detect                         # read-only, proves the link works"
	echo "     heimdall print-pit --no-reboot           # read-only, shows the partition table"
	echo "     heimdall flash --BOOT $IMG               # the actual restore"
else
	echo "     sudo dnf install heimdall                # not installed yet"
	echo "     heimdall detect"
	echo "     heimdall print-pit --no-reboot"
	echo "     heimdall flash --BOOT $IMG"
fi
echo
echo "  Or with Samsung's own tool (more reliable on recent devices, XDA-distributed):"
echo "     odin4 -a $TAR"
echo
echo "  Start with 'detect' and 'print-pit'. Both are READ-ONLY. If those work, the"
echo "  rescue path is proven and the flash will work too."
