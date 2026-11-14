#!/usr/bin/env bash
# Pull the previous boot's kernel log out of ramoops, then (optionally) restore boot.
#
# Run this from TWRP (or Android) IMMEDIATELY after a failed attempt -- the records
# live in DRAM at 0xf0b00000 and do not survive a long power-off.
#
#   ./tools/pull-pstore.sh                # pull + analyse
#   ./tools/pull-pstore.sh --restore      # pull + analyse, then restore stock boot
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/capture/pstore-$(date +%Y%m%d-%H%M%S)"

st=$(timeout 10 adb get-state 2>/dev/null | tr -d '\r')
[ -n "$st" ] || { echo "!! no adb. In TWRP? Try: adb kill-server; adb devices"; exit 1; }
if [ "$(timeout 10 adb shell 'id -u' 2>/dev/null | tr -d '\r')" = "0" ]; then SU=""
elif [ "$(timeout 10 adb shell 'su -c id -u' 2>/dev/null | tr -d '\r')" = "0" ]; then SU="su -c "
else echo "!! need root"; exit 1; fi
echo "adb state: $st   root: yes"

mkdir -p "$OUT"
echo
echo "=== /sys/fs/pstore ==="
timeout 20 adb shell "${SU}ls -la /sys/fs/pstore/" 2>/dev/null | tr -d '\r' | sed 's/^/  /'

n=0
for f in $(timeout 20 adb shell "${SU}ls /sys/fs/pstore/" 2>/dev/null | tr -d '\r'); do
	timeout 90 adb exec-out "${SU}cat /sys/fs/pstore/$f" > "$OUT/$f" 2>/dev/null
	sz=$(stat -c%s "$OUT/$f" 2>/dev/null || echo 0)
	if [ "$sz" -gt 0 ]; then printf "  pulled %-26s %s bytes\n" "$f" "$sz"; n=$((n+1));
	else rm -f "$OUT/$f"; fi
done
# last_kmsg is a second, independent source
timeout 60 adb exec-out "${SU}cat /proc/last_kmsg" > "$OUT/last_kmsg" 2>/dev/null
[ -s "$OUT/last_kmsg" ] && { printf "  pulled %-26s %s bytes\n" last_kmsg "$(stat -c%s "$OUT/last_kmsg")"; n=$((n+1)); } || rm -f "$OUT/last_kmsg"

echo
if [ "$n" -eq 0 ]; then
	cat <<'EOF'
  NOTHING RECORDED.
  Either the kernel never reached console init, or ramoops still is not probing.
  Both are informative: it means the failure is before/at kernel start, not after.
EOF
else
	LOG=$(ls -S "$OUT"/console-ramoops-* "$OUT"/dmesg-ramoops-* "$OUT"/last_kmsg 2>/dev/null | head -1)
	echo "=== analysing $(basename "$LOG") ($(wc -l < "$LOG") lines) ==="
	echo
	echo "--- first 25 lines (did OUR kernel boot?) ---"
	head -25 "$LOG" | cut -c1-150 | sed 's/^/  /'
	echo
	echo "--- banner / version ---"
	grep -m3 -iE 'Linux version|Booting Linux' "$LOG" | cut -c1-160 | sed 's/^/  /' || echo "  (none)"
	echo
	echo "--- anything that touched the DISPLAY ---"
	grep -inE 'dispcc|simpledrm|simple-framebuffer|fb0|fbcon|mdss|drm' "$LOG" | head -14 | cut -c1-160 | sed 's/^/  /' || echo "  (none)"
	echo
	echo "--- panics / oopses / BUGs ---"
	grep -inE 'Unable to handle|Internal error|Oops|BUG:|Kernel panic|Call trace|SError|synchronous abort' "$LOG" | head -14 | cut -c1-160 | sed 's/^/  /' || echo "  (none)"
	echo
	echo "--- late lines (where did it stop?) ---"
	tail -20 "$LOG" | cut -c1-150 | sed 's/^/  /'
fi
echo
echo "saved to: $OUT"

if [ "${1:-}" = "--restore" ]; then
	echo
	echo "=== restoring stock boot ==="
	"$ROOT/rescue/restore-boot.sh" || echo "  (restore-boot.sh reported a problem)"
fi
