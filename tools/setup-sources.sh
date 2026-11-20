#!/usr/bin/env bash
# Recreate everything the repository deliberately does not track: the kernel
# and uniLoader trees with our changes applied, the busybox source, and the
# small static helpers that go into the initramfs.
#
#   ./tools/setup-sources.sh [all|kernel|uniloader|busybox|lrzsz|kexec-load|diag]...
#
# Each step is skipped when its result already exists, so it is safe to re-run.
# Pinned versions (override the URLs to use a local mirror):
#   kernel     stable v7.2.15          LINUX_URL
#   uniLoader  commit 5d3c7f1          UNILOADER_URL
#   busybox    1.36.1 (sha256 below)   BUSYBOX_URL
# Host needs: git curl gcc-aarch64-linux-gnu sysroot-aarch64-fc44-glibc
#             rpm2cpio cpio make
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

LINUX_URL="${LINUX_URL:-https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git}"
LINUX_TAG=v7.2.15
UNILOADER_URL="${UNILOADER_URL:-https://github.com/ivoszbg/uniLoader.git}"
UNILOADER_REV=5d3c7f1134793c97ac5df03edabbad1f9794dbe8
BUSYBOX_VER=1.36.1
BUSYBOX_URL="${BUSYBOX_URL:-https://busybox.net/downloads/busybox-$BUSYBOX_VER.tar.bz2}"
BUSYBOX_SHA=b8cc24c9574d809e7279c3be349795c5d5ceb6fdf19ca709f80cde50e47de314
SYSROOT=/usr/aarch64-redhat-linux/sys-root/fc44

say(){ printf '== %s\n' "$*"; }
# Apply a -p1 patch inside a plain (non-git) source directory. git-apply so
# that patch(1) is not a dependency; GIT_CEILING_DIRECTORIES keeps it from
# treating the directory as part of this repository.
apply_in(){ ( cd "$1" && GIT_CEILING_DIRECTORIES="$(dirname "$1")" git apply -p1 "$2" ); }

do_kernel(){
	local T="$ROOT/linux-fedora"
	if [ -d "$T/.git" ]; then
		say "kernel: $T exists, leaving it alone"
	else
		say "kernel: cloning $LINUX_TAG"
		git clone --depth 1 --branch "$LINUX_TAG" "$LINUX_URL" "$T"
		for p in "$ROOT"/patches/0*.patch; do
			git -C "$T" apply "$p"
			say "kernel: applied $(basename "$p")"
		done
	fi
	# The inner panel driver is NO LONGER installed into the tree. It is
	# built out-of-tree from panel-work/ (like cover-work/), so there is
	# nothing to copy and patches/0007 is gone. See docs/18.
	# (The board DTS is still installed by build-kernel.sh.)
	# Same deal for the camera clock controller: ours, generated, and its
	# Kconfig/Makefile hookup is a tree edit rather than a patch file. It was
	# missing from here until 2026-11-16, so a fresh checkout built a kernel
	# with no camera clocks and nothing said so. install-camcc.sh is
	# idempotent.
	"$ROOT/camera-work/install-camcc.sh" "$T" | sed 's/^/   /'
	say "kernel: installed camcc-sm8350"
}

do_uniloader(){
	local U="$ROOT/uniloader"
	if [ -d "$U/.git" ]; then
		say "uniLoader: $U exists, leaving the checkout alone"
	else
		say "uniLoader: cloning at ${UNILOADER_REV:0:7}"
		git clone "$UNILOADER_URL" "$U"
		git -C "$U" checkout -q "$UNILOADER_REV"
	fi
	"$ROOT/uniloader-work/install.sh" "$U"
}

do_busybox(){
	local W="$ROOT/initramfs-work" TB
	if [ -d "$W/busybox-src" ]; then
		say "busybox: $W/busybox-src exists, leaving it alone"; return
	fi
	TB="$W/busybox.tar.bz2"
	[ -f "$TB" ] || { say "busybox: downloading $BUSYBOX_VER"; curl -fL -o "$TB" "$BUSYBOX_URL"; }
	echo "$BUSYBOX_SHA  $TB" | sha256sum -c - >/dev/null || { echo "!! busybox tarball checksum mismatch"; exit 1; }
	tar -xjf "$TB" -C "$W"
	mv "$W/busybox-$BUSYBOX_VER" "$W/busybox-src"
	apply_in "$W/busybox-src" "$ROOT/patches/userspace/busybox-$BUSYBOX_VER-long-bit.patch"
	cp "$W/busybox.config" "$W/busybox-src/.config"
	say "busybox: source ready (build it with tools/build-busybox.sh)"
}

