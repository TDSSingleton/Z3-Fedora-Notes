#!/usr/bin/env bash
# Turn the stock Fedora Mobile disk image into something that can boot on q2q.
#
#   ./tools/prep-rootfs.sh [path-to-Fedora-...raw.xz]
#
# Everything here runs as a NORMAL USER. libguestfs starts a small qemu
# appliance and edits the filesystem through that, so no loop mounts, no sudo,
# and no risk of touching the host's own disks. The appliance is x86_64 while
# the image is aarch64: that is fine for file operations, but it means we can
# never RUN anything from inside the image (guestfish's `command` will fail
# with "Exec format error"), so every change here is a file edit, not a
# chroot + dnf/systemctl.
#
# What the stock image assumes, and why each assumption breaks here:
#
#   1. /boot (p2, ext4) and /boot/efi (p1, vfat) exist.
#      We copy only p3, the rootfs, because our kernel comes from the Android
#      boot partition, not from /boot. Those two fstab lines have passno 0 and
#      no `nofail`, so systemd makes them required mounts, local-fs.target
#      never completes, and the boot ends in emergency mode after a 90 s wait.
#      -> commented out.
#
#   2. root's password is `!` (locked) and there is no user account at all;
#      plasma-setup.service creates the first user on first boot, graphically.
#      A locked root means the serial console offers a login prompt nothing can
#      satisfy. Separately, the `plasma-setup` account's password-change date is
#      in the FUTURE relative to this device's stale clock (no RTC driver
#      exists), so PAM refuses it and the wizard never starts.
#      -> root password set; plasma-setup's sp_lstchg pinned to the past;
#         plasma-setup LEFT ENABLED.
#
#   3. default.target is graphical.target.
#      This was forced to multi-user.target while it was still unproven that
#      systemd even came up. That is settled now -- Plasma Mobile and the setup
#      wizard both run (2026-11-11) -- so the stock default is correct and the
#      override is gone.
#      -> left as graphical.target.
#
#   3b. plasma-setup-bootutil configures autologin in *SDDM* paths, but this
#      image's display manager is plasmalogin, SDDM's replacement, which never
#      reads them. The wizard is not drawn by the service at all: it runs from
#      an autostart entry in the plasma-setup user's home, so the display
#      manager only has to autologin that user.
#      -> /etc/plasmalogin.conf.d/10-plasma-setup.conf written here.
#
#   3c. zram-generator wants a /dev/zram0 our kernel cannot provide, costing a
#      45-52 s dead wait on dev-zram0.device every boot.
#      -> empty /etc/systemd/zram-generator.conf, which is the documented
#         off-switch.
#
#   3d. Suspend is unrecoverable here: no wakeup source exists (no pwrkey
#      bound, and dwc3 has no VBUS awareness so the gadget never comes back).
#      powerdevil idle-suspended a live session on 2026-11-11 and the device
#      had to be hard-reset. The kernel also builds CONFIG_SUSPEND=n.
#      -> sleep/suspend/hibernate targets masked, logind IdleAction=ignore.
#
#   4. ModemManager is enabled, and it AT-probes every serial device it finds.
#      One of those is /dev/ttyGS0 -- our console, and currently our only way
#      of talking to the phone at all.
#      -> disabled.
#
#   5. SELINUX=enforcing. Our kernel has no SELinux support compiled in, so
#      this is inert today, but the files we write here get no security labels
#      and a later kernel that DOES have SELinux would refuse to boot on them.
#      -> permissive, which degrades instead of locking us out.
#
# Left deliberately alone: x-systemd.growfs on /. The image's filesystem is
# 9.28 GiB and the partition is 190.5 GiB; systemd-growfs expands it on first
# boot by itself, so there is no manual resize step.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
XZ="${1:-$ROOT/Fedora-KDE-Mobile-Disk-45-1.4.aarch64.raw.xz}"
W="$ROOT/rootfs-work"
IMG="$W/fedora-mobile/p3-root.btrfs"
STAGE="$W/stage"
MODS="$W/modules-stage"
ROOTPW="${ROOTPW:-fold3}"
export LIBGUESTFS_BACKEND=direct

# p3's offset and length come from the image's MBR. Hardcoded after reading it
# once; re-derive with `file` on the first sector if the image is ever updated.
P3_OFF=2639265792
P3_LEN=9965666304

mkdir -p "$W/fedora-mobile" "$STAGE"

if [ ! -s "$IMG" ] || [ "$(stat -c%s "$IMG")" != "$P3_LEN" ]; then
	[ -f "$XZ" ] || { echo "!! no image: $XZ"; exit 1; }
	echo "extracting p3 (rootfs) from $(basename "$XZ") ..."
	# dd, not `tail -c +N | head -c M`: that pipeline silently truncated at a
	# few GiB. Also note xz -T0 -- single-threaded this step takes minutes.
	xz -T0 -dc "$XZ" | dd bs=1M iflag=skip_bytes,count_bytes,fullblock \
		skip="$P3_OFF" count="$P3_LEN" of="$IMG" status=none || exit 1
