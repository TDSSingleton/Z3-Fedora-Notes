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
