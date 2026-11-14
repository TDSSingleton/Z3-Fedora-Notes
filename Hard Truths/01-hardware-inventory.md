# Hardware inventory — SM-F926B (`q2q`)

**Source of truth:** `SM-F926B/Kernel/arch/arm64/boot/dts/samsung/q2/q2q/q2q_eur_openx_w00_r08.dts`
(17,889 lines), cross-referenced against the live `torvalds/linux` tree on 2026-11-06.
Upstream status was checked by fetching the relevant `Makefile`/`Kconfig` from
git.kernel.org, not from memory.

The Samsung drop is **kernel 5.4.274**, config `vendor/q2q_eur_openx_defconfig`,
platform `lahaina`. Board DTS files exist for hardware revisions r01–r08; `r08` is the
newest and is what the tables below use.

---

## 1. SoC and core platform

| Item | Value |
|------|-------|
| SoC | Qualcomm Snapdragon 888 — **SM8350**, codename `lahaina` |
| Upstream DT | `arch/arm64/boot/dts/qcom/sm8350.dtsi`, 4,634 lines — mature |
| Board model string | `Samsung Q2Q PROJECT - REV0.4 (board-id,08)` |
| `qcom,board-id` | `<0x10008 0x8>` |
| ABL compatible | `QCOM,LAHAINA-MTP`, `QCOM,LAHAINA`, `QCOM,MTP` |
| Storage | UFS 3.1 — `qcom,ufs-phy-qmp-v4-lahaina`; upstream `ufs_mem_hc` + `ufs_mem_phy` |
| GPU | Adreno 660 — upstream `gpu`/`gmu`/`gpucc`/`adreno_smmu`, freedreno/Turnip |

### PMIC complement (all standard SM8350, all upstream)

`pm8350`, `pm8350b`, `pm8350c`, `pmk8350`, `pmr735a`, `pmr735b` — via `qcom,spmi-pmic`
on `spmi_bus`, with `qcom,pm8350-rpmh-regulators` / `qcom,pm8350c-rpmh-regulators`.
The upstream `sm8350-microsoft-surface-duo2.dts` and `sm8450-samsung-r0q.dts` are both
usable as copy-paste references for the regulator tree.

Also present: `qcom,pmk8350-rtc`, `qcom,spmi-adc7` / `qcom,adc-tm7` (thermal),
`qcom,pm8350c-flash-led`, `qcom,pm8350b-swr-haptics`, `qcom,pwm-lpg`, `qcom,tri-led`.

> **Known trap (reported by the Galaxy S22 port):** Bluetooth needs the **PMR735A L7**
> rail enabled, and `qcrypto` must stay blocklisted or Samsung's TrustZone hangs the
> phone. Both are worth remembering early.

---

## 2. Displays — the centre of the project

Two **command-mode** DSI panels, both 4-lane, both using **DSC** compression, both with
DCS backlight control. Resolutions and physical dimensions are self-consistent
(aspect ratios agree to 3 decimal places), which is a good sign the DTS values are real.

| | **Main (inner, foldable)** | **Cover (outer)** |
|---|---|---|
| DDIC / module | `S6E3XA2_AMF755ZE01` (rev r08; earlier revs use `S6E3XA1`) | `S6E3FAB_AMB623ZF01` |
| Resolution | **2208 × 1768** (natively *landscape*) | **832 × 2268** (portrait) |
| Physical size | 149 × 119 mm | 54 × 148 mm |
| Refresh modes | 120 / 96 / 60 / 48 Hz | 120 / 96 / 60 / 48 Hz |
| DSI bit clock | 1,362,000,000 Hz (1362 MHz) | 766,000,000 Hz (766 MHz) |
| DSC slice | 1104 × 34 → 2 slices across | 416 × 42 → 2 slices across |
| H timings (pw/bp/fp) | 76 / 76 / 76 | 40 / 40 / 63 |
| V timings (pw/bp/fp @120Hz) | 68 / 68 / 61 | 60 / 60 / 146 |
| Mode | `dsi_cmd_mode`, TE pin, `rgb_swap_rgb`, 24 bpp | same |
| Backlight | `bl_ctrl_dcs`, levels 1–510 (`0x1fe`) | `bl_ctrl_dcs`, levels 1–510 |
| Extra GPIOs | reset, TE, **`samsung,mipisel-gpio`** | reset, **`platform-sec-reset-gpio`**, TE, `esd-irq-gpio1` |

