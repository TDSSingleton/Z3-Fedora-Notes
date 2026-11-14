#!/bin/bash
# Build a static aarch64 busybox and pack the Stage-1b initramfs.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/initramfs-work/busybox-src"
# Fedora puts the cross sysroot here. /usr/aarch64-linux-gnu/sys-root is an
# empty stub owned by binutils/gcc-aarch64-linux-gnu -- do not use it.
SYSROOT=/usr/aarch64-redhat-linux/sys-root/fc44
OUT="$ROOT/initramfs-work/initramfs.cpio.gz"

[ -d "$SYSROOT/usr/include" ] || { echo "!! missing $SYSROOT -- run: sudo dnf install sysroot-aarch64-fc44-glibc"; exit 1; }

# -DLONG_BIT=64: busybox 1.36.1 networking/tls_aesgcm.c uses LONG_BIT without
# including <limits.h>, and newer glibc no longer leaks it in. 64 is correct
# for aarch64 (bits in a long).
# -fno-link-libatomic: Fedora's cross-gcc specs add -latomic_asneeded, which
# does not exist in the sysroot, so every static link fails without this.
CF="--sysroot=$SYSROOT -DLONG_BIT=64"
# (LDFLAGS live in busybox .config as CONFIG_EXTRA_LDFLAGS -- LDFLAGS_EXTRA
#  on the make line is silently ignored for the final link.)

echo "building busybox (static, aarch64) ..."
make -C "$SRC" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- CONFIG_SYSROOT="$SYSROOT" CFLAGS_EXTRA="$CF" -j"$(nproc)" >/dev/null 2>"$ROOT/initramfs-work/busybox-build.log" \
  || { echo "!! build failed:"; grep -iE ': error:|Error [0-9]' "$ROOT/initramfs-work/busybox-build.log" | head -8; exit 1; }

BB="$SRC/busybox"
[ -s "$BB" ] || { echo "!! no busybox binary"; exit 1; }
aarch64-linux-gnu-strip "$BB" 2>/dev/null
file "$BB" | grep -q 'statically linked' || { echo "!! busybox is NOT static -- it will not run"; exit 1; }
printf "  busybox: %s bytes, %s applets\n" "$(stat -c%s "$BB")" "$("$SRC/busybox" --list 2>/dev/null | wc -l)"

echo "packing initramfs ..."
GEN="$ROOT/linux-fedora/usr/gen_init_cpio"
[ -x "$GEN" ] || ( cd "$ROOT/linux-fedora" && make -s usr/gen_init_cpio )

SPEC="$ROOT/initramfs-work/initramfs-bb.spec"
{
	echo "dir /dev 0755 0 0"
	echo "nod /dev/console 0600 0 0 c 5 1"
	echo "nod /dev/null    0666 0 0 c 1 3"
	echo "nod /dev/zero    0666 0 0 c 1 5"
	echo "nod /dev/tty     0666 0 0 c 5 0"
	echo "nod /dev/tty0    0620 0 0 c 4 0"
	echo "nod /dev/tty1    0620 0 0 c 4 1"
	echo "dir /proc 0755 0 0"
	echo "dir /sys  0755 0 0"
	echo "dir /tmp  1777 0 0"
	echo "dir /run  0755 0 0"
	echo "dir /bin  0755 0 0"
	echo "dir /sbin 0755 0 0"
	echo "dir /usr  0755 0 0"
	echo "dir /usr/bin  0755 0 0"
	echo "dir /usr/sbin 0755 0 0"
	echo "file /bin/busybox $BB 0755 0 0"
	echo "file /init $ROOT/initramfs-work/init.sh 0755 0 0"
	# the handful of applet symlinks /init itself needs before 'sh' takes over
	for a in sh ash mount umount mkdir cat echo ls uname grep awk cut sleep reboot poweroff dmesg mknod; do
		echo "slink /bin/$a /bin/busybox 0777 0 0"
	done
} > "$SPEC"
"$GEN" "$SPEC" | gzip -9 > "$OUT"
printf "  initramfs: %s bytes (%.2f MiB)\n" "$(stat -c%s "$OUT")" "$(echo "scale=2;$(stat -c%s "$OUT")/1048576"|bc)"
