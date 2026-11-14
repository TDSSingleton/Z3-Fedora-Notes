#!/usr/bin/env bash
# Tier 3: vendor firmware the mainline kernel needs.
# Qualcomm-proprietary and NOT redistributable -- keep it out of git.
cd "$(dirname "$0")" && . ./lib-common.sh

OUT="${1:-../capture/firmware-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"
require_device; require_root; manifest_init
echo "Output: $(cd "$OUT" && pwd)"

hdr "remoteproc / subsystem images (adsp, cdsp, slpi, a660_zap, evass)"
# apnhlos partition, mounted at /vendor/firmware_mnt on SM-F926B
pull_dir /vendor/firmware_mnt/image "$OUT/firmware_mnt" || \
  pull_dir /firmware/image "$OUT/firmware_mnt"

hdr "modem / MPSS firmware (needed for Goal 5 -- LTE)"
# NOTE: Samsung puts the modem image in its OWN partition mounted at
# /vendor/firmware-modem, NOT in firmware_mnt. An earlier version of this script
# missed the modem entirely because it only looked in firmware_mnt.
pull_dir /vendor/firmware-modem/image "$OUT/firmware_modem" || \
  pull_dir /vendor/firmware-modem "$OUT/firmware_modem"

hdr "DSP partition"
pull_dir /vendor/dsp "$OUT/vendor_dsp"

hdr "peripheral firmware (WiFi amss/m3/regdb/bdwlan, BT, touch)"
pull_dir /vendor/firmware        "$OUT/vendor_firmware"
pull_dir /vendor/lib/firmware    "$OUT/vendor_lib_firmware"
pull_dir /vendor/etc/wifi        "$OUT/vendor_etc_wifi"
pull_dir /odm/firmware           "$OUT/odm_firmware"
pull_dir /mnt/vendor/persist     "$OUT/persist_mount"

hdr "inventory of what matters"
# Paths verified on SM-F926B 2026-11-07. Wi-Fi firmware is in a qca6490/
# SUBDIRECTORY, not the /vendor/firmware root -- an earlier version of this
# script looked in the wrong place and reported nothing.
{
  echo "### Wi-Fi (QCA6490) -> /lib/firmware/ath11k/WCN6855/hw2.0/"
  echo "###   amss20.bin -> amss.bin ; m3.bin ; regdb.bin ; bdwlan.elf* -> board-2.bin"
  SU 'ls -la /vendor/firmware/qca6490/ 2>/dev/null'
  echo
  echo "### Bluetooth (hp = WCN6855/QCA6490 family, rom_ver 0x20) -> /lib/firmware/qca/"
  SU 'ls -la /vendor/firmware/ 2>/dev/null | grep -iE "hpbtfw|hpnv|bt_nvm"'
  echo
  echo "### GPU (Adreno 660) -> /lib/firmware/qcom/"
  SU 'ls -la /vendor/firmware/ 2>/dev/null | grep -iE "a660"'
  SU 'ls -la /vendor/firmware_mnt/image/ 2>/dev/null | grep -iE "a660"'
  echo
  echo "### IPA (needed for mobile data)"
  SU 'ls -la /vendor/firmware/ 2>/dev/null | grep -iE "^.*ipa_fws"'
  echo
  echo "### remoteproc images -> /lib/firmware/qcom/sm8350/"
  SU 'ls -la /vendor/firmware_mnt/image/ 2>/dev/null | grep -iE "adsp\.mdt|cdsp\.mdt|slpi\.mdt|modem\.mdt|venus|evass"'
  echo
  echo "### touch + pen firmware"
  SU 'ls -la /vendor/firmware/ 2>/dev/null | grep -iE "fts9cu|wez01"'
} | tee "$OUT/INVENTORY.txt"

cat <<EOF

Done. $(cd "$OUT" && pwd)

Where these go on the Linux side:
  remoteproc (adsp/cdsp/slpi/modem/ipa_fws/a660_zap)
        -> /lib/firmware/qcom/sm8350/
  Wi-Fi: /vendor/firmware/qca6490/{amss20.bin,m3.bin,regdb.bin}
        -> /lib/firmware/ath11k/WCN6855/hw2.0/   (rename amss20.bin -> amss.bin)
  Wi-Fi board data (bdwlan*.bin is a BARE BDF)
        -> must be wrapped into board-2.bin with ath11k-bdencoder
           (see 12-wifi-qca6490.md section 6)
  Bluetooth: hpbtfw20.tlv + hpnv20.bin -> /lib/firmware/qca/
        (upstream btqca asks for qca/hpbtfw20.tlv at rom_ver 0x20; linux-firmware
         ships only the 21 variants, so these MUST come from the device)
           BT MAC address comes from the EFS backup, not from here.

REMINDERS:
  * a660_zap is easy to miss and the Adreno GPU will NOT come up without it.
  * This firmware is Qualcomm's. Do not commit it, do not publish it.
    A Fedora image must extract it at boot (droid-juicer) instead of shipping it.
EOF