**Note the main panel is natively 2208 × 1768 — landscape.** The compositor will have to
rotate it. This is not a DTS typo; the physical dimensions (149 mm wide × 119 mm tall)
confirm the scan orientation.

### `samsung,mipisel-gpio` — resolved

Initially this looked like it might be a MIPI lane mux between the two panels, which
would have been a serious problem for Goal 3. It is not. Traced through the Samsung
source:

- DTS: `samsung,mipisel-gpio = <&tlmm 0x61 0>` → **TLMM `gpio97`**, `samsung,mipisel-on_val = <1>`,
  with `panel_*_mipisel_active` / `_suspend` pinctrl states (plain `gpio` function,
  drive-strength 2, `bias-disable`) — identical in both states.
- `techpack/display/msm/samsung/ss_dsi_panel_common.c:5375` parses it.
- `techpack/display/msm/dsi/dsi_panel.c:532` drives it to `mipisel_on_val` (**1**) during
  panel **power-on**, and `:652` drives it to `!mipisel_on_val` (**0**) during
  **power-off**.

So it is simply a GPIO raised and lowered with the main panel's power sequence — most
likely a lane-switch or redriver *enable* on the flex that crosses the hinge. In a
mainline DRM panel driver this is one `gpiod` toggled in `prepare()`/`unprepare()`.

It is present only on the main panel (both `S6E3XA1` and `S6E3XA2` variants), never on
the cover panel. It does **not** arbitrate between the two displays: the two panels have
separate DSI controllers, separate PHYs and separate TE GPIOs (`0x52` primary, `0x53`
secondary), which is not a topology you would build for a 2:1 mux.

### Display upstream status

| Piece | Upstream? | Notes |
|---|---|---|
| DPU / MDSS | ✅ `qcom,sm8350-mdss`, `mdss_mdp` | Catalog `dpu_7_0_sm8350.h`: **4 DSC blocks, 4 INTFs** |
| DSI controllers | ✅ **both** `mdss_dsi0` + `mdss_dsi1` | `qcom,sm8350-dsi-ctrl` |
| DSI PHYs | ✅ both | `qcom,sm8350-dsi-phy-5nm` |
| DisplayPort | ✅ `mdss_dp` | For USB-C video out |
| Display clock controller | ✅ **`dispcc-sm8250.c`** | Multi-SoC driver; claims `qcom,sm8350-dispcc`. `CONFIG_SM_DISPCC_8250`. |
| Main panel driver | ❌ none | No `panel-samsung-s6e3xa*` upstream |
| Cover panel driver | ❌ none | No `panel-samsung-s6e3fab` upstream |
| Panel power rail | ✅ `REGULATOR_S2DOS05` | `samsung,s2dos05pmic` — the display PMIC *is* upstream |

**Correction (2026-11-06):** this previously said the display clock controller was
missing and called it the project's critical path. That was wrong — `qcom,sm8350-dispcc`
is claimed by `dispcc-sm8250.c`, a four-SoC driver that applies SM8350's register deltas
at runtime. See [02-upstream-status.md](02-upstream-status.md) §3.

**So the whole SM8350 display chain is upstream** — dispcc, DPU, DSI controller and 5nm
DSI PHY. The only missing display pieces are the two panel drivers below.

Upstream panel drivers in the same family, useful as templates: `panel-samsung-s6e3fa7`,
`panel-samsung-s6e3ha8`, `panel-samsung-s6e3fc2x01`.

### Bootloader splash framebuffer (the Phase-1 shortcut)

```
cont_splash_region   @ 0xE4000000, size 0x2300000  (35 MiB)
disp_rdump_region    @ 0xE4000000, size 0x1200000
dfps_data_region     @ 0xE6300000, size 0x100000
```