fi
got="$(stat -c%s "$IMG")"
[ "$got" = "$P3_LEN" ] || { echo "!! p3 is $got bytes, expected $P3_LEN"; exit 1; }
echo "rootfs image: $IMG ($(( got / 1024 / 1024 )) MiB)"

echo "editing the image ..."
guestfish --ro -a "$IMG" >/dev/null 2>&1 <<EOF
run
mount-options subvol=root /dev/sda /
download /etc/fstab $STAGE/fstab.orig
download /etc/shadow $STAGE/shadow.orig
download /etc/selinux/config $STAGE/selinux.orig
EOF
[ -s "$STAGE/fstab.orig" ] || { echo "!! could not read the image"; exit 1; }

sed -E 's|^(UUID=[^ ]+ /boot ext4 .*)$|# [q2q] p2 is not copied to the phone:\n#\1|
        s|^(UUID=[^ ]+ /boot/efi vfat .*)$|# [q2q] p1 is not copied to the phone:\n#\1|' \
	"$STAGE/fstab.orig" > "$STAGE/fstab.new"
HASH="$(openssl passwd -6 "$ROOTPW")" || exit 1
# The `plasma-setup` account's sp_lstchg in the stock image is a date in the
# FUTURE relative to this device's clock, because there is no RTC driver at all
# (/sys/class/rtc/ is empty) and the clock boots stale. PAM then refuses the
# account -- "account plasma-setup has password changed in future" -- and
# plasmalogin idles forever without ever starting the setup wizard. Pinning the
# date to the past fixes it regardless of what the clock says, which `date -s`
# does not: that has to be redone on every boot.
PWDAYS=$(( $(date -u -d 2024-01-01 +%s) / 86400 ))
awk -v h="$HASH" -v d="$PWDAYS" -F: 'BEGIN{OFS=":"} $1=="root"{$2=h} $1=="plasma-setup"{$3=d} {print}' \
	"$STAGE/shadow.orig" > "$STAGE/shadow.new"
sed 's/^SELINUX=enforcing/SELINUX=permissive/' "$STAGE/selinux.orig" > "$STAGE/selinux.new"

MODARG=""
if [ -f "$MODS/release.env" ]; then
	. "$MODS/release.env"
	if [ -d "$MODS/lib/modules/$KERNELRELEASE" ]; then
		tar -C "$MODS" -cf "$STAGE/modules.tar" "lib/modules/$KERNELRELEASE"
		MODARG="yes"
		echo "  will install /lib/modules/$KERNELRELEASE"
	fi
fi

# Never let userspace ask for suspend. There is no wakeup source on this device
# (no pwrkey bound, and dwc3 has no VBUS awareness so the gadget never returns),
# so a suspend is unrecoverable and looks like "the phone switched itself off
# forever". KDE's powerdevil did exactly this on 2026-11-11. The kernel also
# builds with CONFIG_SUSPEND=n; this is the userspace belt to that braces.
# Power key: nothing on a short press, poweroff on a long one (logind's
# threshold is a fixed 5s).
#
# PowerKeyIgnoreInhibited=yes is REQUIRED, not optional. PowerDevil holds a
# *block* inhibitor on handle-power-key for the whole session:
#   PowerDevil ... handle-power-key:handle-suspend-key:...:handle-lid-switch block
# so without it every HandlePowerKey* setting here is a dead letter and logind
# never sees the key at all.
printf '[Login]\nIdleAction=ignore\nHandlePowerKey=ignore\nHandlePowerKeyLongPress=poweroff\nPowerKeyIgnoreInhibited=yes\nHandleLidSwitch=ignore\nHandleLidSwitchDocked=ignore\n' \
	> "$STAGE/logind-no-suspend.conf"

# plasma-setup-bootutil writes autologin into *SDDM* paths, but this image's
# display manager is plasmalogin (SDDM's replacement) and never reads them, so
# the greeter comes up instead of the first-run wizard. Configure it directly.
#
# IMPORTANT: this is correct only until the wizard is finished. It pins the
# session to the `plasma-setup` account, so once setup completes you keep
# booting into the already-done welcome screen forever -- it looks exactly like
# the wizard failing to record completion, but plasma-setup.service is in fact
# being skipped properly on ConditionPathExists=!/etc/plasma-setup-done. After
# first setup, repoint it at the account the wizard created:
#
#   printf '[Autologin]\nUser=<name>\nSession=plasma-mobile.desktop\n' \
#       > /etc/plasmalogin.conf.d/10-plasma-setup.conf
#
# and run `chage -d 2026-01-01 <name>`: the wizard stamps the new account's
# sp_lstchg with the (wrong, RTC-less) boot clock, so if a later boot lands even
# one day earlier, PAM rejects the login with "password changed in the future"
# -- the same trap that blocked plasma-setup itself. See HANDBOOK section 13.
printf '[Autologin]\nUser=plasma-setup\nSession=plasma-mobile.desktop\n' \
	> "$STAGE/plasmalogin-autologin.conf"

