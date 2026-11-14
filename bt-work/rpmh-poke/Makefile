KDIR ?= $(CURDIR)/../../linux-fedora
obj-m += rpmh_poke.o
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= modules
