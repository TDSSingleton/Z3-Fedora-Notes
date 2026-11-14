#!/usr/bin/env bash
# Tiers 1 + 2: irreplaceable per-device data, then recovery images.
# RUN THIS FIRST after gaining root, before any flashing experiments.
# Read-only: never writes to the device.
cd "$(dirname "$0")" && . ./lib-common.sh

OUT="${1:-../capture/backup-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"/{tier1-irreplaceable,tier2-recovery}
require_device; require_root; manifest_init
echo "Output: $(cd "$OUT" && pwd)"

# Tier 1 -- cannot be regenerated, not in any firmware download.
TIER1="efs sec_efs persist modemst1 modemst2 fsg fsc"
# Samsung region/CSC + device identity. Not strictly unrecoverable, but not in a
# generic firmware download either -- cheap to keep.
TIER1B="optics prism devinfo cdt steady omr"
# Tier 2 -- restorable from stock firmware, but handy to have locally.
TIER2="boot vendor_boot dtbo vbmeta vbmeta_system recovery param"

hdr "TIER 1 -- irreplaceable (IMEI, BT/WiFi MAC, sensor calibration, modem NV)"
fail=0
for p in $TIER1; do pull_partition "$p" "$OUT/tier1-irreplaceable/$p.img" || fail=$((fail+1)); done

hdr "TIER 1B -- Samsung region/CSC + device identity"
for p in $TIER1B; do pull_partition "$p" "$OUT/tier1-irreplaceable/$p.img" || true; done

hdr "TIER 2 -- recovery images"
for p in $TIER2; do pull_partition "$p" "$OUT/tier2-recovery/$p.img" || true; done

hdr "partition table"
SU 'ls -l /dev/block/by-name/' > "$OUT/by-name.txt"
SU 'cat /proc/partitions'      > "$OUT/proc-partitions.txt"

echo
if [ "$fail" -gt 0 ]; then
  echo "!! $fail Tier-1 partition(s) failed or were missing. Check MANIFEST.txt."
  echo "!! Do NOT proceed to flashing until every Tier-1 image is present and hash-verified."
else
  echo "All Tier-1 partitions captured and hash-verified."
fi
cat <<EOF

MANIFEST: $(cd "$OUT" && pwd)/MANIFEST.txt

NOW DO THIS, before anything else:
  1. Copy this directory to TWO places that are not this machine.
  2. Re-verify: sha256sum -c against MANIFEST.txt on each copy.
  3. Treat tier1-irreplaceable/ as read-only forever. Never flash it back
     unless you are recovering, and never write to those partitions.

NEXT: ./02-extract-firmware.sh
EOF
