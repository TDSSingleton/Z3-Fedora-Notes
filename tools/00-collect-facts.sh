#!/usr/bin/env bash
# Tier 4: hardware facts. Closes research questions Q5, Q8, Q9, Q10, Q4-GPIO,
# and produces the uniLoader load addresses.
# Runs unrooted (partial) or rooted (full). Writes nothing to the device.
cd "$(dirname "$0")" && . ./lib-common.sh

OUT="${1:-../capture/facts-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"/{props,sysfs,dt,logs,boot}
require_device; manifest_init
echo "Output: $(cd "$OUT" && pwd)"

hdr "props"
A 'getprop' > "$OUT/props/getprop-all.txt"
for p in ro.product.model ro.product.device ro.board.platform ro.bootloader ro.revision \
         ro.build.version.incremental ro.build.version.release ro.build.version.security_patch \
         ro.boot.verifiedbootstate ro.boot.flash.locked ro.boot.warranty_bit \
         sys.oem_unlock_allowed ro.boot.dtb_idx ro.boot.dtbo_idx ro.oem.key1; do
  printf '%-40s %s\n' "$p" "$(A getprop "$p")"
done | tee "$OUT/props/key-props.txt"

hdr "soc0"
for n in machine soc_id revision hw_platform platform_version raw_id raw_version; do
  printf '%-18s %s\n' "$n" "$(A "cat /sys/devices/soc0/$n")"
done | tee "$OUT/sysfs/soc0.txt"

if ! have_root; then
  cat <<'EOF'

!! No root -- stopping after the unrooted section.
!! Still needed (re-run once rooted):
!!   Q9  which main panel DDIC is fitted  (S6E3XA1 vs S6E3XA2)
!!   Q5  QCA6490 soc_hw_version           (zero code vs small ath11k patch)
!!   Q8  merged post-ABL device tree
!!   Q4  bat_enb GPIO default states
!!       uniLoader TEXT_BASE / PAYLOAD_ENTRY / RAMDISK_ENTRY
EOF
  exit 0
fi

hdr "partitions"
SU 'ls -l /dev/block/by-name/' > "$OUT/sysfs/by-name.txt"
SU 'cat /proc/partitions'      > "$OUT/sysfs/proc-partitions.txt"

hdr "Q8: merged post-ABL device tree"
SU 'find /sys/firmware/devicetree/base -type f' > "$OUT/dt/dt-files.txt"
adb exec-out "su -c 'tar -c -C /sys/firmware/devicetree base 2>/dev/null'" > "$OUT/dt/devicetree-base.tar"
note "$(wc -l < "$OUT/dt/dt-files.txt") DT property files"
note "decompile with: mkdir -p dtb && tar -xf $OUT/dt/devicetree-base.tar -C dtb && dtc -I fs -O dts dtb/base > q2q-merged-postabl.dts"
note "then diff the /memory node against the source overlay -- ABL is reported to emit bogus memory nodes"

hdr "Q9: panel identity"
for n in /sys/class/lcd/panel/lcd_type /sys/class/lcd/panel/window_type \
         /sys/class/lcd/panel/SVC_OCTA /sys/class/lcd/panel1/lcd_type \
         /sys/class/lcd/panel1/window_type /sys/class/lcd/panel1/SVC_OCTA; do
  printf '%-46s %s\n' "$n" "$(SU "cat $n")"
done | tee "$OUT/sysfs/panel.txt"
SU 'dmesg | grep -iE "s6e3|panel|dsi|mdss|dispcc"' > "$OUT/logs/dmesg-display.txt"
note "expect S6E3XA1_AMF755ZE01 or S6E3XA2_AMF755ZE01 (r08 offers both)"

hdr "Q5: QCA6490 revision"
SU 'dmesg | grep -iE "cnss|qca6490|wlan|ath1|soc_hw_version|chip_id|board_id|fw_build"' \
   > "$OUT/logs/dmesg-wifi.txt"
SU 'cat /sys/kernel/debug/cnss2/* 2>/dev/null' > "$OUT/sysfs/cnss2.txt"
SU 'cat /sys/bus/pci/devices/*/uevent 2>/dev/null' > "$OUT/sysfs/pci.txt"
note "want soc_hw_version major/minor: major 2 + minor 0x00/0x01 => ath11k WCN6855_HW20 with NO code change"

hdr "Q4: battery / dual-cell limiter"
SU 'dmesg | grep -iE "s2asl01|max77705|sm5451|dual_battery|limiter"' > "$OUT/logs/dmesg-battery.txt"
SU 'for d in /sys/class/power_supply/*; do echo "### $d"; cat $d/uevent; done' > "$OUT/sysfs/power-supply.txt"
SU 'cat /sys/kernel/debug/gpio' > "$OUT/sysfs/gpio-debug.txt"
note "look up the bat_enb GPIOs -- if they default to ENABLED, 'leave it to the hardware' is validated"

hdr "Q10: audio amp variant"
SU 'dmesg | grep -iE "cs35l41|tas256|sma130|wcd938|wsa883"' > "$OUT/logs/dmesg-audio.txt"

hdr "uniLoader load addresses"
SU 'cat /proc/iomem'   > "$OUT/sysfs/proc-iomem.txt"
SU 'cat /proc/cmdline' > "$OUT/sysfs/proc-cmdline.txt"
adb exec-out "su -c 'dd if=/dev/block/by-name/boot bs=1M count=4 2>/dev/null'" > "$OUT/boot/boot-head.img"
note "run: unpack_bootimg --boot_img $OUT/boot/boot-head.img  (header ver, page size, os_version, os_patch_level)"

hdr "full dmesg"
SU 'dmesg' > "$OUT/logs/dmesg-full.txt"

echo; echo "Done. $(cd "$OUT" && pwd)"
echo "NEXT: ./01-backup-critical.sh   (do this before any flashing)"
