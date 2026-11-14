#!/usr/bin/env bash
# Compile dts-work/sm8350-samsung-q2q.dts in a kernel tree and sanity-check the DTB.
#   ./tools/build-dtb.sh [kernel-tree]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:-$ROOT/linux-fedora}"
SRC="$ROOT/dts-work/sm8350-samsung-q2q.dts"
D=arch/arm64/boot/dts/qcom
[ -d "$TREE/$D" ] || { echo "!! no kernel tree at $TREE"; exit 1; }

export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
cp "$SRC" "$TREE/$D/"
grep -q 'sm8350-samsung-q2q.dtb' "$TREE/$D/Makefile" || \
  sed -i 's|^dtb-$(CONFIG_ARCH_QCOM)\t+= sm8350-mtp.dtb|dtb-$(CONFIG_ARCH_QCOM)\t+= sm8350-samsung-q2q.dtb\ndtb-$(CONFIG_ARCH_QCOM)\t+= sm8350-mtp.dtb|' "$TREE/$D/Makefile"
grep -n 'samsung-q2q' "$TREE/$D/Makefile" | sed 's/^/  Makefile: /'

cd "$TREE"
[ -f .config ] || make -s defconfig >/dev/null
echo
echo "building qcom/sm8350-samsung-q2q.dtb ..."
OUT="$D/sm8350-samsung-q2q.dtb"
# Delete the old artifact first. This script used to report "DTB OK" off a
# stale .dtb from a previous run while dtc was printing "FATAL ERROR: Unable
# to parse input tree" right above it, because existence was the only check.
rm -f "$OUT"
make -j"$(nproc)" "qcom/sm8350-samsung-q2q.dtb" 2>&1 | grep -vE '^\s*(CC|AR|GEN|UPD|HOSTCC|CALL|DESCEND|MKDIR|LDS|AS|LD|OBJCOPY|VDSOSYM|MKELF|HOSTLD)' | head -30
rc=${PIPESTATUS[0]}
echo
if [ "$rc" -ne 0 ]; then echo "BUILD FAILED (make exit $rc)"; exit 1; fi
if [ ! -f "$OUT" ]; then echo "BUILD FAILED (no $OUT)"; exit 1; fi
echo "=============================================="
echo " DTB OK: $OUT  ($(stat -c%s "$OUT") bytes)"
echo "=============================================="
