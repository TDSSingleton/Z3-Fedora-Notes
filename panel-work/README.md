# Panel bring-up — working directory

**The inner panel works.** See "Status" below. This file is the work state.

Status of the two Fold 3 panel drivers. The **verified** decoded data is in
[`../Hard Truths/13-panel-reference.md`](../Hard%20Truths/13-panel-reference.md); this
file is the work state, which changes.

## Contents

| File | What it is |
|---|---|
| `panel-samsung-s6e3xa2.c` | Main (inner) panel driver. **WORKS ON HARDWARE** since 2026-11-11. Source of truth; copy into the kernel tree when changed |
| `display.dtsi` | **OUTDATED SKETCH, do not use.** Two wrong values (reset gpio 14, vci on ldo2) and it duplicates nodes the touch work already added. The live wiring is the DISPLAY section of `../dts-work/sm8350-samsung-q2q.dts` |
| `decode-main-s6e3xa2.txt` | Full annotated decode of the main panel's DTS command streams |
| `decode-cover-s6e3fab.txt` | Same for the cover panel |
| `../tools/extract-panel-cmds.py` | Decodes Qualcomm MDSS command streams out of the vendor DTS |
| `../tools/gen-panel-init.py` | Emits a mainline-idiom init function from one of those streams |

## What's done

- **Both panels fully decoded.** Mode tables, DSI PHY timings, DSC parameters, init/off
  sequences, GPIOs, supplies, topology. Cross-checked two independent ways (DTS timing
  properties vs. the transmitted DSC PPS blob) and they agree exactly.
- **Main panel driver written**, structured after upstream
  `drivers/gpu/drm/panel/panel-samsung-s6e3ha8.c` — the closest in-tree relative, a
  Samsung command-mode DSC panel.
- **All kernel APIs used were verified against current upstream headers.** That check
  caught two real bugs: `drm_panel_init()` has been removed in favour of
  `devm_drm_panel_alloc()`, and the DSC config must be mutable per-instance because
  msm's DSI host writes computed fields into it.
- **Confirmed no SoC-level work is needed** — the SM8350 display stack is already upstream.

## Status: WORKING ON HARDWARE (2026-11-11)

The inner panel **lit on the first attempt**, under DPU + DSI0 at 2208x1768 on
kernel `7.2.15-q2q #56`, with KWin compositing on the Adreno 660 through the
same DRM device. The user's description was "smooth as butter".

Evidence from that boot:

```
msm_dpu ae01000.display-controller: bound ae94000.dsi (ops dsi_ops [msm])
msm_dpu ae01000.display-controller: bound 3d00000.gpu (ops a3xx_ops [msm])
[drm] Initialized msm 1.13.0 for ae01000.display-controller on minor 0
msm_dpu ae01000.display-controller: [drm] fb0: msmdrmfb frame buffer device
/sys/class/drm/card0-DSI-1: status=connected enabled=enabled
  modes: 2208x1768 2208x1768
```

Caveat worth keeping in mind: every register write in the init sequence is
still a transcription from the vendor DTS. "It lights and shows a correct
image" validates the sequence as a whole, not each command individually.

### Build status — compiles clean

Cross-compiled for arm64 with GCC 16.2.1 against **two** trees:

| Tree | Version | Result |
|---|---|---|
| `linux-fedora/` | **v7.2.15** — Fedora 44 *and* 45's kernel base | 0 errors, 0 warnings |
| `linux/` | v7.4.0-rc1 (mainline) | 0 errors, 0 warnings |

`make W=1` clean; `checkpatch.pl --strict` reports 0 errors, 0 warnings,
0 checks. Reproduce with `tools/build-panel-test.sh`.

### It is NOT upstream — correcting an earlier claim

An earlier version of the handbook said this panel driver "already exists
upstream". It does not: **v7.2.15 ships no `s6e3xa2` at all.** The file in
`linux-fedora/drivers/gpu/drm/panel/` is *ours*, untracked, with Kconfig and
Makefile entries added by `tools/build-panel-test.sh`.

Keep `panel-work/panel-samsung-s6e3xa2.c` as the source of truth and copy it
into the tree when it changes — `tools/build-kernel.sh` installs the **DTS**
only, not this driver, so an edit here does not reach a build by itself.

## What is still not done

1. ~~Panel orientation is not declared.~~ **DONE 2026-11-11: `LEFT_UP`**,
   declared in `s6e3xa2_get_modes()`. Determined by applying
   `kscreen-doctor output.DSI-1.rotation.left` and looking at the glass —
   `.right` came out upside down. It **cannot** be reasoned out: the device's-eye
   description and the touchscreen's DT handedness both point at `RIGHT_UP`,
   and both are wrong. It also **composes with** the DT touch transform rather
   than replacing it (digitizer→raster in the DTS, panel→casing in the driver);
   verified that image and touch are both correct with both in place.
