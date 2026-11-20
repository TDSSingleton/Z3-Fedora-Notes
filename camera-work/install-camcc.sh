#!/usr/bin/env bash
# Drop the generated camcc-sm8350 driver into a kernel tree and wire up
# Kconfig + Makefile. Idempotent.
#   ./camera-work/install-camcc.sh [kernel-tree]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:-$ROOT/linux-fedora}"
[ -d "$TREE/drivers/clk/qcom" ] || { echo "!! no kernel tree at $TREE"; exit 1; }

cp "$ROOT/camera-work/out/camcc-sm8350.c"        "$TREE/drivers/clk/qcom/"
cp "$ROOT/camera-work/out/qcom,sm8350-camcc.h"   "$TREE/include/dt-bindings/clock/"
echo "copied driver + bindings header"

K="$TREE/drivers/clk/qcom/Kconfig"
if ! grep -q "^config SM_CAMCC_8350$" "$K"; then
	python3 - "$K" <<'PY'
import sys, re
p = sys.argv[1]; t = open(p).read()
anchor = "config SM_CAMCC_8450"
new = """config SM_CAMCC_8350
	tristate "SM8350 Camera Clock Controller"
	depends on ARM64 || COMPILE_TEST
	select SM_GCC_8350
	help
	  Support for the camera clock controller on SM8350 devices.
	  Say Y if you want to support camera devices and camera functionality.

"""
assert t.count(anchor) == 1, "Kconfig anchor not unique"
open(p, "w").write(t.replace(anchor, new + anchor, 1))
PY
	echo "Kconfig: added SM_CAMCC_8350"
else
	echo "Kconfig: already present"
fi

M="$TREE/drivers/clk/qcom/Makefile"
if ! grep -q "CONFIG_SM_CAMCC_8350" "$M"; then
	sed -i 's|^obj-$(CONFIG_SM_CAMCC_8450) += camcc-sm8450.o|obj-$(CONFIG_SM_CAMCC_8350) += camcc-sm8350.o\nobj-$(CONFIG_SM_CAMCC_8450) += camcc-sm8450.o|' "$M"
	echo "Makefile: added camcc-sm8350.o"
else
	echo "Makefile: already present"
fi
grep -n "CAMCC_8350" "$M" | sed 's/^/  /'
