#!/bin/sh
# Stage 4 init: mount the real Fedora root on sda37 and hand over to systemd.
#
# Why this is a userspace step at all: our initramfs is embedded inside
# uniLoader, so the kernel always unpacks it and runs THIS file. It never looks
# at root= on the command line. The pivot has to happen here.
#
# Every failure path below ends in a busybox shell rather than a reboot or a
# panic. On this device a reboot drops the USB gadget and needs a physical
# cable replug, so an unexplained reboot loop is genuinely expensive. A shell
# on ttyGS0 with a diagnostic printed above it is worth far more.

ROOTDEV=/dev/sda37
SUBVOL=root

/bin/busybox mkdir -p /proc /sys /dev /tmp /run /newroot
/bin/busybox mount -t proc     proc     /proc 2>/dev/null
/bin/busybox mount -t sysfs    sysfs    /sys  2>/dev/null
/bin/busybox mount -t devtmpfs devtmpfs /dev  2>/dev/null
/bin/busybox mount -t tmpfs    tmpfs    /tmp  2>/dev/null

# ---------------------------------------------------------------------------
# USB composite gadget (2026-11-16). This replaces the legacy built-in
# g_serial driver, which is now CONFIG_USB_G_SERIAL=n.
#
# Why here and not in the rootfs: whichever gadget driver reaches the UDC
# first owns it, and swapping it on a RUNNING system is not an option -- a
# live unbind oopses and wedges every process holding ttyGS0 (HANDBOOK 20).
# So the composite must exist before anything opens the console, which means
# before switch_root.
#
# Two functions, always present together:
#   acm.0  the console, ttyGS0 -- byte-for-byte what g_serial gave us
#   ncm.0  USB networking, a second way in when WiFi is down
#
# The UDC is bound HERE, in the initramfs, and that is the point: it is what
# gives the bail-out shell below a working serial console. Anything that has
# to be added to this gadget later cannot be, without unbinding it first --
# see HANDBOOK 36.5 for why that rules out putting MTP in here.
#
# mass_storage was here and was removed: it is a block protocol, so it can
# only export a whole filesystem image, never a folder.
# ---------------------------------------------------------------------------
usb_gadget_up() {
	CFG=/sys/kernel/config
	/bin/busybox mkdir -p "$CFG" 2>/dev/null
	/bin/busybox mount -t configfs none "$CFG" 2>/dev/null
	[ -d "$CFG/usb_gadget" ] || return 1

	G="$CFG/usb_gadget/fold3"
	/bin/busybox mkdir -p "$G" 2>/dev/null || return 1

	# 1d6b:0104 is the Linux Foundation's "Multifunction Composite Gadget".
	echo 0x1d6b > "$G/idVendor"
	echo 0x0104 > "$G/idProduct"
	echo 0x0200 > "$G/bcdUSB"
	echo 0x0100 > "$G/bcdDevice"
	/bin/busybox mkdir -p "$G/strings/0x409"
	echo "Samsung"                    > "$G/strings/0x409/manufacturer"
	echo "Galaxy Z Fold 3 (mainline)" > "$G/strings/0x409/product"
	echo "fold3-q2q-0001"             > "$G/strings/0x409/serialnumber"

	/bin/busybox mkdir -p "$G/functions/acm.0" 2>/dev/null

	if /bin/busybox mkdir -p "$G/functions/ncm.0" 2>/dev/null; then
		# Fixed, locally-administered MACs: a random one every boot makes
		# the host invent a new interface name each time.
		echo 02:f0:1d:03:00:01 > "$G/functions/ncm.0/dev_addr"  2>/dev/null
		echo 02:f0:1d:03:00:02 > "$G/functions/ncm.0/host_addr" 2>/dev/null
	fi

	/bin/busybox mkdir -p "$G/configs/c.1/strings/0x409"
	echo "console + storage + network" > "$G/configs/c.1/strings/0x409/configuration"
	echo 500 > "$G/configs/c.1/MaxPower"
	for f in acm.0 ncm.0; do
		[ -d "$G/functions/$f" ] || continue
		/bin/busybox ln -sf "$G/functions/$f" "$G/configs/c.1/$f" 2>/dev/null
	done

	UDC="$( /bin/busybox ls /sys/class/udc 2>/dev/null | /bin/busybox head -n1 )"
	[ -n "$UDC" ] || return 1
	echo "$UDC" > "$G/UDC" 2>/dev/null || return 1
	return 0
}

if usb_gadget_up; then
	echo "fold3: USB composite gadget up (acm + ncm)" > /dev/kmsg 2>/dev/null
	# Give the ACM port a moment to register before the banner goes to it,
	# otherwise the first lines land only on tty0.
	/bin/busybox sleep 1
else
	echo "fold3: USB composite gadget FAILED -- no ttyGS0 this boot, use ssh over WiFi" > /dev/kmsg 2>/dev/null
fi

echo
echo "==============================================================="
echo "  Galaxy Z Fold 3 (SM-F926B / q2q)  --  mainline Linux"
echo "  $( /bin/busybox uname -srm )"
echo "  stage 4: handing off to the real root filesystem"
echo "==============================================================="
echo

bail() {
	echo
	echo "!! $1"
	echo "!! staying in the initramfs. Block devices the kernel found:"
	/bin/busybox ls /dev/sd* 2>/dev/null || echo "   (none -- UFS did not probe at all)"
	echo
	exec /bin/busybox sh
}

