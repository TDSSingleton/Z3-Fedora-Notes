#!/usr/bin/env bash
# Build the Stage-1 arm64 kernel for q2q.
#   ./tools/build-kernel.sh [kernel-tree]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:-$ROOT/linux-fedora}"
FRAG="$ROOT/kernel-work/q2q-stage1.config"
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
# Setting LOCALVERSION at all (even empty) stops scripts/setlocalversion
# appending "-dirty". Our tree is permanently dirty because build-kernel.sh
# itself copies the board DTS in, so without this the kernel release -- and
# therefore the /lib/modules path in the rootfs -- carries a "-dirty" tail.
export LOCALVERSION=

# Install the board DTS before building. build-dtb.sh also does this, and when
# only ONE of the two installs it the tree silently keeps a stale copy -- which
# is exactly how a ramoops fix got "applied" to dts-work/ and never reached the
# DTB. Both entry points must install.
DTS="$ROOT/dts-work/sm8350-samsung-q2q.dts"
D=arch/arm64/boot/dts/qcom
if [ -f "$DTS" ]; then
	cp "$DTS" "$TREE/$D/"
	grep -q 'sm8350-samsung-q2q.dtb' "$TREE/$D/Makefile" || \
	  sed -i 's|^dtb-$(CONFIG_ARCH_QCOM)\t+= sm8350-mtp.dtb|dtb-$(CONFIG_ARCH_QCOM)\t+= sm8350-samsung-q2q.dtb\ndtb-$(CONFIG_ARCH_QCOM)\t+= sm8350-mtp.dtb|' "$TREE/$D/Makefile"
	echo "installed $(basename "$DTS") into the tree"
fi

cd "$TREE"

echo "tree: $TREE  ($(grep -m1 VERSION Makefile | tr -d ' ').$(grep -m1 PATCHLEVEL Makefile | sed 's/.*= //').$(grep -m1 SUBLEVEL Makefile | sed 's/.*= //'))"
make -s defconfig >/dev/null || exit 1
# apply the fragment
./scripts/kconfig/merge_config.sh -m -O . .config "$FRAG" >/dev/null 2>&1 || {
  echo "merge_config failed, falling back to scripts/config"; 
  while read -r l; do
    case "$l" in
      CONFIG_*=y) ./scripts/config --enable "${l%%=*}" ;;
      CONFIG_*=m) ./scripts/config --module "${l%%=*}" ;;
      \#*is\ not\ set) sym=$(echo "$l" | sed 's/^# \(CONFIG_[A-Z0-9_]*\).*/\1/'); ./scripts/config --disable "$sym" ;;
      CONFIG_CMDLINE=*) ./scripts/config --set-str CONFIG_CMDLINE "$(echo "$l" | sed 's/^CONFIG_CMDLINE="\(.*\)"$/\1/')" ;;
    esac
  done < "$FRAG"
}
make -s olddefconfig >/dev/null || exit 1

echo "key options as configured:"
for s in DRM_SIMPLEDRM FRAMEBUFFER_CONSOLE PSTORE_RAM USB_DWC3_QCOM USB_CONFIGFS_NCM \
         SM_GCC_8350 PINCTRL_SM8350 REGULATOR_QCOM_RPMH CMDLINE_FORCE DRM_MSM DRM_MSM_KMS; do
  printf "  %-24s %s\n" "$s" "$(./scripts/config --state "$s")"
done
echo "  CMDLINE                  $(./scripts/config --state CMDLINE)"
echo
echo "building Image + dtbs with -j$(nproc) ..."
# Remove the outputs first and check make's own status: piping make through
# grep discards its exit code, and `[ -f Image ]` then happily reports a
# STALE image from the previous build as a success. A dtc syntax error once
# printed "DTB OK" that way.
rm -f arch/arm64/boot/Image arch/arm64/boot/dts/qcom/sm8350-samsung-q2q.dtb
set -o pipefail
make -j"$(nproc)" Image qcom/sm8350-samsung-q2q.dtb 2>&1 | grep -iE 'error|warning: ' | head -20
st=${PIPESTATUS[0]}
set +o pipefail
echo
if [ "$st" != 0 ]; then
  echo " KERNEL BUILD FAILED (make exited $st)"; exit 1
fi
if [ -f arch/arm64/boot/Image ] && [ -f arch/arm64/boot/dts/qcom/sm8350-samsung-q2q.dtb ]; then
  echo "=============================================="
  printf " Image OK  %s bytes (%.1f MiB)\n" "$(stat -c%s arch/arm64/boot/Image)" \
         "$(echo "scale=1;$(stat -c%s arch/arm64/boot/Image)/1048576"|bc)"
  printf " DTB   OK  %s bytes\n" "$(stat -c%s arch/arm64/boot/dts/qcom/sm8350-samsung-q2q.dtb)"
  echo "=============================================="
else
  echo " KERNEL BUILD FAILED"; exit 1
fi
