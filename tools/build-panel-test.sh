#!/usr/bin/env bash
# Compile-test panel-work/panel-samsung-s6e3xa2.c against a real kernel tree.
#
# Builds only our translation unit, which is the fastest way to check the code
# against real headers. Cross-compiles for arm64 with GCC (no clang on this
# host; GCC checks the same C and the same APIs).
#
#   ./tools/build-panel-test.sh [path-to-kernel-tree]
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:-$ROOT/linux-fedora}"   # Fedora 44/45 kernel base; pass $ROOT/linux for mainline
SRC="$ROOT/panel-work/panel-samsung-s6e3xa2.c"
DRV="drivers/gpu/drm/panel"
OBJ="$DRV/panel-samsung-s6e3xa2.o"
SYM="DRM_PANEL_SAMSUNG_S6E3XA2"

[ -d "$TREE" ]  || { echo "!! no kernel tree at $TREE"; exit 1; }
[ -f "$SRC" ]   || { echo "!! no driver at $SRC"; exit 1; }

export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-

echo "tree:   $TREE  ($(grep -m1 VERSION "$TREE/Makefile" | tr -d ' ').$(grep -m1 PATCHLEVEL "$TREE/Makefile" | sed 's/.*= //'))"
echo "driver: $SRC"
echo

# ---- 1. install the source ------------------------------------------------
cp "$SRC" "$TREE/$DRV/"

# ---- 2. Kconfig entry (idempotent) ---------------------------------------
if ! grep -q "$SYM" "$TREE/$DRV/Kconfig"; then
  # Mirror the dependency set of s6e3ha8, the closest in-tree relative
  # (Samsung command-mode DSC panel), so we inherit whatever it needs.
  python3 - "$TREE/$DRV/Kconfig" "$SYM" <<'PY'
import re, sys
path, sym = sys.argv[1], sys.argv[2]
s = open(path).read()
m = re.search(r'(config DRM_PANEL_SAMSUNG_S6E3HA8\n(?:[ \t].*\n|\n)*?)(?=config |\Z)', s)
if not m:
    sys.exit("could not find the S6E3HA8 stanza to mirror")
tmpl = m.group(1)
deps = [l for l in tmpl.splitlines()
        if re.match(r'\s+(depends on|select)\b', l)]
new = (f"config {sym}\n"
       '\ttristate "Samsung S6E3XA2 AMF755ZE01 foldable AMOLED panel"\n'
       + "\n".join(deps) + "\n"
       "\thelp\n"
       "\t  Say Y or M here if you want to enable support for the Samsung\n"
       "\t  S6E3XA2 (AMF755ZE01) 2208x1768 command-mode AMOLED panel with DSC,\n"
       "\t  as fitted to the inner display of the Galaxy Z Fold 3 (SM-F926B).\n\n")
s = s[:m.start(1)] + new + s[m.start(1):]
open(path, 'w').write(s)
print(f"  Kconfig: added {sym} (deps mirrored from S6E3HA8)")
PY
  [ $? -ne 0 ] && exit 1
else
  echo "  Kconfig: $SYM already present"
fi

# ---- 3. Makefile entry (idempotent) --------------------------------------
if ! grep -q "$SYM" "$TREE/$DRV/Makefile"; then
  echo "obj-\$(CONFIG_$SYM) += panel-samsung-s6e3xa2.o" >> "$TREE/$DRV/Makefile"
  echo "  Makefile: added obj rule"
else
  echo "  Makefile: already present"
fi

# ---- 4. configure --------------------------------------------------------
cd "$TREE"
if [ ! -f .config ]; then
  echo; echo "configuring (arm64 defconfig)..."
  make -s defconfig >/dev/null || exit 1
fi
./scripts/config --enable DRM \
                 --enable DRM_MIPI_DSI \
                 --enable DRM_PANEL \
                 --enable BACKLIGHT_CLASS_DEVICE \
                 --enable REGULATOR \
                 --module "$SYM"
# whatever S6E3HA8 selects for DSC, enable it too
grep -oE 'DRM_DISPLAY_DSC_HELPER|DRM_DISPLAY_HELPER' "$DRV/Kconfig" | sort -u | while read -r c; do
  ./scripts/config --enable "$c"
done
make -s olddefconfig >/dev/null || exit 1
echo "  config: CONFIG_$SYM = $(./scripts/config --state "$SYM")"

# ---- 5. build just our object -------------------------------------------
echo; echo "building $OBJ ..."
if make -j"$(nproc)" "$OBJ" 2>&1 | tee /tmp/panel-build.log | grep -E 'error|warning|Error' ; then
  :
fi
echo
if [ -f "$OBJ" ]; then
  echo "=============================================="
  echo " BUILD OK: $OBJ"
  "${CROSS_COMPILE}size" "$OBJ" 2>/dev/null
  echo "=============================================="
  exit 0
else
  echo "=============================================="
  echo " BUILD FAILED -- see /tmp/panel-build.log"
  echo "=============================================="
  grep -E 'error' /tmp/panel-build.log | head -40
  exit 1
fi
