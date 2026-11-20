obj-m += q2q-sensor-rig.o
KDIR ?= $(CURDIR)/../../linux-fedora
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- clean
