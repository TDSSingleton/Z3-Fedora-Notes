# Panel reference — decoded from the vendor DTS

Decoded on 2026-11-06 from `q2q_eur_openx_w00_r08.dts` (the revision fitted to units
reporting `ro.revision = 9`) with `tools/extract-panel-cmds.py`. Full dumps in
`panel-work/decode-main-s6e3xa2.txt` and `panel-work/decode-cover-s6e3fab.txt`.

**Every number here was cross-checked two independent ways that agree exactly:** the
`qcom,mdss-*` timing properties in the DTS, and a decode of the raw DSC Picture Parameter
Set blob that the vendor init stream transmits. Those are separate data in separate
formats, so their agreement is strong evidence both were read correctly.

---

> **Confirmed fitted on this unit (2026-11-07).** ABL's own kernel command line reads
> `msm_drm.dsi_display0=ss_dsi_panel_S6E3XA2_AMF755ZE01_QXGA` (`lcd_id=811044`) and
> `msm_drm.dsi_display1=ss_dsi_panel_S6E3FAB_AMB623ZF01_HD` (`lcd_id1=811043`), and the
> merged post-ABL DT agrees. So it is **S6E3XA2, not XA1** — the uncertainty this file
> previously flagged is resolved.

## 1. Main panel — S6E3XA2_AMF755ZE01 (inner, foldable)

DTS node `ss_dsi_panel_S6E3XA2_AMF755ZE01_QXGA`, lines 12238–12624.

### Modes — 4 timing nodes

| node | resolution | fps | h pw/bp/fp | v pw/bp/fp | bit clock | DSC slice | xfer µs |
|---|---|---|---|---|---|---|---|
| `qxga120hs` | 2208×1768 | 120 | 76/76/76 | 68/68/61 | 1,362,000,000 | 1104×34 | 7533 |
| `qxga96hs` | 2208×1768 | 96 | 76/76/76 | 68/67/62 | 1,362,000,000 | 1104×34 | 7533 |
| `qxga60hs` | 2208×1768 | 60 | 76/76/76 | 68/66/63 | 1,362,000,000 | 1104×34 | 7533 |
| `qxga48hs` | 2208×1768 | 48 | 76/76/76 | 68/65/64 | 1,362,000,000 | 1104×34 | 7533 |

- **Natively landscape.** 2208 wide × 1768 high, physical 149 × 119 mm. The aspect ratios
  agree to three decimal places (1.2489 vs 1.2521), so this is not a DTS error — the glass
  scans along the hinge and the compositor must rotate.
- **The bit clock is constant across all four modes**, and `vtotal` is a constant **1965**
  (1768 + vfp + 68 + vbp, with the porch split shifting). Expected for a command-mode
  panel: refresh rate is set by how often the host pushes a frame, not by blanking.
- **DSI PHY timings are identical in all four modes:**
  `[00 2c 0c 0c 29 26 0c 0c 0b 02 04 00 25 1b]`

### DSC (from the transmitted PPS blob)

```
dsc_version        1.1          pic_width          2208
bits_per_component 8            pic_height         1768
linebuf_depth      9            slice_width        1104
bits_per_pixel     8.0          slice_height       34
  (raw 128, 1/16 units)         slices_per_line    2
block_pred_enable  1            chunk_size         1104
convert_rgb        1            initial_xmit_delay 512
                                initial_dec_delay  808
```

8.0 bpp from 24 bpp input is exactly **3:1 compression**.

### Init sequences — the useful finding

All four modes carry a **602-byte** `qcom,mdss-dsi-on-command` → 50 commands, 120 ms total
delay. There are only **two unique streams**, and they differ by **exactly one byte**:

| | modes | `0xb9` payload |
|---|---|---|
| variant 0 | `qxga120hs`, `qxga96hs` | `b9 01 **00** 06 fe 07 09` |
| variant 1 | `qxga60hs`, `qxga48hs` | `b9 01 **01** 06 fe 07 09` |

Everything else in all 602 bytes is byte-identical. So one init sequence plus a single
per-mode byte covers the whole panel.

`off-command`: 56 bytes, 6 commands — level keys, `0x28` display off, `0x10` sleep in,
keys off, 120 ms.

