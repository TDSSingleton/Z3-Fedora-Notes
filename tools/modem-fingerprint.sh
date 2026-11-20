#!/bin/bash
# modem-fingerprint.sh -- capture the modem's SEMANTIC configuration state.
#
# Why this exists: modemst1/2 are encrypted, so a byte diff of the partitions
# tells us only THAT they changed, never WHAT changed (one re-flushed NV item
# re-encrypts the whole payload and looks identical to a full re-provision).
# This reads the same state back out of the modem by name, over QMI, where it
# is plaintext and diffable.
#
# STRICTLY READ-ONLY. No writes to modem storage, no config activation, no
# band/power changes, no scans. Every probe here is a getter.
#
# Usage:  modem-fingerprint.sh [label]     (run ON the phone, as root)
# Output: one text file on stdout; identifiers are redacted (see scrub()).
set -u

DEV="qrtr://0"
LABEL="${1:-unlabeled}"

# Redact subscriber/device identifiers: IMEI/IMSI/ICCID/MEID are long digit
# runs. Cell IDs, PLMNs and versions are shorter and survive. PDC config IDs
# are colon-hex (config identity, not personal) and are kept deliberately.
scrub() { sed -E 's/[0-9]{14,21}/<redacted-id>/g'; }

probe() {  # probe <section> <qmicli args...>
	local name="$1"; shift
	echo "### $name"
	timeout 25 qmicli -d "$DEV" "$@" 2>&1 | scrub | sed 's/^/    /'
	echo
}

echo "# fold3 modem semantic fingerprint"
echo "# label: $LABEL"
echo "# taken: $(date -u +%Y-%m-%dT%H:%M:%SZ) (device clock; may be wrong)"
echo "# host:  $(uname -srm)"
echo

echo "## 0. storage identity (the encrypted layer -- THAT it changed, not what)"
echo "### partition hashes"
sha256sum /dev/sda1 /dev/sda2 /dev/sda3 2>/dev/null | sed 's/^/    /'
echo "### modemst header (plaintext 48-byte container header; last byte = flush counter)"
for p in /dev/sda1 /dev/sda2; do
	echo "    $p: $(head -c 48 "$p" | xxd -p | tr -d '\n')"
done
echo
echo "### rmtfs invocation (read-only is what freezes the store under Linux)"
systemctl show rmtfs -p ExecStart --value 2>/dev/null | sed 's/^/    /'
echo
echo "### remoteproc"
for r in /sys/class/remoteproc/remoteproc*; do
	echo "    $(basename "$r") $(cat "$r/name" 2>/dev/null) $(cat "$r/state" 2>/dev/null)"
done
echo

echo "## 1. PDC -- persistent device configuration (carrier + platform configs)"
probe "platform configs" --pdc-list-configs=platform
probe "software configs" --pdc-list-configs=software
echo "### selected config IDs (active/pending, incl. pending queued for next boot)"
if [ -x /usr/local/sbin/pdc-selected-config.py ]; then
	timeout 40 /usr/local/sbin/pdc-selected-config.py 2>&1 | sed 's/^/    /'
else
	echo "    (pdc-selected-config.py not installed)"
fi
echo

echo "## 2. UIM -- card, slots, and which subscription the app is bound to"
probe "slot status"      --uim-get-slot-status
probe "card status"      --uim-get-card-status
probe "configuration"    --uim-get-configuration

echo "## 3. WDS -- data profiles (the APN config that survives, or does not)"
probe "default profile num (3gpp)" --wds-get-default-profile-number=3gpp
probe "profile list (3gpp)"        --wds-get-profile-list=3gpp
probe "LTE attach parameters"      --wds-get-lte-attach-parameters
probe "LTE attach PDN list"        --wds-get-lte-attach-pdn-list

echo "## 4. NAS -- selection policy (what the modem is allowed to camp on)"
probe "system selection preference" --nas-get-system-selection-preference
probe "technology preference"       --nas-get-technology-preference
probe "operator name"               --nas-get-operator-name
probe "serving system"              --nas-get-serving-system
probe "system info"                 --nas-get-system-info

echo "## 5. DMS -- device/firmware revision and operating mode"
probe "operating mode"   --dms-get-operating-mode
probe "revision"         --dms-get-revision
probe "model"            --dms-get-model
probe "capabilities"     --dms-get-capabilities

echo "## 6. DSD / WDA -- data system determination and data format"
probe "DSD system status" --dsd-get-system-status
probe "DSD APN info (default)" --dsd-get-apn-info=default
probe "WDA data format"  --wda-get-data-format=

echo "## 7. ModemManager's view (cross-check, redacted)"
echo "### mmcli -m 0"
timeout 20 mmcli -m 0 2>&1 | scrub | sed 's/^/    /'
echo
echo "### mmcli -b 0"
timeout 20 mmcli -b 0 2>&1 | scrub | sed 's/^/    /'
echo
echo "### fold3-sim-primary.service"
systemctl status fold3-sim-primary --no-pager 2>&1 | head -15 | scrub | sed 's/^/    /'
echo
echo "# end of fingerprint"
