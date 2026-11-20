#!/bin/bash
# modem-fingerprint-diff.sh -- compare two modem fingerprints, ignoring noise.
#
# A fingerprint mixes durable CONFIGURATION (what we care about: carrier
# config selection, provisioning bindings, profiles, selection policy) with
# per-session STATE that changes every boot no matter what (cell id, signal,
# byte counters, the session's IP). Diffing raw drowns the first in the
# second. This strips the known-volatile lines first.
#
#   modem-fingerprint-diff.sh A.txt B.txt          # configuration only
#   modem-fingerprint-diff.sh --raw A.txt B.txt    # everything
set -u

RAW=0
[ "${1:-}" = "--raw" ] && { RAW=1; shift; }
A="${1:?usage: $0 [--raw] OLD.txt NEW.txt}"
B="${2:?usage: $0 [--raw] OLD.txt NEW.txt}"

strip() {
	if [ "$RAW" = 1 ]; then cat "$1"; return; fi
	grep -vE \
		-e '^# taken:' -e '^# label:' \
		-e 'cell id|Cell ID|3GPP cell ID|Tracking Area Code|LTE tracking area code' \
		-e 'signal quality|RSRP|RSRQ|SNR|RSSI' \
		-e 'start_time=|pid=[0-9]+|start date|duration:|bytes rx|bytes tx' \
		-e 'Active: .*(timestamp|since)' \
		-e '^\s+(address|gateway|dns|prefix): ' \
		-e 'device id:' \
		-e 'Since:|Main PID:|Tasks:|Memory:|CPU:|CGroup:|^\s+└─|^\s+├─' \
		-e 'systemd\[1\]|fold3-sim-primary\[' \
		"$1"
}

echo "# fingerprint diff"
echo "#   old: $A ($(grep -m1 '^# label:' "$A" | cut -d: -f2-))"
echo "#   new: $B ($(grep -m1 '^# label:' "$B" | cut -d: -f2-))"
[ "$RAW" = 1 ] && echo "#   mode: RAW (volatile session state included)" \
               || echo "#   mode: configuration only (volatile session state stripped)"
echo

if diff -u <(strip "$A") <(strip "$B") > /tmp/.fpdiff.$$ 2>&1; then
	echo "NO CONFIGURATION DIFFERENCE."
	rm -f /tmp/.fpdiff.$$
	exit 0
fi
tail -n +3 /tmp/.fpdiff.$$
rm -f /tmp/.fpdiff.$$
exit 1
