# Out-of-tree build, so the driver can be iterated with insmod over the serial
# console instead of a reflash per attempt. The DTB is inside boot.img, so DT
# changes cost a flash; the module does not.
KDIR ?= $(CURDIR)/../linux-fedora
obj-m += fts9cu80f.o

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- clean
