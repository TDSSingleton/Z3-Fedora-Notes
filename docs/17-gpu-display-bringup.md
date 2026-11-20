# GPU and display bring-up — the 2026-11-11 session

A blow-by-blow record of the session that took the Fold 3 from
software-composited Plasma on the bootloader framebuffer to **GPU-accelerated
Plasma on the real inner panel**, plus a console that no longer needs a USB
host to boot.

`HANDBOOK.md` sections 12, 17 and 18 carry the durable versions of all of this.
This file is the narrative and the evidence, kept because several of the dead
ends were more informative than the successes.

Start state: kernel `7.2.15-q2q #54`, simpledrm on XBL's framebuffer, inner
touch working, no GPU, `DRM_MSM=n`.
End state: `#56`, DPU + DSI + S6E3XA2 under KMS, `GL_RENDERER FD660`, and the
user's own verdict — "smooth as butter".

---

## 1. Three of the four listed blockers did not exist

The old handbook section 18 listed "three traps waiting". Checking each before
writing any code cost twenty minutes and removed most of the projected work.

**`adreno_smmu` failing with `-110`.** The old logs really did show
`arm-smmu 3da0000.iommu: probe with driver arm-smmu failed with error -110`,
read as the GPU's SMMU being secure-world protected. The line immediately
above it settles it:

```
arm-smmu 3da0000.iommu: deferred probe timeout, ignoring dependency
arm-smmu 3da0000.iommu: probe with driver arm-smmu failed with error -110
```

`-110` is `ETIMEDOUT` from the **deferred probe timeout**, not from the
hardware. `adreno_smmu` consumes `gpucc`, and `gpucc_sm8350` is a module loaded
from userspace — with `deferred_probe_timeout=1` the deferred list was flushed
a second after initcalls, long before it could load. That timeout is now 60,
and the live device answered the question directly:

```
$ ls /sys/bus/platform/drivers/arm-smmu/
15000000.iommu  3da0000.iommu  module  uevent
```

Bound. Later, with the GPU on: `7 context banks`, `Stage-1: 48-bit VA`.

**The qfprom speed-bin fuse.** A real risk, because our qfprom is TZ-protected.
It does not apply: the `a660.1` catalog entry (`chip_ids = 0x06060001`) declares
no `.speedbins`, so nothing reads the `speed_bin` nvmem cell, and
`a6xx_set_supported_hw()` explicitly treats `-ENOENT` as "the platform doesn't
support speedbin which is fine".

**AOSS / interconnect dependencies.** The `gmu` node has no `qcom,qmp` and the
`gpu` node has no `interconnects` in `sm8350.dtsi`. Nothing to satisfy.

**The one that was real:** `SM_DISPCC_8250` must stay out until the panel lands,
because probing it reprograms the display clocks and destroys the live
bootloader scanout. That is why the GPU went first, alone.

---

## 2. The console fix, and why it was not what it looked like

The complaint was that the phone would not boot unless USB was connected. The
project had documented "an unread console stalls the device" and the remedy
"always keep a host draining it", but not the mechanism.

The mechanism is specific. `console=ttyGS0` makes `/dev/console` resolve to the
gadget tty, because the console driver supplies a `.device` callback
(`gs_console_device()` returns `gs_tty_driver`). So **userspace** console
writes take the *tty* path, and:

```c
static unsigned int gs_write_room(struct tty_struct *tty)
{
	...
	if (port->port_usb)
		room = kfifo_avail(&port->port_write_buf);
	...
	return room;            /* 0 when no host is enumerated */
}
```

Room 0 → the tty layer blocks the writer indefinitely → systemd's first status
write to `/dev/console` hangs the boot until a host appears.

Kernel `printk` was **never** affected, which is worth knowing because it
misdirects: `gs_console_write()` is a separate, non-blocking path that drops
into a `[missed N bytes]` counter. So the kernel log looked fine and only
userspace stalled.

`patches/0003` makes the three tty write paths discard when
`port->port_usb == NULL`. Verified by rebooting with nothing attached, waiting
out a 90-second window, then plugging in: the phone had reached a login prompt
on its own.

**Still unfixed:** a host that enumerates but never *opens* the port. Then
`port_usb` is set, the 8 KiB fifo fills for real, and writes block exactly as
before. The "keep draining `/dev/fold3`" rule therefore stands.

### A warning that is not ours

The fix made this appear on every boot, so it was briefly suspected:

```
WARNING: drivers/usb/gadget/function/u_serial.c:703 at gs_close+0x12c/0x2d0, CPU#2: (agetty)
```

It is `WARN_ON(1)` for `gs_close()` entered with `port.count == 0`. It is
**pre-existing** — present four times in every boot log from before the patch,
always from agetty. Checking the old captures took one `grep` and avoided
rewriting a correct patch.

---

## 3. GPU, render-only — one hour, two upstream bugs

Deliberately staged: GPU first with the display untouched, because the zap
shader's TZ authentication was the single most likely hard blocker and it is
independent of the panel.

`DRM_MSM_KMS` has been its own Kconfig symbol since v6.15 (`def_bool n`,
select-ed by MDP4/MDP5/DPU). With all of MDP4/MDP5/DPU/DSI/DP/HDMI off, msm
registers a render-only DRM device through `msm_gpu_probe()` and leaves
simpledrm holding `card0`.

### Bug 1: the silent one

First load produced **nothing**. Not an error — nothing at all. And yet:

```
$ ls -l /sys/bus/platform/devices/3d00000.gpu/driver
... -> ../../../../bus/platform/drivers/adreno
```

Bound to `adreno`, zero log output, no DRM device. The cause:

```c
static int adreno_probe(struct platform_device *pdev)
{
	if (of_device_is_compatible(pdev->dev.of_node, "amd,imageon") ||
	    msm_gpu_no_components())
		return msm_gpu_probe(pdev, &a3xx_ops);

	return component_add(&pdev->dev, &a3xx_ops);
}

bool msm_gpu_no_components(void)
{
	return separate_gpu_kms;     /* no CONFIG_DRM_MSM_KMS guard */
}
```

`separate_gpu_kms` is a module parameter defaulting to 0, with **no
`CONFIG_DRM_MSM_KMS` guard**. So on a GPU-only build `adreno_probe()` registers
as a component and waits for a KMS master that can never be created.
`component_add()` returns 0, so the device looks bound and healthy.

`insmod msm.ko separate_gpu_kms=1` fixed it instantly. **`ls /dev/dri` is the
check, not the bind state.**

### Bug 2: the destructive one

`rmmod msm` to retry oopsed:

```
Unable to handle kernel NULL pointer dereference
  adreno_remove+0x10/0x60 [msm]
  platform_remove ... driver_unregister ... __arm64_sys_delete_module
```

```c
static void adreno_remove(struct platform_device *pdev)
{
	struct msm_drm_private *priv = platform_get_drvdata(pdev);

	if (priv->kms_init)        /* priv is NULL on the component path */
```

Worse than it first looks. drvdata cannot answer the question *at all*: on the
component path nothing ever sets it, and on the other path `msm_gpu_probe()`
sets it to `priv` and then `msm_gpu_init()` **overwrites it** with
`&gpu->adreno_smmu` (`msm_gpu.c:969`), so `priv->kms_init` reads a field of the
wrong struct either way.

`patches/0004` mirrors `adreno_probe()`'s own condition instead, which cannot
disagree because `separate_gpu_kms` is a `0400` parameter. Without it, every
failed GPU experiment costs a reboot and therefore a physical cable replug.

### Firmware

Three blobs, all already captured, none needing new code:

| file | source | installed as |
|---|---|---|
| `a660_sqe.fw` | `vendor_firmware/firmware.tar` | `/lib/firmware/qcom/a660_sqe.fw` |
| `a660_gmu.bin` | same | `/lib/firmware/qcom/a660_gmu.bin` |
| `a660_zap.mdt` + `.b00/.b01/.b02` | `firmware_mnt/image.tar` | `qcom/sm8350/samsung/q2q/` |

Two details that mattered:

- **Uncompressed, deliberately.** Fedora's `linux-firmware` already ships
  `qcom/a660_{sqe.fw,gmu.bin}.xz`, but `CONFIG_FW_LOADER_COMPRESS` is **off** in
  our config, so `.xz` files are invisible to the loader. Enabling it was
  rejected rather than done: the loader tries the plain name first for *every*
  request, so turning on xz support would let Fedora's `board-2.bin.xz` win
  over the bare `board.bin` staged for ath11k, silently changing WiFi
  behaviour.
- **The zap shader must be Samsung's.** It is signed per device family and
  authenticated by TZ via `qcom_scm_pas_auth_and_reset()`; linux-firmware
  cannot ship one this TZ will accept. Setting `firmware-name` on the
  `zap-shader` node makes the driver load the path verbatim with
  `request_firmware_direct()` and skip `adreno_request_fw()`'s `qcom/`-prefix
  guessing; `qcom_mdt_load()` then derives `.b00`..`.b02` from that same name,
  so all four files must share a directory.