### Platform wiring

```
reset-gpio     tlmm 14
te-gpio        tlmm 82
mipisel-gpio   tlmm 97,  on_val 1
reset-sequence <1 10>  (assert, 10 ms)

panel_vdd3      1.8 V  (enable load 100 mA)
panel_vddr      1.8 V  (1.6 V in LPM, per samsung,lpm-power-control-*)
panel_vci       3.0 V  (10 ms post-on sleep)
panel_vdd3_sub  1.8 V
                 all from the S2DOS05 display PMIC (upstream)

topology       <2 2 1>   lm-split <1104 1104>   dsc-encoders 2
roi-alignment  1104 x 34 (= one DSC slice), partial-update "single_roi"
backlight      bl_ctrl_dcs, levels 1..510 (0x1fe), default 255
```

---

## 2. Cover panel — S6E3FAB_AMB623ZF01 (outer)

DTS node `ss_dsi_panel_S6E3FAB_AMB623ZF01_HD`, lines 10819–11336.

### Modes — 6 timing nodes

| node | resolution | fps | h pw/bp/fp | v pw/bp/fp | bit clock | DSC slice | xfer µs |
|---|---|---|---|---|---|---|---|
| `hd120hs` | 832×2268 | 120 | 40/40/63 | 60/60/146 | 766,000,000 | 416×42 | 7533 |
| `hd96hs` | 832×2268 | 96 | 40/40/63 | 60/60/778 | 766,000,000 | 416×42 | 9616 |
| `hd60hs` | 832×2268 | 60 | 40/40/63 | 60/60/2680 | 766,000,000 | 416×42 | 15666 |
| `hd60phs` | 832×2268 | 60 | 40/40/63 | 60/59/2681 | 766,000,000 | 416×42 | 7533 |
| `hd48hs` | 832×2268 | 48 | 40/40/63 | 60/60/3945 | 766,000,000 | 416×42 | 20032 |
| `hd48phs` | 832×2268 | 48 | 40/40/63 | 60/59/3946 | 766,000,000 | 416×42 | 9616 |

Portrait, constant resolution. Unlike the main panel, the cover panel varies refresh via a
large `vfp` (146 → 3946) rather than keeping `vtotal` fixed. The `*phs` variants pair the
same refresh rate with a different transfer time — presumably the low-frequency-driving
idle variants.

DSI PHY timings, identical across all six: `[00 1a 07 06 22 21 07 07 07 02 04 00 18 16]`

### DSC (from the transmitted PPS blob)

```
dsc_version 1.1   pic_width 832    slice_width 416   slices_per_line 2
bpc 8             pic_height 2268  slice_height 42   chunk_size 416
bits_per_pixel 8.0 (3:1)           initial_xmit_delay 512
block_pred_enable 1                initial_dec_delay  465
```

### Init sequences
Six modes, **556 bytes** each, **two unique streams** differing by one byte in the `0x60`
command: `60 20` (modes `hd120hs`, `hd96hs`, `hd60phs`, `hd48phs`) vs `60 00`
(`hd60hs`, `hd48hs`).

`off-command`: 38 bytes, 4 commands — `0x28` + 20 ms, `0x10`, keys off + 120 ms.

### ⚠️ A contradiction in the vendor DTS, recorded deliberately

The cover panel's `qcom,mdss-dsi-timing-switch-command` sets, **in all six modes**:

```
0x2a (set_column_address)  0..1079   -> 1080 px
0x2b (set_page_address)    0..2339   -> 2340 px
```

That is **1080×2340**, not the 832×2268 that the panel-width/height properties, the DSC
PPS, and the physical dimensions (54 × 148 mm, aspect 0.365 vs 0.367) all agree on.

Assessment: almost certainly **stale vendor boilerplate** copied from an FHD+ panel —
1080×2340 is a stock Samsung resolution, and the values are identical across all six
modes, which is the signature of copy-paste rather than intent. The main panel sends no
`0x2a`/`0x2b` at all.

**Do not transcribe those two commands.** Either omit them (as the main panel does) or
send the correct `0..831` / `0..2267`. Flagged for on-hardware resolution rather than
silently copied.
