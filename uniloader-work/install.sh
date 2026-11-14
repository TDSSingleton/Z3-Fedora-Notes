#!/usr/bin/env bash
# Install the q2q port into a uniLoader checkout, idempotently, then build it.
#   ./uniloader-work/install.sh [path-to-uniloader] [--build]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UL="${1:-$ROOT/uniloader}"
[ -d "$UL/board/samsung" ] || { echo "!! not a uniLoader tree: $UL"; exit 1; }

say(){ printf '  %s\n' "$*"; }

# ---- 1. board source + defconfig ----
cp "$ROOT/uniloader-work/board-q2q.c" "$UL/board/samsung/board-q2q.c"
cp "$ROOT/uniloader-work/q2q_defconfig" "$UL/configs/q2q_defconfig"
say "installed board/samsung/board-q2q.c + configs/q2q_defconfig"

# ---- 2. soc/Kconfig: add SM8350 next to SM8450 ----
if grep -q 'config SM8350' "$UL/soc/Kconfig"; then
	say "soc/Kconfig: SM8350 already present"
else
	python3 - "$UL/soc/Kconfig" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p).read()
m = re.search(r'(\tconfig SM8450\n(?:\t\t.*\n|\n)*?)(?=\tconfig |\Z)', s)
if not m:
    sys.exit("could not find the SM8450 stanza to mirror")
new = ("\tconfig SM8350\n"
       '\t\tbool "Support for QUALCOMM SM8350"\n'
       "\t\tselect QUALCOMM\n"
       "\t\thelp\n"
       "\t\t  Say Y if your device uses this Qualcomm SoC\n\n")
open(p, 'w').write(s[:m.start(1)] + new + s[m.start(1):])
PY
	[ $? -eq 0 ] && say "soc/Kconfig: added SM8350" || exit 1
fi

# ---- 3. board/Kconfig: add SAMSUNG_Q2Q ----
if grep -q 'config SAMSUNG_Q2Q' "$UL/board/Kconfig"; then
	say "board/Kconfig: SAMSUNG_Q2Q already present"
else
	python3 - "$UL/board/Kconfig" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p).read()
m = re.search(r'(\tconfig SAMSUNG_R0Q\n(?:\t\t.*\n|\n)*?)(?=\tconfig |\Z)', s)
if not m:
    sys.exit("could not find the SAMSUNG_R0Q stanza to anchor against")
new = ("\tconfig SAMSUNG_Q2Q\n"
       '\t\tbool "Support for Samsung Galaxy Z Fold 3"\n'
       "\t\tdefault n\n"
       "\t\tdepends on SM8350\n"
       "\t\thelp\n"
       "\t\t  Say Y if you want to include support for Samsung Galaxy Z Fold 3\n\n")
open(p, 'w').write(s[:m.start(1)] + new + s[m.start(1):])
PY
	[ $? -eq 0 ] && say "board/Kconfig: added SAMSUNG_Q2Q" || exit 1
fi

# ---- 4. board/Makefile ----
if grep -q 'SAMSUNG_Q2Q' "$UL/board/Makefile"; then
	say "board/Makefile: already present"
else
	# keep the file's alphabetical-ish grouping: insert next to the other samsung entries
	python3 - "$UL/board/Makefile" <<'PY'
import sys
p = sys.argv[1]; lines = open(p).read().splitlines(True)
entry = "lib-$(CONFIG_SAMSUNG_Q2Q) += samsung/board-q2q.o\n"
idx = next((i for i, l in enumerate(lines) if 'SAMSUNG_R0Q' in l), None)
if idx is None:
    lines.append(entry)
else:
    lines.insert(idx, entry)
open(p, 'w').writelines(lines)
PY
	say "board/Makefile: added obj rule"
fi

[ "${2:-}" = "--build" ] || { echo; say "installed. re-run with --build to compile."; exit 0; }

# ---- 5. build ----
echo
cd "$UL"
command -v aarch64-linux-gnu-gcc >/dev/null || { echo "!! need aarch64-linux-gnu-gcc"; exit 1; }
# uniLoader embeds kernel/dtb/ramdisk; provide placeholders so a standalone
# build can be verified before the real payloads exist.
mkdir -p blob
for f in Image dtb ramdisk; do
	[ -s "blob/$f" ] || { printf '\0' > "blob/$f"; say "blob/$f: placeholder created"; }
done
make ARCH=aarch64 CROSS_COMPILE=aarch64-linux-gnu- q2q_defconfig >/dev/null 2>&1 \
	|| { echo "!! defconfig failed"; exit 1; }
say "configured q2q_defconfig"
make ARCH=aarch64 CROSS_COMPILE=aarch64-linux-gnu- -j"$(nproc)" 2>&1 | tail -25
echo
if [ -f uniLoader ]; then
	echo "=============================================="
	echo " BUILD OK: $UL/uniLoader"
	file uniLoader 2>/dev/null | sed 's/^/   /'
	ls -la uniLoader | awk '{print "   size:", $5, "bytes"}'
	echo "=============================================="
else
	echo "=============================================="
	echo " BUILD FAILED"
	echo "=============================================="
	exit 1
fi
