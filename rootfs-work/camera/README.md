# Camera: what the root filesystem needs

The kernel side is `patches/0010`-`0012` plus the DT; this directory holds the
two userspace facts without which no camera application works, however good
the driver is.

## 1. `71-dma-heap-uaccess.rules`

`/dev/dma_heap/system` is created `root:video 0660`, and `systemd-logind` does
not grant the active session an ACL on it the way it does for `/dev/video*`.
libcamera's software ISP needs a dma-buf provider, so **every libcamera client
in the user session silently loses software debayering** and the camera
exposes raw Bayer, which nothing can display.

This is invisible when testing as root -- `cam` works perfectly -- and it is
why the camera app failed while the kernel was fine.

```sh
install -m0644 71-dma-heap-uaccess.rules /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger --subsystem-match=dma_heap
```

Verify: `getfacl -p /dev/dma_heap/system` must list `user:<you>:rw-`.

## 2. The `video` group

Belt and braces for sessions that are not seat-attached (ssh, systemd user
units started outside the seat), where `uaccess` does not apply:

```sh
usermod -aG video <user>
```

Restart `pipewire`, `pipewire-pulse` and `wireplumber` afterwards, or the
already-running libcamera monitor keeps its old, failed probe:

```sh
systemctl --user restart wireplumber pipewire pipewire-pulse
```

After this `wpctl status` shows the camera as the **default** video source
(`*  NNN. Built-in Back Camera`). Before it, there is a source listed but no
default, and `gst-launch-1.0 pipewiresrc` fails with `target not found`.

## Not a bug: the stride INFO line

```
INFO SimplePipeline simple.cpp:1570 Input buffer stride ignored by the driver.
                                    Requested 5376, got 5264
```

is harmless. libcamera asks for a 256-byte-aligned stride, camss returns its
own 16-byte-aligned 5264, and libcamera then uses 5264 -- the next line,
`software_isp.cpp:299 Input 4208x3120-RGGB-10-CSI2P stride 5264`, is the proof.

The diagonal shear once blamed on this was in **our host-side decoder**:
libcamera pads its ABGR output to a 64-pixel stride (16896 B for a 4200 px
frame), and `camera-work/abgr2png.py` assumed tight packing. It now derives
the stride from the file size. See HANDBOOK 33.13.
