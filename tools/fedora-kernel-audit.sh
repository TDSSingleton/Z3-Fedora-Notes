#!/usr/bin/env bash
# Audit a stock Fedora kernel config against what this phone needs.
#
#   ./tools/fedora-kernel-audit.sh [path/to/fedora/config]
#   ./tools/fedora-kernel-audit.sh --from-phone [<release>]
#
# With no argument it uses the newest config under kernel-work/fedora-configs/.
# --from-phone copies /usr/lib/modules/<release>/config off the device first
# (newest installed kernel-core if no release is given) and keeps it there.
#
# Why this exists: the plan for running Fedora's own kernel (docs/18) rests on
# every driver this phone needs being reachable as a MODULE. Fedora can change
# a symbol from m to n, or drop one, in any update. Re-run this before
# adopting a new kernel; a new line under BLOCKER or SHADOW is new work.
#
# Classification, against our own linux-fedora/.config:
#   ok       Fedora already builds it, =y or =m -- nothing to do
#   extra    Fedora does not build it, but the source is in-tree and the
#            symbol is tristate: we build it out-of-tree into extra/
#   shadow   Fedora builds it, but we carry a patch against it: our build
#            must take precedence (see /etc/depmod.d/fold3.conf)
#   BLOCKER  needed, not modular, and not something the loader can do for us
#   debug    we set it for diagnostics only; absence costs comfort, not boot
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OURS="$ROOT/linux-fedora/.config"
CFGDIR="$ROOT/kernel-work/fedora-configs"
PHONE="${FOLD3_SSH:-root@192.168.11.131}"
KEY="${FOLD3_KEY:-$HOME/.ssh/fold3_ed25519}"

# Drivers we patch: our build must win over Fedora's own module.
SHADOW="CONFIG_BATTERY_MAX17042 CONFIG_CHARGER_MAX77705 CONFIG_VIDEO_QCOM_CAMSS
        CONFIG_VIDEO_IMX258 CONFIG_USB_U_SERIAL"
# Drivers Fedora does not enable that we build from in-tree sources.
EXTRA="CONFIG_PINCTRL_SM8350 CONFIG_INTERCONNECT_QCOM_SM8350 CONFIG_SM_GPUCC_8350
       CONFIG_MFD_SEC_CORE CONFIG_MFD_SEC_I2C CONFIG_REGULATOR_S2DOS05"
# Must exist and be loadable or built in, or the phone does not come up.
CRITICAL="CONFIG_ARCH_QCOM CONFIG_QCOM_SCM CONFIG_PINCTRL_MSM CONFIG_COMMON_CLK_QCOM
          CONFIG_SM_GCC_8350 CONFIG_QCOM_RPMH CONFIG_REGULATOR_QCOM_RPMH
          CONFIG_QCOM_RPMHPD CONFIG_QCOM_COMMAND_DB CONFIG_QCOM_PDC CONFIG_QCOM_SMEM
          CONFIG_INTERCONNECT_QCOM_RPMH CONFIG_INTERCONNECT_QCOM_BCM_VOTER
          CONFIG_SCSI_UFSHCD CONFIG_SCSI_UFSHCD_PLATFORM CONFIG_SCSI_UFS_QCOM
          CONFIG_PHY_QCOM_QMP_UFS CONFIG_BLK_DEV_SD CONFIG_BTRFS_FS
          CONFIG_ARM64_4K_PAGES CONFIG_BLK_DEV_INITRD
          CONFIG_DRM_MSM CONFIG_DRM_MSM_DSI CONFIG_DRM_MSM_DPU CONFIG_SM_DISPCC_8250
          CONFIG_I2C_QCOM_GENI CONFIG_SPI_QCOM_GENI CONFIG_QCOM_GPI_DMA
          CONFIG_REMOTEPROC CONFIG_QCOM_Q6V5_PAS CONFIG_RPMSG_QCOM_GLINK_SMEM
          CONFIG_QCOM_SYSMON CONFIG_ATH11K CONFIG_ATH11K_PCI CONFIG_PCIE_QCOM
          CONFIG_POWER_SEQUENCING_QCOM_WCN CONFIG_USB_DWC3 CONFIG_USB_DWC3_QCOM
          CONFIG_USB_CONFIGFS CONFIG_USB_F_ACM CONFIG_USB_F_SERIAL CONFIG_USB_F_NCM
          CONFIG_USB_F_MASS_STORAGE CONFIG_CONFIGFS_FS CONFIG_DMABUF_HEAPS_CMA
          CONFIG_DMABUF_HEAPS_SYSTEM CONFIG_ARM_QCOM_CPUFREQ_HW CONFIG_QCOM_TSENS
          CONFIG_I2C_QCOM_CCI CONFIG_QCOM_SPMI_ADC5 CONFIG_MFD_MAX77705
          CONFIG_ARM_SMMU CONFIG_MEDIA_SUPPORT CONFIG_MEDIA_CONTROLLER"
# Comfort, not correctness.
DEBUG="CONFIG_PSTORE_RAM CONFIG_PSTORE_CONSOLE CONFIG_PSTORE_PMSG CONFIG_DETECT_HUNG_TASK
       CONFIG_WQ_WATCHDOG CONFIG_MAGIC_SYSRQ CONFIG_ATH11K_DEBUG CONFIG_FONTS
       CONFIG_DYNAMIC_DEBUG CONFIG_FTRACE CONFIG_KPROBES"
# Things whose presence is a HAZARD rather than a requirement.
HAZARD="CONFIG_QCOM_WDT CONFIG_SUSPEND CONFIG_HIBERNATION CONFIG_MODULE_SIG_FORCE
        CONFIG_KEXEC_SIG CONFIG_SECURITY_LOCKDOWN_LSM"

