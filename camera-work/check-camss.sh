#!/usr/bin/env bash
# Report the state of the camera capture path on the device. Read-only.
#   ssh root@phone 'bash -s' < camera-work/check-camss.sh
# or, from the host:
#   ./camera-work/check-camss.sh            (ssh's itself in)
set -u

# Run on the phone if we are not already there. $FOLD3 overrides the address.
if [ "$(uname -m)" != "aarch64" ]; then
	exec ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no \
		-i "$HOME/.ssh/fold3_ed25519" root@"${FOLD3:-192.168.11.131}" \
		'bash -s' < "$0"
fi

hr() { printf '=== %s\n' "$1"; }

hr "kernel"
uname -r

hr "camcc"
ls -d /sys/bus/platform/devices/ad00000.clock-controller 2>/dev/null \
	&& echo "  bound: $(basename "$(readlink -f /sys/bus/platform/devices/ad00000.clock-controller/driver 2>/dev/null)")" \
	|| echo "  !! camcc device not present"

hr "titan_top / IFE power domains"
if [ -r /sys/kernel/debug/pm_genpd/pm_genpd_summary ]; then
	grep -iE 'titan|ife' /sys/kernel/debug/pm_genpd/pm_genpd_summary || echo "  (none listed)"
else
	echo "  (no genpd debugfs; CONFIG_DEBUG_FS or mount missing)"
fi

hr "CCI1 (camera i2c controller)"
for d in /sys/bus/platform/devices/ac50000.cci; do
	if [ -d "$d" ]; then
		echo "  device: $(basename "$d")"
		echo "  driver: $(basename "$(readlink -f "$d/driver" 2>/dev/null)" 2>/dev/null)"
	else
		echo "  !! ac50000.cci not present"
	fi
done
echo "  i2c adapters that are CCI masters:"
for a in /sys/class/i2c-adapter/i2c-*; do
	n=$(cat "$a/name" 2>/dev/null)
	case "$n" in
		*cci*|*Qualcomm*CCI*) echo "    $(basename "$a")  $n" ;;
	esac
done

hr "camss"
if [ -d /sys/bus/platform/devices/ac6a000.isp ]; then
	echo "  device: ac6a000.isp"
	echo "  driver: $(basename "$(readlink -f /sys/bus/platform/devices/ac6a000.isp/driver 2>/dev/null)" 2>/dev/null)"
else
	echo "  !! ac6a000.isp not present"
fi

hr "imx258 subdev"
found=0
for d in /sys/bus/i2c/devices/*; do
	[ -r "$d/name" ] || continue
	case "$(cat "$d/name")" in
		imx258*) found=1
			echo "  $(basename "$d")  name=$(cat "$d/name")"
			echo "    driver: $(basename "$(readlink -f "$d/driver" 2>/dev/null)" 2>/dev/null)"
			;;
	esac
done
[ "$found" = 0 ] && echo "  !! no imx258 i2c client bound"

hr "media / video devices"
ls -l /dev/media* /dev/video* /dev/v4l-subdev* 2>/dev/null || echo "  (none)"

hr "camera regulators"
for r in /sys/class/regulator/*/; do
	n=$(cat "$r/name" 2>/dev/null) || continue
	case "$n" in
		cam_*|*csi*)
			printf "  %-18s %8s uV  state=%s  use=%s\n" "$n" \
				"$(cat "$r/microvolts" 2>/dev/null)" \
				"$(cat "$r/state" 2>/dev/null)" \
				"$(cat "$r/num_users" 2>/dev/null)"
			;;
	esac
done

hr "MCLK1 rate (cam_cc_mclk1_clk)"
if [ -r /sys/kernel/debug/clk/clk_summary ]; then
	grep -E 'cam_cc_mclk1_clk|cam_cc_csiphy4|cam_cc_ife_0_clk ' \
		/sys/kernel/debug/clk/clk_summary || echo "  (not found)"
else
	echo "  (no clk debugfs)"
fi

hr "kernel log: camera"
journalctl -k --no-pager 2>/dev/null \
	| grep -iE 'camss|csiphy|csid|vfe|imx258|cci|camcc|titan' \
	| grep -viE 'handover' | tail -40