A 2208 × 1768 × 32 bpp framebuffer is 14.89 MiB, which fits in the 35 MiB region. This
lets you use `simple-framebuffer` to get pixels on screen with **zero display driver
work** — exactly what the upstream `sm8450-samsung-r0q.dts` does. That DTS carries a
comment worth copying verbatim:

> *The bootloader will only keep display hardware enabled if this memory region is named
> exactly `splash_region`.*

---

## 3. Touch and pen

| Device | Compatible | Bus | Upstream? |
|---|---|---|---|
| Main touchscreen | `stm,stm_ts_spi` (`touchscreen@0`, `fragment@142`) | **SPI** | ❌ `stmfts` upstream is a *different*, older ST part |
| Cover touchscreen | `stm,stm_ts` (`touchscreen@49`, `fragment@123`) | **I²C** | ❌ same |
| S Pen digitiser | `wacom,w90xx` (`wacom@56`) | I²C | ❌ |
| Fingerprint | `goodix,fingerprint` (`gw3x`) | SPI | ❌ |

The main/cover assignment is **inferred** from DTS fragment ordering (`fragment@136` =
main panel is immediately followed by `fragment@142` = SPI touch; `fragment@118` = cover
panel is followed by `fragment@123` = I²C touch) and from the main panel being the
higher-bandwidth, S-Pen-capable surface. Confirm on device — see
[05-research-gaps.md](../05-research-gaps.md) Q6.

**Your "cover screen with touchscreen off" requirement is free:** leave
`touchscreen@49`'s node out of the device tree, or mark it `status = "disabled"`.

Both touch drivers must be written. Two recent precedents exist to crib from —
`fts1ba90a` (Galaxy Tab S8 port) and `fts2ba61y` (Galaxy S22 port) — both are the same
STM `stm_ts` generation.

---

## 4. Power, charging and battery

The Fold 3 has a **dual-cell battery** with per-cell current limiters. This is the part
with no upstream precedent.

| Device | Compatible | Role | Upstream? |
|---|---|---|---|
| Main PMIC / charger | `maxim,max77705` | Charger, fuel gauge, OTG, Type-C PD | ✅ `MFD_MAX77705` + `CHARGER_MAX77705` |
| Type-C / PD controller | `maxim,max77705_pdic` | USB-C orientation, PD negotiation | ⚠️ partial — no `max77705` entry in `tcpm/Makefile` |
| Direct charger | `siliconmitus,sm5451` | Switched-cap charge pump (fast charge) | ❌ none |
| Wireless charger | `lsi,mfc-s2miw04-charger` | Qi receiver | ❌ none |
| Dual-battery limiter | `samsung,s2asl01-limiter` (main@38 + sub@39) | Balances the two cells | ❌ none |
| Battery framework | `samsung,sec-battery`, `samsung,sec-direct-charger`, `samsung,sec-dual-battery` | Samsung's own stack | ❌ (but `BATTERY_SAMSUNG_SDI` upstream carries profile data) |
| Display PMIC | `samsung,s2dos05pmic` | Panel rails | ✅ `REGULATOR_S2DOS05` |
| Camera PMIC | `s2mpb02,s2mpb02mfd` | Camera rails + torch | ❌ (out of scope) |

**Practical read:** basic USB-C charging through `max77705_charger` is realistic and is
your Goal 1. Expect to **lose** fast charging (no `sm5451`), wireless charging (no
`s2miw04`), and proper two-cell balancing (no `s2asl01`). Whether charging a dual-cell
pack without the limiter driver is *safe* is an open question — see
[05-research-gaps.md](../05-research-gaps.md) Q4. Treat it as a safety question, not a
feature question.

---

## 5. Wireless

| Device | Part | Upstream? |
|---|---|---|
| Wi-Fi + BT combo | **QCA6490** (`qcom,cnss-qca6490`, PCIe, `lahaina.dtsi:5381`) | ⚠️ see below |
| PCIe root complex | `qcom,wlan-rc-num = <0>` → upstream `pcie0` | ✅ |
| Modem | SM8350 integrated (Snapdragon X60) | ✅ `qcom,sm8350-mpss-pas` |
| Modem data path | IPA | ✅ **`qcom,sm8350-ipa` is upstream** |
| NFC | `pn547` / `qcom,sn-nci` | partial |
| UWB | `nxp,sr100` | ❌ |
| GNSS | via SLPI / QRTR | ✅ `qcom,sm8350-slpi-pas` |

