#!/usr/bin/env bash
# Build the Stage-1 initramfs.
#
# Stage 1a (default): freestanding static /init, no libc, ~2 KB. Answers only
#   "did the kernel reach userspace?" -- minimum surface for anything else to
#   go wrong.
# Stage 1b (--busybox): adds a real shell. Needs the aarch64 sysroot:
#   sudo dnf install sysroot-aarch64-fc44-glibc
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
W="$ROOT/initramfs-work"
OUT="$W/initramfs.cpio.gz"
MODE="${1:-minimal}"

cd "$W"
[ -f init.c ] || { echo "!! no init.c"; exit 1; }

echo "building freestanding init ..."
aarch64-linux-gnu-gcc -nostdlib -static -ffreestanding -Os -Wall -Wextra \
	-Wl,-z,max-page-size=4096 -Wl,--build-id=none -o init init.c || exit 1
aarch64-linux-gnu-strip init

rm -rf root && mkdir -p root/{dev,proc,sys,tmp}
cp init root/init
chmod 755 root/init

if [ "$MODE" = "--busybox" ]; then
	SYSROOT=/usr/aarch64-redhat-linux/sys-root/fc44
	[ -f "$SYSROOT/usr/lib64/libc.a" ] || {
		echo "!! need the target sysroot: sudo dnf install sysroot-aarch64-fc44-glibc"; exit 1; }
	[ -d busybox-src ] || { echo "!! busybox-src/ missing"; exit 1; }
	echo "building static busybox against $SYSROOT ..."
	( cd busybox-src
	  export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
	  export CFLAGS="--sysroot=$SYSROOT" LDFLAGS="--sysroot=$SYSROOT"
	  make -j"$(nproc)" busybox >/dev/null 2>&1 ) || { echo "!! busybox build failed"; exit 1; }
	install -Dm755 busybox-src/busybox root/bin/busybox
	aarch64-linux-gnu-strip root/bin/busybox
	( cd root && for a in sh ls cat mount umount dmesg ip ifconfig poweroff reboot \
	                      mkdir echo sleep ps free df cut grep sed; do ln -sf /bin/busybox bin/$a; done )
	# a shell-based init that still prints the banner, then drops to a shell
	mv root/init root/init.static
	cat > root/init <<'INIT'
#!/bin/sh
/init.static &
BANNER=$!
mount -t proc  proc  /proc  2>/dev/null
mount -t sysfs sysfs /sys   2>/dev/null
mount -t devtmpfs dev /dev  2>/dev/null
kill $BANNER 2>/dev/null
echo
echo "=== q2q stage-1b: busybox shell ==="
uname -a
echo
exec /bin/sh
INIT
	chmod 755 root/init
fi

# Build with gen_init_cpio, not `find | cpio`.
#
# cpio can only archive device nodes that already exist on disk, which needs
# root. gen_init_cpio takes a spec file and synthesises them, so we can create
# /dev/console unprivileged. That node is not optional: without it the kernel
# cannot give init stdin/stdout/stderr and every write() is silently dropped.
GEN="$ROOT/linux-fedora/usr/gen_init_cpio"
[ -x "$GEN" ] || { ( cd "$ROOT/linux-fedora" && make -s usr/gen_init_cpio ) || \
	{ echo "!! could not build gen_init_cpio"; exit 1; }; }

SPEC="$W/initramfs.spec"
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
	for f in $(cd root && find . -type f | sed 's|^\./||' | sort); do
		m=755
		case "$f" in init|init.static|bin/*) m=755 ;; *) m=644 ;; esac
		echo "file /$f $W/root/$f 0$m 0 0"
	done
	for l in $(cd root && find . -type l | sed 's|^\./||' | sort); do
		echo "slink /$l $(readlink "root/$l") 0777 0 0"
	done
} > "$SPEC"
"$GEN" "$SPEC" | gzip -9 > "$OUT"
echo
printf "initramfs: %s\n  %s bytes (%.1f KiB)  mode=%s\n" "$OUT" "$(stat -c%s "$OUT")" \
       "$(echo "scale=1;$(stat -c%s "$OUT")/1024"|bc)" "$MODE"
echo "  contents:"
gzip -dc "$OUT" | cpio -t --quiet 2>/dev/null | sed 's/^/    /' | head -30
