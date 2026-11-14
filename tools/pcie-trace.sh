#!/bin/sh
# Measure the QCA6490 PCIe bring-up ordering ON THE DEVICE.
#
#   tools/dev.py put tools/pcie-trace.sh /root/pcie-trace.sh
#   tools/dev.py run 'sh /root/pcie-trace.sh'
#
# Why this exists: the first WiFi attempt could only INFER the ordering of
# pwrseq's power-on against qcom-pcie's PERST pulse, because FTRACE and
# KPROBE_EVENTS were off. See "Hard Truths/12-wifi-qca6490.md" section 9.
#
# The question it answers: does the endpoint get >=100 ms of stable rails
# before PERST# is released? Nothing in the kernel enforces that gap, and it
# is hypothesis 1 for "root port enumerates, endpoint never trains".
set -u
T=/sys/kernel/debug/tracing
[ -d "$T" ] || { echo "!! no tracefs -- FTRACE/KPROBE_EVENTS not built in"; exit 1; }

echo "=== rail voltages (the pinned one should read 1012000)"
for r in /sys/kernel/debug/regulator/*; do
	n=$(basename "$r")
	case "$n" in
	pmr735a_s2|pm8350_s10|pm8350_s11|pm8350_s12|pm8350c_s1)
		printf "  %-14s voltage=%s enabled=%s\n" "$n" \
			"$(cat "$r/voltage" 2>/dev/null)" \
			"$(cat "$r/enable" 2>/dev/null || cat "$r/use_count" 2>/dev/null)"
		;;
	esac
done

echo "=== link state"
printf "  LnkSta = 0x%s   (0x1011 = DLActive 0, LinkTraining 0 = no endpoint)\n" \
	"$(setpci -s 00:00.0 CAP_EXP+12.w 2>/dev/null)"
printf "  perst gpio94 / wlan-en gpio64:\n"
grep -E "gpio-(64|94|95|96|153)\b" /sys/kernel/debug/gpio 2>/dev/null | sed 's/^/    /'

echo "=== arming trace"
echo 0 > $T/tracing_on
echo > $T/trace
echo nop > $T/current_tracer
# Function tracer over the two subsystems whose relative order is the question.
echo 'qcom_pcie_* dw_pcie_* pwrseq_* pci_pwrctrl_*' > $T/set_ftrace_filter 2>/dev/null
echo function > $T/current_tracer
echo 1 > $T/tracing_on

echo "=== forcing a re-bringup (unbind/rebind the host)"
D=/sys/bus/platform/drivers/qcom-pcie
if [ -e "$D/1c00000.pcie" ]; then
	echo 1c00000.pcie > $D/unbind 2>&1
	sleep 1
	echo 1c00000.pcie > $D/bind 2>&1
	sleep 3
fi
echo 0 > $T/tracing_on

echo "=== trace (first 120 lines, timestamps are what matter)"
head -120 $T/trace

echo "=== link state after"
printf "  LnkSta = 0x%s\n" "$(setpci -s 00:00.0 CAP_EXP+12.w 2>/dev/null)"
lspci 2>&1 | sed 's/^/  /'
