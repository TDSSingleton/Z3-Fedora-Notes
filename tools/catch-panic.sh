#!/bin/bash
# Pull every pstore record the moment the device is reachable, and work out
# which came from OUR kernel rather than Samsung's.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/capture/panic-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$OUT"

echo "waiting for device ..."
timeout 300 adb wait-for-device 2>/dev/null || { adb kill-server; adb start-server >/dev/null 2>&1; timeout 300 adb wait-for-device; }
ST=$(adb get-state 2>/dev/null | tr -d '\r'); echo "  state: $ST"

if [ "$ST" = "device" ]; then SU='su -c'; else SU=''; fi
run() { if [ -n "$SU" ]; then timeout 90 adb shell "su -c '$1'" 2>/dev/null; else timeout 90 adb shell "$1" 2>/dev/null; fi; }

echo; echo "=== /sys/fs/pstore ==="
run 'ls -la /sys/fs/pstore/' | tr -d '\r' | sed 's/^/  /'

echo; echo "=== pulling ==="
for f in $(run 'ls /sys/fs/pstore/' | tr -d '\r'); do
	[ -z "$f" ] && continue
	run "cat /sys/fs/pstore/$f" | tr -d '\r' > "${OUT:?}/${f:?}"
	sz=$(stat -c%s "$OUT/$f" 2>/dev/null || echo 0)
	[ "$sz" -gt 0 ] && echo "  $f  ($sz bytes)"
done

echo; echo "=== OURS or SAMSUNG'S? ==="
for f in "$OUT"/*; do
	[ -f "$f" ] || continue
	ours=0; theirs=0
	for m in 'simpledrm' 'samsung-q2q' 'cpuidle.off' 'Demotion targets' 'uniLoader' 'e4000000.framebuffer' 'mainline'; do
		c=$(grep -aic -- "$m" "$f" 2>/dev/null | head -1); ours=$((ours + ${c:-0}))
	done
	for m in 'max77705' 'zygote' 'sec_debug' 'SurfaceFlinger' 'init: Service'; do
		c=$(grep -aic -- "$m" "$f" 2>/dev/null | head -1); theirs=$((theirs + ${c:-0}))
	done
	printf "  %-24s ours=%-4s samsung=%-4s %s\n" "$(basename "$f")" "$ours" "$theirs" \
		"$([ "$ours" -gt 0 ] && echo '  <-- OUR KERNEL' || true)"
done

echo; echo "=== the thing we actually want ==="
grep -al 'Internal error\|Unable to handle kernel\|Kernel panic\|Call trace' "$OUT"/* 2>/dev/null | sed 's/^/  crash text in: /' || echo "  no crash text found"
echo; echo "OUT=$OUT"
