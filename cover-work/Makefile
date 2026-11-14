# Out-of-tree on purpose: no Kconfig symbol, so no kernel config change and no
# module-tree rebuild. Install to /lib/modules/<rel>/extra/ + depmod.
KDIR ?= $(CURDIR)/../linux-fedora
obj-m += panel-samsung-s6e3fab.o

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- clean