Its one loadable segment is 1976 bytes (checked by parsing the MDT program
headers: `PT_LOAD`, `p_flags & 0x7000000 != MDT_TYPE_HASH`), comfortably inside
the 8 KiB `pil_gpu_mem` at `0x8b51a000` — a region inherited from
`sm8350.dtsi` and byte-for-byte identical to Samsung's own `lahaina.dtsi`, so
it lands where this device's TZ expects it.

It authenticated on the first attempt. No message is printed on success, only
on failure, so "no zap line in dmesg" is the good outcome.

### Proving it

The Fedora Mobile image has no glmark2, no vulkan-tools and no `eglinfo`, and
the phone has no network to install them. `tools/gl-probe.py` drives
`libEGL`/`libGLESv2` through `ctypes` on a surfaceless display instead — no
packages, no compiler:

```
render nodes: ['renderD128']
EGL 1.5  vendor Mesa Project
GL_VENDOR   freedreno
GL_RENDERER FD660
GL_VERSION  OpenGL ES 3.2 Mesa 26.2.3
centre pixel (0, 255, 0, 255) (expect (0, 255, 0, 255) green)
RESULT: hardware rendering on FD660
```

It renders a triangle into an FBO and **reads the pixels back**, because
context creation alone can succeed without the GPU executing anything, and
because `GL_RENDERER` is the only thing that distinguishes hardware from an
`llvmpipe` fallback. `/sys/kernel/debug/dri/1/gpu` corroborated:
`gpu-initialized: 1`, `revision: 660 (06060001)`, ringbuffer fences retiring,
GMU log populated.

### Why this did not make the UI faster

Worth stating plainly, because it is counter-intuitive and was the reason to
keep going. KWin still composited 2208x1768 through `kms_swrast` on simpledrm:
simpledrm has no render node, is not one of Mesa's `kmsro` display drivers, and
cannot scan out an imported dmabuf (it memcpys from a shadow buffer). There is
no path for a GPU-rendered buffer to reach the glass. A render node alone buys
nothing for a compositor.

---

## 4. The display — first attempt, and it lit

### What the DT needed

`sm8350.dtsi` already describes `mdss`, the DPU, `mdss_dsi0`, `mdss_dsi0_phy`
and the OPP tables. Board-level additions only:

```dts
&mdss { status = "okay"; };

&mdss_dsi0 {
	vdda-supply = <&pm8350_l6>;        /* L6B 1.2 V,  per sm8350-hdk */
	status = "okay";
	panel@0 {
		compatible = "samsung,s6e3xa2-amf755ze01";
		reg = <0>;
		vdd3-supply = <&s2dos05_ldo1>;
		vddr-supply = <&s2dos05_buck>;
		vci-supply  = <&s2dos05_ldo4>;
		reset-gpios = <&tlmm 24 GPIO_ACTIVE_LOW>;
		mipi-sel-gpios = <&tlmm 97 GPIO_ACTIVE_HIGH>;
		pinctrl-names = "default";
		pinctrl-0 = <&panel_reset_active>, <&panel_te_active>,
			    <&panel_mipisel_active>;
		port { panel_in: endpoint { remote-endpoint = <&mdss_dsi0_out>; }; };
	};
};

&mdss_dsi0_out { remote-endpoint = <&panel_in>; data-lanes = <0 1 2 3>; };
&mdss_dsi0_phy { vdds-supply = <&pm8350_l5>; status = "okay"; };  /* L5B 0.88 V */
```

### The three pins, and the one that is not a GPIO

All three were inside `gpio-reserved-ranges` and had to be freed. All three came
from the vendor DT rather than from guesswork — which caught an error in the
old `panel-work/display.dtsi` sketch:

| pin | role | vendor source |
|---|---|---|
| **24** | panel reset | `qcom,platform-reset-gpio = <… 0x18 0>`. The sketch said **14** |
| **82** | panel TE | `sde_te_active` in `lahaina-pinctrl.dtsi`, function **`mdp_vsync`** |
| **97** | mipi-sel | `samsung,mipisel-gpio = <… 0x61 0>`, `on_val = 1` |

