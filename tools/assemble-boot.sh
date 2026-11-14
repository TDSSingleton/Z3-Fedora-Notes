#!/usr/bin/env bash
# Assemble the Stage-1 experiment image:
#   mainline Image + q2q DTB + initramfs  ->  uniLoader  ->  Android boot image
#
# Targets the BOOT slot with header v3, mirroring stock boot. Rationale:
#   - v3 has NO recovery_dtbo and NO dtb field, so the two things that got our
#     first (recovery-slot, v2) attempt rejected cannot structurally recur.
#   - v3 also has no load-address fields; the bootloader fixes them.
#   - every Samsung mainline port (S22, Tab S8+, M52) flashes `boot`.
#   - TWRP now lives in `recovery`, so a bad `boot` is recoverable with
#     Vol-Up+Power -> adb -> dd. No Download Mode needed.
#
#   ./tools/assemble-boot.sh [kernel-tree]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:-$ROOT/linux-fedora}"
UL="$ROOT/uniloader"
OUTDIR="$ROOT/images"; mkdir -p "$OUTDIR"
OUT="$OUTDIR/q2q-stage1-boot.img"

IMAGE="$TREE/arch/arm64/boot/Image"
DTB="$TREE/arch/arm64/boot/dts/qcom/sm8350-samsung-q2q.dtb"
IRFS="$ROOT/initramfs-work/initramfs.cpio.gz"
RAMDISK="$OUTDIR/stock-boot-ramdisk.img"
STOCKBOOT="$ROOT/capture/backup-20261107-005831/tier2-recovery/boot.img"

for f in "$IMAGE" "$DTB" "$IRFS" "$RAMDISK"; do
	[ -s "$f" ] || { echo "!! missing $f"; exit 1; }
done

echo "inputs:"
printf "  %-30s %10s bytes\n" "Image"              "$(stat -c%s "$IMAGE")"
printf "  %-30s %10s bytes\n" "q2q.dtb"            "$(stat -c%s "$DTB")"
printf "  %-30s %10s bytes\n" "initramfs (ours)"   "$(stat -c%s "$IRFS")"
printf "  %-30s %10s bytes  (header ballast)\n" "stock boot ramdisk" "$(stat -c%s "$RAMDISK")"

# --- 1. embed the real payloads and build uniLoader ---
cp "$IMAGE" "$UL/blob/Image"
cp "$DTB"   "$UL/blob/dtb"
cp "$IRFS"  "$UL/blob/ramdisk"
echo
echo "building uniLoader ..."
( cd "$UL" && make ARCH=aarch64 CROSS_COMPILE=aarch64-linux-gnu- q2q_defconfig >/dev/null 2>&1 \
            && make ARCH=aarch64 CROSS_COMPILE=aarch64-linux-gnu- -j"$(nproc)" >/dev/null 2>&1 ) \
	|| { echo "!! uniLoader build failed"; exit 1; }
[ -s "$UL/uniLoader" ] || { echo "!! no uniLoader output"; exit 1; }
printf "  uniLoader: %s bytes (%.1f MiB)\n" "$(stat -c%s "$UL/uniLoader")" \
	"$(echo "scale=1;$(stat -c%s "$UL/uniLoader")/1048576"|bc)"
magic=$(python3 -c "print(open('$UL/uniLoader','rb').read()[56:60].hex())")
[ "$magic" = "41524d64" ] || { echo "!! arm64 magic wrong ($magic) -- ABL will reject"; exit 1; }
echo "  arm64 Image magic: OK"

# --- 2. mirror the stock boot header ---
echo
echo "stock boot header (mirroring):"
read -r HV OSV OSP CMD <<<"$("$ROOT/tools/bootimg-hdr.py" "$STOCKBOOT")"
CMD="${CMD//$'\x01'/ }"
printf "  header_version %s   os_version %s   os_patch %s\n" "$HV" "$OSV" "$OSP"
printf "  cmdline (%s chars, passed through for fidelity)\n" "${#CMD}"

# --- 3. pack. v3: no dtb field, no load addresses, ramdisk REQUIRED in practice ---
echo
echo "packing boot image (header v$HV) ..."
mkbootimg --header_version "$HV" \
          --os_version "$OSV" --os_patch_level "$OSP" \
          --kernel "$UL/uniLoader" \
          --ramdisk "$RAMDISK" \
          --cmdline "$CMD" \
          -o "$OUT" || { echo "!! mkbootimg failed"; exit 1; }

SZ=$(stat -c%s "$OUT"); PART=100663296
[ "$SZ" -le "$PART" ] || { echo "!! image $SZ > boot partition $PART"; exit 1; }
echo
echo "=============================================="
printf " OK  %s\n     %s bytes (%.1f MiB of 96.0 MiB, %.0f%% used)\n" \
  "$OUT" "$SZ" "$(echo "scale=1;$SZ/1048576"|bc)" "$(echo "scale=0;$SZ*100/$PART"|bc)"
printf "     sha256 %s\n" "$(sha256sum "$OUT" | cut -c1-40)..."
echo "=============================================="