usage(){ sed -n '2,12p' "$0" | sed 's/^# \?//'; exit 1; }

FED=""
if [ "${1-}" = "--from-phone" ]; then
	rel="${2-}"
	if [ -z "$rel" ]; then
		rel=$(ssh -o IdentitiesOnly=yes -i "$KEY" "$PHONE" \
		      "rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core | sort -V | tail -1") \
		      || { echo "!! cannot reach $PHONE"; exit 1; }
	fi
	[ -n "$rel" ] || { echo "!! no kernel-core installed on the phone"; exit 1; }
	mkdir -p "$CFGDIR"
	FED="$CFGDIR/config-$rel"
	echo "== fetching $rel config from $PHONE"
	scp -q -o IdentitiesOnly=yes -i "$KEY" \
	    "$PHONE:/usr/lib/modules/$rel/config" "$FED" || exit 1
elif [ -n "${1-}" ]; then
	case "$1" in -h|--help) usage ;; esac
	FED="$1"
else
	FED=$(ls -1t "$CFGDIR"/config-* 2>/dev/null | head -1)
	[ -n "$FED" ] || { echo "!! no config given and none under $CFGDIR"; usage; }
fi
[ -f "$FED" ] || { echo "!! no such config: $FED"; exit 1; }
[ -f "$OURS" ] || { echo "!! our reference config is missing: $OURS
   run tools/build-kernel.sh (or setup-sources.sh) first"; exit 1; }

# Effective value of a symbol: kconfig takes the LAST setting in a file.
val(){ local v
	v=$(grep -E "^$2=" "$1" | tail -1 | cut -d= -f2-)
	if [ -n "$v" ]; then printf '%s' "$v"
	elif grep -qE "^# $2 is not set" "$1"; then printf 'n'
	else printf -- '--'; fi
}

echo "== ours   $OURS  ($(val "$OURS" CONFIG_LOCALVERSION))"
echo "== fedora $FED"
echo
printf '%-38s %-8s %-8s %s\n' SYMBOL OURS FEDORA VERDICT
printf '%-38s %-8s %-8s %s\n' "------" "----" "------" "-------"
blockers=0; news=0
emit(){ printf '%-38s %-8s %-8s %s\n' "$1" "$2" "$3" "$4"; }

for s in $CRITICAL; do
	o=$(val "$OURS" "$s"); f=$(val "$FED" "$s")
	case "$f" in
		y|m) [ "$o" = n ] || [ "$o" = -- ] && continue
		     emit "$s" "$o" "$f" "ok" ;;
		*)   # we need it; Fedora has it off or does not know it
		     if [ "$o" = n ] || [ "$o" = -- ]; then continue; fi
		     emit "$s" "$o" "$f" "BLOCKER -- needed, Fedora says $f"
		     blockers=$((blockers+1)) ;;
	esac
done
echo
for s in $EXTRA; do
	o=$(val "$OURS" "$s"); f=$(val "$FED" "$s")
	if [ "$f" = y ] || [ "$f" = m ]; then
		emit "$s" "$o" "$f" "ok now -- Fedora enabled it, drop from extra/"
	else
		emit "$s" "$o" "$f" "extra -- build out-of-tree"
	fi
done
echo
for s in $SHADOW; do
	o=$(val "$OURS" "$s"); f=$(val "$FED" "$s")
	case "$f" in
		m) emit "$s" "$o" "$f" "shadow -- ours must win in depmod order" ;;
		y) emit "$s" "$o" "$f" "BLOCKER -- patched driver is built into Fedora's kernel"
		   blockers=$((blockers+1)) ;;
		*) emit "$s" "$o" "$f" "extra -- Fedora does not build it at all" ;;
	esac
done
echo
for s in $HAZARD; do
	f=$(val "$FED" "$s")
	case "$s:$f" in
		CONFIG_QCOM_WDT:y|CONFIG_QCOM_WDT:m)
			emit "$s" "$(val "$OURS" "$s")" "$f" \
			"hazard -- our DT has no watchdog node, keep it that way" ;;
		CONFIG_SUSPEND:y|CONFIG_HIBERNATION:y)
			emit "$s" "$(val "$OURS" "$s")" "$f" \
			"hazard -- unrecoverable here, must be blocked in userspace" ;;
		CONFIG_MODULE_SIG_FORCE:y)
			emit "$s" "$(val "$OURS" "$s")" "$f" \
			"hazard -- our unsigned out-of-tree modules would be refused" ;;
		CONFIG_KEXEC_SIG:y)
			emit "$s" "$(val "$OURS" "$s")" "$f" \
			"note -- only bites if Fedora's kernel ever becomes the LOADER" ;;
		CONFIG_SECURITY_LOCKDOWN_LSM:y)
			emit "$s" "$(val "$OURS" "$s")" "$f" \
			"note -- inert while we do not boot via EFI secure boot" ;;
		*)      emit "$s" "$(val "$OURS" "$s")" "$f" "ok" ;;
	esac
done
echo
for s in $DEBUG; do
	o=$(val "$OURS" "$s"); f=$(val "$FED" "$s")
	[ "$o" = "$f" ] && continue
	[ "$o" = n ] || [ "$o" = -- ] && continue
	emit "$s" "$o" "$f" "debug -- lost comfort only"
done
echo
if [ "$blockers" != 0 ]; then
	echo "!! $blockers BLOCKER(s): this Fedora kernel cannot be driven by modules alone."
	echo "   Either the symbol has to be enabled in a rebuilt kernel, or the"
	echo "   feature is unavailable. See docs/18-fedora-kernel-updates.md."
	exit 2
fi
echo "no blockers: every symbol this phone needs is reachable as y/m or out-of-tree."