**TE is a pinctrl mux, not a GPIO consumer.** The pin is muxed to the
`mdp_vsync` function so the panel's tear-effect line reaches the DPU's INTF in
hardware. A command-mode panel has no periodic timing of its own — the host
pushes a frame when TE says the scanout wrapped — so with no TE mux there is no
vsync at all. Nothing in the panel driver references pin 82.

Ranges went from
`<0 5>, <6 14>, <24 8>, <34 30>, <66 10>, <78 16>, <97 56>, <154 11>, <166 37>`
to
`<0 5>, <6 14>, <25 7>, <34 30>, <66 10>, <78 4>, <83 11>, <98 55>, <154 11>, <166 37>`.

### Rails: left alone on purpose

The panel's three supplies come off the s2dos05 sub-PMIC and were already
`regulator-always-on` with **no voltage constraints**, from the touchscreen
work — enough to stop anything disabling them, without reprogramming a voltage
under a display that could not be re-initialised. They were left exactly as
they were, which makes the driver's `regulator_bulk_enable()` a no-op. That was
the right first attempt: XBL already powers the panel, so only the reset pulse
and the init sequence were ever in question. It worked, so they stay.

### simpledrm had to go

`framebuffer@e4000000` was deleted from `chosen`. The two cannot coexist:
simpledrm would keep scanning out of XBL's surface while DPU reprograms the
display controller underneath it. `CONFIG_DRM_SIMPLEDRM` stays **compiled in**
though, so restoring that node is a DTS-only change if a future panel edit
leaves the screen dark.

### The result

```
msm_dpu ae01000.display-controller: bound ae94000.dsi (ops dsi_ops [msm])
msm_dpu ae01000.display-controller: bound 3d00000.gpu (ops a3xx_ops [msm])
[drm:dpu_kms_hw_init:1168] dpu hardware revision:0x70000000
[drm] Initialized msm 1.13.0 for ae01000.display-controller on minor 0
msm_dpu ...: [drm] fb0: msmdrmfb frame buffer device
/sys/class/drm/card0-DSI-1: status=connected enabled=enabled
  modes: 2208x1768 2208x1768
```

**The second line is the one that matters.** DPU binds the DSI *and* the GPU
into one DRM device, so `card0` and `renderD128` are the same device and KWin
renders and scans out with no copy:

```
$ cat /sys/kernel/debug/dri/0/clients
        command  tgid dev master a   uid
   kwin_wayland  1025 128   n    n  1000      <- render node
   kwin_wayland  1025   0   n    y  1000      <- scanout, master
```

So `separate_gpu_kms` must go back to its default **0** for the display build,
and `/etc/modprobe.d/msm-gpu.conf` from the render-only stage was deleted.
Setting it now would split GPU and display into two DRM devices and throw away
the zero-copy path — the exact opposite of what it was needed for an hour
earlier.

### One error to ignore

```
DSI PLL(0) lock failed, status=0x00000000
PLL(0) lock failed
dsi0_phy_pll_out_dsiclk already disabled
dsi0_phy_pll_out_dsiclk already unprepared        (+2 WARN backtraces)
    dsi_phy_driver_probe+0x2fc/0x344 [msm]
```

at ~6.07 s, in PHY probe. **Not fatal** — the PLL locks when the real modeset
runs, the connector comes up `connected`/`enabled` and the panel lights. It is
the handoff from the display clocks XBL left running. Recorded here so it is
not chased as a panel bug later.

`Fixed dependency cycle(s)` between dpu/dsi/panel is ordinary `fw_devlink`
chatter on every msm display.

---

## 5. Process notes

**Ship together, activate separately.** The GPU and console changes shipped in
one flash but only one was *active*: the GPU modules were staged outside
`/lib/modules` so udev could not autoload them, leaving them inert until
`insmod`. That kept the two diagnostically separate without a second flash —
each flash cycle costs a cable replug by hand, so they are not free.

**Snapshot before a one-way door.** `golden/stage4-gpu-*` was taken before the
display work specifically because removing simpledrm means a wrong panel init
leaves no screen at all. `golden/stage5-display-*` is the working display
build. Each carries a `MANIFEST.txt` explaining every decision baked into it.

**What cost the most time, and it was not the hardware.** Five minutes were
lost to `selfflash.py` calling `busybox base64` on a rootfs that has coreutils
and no busybox — written for the Stage-1 initramfs and never revisited after
the pivot into Fedora. The receiver died instantly and bash then read 61 MiB of
base64 as commands, writing nothing, looking like a slow flash. See
HANDBOOK section 17.