2. **Only 120 Hz and 96 Hz are advertised.** Those two share a byte-identical
   vendor init stream, so the driver is correct for them. 60/48 Hz need the
   `0xb9` byte set to `0x01`, and `drm_panel` has no `mode_set` callback to
   select per-mode init from. Omitted rather than advertised-and-wrong.
3. **No cover-panel driver yet.** Decoded and ready to generate. Its board
   wiring: reset gpio 25, TE gpio 83 (same `mdp_vsync` mux as the inner
   panel's 82), on `&mdss_dsi1` with its own PHY.
4. **The `0x2a`/`0x2b` trap in the cover panel's DTS is unresolved** — see the
   panel reference, §2. It claims 1080x2340 against everything else saying
   832x2268.
5. A cosmetic `DSI PLL(0) lock failed, status=0x00000000` during
   `dsi_phy_driver_probe`, with two WARN backtraces. The PLL locks when the
   real modeset runs; this is the handoff from the display clocks XBL left
   running. No user-visible effect.

## Confirmed by the bring-up

- **DDIC is `S6E3XA2`** — ABL's command line names it
  (`msm_drm.dsi_display0=ss_dsi_panel_S6E3XA2_AMF755ZE01_QXGA`,
  `lcd_id=811044`) and the panel answers this driver's init sequence.
  Cover panel is `S6E3FAB_AMB623ZF01` (`lcd_id1=811043`).
- **No SoC-level work was needed.** `CONFIG_SM_DISPCC_8250` plus
  `DRM_MSM_DPU`/`DRM_MSM_DSI`/`DRM_MSM_DSI_7NM_PHY` was the whole kernel-side
  change.
- **The S2DOS05 rail mapping** (`ldo1`=vdd3, `buck`=vddr, `ldo4`=vci) is right,
  though it was not really exercised: those rails are `regulator-always-on`
  with no voltage constraints because XBL leaves them on, so the driver's
  `regulator_bulk_enable()` is effectively a no-op. Only the reset pulse and
  the init sequence were ever in question.

## Device-tree node (AS SHIPPED — was a sketch, now corrected and working)

```dts
&mdss_dsi0 {
	panel@0 {
		compatible = "samsung,s6e3xa2-amf755ze01";
		reg = <0>;

		vdd3-supply = <&s2dos05_ldo1>;   /* panel_vdd3 */
		vddr-supply = <&s2dos05_buck>;   /* panel_vddr -- node is "buck", not buck1 */
		vci-supply  = <&s2dos05_ldo4>;   /* panel_vci  -- ldo4, NOT ldo2 (that is tsp_io) */

		/* 24, not 14: vendor qcom,platform-reset-gpio = 0x18 */
		reset-gpios    = <&tlmm 24 GPIO_ACTIVE_LOW>;
		mipi-sel-gpios = <&tlmm 97 GPIO_ACTIVE_HIGH>;

		/* TE on gpio 82 is a PINCTRL mux to function "mdp_vsync",
		 * not a gpio property. Without it there is no vsync. */
		pinctrl-names = "default";
		pinctrl-0 = <&panel_reset_active>, <&panel_te_active>,
			    <&panel_mipisel_active>;

		port {
			endpoint {
				remote-endpoint = <&mdss_dsi0_out>;
			};
		};
	};
};
```
The S2DOS05 rail-to-supply mapping is **verified** (see `display.dtsi`). What still needs
checking is the upstream `s2dos05-regulator` binding's expected child-node names and
compatible string, since those must match the driver rather than Samsung's downstream DT.

## Next steps, in order

1. ~~Compile-test~~, ~~confirm the DDIC~~, ~~S2DOS05 rail mapping~~,
   ~~enable the kernel options and write the display nodes~~,
   ~~light the inner panel~~ — **all done 2026-11-11.**
2. Panel orientation **together with** the touch transform (see above).
3. Per-mode init so 60/48 Hz can be advertised.
4. The cover panel, then dual-DSI concurrency.

## Regenerating

```bash
D=SM-F926B/Kernel/arch/arm64/boot/dts/samsung/q2/q2q/q2q_eur_openx_w00_r08.dts

# annotated decode (modes, DSC, every command)
./tools/extract-panel-cmds.py "$D" ss_dsi_panel_S6E3XA2_AMF755ZE01_QXGA --modes
./tools/extract-panel-cmds.py "$D" ss_dsi_panel_S6E3XA2_AMF755ZE01_QXGA

# mainline-idiom init function
./tools/gen-panel-init.py "$D" ss_dsi_panel_S6E3XA2_AMF755ZE01_QXGA s6e3xa2_on

# the cover panel, or the XA1 variant, or any other Samsung board DTS
./tools/extract-panel-cmds.py "$D" ss_dsi_panel_S6E3FAB_AMB623ZF01_HD --modes
```
