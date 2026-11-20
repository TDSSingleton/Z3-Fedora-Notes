#!/usr/bin/env bash
# Capture raw Bayer frames from the Fold 3's rear ultrawide (IMX258) through
# mainline camss. Run ON the phone.
#
#   ./capture-uw.sh [out.raw] [frames] [WxH]
#
# Defaults: /root/uw.raw, 3 frames, 4208x3120.
#
# The pad formats MUST be re-applied before every stream: VIDIOC_STREAMON
# returns -EINVAL on a second run otherwise, because camss validates the whole
# chain's formats at stream start and they do not survive the previous
# stream's teardown. That looked like a capability problem the first time.
#
# Sizes: only 4208x3120 works while the DT declares a single link-frequency of
# 633600000. The 2104x1560 and 1048x780 modes need 320000000 in the sensor
# endpoint's link-frequencies too, or the sensor refuses the mode.
set -u

OUT="${1:-/root/uw.raw}"
N="${2:-3}"
SIZE="${3:-4208x3120}"
W="${SIZE%x*}"; H="${SIZE#*x}"
CODE=SRGGB10_1X10
PIXFMT=pRAA		# 10-bit Bayer RGRG/GBGB, MIPI-packed

MED=/dev/media0
VID=/dev/video0

# The entity name carries the i2c address ("imx258 9-001a") and the subdev node
# number is not stable across boots, so discover both from the topology.
ENT=$(media-ctl -d $MED -p 2>/dev/null | sed -n 's/^- entity [0-9]*: \(imx258 [^ ]*\) .*/\1/p' | head -1)
[ -n "$ENT" ] || { echo "!! no imx258 entity in $MED"; exit 1; }
SD=$(media-ctl -d $MED -e "$ENT" 2>/dev/null)

echo "sensor entity : $ENT  ($SD)"
echo "capturing     : $N x ${W}x${H} $CODE -> $OUT"

# imx258 -> csiphy4 -> csid0 -> vfe0_rdi0 -> video0
media-ctl -d $MED -V "\"$ENT\":0 [fmt:$CODE/${W}x$H]" || exit 1
for pad in '"msm_csiphy4":0' '"msm_csiphy4":1' \
           '"msm_csid0":0'   '"msm_csid0":1' \
           '"msm_vfe0_rdi0":0' '"msm_vfe0_rdi0":1'; do
	media-ctl -d $MED -V "$pad [fmt:$CODE/${W}x$H]" || exit 1
done

v4l2-ctl -d $VID --set-fmt-video=width=$W,height=$H,pixelformat=$PIXFMT || exit 1

v4l2-ctl -d $VID --stream-mmap --stream-count="$N" --stream-to="$OUT" || exit 1
echo
ls -l "$OUT"
