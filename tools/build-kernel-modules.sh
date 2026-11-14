#!/usr/bin/env bash
# Build the kernel, then its modules, then stage them for installation into
# the rootfs. Separate from build-kernel.sh because only a real root
# filesystem has somewhere to put /lib/modules.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TREE="$ROOT/linux-fedora"
STAGE="$ROOT/rootfs-work/modules-stage"
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
# Must match build-kernel.sh: `make modules` runs in THIS shell, and an unset
# LOCALVERSION here would build modules whose vermagic says "-dirty" while the
# kernel says otherwise.
export LOCALVERSION=

"$ROOT/tools/build-kernel.sh" || exit 1

cd "$TREE"
REL="$(make -s kernelrelease)"
echo "building modules for $REL ..."
make -j"$(nproc)" modules 2>&1 | grep -iE '^.*error' | head -20
rm -rf "$STAGE"; mkdir -p "$STAGE"
make -s INSTALL_MOD_PATH="$STAGE" INSTALL_MOD_STRIP=1 modules_install || exit 1
echo "staged: $(find "$STAGE/lib/modules" -name '*.ko*' | wc -l) modules under $STAGE/lib/modules/$REL"
du -sh "$STAGE/lib/modules/$REL" | sed 's/^/  /'
echo "KERNELRELEASE=$REL" > "$STAGE/release.env"

# FRESHNESS GUARD. A staged tree that is merely *complete* is not necessarily
# *current*: on 2026-11-11 a half-finished `make modules` left the previous
# run's stage in place, 1586 modules and a valid modules.dep and all, and
# pushing it bricked the display, touch and PCIe at once with
#   .gnu.linkonce.this_module section size must match ...
# because those modules were built against an older .config. The kernel
# release was identical, so nothing else would have caught it.
IMG="$TREE/arch/arm64/boot/Image"
if [ -f "$IMG" ]; then
	stale=$(find "$STAGE/lib/modules/$REL" -name '*.ko' ! -newer "$IMG" | wc -l)
	if [ "$stale" != 0 ]; then
		echo "!! $stale staged modules are OLDER than $IMG"
		echo "!! the stage is stale -- do NOT push it. Re-run this script."
		exit 1
	fi
	echo "freshness: all staged modules are newer than the Image"
fi
