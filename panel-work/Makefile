# Out-of-tree build for the INNER panel, matching cover-work/ (the cover panel
# has always been built this way).
#
# It was in-tree until 2026-11-16: setup-sources.sh copied the .c into
# drivers/gpu/drm/panel/ and patches/0007 added its Kconfig and Makefile
# entries. That only ever worked for a kernel we build ourselves. Building it
# here instead means the same driver can be built against ANY kernel -- which
# is the whole point of docs/18, running Fedora's kernel as the payload.
#
# The symbol CONFIG_DRM_PANEL_SAMSUNG_S6E3XA2 no longer exists, so nothing in
# q2q-stage1.config refers to it; the module lands in extra/ and depmod finds
# it (see rootfs-work/modules/depmod-fold3.conf).
#
#   make                                  # against ../linux-fedora
#   make KDIR=/usr/src/kernels/<fedora>   # against a Fedora kernel-devel tree
#
# This driver includes only public headers (drm/, linux/), so unlike
# camera-work/out/ it needs no -I into the kernel tree.
KDIR ?= $(CURDIR)/../linux-fedora
obj-m += panel-samsung-s6e3xa2.o

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- clean