### The QCA6490 question, resolved

`ath11k` has **no `qca6490` entry** in its `hw_params` table. But the downstream
`cnss2/bus.h` defines `QCA6490_DEVICE_ID = 0x1103` — and that is **the same PCI device
ID `ath11k` calls `WCN6855_DEVICE_ID`**. So a QCA6490 binds through `ath11k`'s WCN6855
code path, where the exact `hw_rev` is then chosen from the SoC hardware version read
off the chip:

- major 2, minor `0x00`/`0x01` → `ATH11K_HW_WCN6855_HW20`
- major 2, minor `0x10`/`0x11` → `HW21` / `QCA2066_HW21` / `QCA6698AQ_HW21` by sub-version
- anything else → `-EOPNOTSUPP`, "Unsupported WCN6855 SOC hardware version"

So Wi-Fi hinges on what revision this specific chip reports. The Galaxy S22 port
reports `ath11k` Wi-Fi working on 5 GHz (2.4 GHz association times out) using
**Samsung's own firmware and board file**, which is encouraging but needs confirming on
our hardware. Bluetooth goes via `hci_qca`, and **the BT MAC address lives in the `EFS`
partition** — back that up before anything else.

---

## 6. Audio (not a stated goal, listed for completeness)

| Device | Upstream? |
|---|---|
| `qcom,wcd938x-codec` + `wcd938x-slave` | ✅ `SND_SOC_WCD938X` |
| `qcom,wsa883x` speaker amp | ✅ `SND_SOC_WSA883X` |
| `cirrus,cs35l41` amp | ✅ `SND_SOC_CS35L41` |
| `cirrus,cs40l25a` haptics | ⚠️ upstream has `cs40l50`, not `cs40l25a` |
| `sma-amp` / `sma1305` | ⚠️ upstream has `sma1303`/`sma1307` |
| `ti,tas256x` | ⚠️ upstream has `tas2562` |
| LPASS / ADSP routing (`q6afe`, `q6asm`, `q6routing`) | ✅ in `sm8350.dtsi` |

Several amp variants appear in one DTS because Samsung ships different parts per region;
only one is populated on any given unit. Determine which from a running device.

---

## 7. Sensors and misc

| Device | Role | Upstream? |
|---|---|---|
| `hall_ic` (`hall` + `flip` GPIOs), `digital_hall@10` | **Fold-state detection** — needed to switch screens | ❌ needs glue; GPIOs are trivial via `gpio-keys` |
| `sx9360`, `sx9360_sub` | SAR proximity | ✅ `SX9360` |
| `stk,stk3a8x` | Ambient light / proximity | ❌ |
| `akm` | Magnetometer | partial |
| `nxp,pca953x` | I²C GPIO expander | ✅ `pca953x` |
| `qcom,cam-sensor0..13`, `qcom,ois`, `qcom,actuator`, `qcom,eeprom` | Cameras (4 + OIS) | ❌ no `camss` for SM8350 — out of scope |

The hall sensors are how you know whether the device is open or shut, so they matter
more than their obscurity suggests: Goal 3 ("both screens") implies switching the active
display on fold/unfold.

---

## 8. Summary — what has to be written from scratch

Ordered by how much they block your goals:

1. **`panel-samsung-s6e3xa2.c`** — main foldable panel, 2208×1768, cmd mode, DSC.
   *Written* — see `panel-work/`. Not yet compiled or run.
2. **`panel-samsung-s6e3fab.c`** — cover panel, 832×2268, cmd mode, DSC. Decoded, not written.
3. **STM `stm_ts` touch driver** — main screen (SPI). Cover screen deliberately skipped.
4. **Dual-battery / `s2asl01` handling** — or a justified decision to run without it.
5. Fold-state input glue, `sm5451` fast charge, `s2miw04` wireless charge, `w90xx` pen,
   `goodix` fingerprint — all optional for your goals.

*No display clock controller work is needed — that was an error in an earlier revision of
this file.*