# Static aarch64 lrz/lsz from Fedora's SRPM with its distro patches, for
# ZMODEM transfers over the serial console.
do_lrzsz(){
	local V="$ROOT/vendor-src" OUT="$ROOT/initramfs-work/bin" B
	if [ -x "$OUT/lrz" ] && [ -x "$OUT/lsz" ]; then
		say "lrzsz: binaries exist, leaving them alone"; return
	fi
	[ -d "$SYSROOT/usr/include" ] || { echo "!! missing $SYSROOT -- sudo dnf install sysroot-aarch64-fc44-glibc"; exit 1; }
	# never removes anything: refuses to reuse half-built leftovers instead
	if [ -e "$V/lrzsz-extract" ] || [ -e "$V/lrzsz-build" ]; then
		echo "!! $V/lrzsz-extract or lrzsz-build already exists; move them away and re-run"; exit 1
	fi
	mkdir -p "$V/lrzsz-extract" "$OUT"
	( cd "$V/lrzsz-extract" && rpm2cpio ../lrzsz-0.12.20-76.fc44.src.rpm | cpio -idm --quiet )
	tar -xzf "$V/lrzsz-extract/lrzsz-0.12.20.tar.gz" -C "$V"
	mv "$V/lrzsz-0.12.20" "$V/lrzsz-build"
	B="$V/lrzsz-build"
	# patch order as in lrzsz.spec
	for p in $(sed -n 's/^Patch[0-9]*: *//p' "$V/lrzsz-extract/lrzsz.spec"); do
		apply_in "$B" "$V/lrzsz-extract/$p"
	done
	( cd "$B"
	  # exported, not just passed to configure: the distro patches touch
	  # configure.in, so make re-runs configure and needs the same flags
	  export CC=aarch64-linux-gnu-gcc CFLAGS="--sysroot=$SYSROOT -O2"
	  export LDFLAGS="--sysroot=$SYSROOT -static -fno-link-libatomic"
	  ./configure --host=aarch64-linux-gnu --build=x86_64-linux-gnu --disable-nls --prefix=/usr >build.log 2>&1 \
	  && make >>build.log 2>&1 ) || { echo "!! lrzsz build failed, see $B/build.log"; tail -15 "$B/build.log"; exit 1; }
	aarch64-linux-gnu-strip -o "$OUT/lrz" "$B/src/lrz"
	aarch64-linux-gnu-strip -o "$OUT/lsz" "$B/src/lsz"
	say "lrzsz: built $OUT/lrz and lsz"
}

# The chainloader's kexec helper: freestanding, against the kernel's nolibc.
do_kexec_load(){
	local T="$ROOT/linux-fedora" OUT="$ROOT/initramfs-work/bin"
	[ -d "$T" ] || { echo "!! kexec-load needs the kernel tree: run '$0 kernel' first"; exit 1; }
	mkdir -p "$OUT"
	[ -d "$T/usr/include/linux" ] || make -s -C "$T" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- headers
	aarch64-linux-gnu-gcc -nostdlib -static -Os -Wl,-z,max-page-size=4096 -Wl,--build-id=none \
		-include "$T/tools/include/nolibc/nolibc.h" -I"$T/usr/include" \
		-o "$OUT/kexec-load" "$ROOT/initramfs-work/kexec-load.c"
	aarch64-linux-gnu-strip "$OUT/kexec-load"
	say "kexec-load: built $OUT/kexec-load"
}

do_diag(){
	# Upstream trees for DIAG/EFS2 access to the modem's filesystem over QRTR
	# (HANDBOOK 35.2.1). diag-router is built ON the phone: the host's
	# aarch64-linux-gnu-gcc is the kernel-only toolchain with no libc sysroot,
	# and the phone has gcc + libqrtr.so.1 but no libqrtr.h -- which is why the
	# qrtr checkout is needed (for include/libqrtr.h). QCSuper is not built; it
	# is the reference for the EFS2 packet layouts.
	mkdir -p "$ROOT/modem-work"
	for spec in "diag https://github.com/andersson/diag.git" \
	            "qrtr https://github.com/andersson/qrtr.git" \
	            "qcsuper https://github.com/P1sec/QCSuper.git"; do
		set -- $spec
		if [ -d "$ROOT/modem-work/$1/.git" ]; then
			say "diag: $1 already present"
		else
			git clone --depth 1 "$2" "$ROOT/modem-work/$1"
			say "diag: cloned $1"
		fi
	done
	say "diag: now build on the PHONE -- see HANDBOOK 35.2.1 for the make line"
}

[ $# -gt 0 ] || set -- all
for step in "$@"; do
	case "$step" in
		all)        do_kernel; do_uniloader; do_busybox; do_lrzsz; do_kexec_load; do_diag ;;
		kernel)     do_kernel ;;
		uniloader)  do_uniloader ;;
		busybox)    do_busybox ;;
		lrzsz)      do_lrzsz ;;
		kexec-load) do_kexec_load ;;
		diag)       do_diag ;;
		*) echo "!! unknown step: $step"; exit 1 ;;
	esac
done
cat <<'EOF'

Next:
  ./tools/build-kernel.sh            # Image + DTB
  ./tools/build-busybox.sh --rootfs  # initramfs
  ./tools/assemble-boot.sh           # boot.img (see HANDBOOK section 4)
  make -C touch-work && make -C hall-work && make -C wifi-work && make -C cover-work   # out-of-tree modules
EOF