# UFS probes asynchronously: the node does not exist the moment init starts.
n=0
while [ ! -b "$ROOTDEV" ]; do
	n=$(( n + 1 ))
	[ "$n" -gt 30 ] && break
	[ "$n" = 1 ] && printf "waiting for %s " "$ROOTDEV"
	printf "."
	/bin/busybox sleep 1
done
[ "$n" -gt 1 ] && echo

[ -b "$ROOTDEV" ] || bail "$ROOTDEV never appeared after 30s"

echo "mounting $ROOTDEV (btrfs, subvol=$SUBVOL) ..."
/bin/busybox mount -t btrfs -o rw,subvol="$SUBVOL",compress=zstd:1 "$ROOTDEV" /newroot \
	|| bail "mount failed -- is BTRFS_FS built in, and is the image written?"

# ---------------------------------------------------------------------------
# Chainloader (2026-11-13). This kernel + initramfs are embedded in boot.img
# and cannot change without a flash. Kernels under /boot/fold3 can: this
# kernel kexecs into one of them, reusing its own device tree.
#
#   /boot/fold3/entries/<name>/{Image,initramfs,cmdline}
#   /boot/fold3/next      one line, an entry name: booted ONCE, file removed first
#   /boot/fold3/default   one line, an entry name: booted every time
#   /boot/fold3/pending   written before jumping to the default entry; the
#                         booted system deletes it once it is up
#                         (fold3-boot-ok.service). Still there on the next
#                         boot = that kernel never came up: the default is
#                         renamed to default.failed and this embedded kernel
#                         boots instead. A bad kernel costs ONE forced reboot.
#
# /chained exists only in initramfs images handed to a chainloaded kernel:
# never chainload from there (it would loop).
# ---------------------------------------------------------------------------
CL=/newroot/boot/fold3
PICK=""; MODE=""
if [ ! -e /chained ] && [ -d "$CL/entries" ]; then
	if [ -f "$CL/next" ]; then
		PICK="$( /bin/busybox head -n1 "$CL/next" )"; MODE=once
		/bin/busybox rm -f "$CL/next"
	elif [ -f "$CL/default" ]; then
		if [ -e "$CL/pending" ]; then
			echo "!! chainload: '$( /bin/busybox head -n1 "$CL/pending" )' never confirmed its last boot -- disabling it"
			/bin/busybox mv -f "$CL/default" "$CL/default.failed"
			/bin/busybox rm -f "$CL/pending"
		else
			PICK="$( /bin/busybox head -n1 "$CL/default" )"; MODE=default
		fi
	fi
	/bin/busybox sync
fi
E="$CL/entries/$PICK"
if [ -n "$PICK" ] && [ -f "$E/Image" ]; then
	echo "chainload: entry '$PICK' ($MODE)"
	IRD=-; [ -f "$E/initramfs" ] && IRD="$E/initramfs"
	CMD="$( /bin/busybox cat "$E/cmdline" 2>/dev/null )"
	if /bin/kexec-load "$E/Image" "$IRD" "$CMD"; then
		[ "$MODE" = default ] && echo "$PICK" > "$CL/pending"
		echo "fold3: chainloading entry $PICK ($MODE)" > /dev/kmsg
		/bin/busybox sync
		/bin/busybox umount /newroot
		# The GPI DMA driver has no shutdown hook: channels this kernel
		# allocated stay allocated in the hardware, and the next kernel's
		# "EV ALLOCATE" then times out -- no DMA, so no touchscreen (seen
		# on the first chainload). Unbinding the GENI consumers makes
		# them release their channels properly before the jump.
		for drv in geni_spi geni_i2c; do
			for d in /sys/bus/platform/drivers/$drv/*.spi /sys/bus/platform/drivers/$drv/*.i2c; do
				[ -e "$d" ] && echo "${d##*/}" > "/sys/bus/platform/drivers/$drv/unbind"
			done
		done
		/bin/kexec-load exec
		echo "!! kexec did not happen; continuing with the embedded kernel"
		/bin/busybox mount -t btrfs -o rw,subvol="$SUBVOL",compress=zstd:1 "$ROOTDEV" /newroot \
			|| bail "remount after failed kexec failed"
		/bin/busybox rm -f "$CL/pending"
	else
		echo "!! chainload: could not load '$PICK'; continuing with the embedded kernel"
	fi
elif [ -n "$PICK" ]; then
	echo "!! chainload: entry '$PICK' has no Image; continuing with the embedded kernel"
fi
[ -e /chained ] && echo "fold3: this is a CHAINLOADED kernel" > /dev/kmsg

INIT=/sbin/init
[ -e "/newroot$INIT" ] || INIT=/usr/lib/systemd/systemd
[ -e "/newroot$INIT" ] || bail "mounted, but no init inside: $( /bin/busybox ls /newroot )"

# Carry the API filesystems over instead of letting systemd re-mount them.
# /dev matters most: systemd logs to /dev/console long before it would mount
# devtmpfs itself, and losing that window loses the only output we have.
for m in dev proc sys; do
	/bin/busybox mkdir -p "/newroot/$m"
	/bin/busybox mount -o move "/$m" "/newroot/$m" 2>/dev/null
done

echo "switch_root -> $ROOTDEV subvol=$SUBVOL, init=$INIT"
echo
/bin/busybox sync
exec /bin/busybox switch_root /newroot "$INIT" \
	|| bail "switch_root itself failed"
