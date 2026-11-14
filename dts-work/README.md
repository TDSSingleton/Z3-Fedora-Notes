# Device tree — `sm8350-samsung-q2q.dts`

Stage-1 board DTS for the Galaxy Z Fold 3. Built with `tools/build-dtb.sh` (defaults to
the Fedora-matched tree, `linux-fedora/` = v7.2.15).

> **This file describes the Stage-1 DTS and is now behind.** The board DTS has
> since gained UFS, the s2dos05 sub-PMIC on bitbanged i2c, the SPI touchscreen,
> PMIC keys, the RTC, PCIe/WiFi, the GPU, and a full DISPLAY section (DPU + DSI
> + the S6E3XA2 panel) — and the `framebuffer@e4000000` chosen node has been
> **removed**, because simpledrm cannot coexist with DPU. The table below still
> lists that framebuffer; it is history. Read the DTS itself, plus
> `HANDBOOK.md` sections 14, 17 and 18.

## Status — ✅ COMPILES (2026-11-07)

```
DTC  arch/arm64/boot/dts/qcom/sm8350-samsung-q2q.dtb   73,509 bytes
```

No DTC warnings. Verified against the *compiled* DTB, not just the source:

| Check | Result |
|---|---|
| `/memory` | 4 ranges, **11.89 GiB** total |
| reserved-memory | 36 non-zero regions |
| **region overlaps** | **0** |
| **regions outside `/memory`** | **0** |
| framebuffer | 2208×1768, stride 8832, `a8r8g8b8` @ `0xe4000000` |
| ramoops | `0xf0b00000` + 1 MiB, console/record/pmsg/ftrace sized |
| dwc3 core | single phy (`usb2-phy`), peripheral, high-speed |
| USB SS qmpphy | left `disabled` |
| UFS | `disabled` (deliberate) |
| regulators instantiated | 8 |

## Scope — deliberately minimal

Stage 1 is "the smallest thing that can possibly boot", so that a failure has few
candidate causes. It gets you a framebuffer console and a USB gadget, from an initramfs.

**Not in this file yet:** UFS, DSI/panel, Wi-Fi, Bluetooth, audio, remoteprocs, touch,
charging. `panel-work/display.dtsi` holds the display nodes for when we get there.

UFS is off on purpose — and note **upstream sagami also disables it**, so SM8350 UFS isn't
a solved problem in mainline (a patch enabling it on sagami was under review as of 2026).
Booting from initramfs removes storage from the list of first-boot failure modes.

## Where the data came from

Nothing here was guessed:

| Thing | Source |
|---|---|
| `/memory` 4 ranges | **ABL's own memory node**, from the captured merged post-ABL DT |
| reserved-memory | 37 regions from that same merged DT, cross-checked against `lahaina.dtsi` |
| framebuffer geometry | `cont_splash_region` + the S6E3XA2 panel timings |
| ramoops address | `ramoops@1B0B00000` in the merged DT → `0xf0b00000` |
| USB rails | upstream `sm8350-sony-xperia-sagami.dtsi` (same SoC, correct labels) |
| Samsung conventions | upstream `sm8450-samsung-r0q.dts` |

### ABL's `/memory` node is *not* bogus on this device
Both the Galaxy S22 port and U-Boot's Qualcomm docs warn that Samsung bootloaders emit
bogus or zero-sized memory nodes. Checked, and here ABL publishes four sane ranges
totalling 11.90 GiB — consistent with `/proc/iomem` reporting 11.41 GiB usable after
carve-outs on a 12 GB unit. The warning isn't baseless though: ABL's
`demura_region_0`/`_1` reserved nodes **are** zero-sized. It just doesn't affect `/memory`.

### Upstream's `pil_*` addresses are correct — don't override them
A first pass comparing the merged DT against `sm8350.dtsi` suggested 5 `pil_*` regions
were at the wrong addresses upstream. Checking the **vendor source** (`lahaina.dtsi`)
disproved it: `pil_camera_mem@85200000`, `pil_video_mem@85700000`,
`pil_cvp_mem@85c00000`, `pil_adsp_mem@86100000`, `pil_slpi_mem@88200000`,
`pil_spss_mem@8b600000` match upstream exactly. The different addresses in the merged dump
are **ABL relocating them at runtime**. Since uniLoader means ABL never rewrites our DT,
we inherit `sm8350.dtsi`'s values unchanged.

## Two things worth knowing

**The `splash_region` naming is ambiguous.** Upstream `sm8450-samsung-r0q.dts` carries the
comment *"the bootloader will only keep display hardware enabled if this memory region is
named exactly `splash_region`"* — and then writes `splash-region@b8000000`, with a hyphen,
contradicting itself. Samsung's own DT uses `splash_region` (underscore, no unit address)
plus `label = "cont_splash_region"`.

For our boot path it doesn't matter: uniLoader presents itself to ABL as a kernel, so ABL
never parses this DT. The node's only job is stopping Linux allocating over the
framebuffer. We use the underscore plus a unit address and carry the label. **If we ever
boot without uniLoader and the display dies, try renaming it to bare `splash_region`.**

**USB overrides must target the dwc3 *core*, not the glue.** `sm8350.dtsi` has
`usb_1: usb@a6f8800` (glue, `qcom,sm8350-dwc3`) and `usb_1_dwc3: usb@a600000`
(core, `snps,dwc3`), and `phys`/`phy-names` are declared on the **core**. The first draft
of this file overrode them on `&usb_1`, which silently did nothing and left `usb3-phy`
attached — caught only by decompiling the DTB and looking. `qcom,select-utmi-as-pipe-clk`
does belong on the glue.

## NOT verified

1. **Never booted.** Compiling a DTB proves it is well-formed, nothing more.
2. **The regulator set is minimal and may be too minimal.** Only the USB HS PHY rails and
   their parents are described. If something upstream of USB needs a rail we haven't
   declared, it will fail to probe.
3. **No `dtbs_check`** against the DT schema (`dt-schema` isn't installed here). Worth
   running before any upstream submission.
4. `qcom,board-id` / `qcom,msm-id` are **not** set. ABL uses them to pick a DTB — but
   uniLoader bypasses that entirely. They would matter for a `vendor_boot` DT-injection
   approach.

## Next

1. Minimal initramfs (busybox + sshd).
2. `blob/{Image,dtb,ramdisk}` → uniLoader → `mkbootimg --header_version 3` preserving
   `os_version 11.0.0` / `os_patch_level 2026-08`.
3. `dd` to `boot` and watch the inner screen — see [`../14-flashing.md`](../14-flashing.md).