# Stop powerdevil blanking the panel (and from ever asking to suspend).
#
# Masking the systemd sleep targets does NOT cover this: turning the display
# off is a separate powerdevil action, and it fired after ~10 minutes idle on
# 2026-11-11, leaving the DRM connector at dpms=Off / enabled=disabled with
# the device otherwise healthy. It looks exactly like the phone died, and
# nothing short of DRM master can undo it:
#   kscreen-doctor --dpms on   (needs WAYLAND_DISPLAY and QT_QPA_PLATFORM)
#
# Touch does wake it normally, but during bringup the screen must not go dark
# on its own. Large idle times rather than 0, because "0" is ambiguous between
# "disabled" and "immediately" in powerdevil's config.
#
# plasma-setup's home is /run/plasma-setup, a tmpfs created at runtime, so this
# cannot simply be dropped in the image -- it is installed as a system-wide
# default under /etc/xdg instead, which KConfig reads for every user.
{
	for prof in AC Battery LowBattery; do
		printf '[%s][DPMSControl]\nidleTime=86400\nlockBeforeTurnOff=0\n\n' "$prof"
		printf '[%s][DimDisplay]\nidleTime=86400\n\n' "$prof"
		printf '[%s][SuspendSession]\nidleTime=86400\nsuspendType=0\n\n' "$prof"
	done
} > "$STAGE/powermanagementprofilesrc"

# Autoload the inner-display touchscreen driver.
#
# fts9cu80f is an out-of-tree module (touch-work/), so nothing pulls it in by
# itself: the SPI device is instantiated from DT and sits there driverless
# until the module is present. modules-load.d is enough -- once loaded, the
# driver binds the already-registered spi0.0 device.
printf 'fts9cu80f\n' > "$STAGE/fold3-touch.conf"

# ...and stop PowerDevil acting on the short press itself. Plasma 6 has no
# `powerButtonAction` key: the power button runs through kglobalaccel, where
# Plasma Mobile ships it bound to PowerDevil's PowerOff action
#   PowerOff=Power Off,none,Power Off      <- active,default,friendly
# Unbinding it leaves logind as the only actor. This is a /etc/xdg default, so
# it applies to accounts created later; kglobalaccel rewrites the per-user copy
# once a session has run, and the change only takes effect at next login.
printf '[org_kde_powerdevil]\nPowerOff=none,none,Power Off\n' \
	> "$STAGE/kglobalshortcutsrc"

guestfish -a "$IMG" <<EOF >/dev/null || { echo "!! guestfish edit failed"; exit 1; }
run
mount-options subvol=root /dev/sda /
upload $STAGE/fstab.new /etc/fstab
upload $STAGE/shadow.new /etc/shadow
chmod 0000 /etc/shadow
upload $STAGE/selinux.new /etc/selinux/config
rm-f /etc/systemd/system/default.target
ln-sf /usr/lib/systemd/system/graphical.target /etc/systemd/system/default.target
rm-f /etc/systemd/system/multi-user.target.wants/ModemManager.service
rm-f /etc/systemd/system/multi-user.target.wants/vmtoolsd.service
mkdir-p /etc/systemd/system/getty.target.wants
ln-sf /usr/lib/systemd/system/serial-getty@.service /etc/systemd/system/getty.target.wants/serial-getty@ttyGS0.service
touch /etc/systemd/zram-generator.conf
ln-sf /dev/null /etc/systemd/system/sleep.target
ln-sf /dev/null /etc/systemd/system/suspend.target
ln-sf /dev/null /etc/systemd/system/hibernate.target
ln-sf /dev/null /etc/systemd/system/hybrid-sleep.target
ln-sf /dev/null /etc/systemd/system/suspend-then-hibernate.target
mkdir-p /etc/systemd/logind.conf.d
upload $STAGE/logind-no-suspend.conf /etc/systemd/logind.conf.d/10-fold3-no-suspend.conf
mkdir-p /etc/plasmalogin.conf.d
upload $STAGE/plasmalogin-autologin.conf /etc/plasmalogin.conf.d/10-plasma-setup.conf
mkdir-p /etc/xdg
upload $STAGE/powermanagementprofilesrc /etc/xdg/powermanagementprofilesrc
mkdir-p /etc/modules-load.d
upload $STAGE/fold3-touch.conf /etc/modules-load.d/fold3-touch.conf
upload $STAGE/kglobalshortcutsrc /etc/xdg/kglobalshortcutsrc
EOF

if [ -n "$MODARG" ]; then
	guestfish -a "$IMG" <<EOF >/dev/null || { echo "!! module install failed"; exit 1; }
run
mount-options subvol=root /dev/sda /
mkdir-p /lib/modules
tar-in $STAGE/modules.tar /
EOF
fi

echo
echo "=== prepared ==="
guestfish --ro -a "$IMG" <<EOF 2>&1 | sed 's/^/  /'
run
mount-options subvol=root /dev/sda /
readlink /etc/systemd/system/default.target
ls /lib/modules
EOF
echo
echo "root password: $ROOTPW"
echo "next: ./tools/install-rootfs.sh   (writes it to sda37 over adb, ~4 min)"
