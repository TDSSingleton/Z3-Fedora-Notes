> **HISTORICAL** — written during planning, before any code existed. Parts are now wrong.
> See [HANDBOOK.md](HANDBOOK.md) for the current state.

# Roadmap

Seven phases. Each has an **exit criterion** that is a demonstrable fact, not a feeling.
Don't start a phase before its predecessor's exit criterion is met — on a project with
this much irreversible state, skipping ahead is how devices die.

Effort estimates assume one person, evenings and weekends, already fluent in C and
kernel build mechanics.

---

## Phase 0 — Reconnaissance and insurance
~1–2 weeks · *Steps 1–3 are reversible; step 4 onward is not.*

1. ~~Answer the blocking questions~~ — **both done.** Q1: the device is unlockable
   ([08-device-facts.md](Hard%20Truths/08-device-facts.md)). Q2: uniLoader port scoped
   ([09-bootloader-plan.md](09-bootloader-plan.md)). **Turn off automatic system updates.**
2. Archive full stock firmware for this exact model and region.
3. **Disable automatic system updates**, then **unlock** (Knox trips, `userdata` wiped;
   `EFS`/`persist` survive), then flash TWRP to `recovery`.
4. **`tools/01-backup-critical.sh` immediately** — `EFS`, `sec_efs`, `persist`,
   `modemst1/2`, `fsg`, `fsc` + recovery images, hash-verified, two off-device copies.
   Then `tools/02-extract-firmware.sh` for vendor firmware.
   *(Note: these need root, so they come* after *unlock — see
   [11-extraction-plan.md](11-extraction-plan.md) §0 for why.)*
5. **Root, then run `tools/00-collect-facts.sh`.** One pass captures:
   - the merged **post-ABL** device tree (Q8) — shows what ABL does to a DTB
   - which main-panel DDIC is fitted, `S6E3XA1` vs `S6E3XA2` (Q9)
   - QCA6490 SoC hw version — decides whether `ath11k` accepts it (Q5)
   - `bat_enb` GPIO default states — decides the charging plan (Q4,
     [10-battery-plan.md](10-battery-plan.md))
   - `/proc/iomem` + boot image header — the three uniLoader load addresses
   - audio amp variant (Q10), full `dmesg`, partition map

**Exit:** you can restore this device to stock from your own archives, and
`tools/00-collect-facts.sh` output is safely off-device.

> The stock firmware archive (step 2) is the only part that must happen **before**
> unlocking. Everything else needs root, which needs unlock. The hardware facts and
> Tier-1 backups are readable after unlock because unlock wipes `userdata` but leaves
> `EFS`/`persist` intact — see [11-extraction-plan.md](11-extraction-plan.md) §0.

---

## Phase 1 — First boot, console only
~2–6 weeks

Goal: a mainline kernel executing its own code on the device, with a way to see output.
Nothing else.

1. **Port uniLoader to `q2q`** — the five files in
   [09-bootloader-plan.md](09-bootloader-plan.md) §2, using the load addresses measured
   in Phase 0. Cheap experiment worth trying first: whether a `vendor_boot`-injected DT
   boots through the stock chain, as it does on the M52.
2. Write a minimal `sm8350-samsung-q2q.dts`. Model it directly on
   `sm8450-samsung-r0q.dts`: `chosen` + `simple-framebuffer`, `vph_pwr`, the `pm8350` /
   `pm8350c` rpmh regulator tree, `splash-region@e4000000`, `gpio-reserved-ranges`, and
   USB 2.0 peripheral only.
3. Get a console. In rough order of preference:
   - **`simple-framebuffer` on `cont_splash_region` @ `0xE4000000`** (35 MiB region;
     a 2208×1768×32bpp buffer needs 14.89 MiB) — gives a visible console with no
     display driver. Add `clocks` and `power-domains` to the node; the Tab S8 port
     reports the bootloader scanout is torn down without them.
   - **USB gadget network + SSH** once USB works.
   - **UART over USB-C** via the `qcom,msm-geni-serial-hs` pins, if accessible — the most
     reliable early-boot debugging, and worth the effort to find the test points.
4. Minimal initramfs, `CONFIG_CMDLINE_FORCE`, `earlycon`.

**Exit:** kernel log visible, kernel reaches userspace, `reboot` works.

---

## Phase 2 — Core platform
~2–4 weeks

1. **UFS** — root filesystem from internal storage. The S22 port notes mainline needs
   `rootfs_image_sector_size=4096` on Samsung UFS; expect the same class of quirk.
2. **USB** — `usb_1` in peripheral mode first (copy `r0q`: USB 2.0 only, drop the SS
   PHY), then host mode.
3. **Buttons** — power and volume via `gpio-keys`.
3b. **Touch (inner screen only)** — `stm,stm_ts_spi` on SPI. Templates: `fts1ba90a`
   (Tab S8) and `fts2ba61y` (S22). The cover digitiser and the `wacom` S-Pen digitiser
   are both deliberately **not** built.
4. **Hall sensors** — the `hall` and `flip` GPIOs, exposed as switches. Needed later for
   fold-state display switching, trivial to do now.
5. **GPU** — Adreno 660 via freedreno; `gpucc-sm8350` is already upstream.
6. **[3P] Blocklist `qcrypto`** — reported to hang the phone via Samsung's TrustZone.

**Exit:** boots to a shell from internal storage, reachable over SSH on USB.

---

## Phase 3 — Goal 1 (charging) + Goal 2 (Wi-Fi/Bluetooth)
~3–6 weeks

These are grouped because they're independent of display and of each other, and both are
mostly device-tree plus firmware plumbing rather than new drivers.

**Charging:**
1. `max77705` MFD on its I²C bus, then `max77705_charger`.
2. Type-C / PD: upstream `tcpm/` has no `max77705` entry; the S22 port carries
   "MAX77705 rev2" patches. Expect to port those.
3. Battery: `samsung-sdi-battery` for profile data. **Resolve the dual-cell safety
   question (Q4) before leaving it charging unattended.**
4. Accept the loss of `sm5451` fast charge and `s2miw04` wireless charge.

**Wi-Fi / Bluetooth:**
1. `pcie0` up, QCA6490 enumerating.
2. Check the reported SoC hw version against `ath11k`'s accepted set (Q5). If it lands
   outside, this becomes a driver task rather than a configuration task.
3. Install extracted firmware + board file; `ath11k` up.
4. Bluetooth via `hci_qca`, MAC from `EFS`. **[3P]** Enable the **PMR735A L7** rail —
   the S22 port reports Bluetooth needs it.
5. **[3P]** Expect 2.4 GHz trouble: the S22 port has 5 GHz working and 2.4 GHz
   association timing out.

**Exit:** device charges from a USB-C charger and reports sane battery state; associates
to Wi-Fi; pairs a Bluetooth device.

---

## Phase 4 — Goal 3 (both screens)
~1–3 months *(revised down: the clock-driver work turned out to be unnecessary)*

1. ~~Write `dispcc-sm8350.c`~~ — **not needed.** The SM8350 display clock controller is
   already upstream inside the multi-SoC `dispcc-sm8250.c`; just enable
   `CONFIG_SM_DISPCC_8250`. DPU, DSI controller and 5nm PHY are upstream too, and
   `sm8350.dtsi` is already wired correctly. See
   [Hard Truths/02-upstream-status.md](Hard%20Truths/02-upstream-status.md) §3.
   *This removes what an earlier revision of this plan wrongly called the critical path,
   and takes an estimated 2–6 months of clock-driver work off Phase 4.*
2. **Write `panel-samsung-s6e3xa2.c`** — main panel, 2208×1768, cmd mode, 4 lanes,
   DSC 2×(1104×34), DCS backlight 1–510, 120/96/60/48 Hz. Init sequences come from
   `SM-F926B/Kernel/techpack/display/msm/samsung/S6E3XA2_AMF755ZE01/`. Template:
   upstream `panel-samsung-s6e3fa7.c` / `s6e3ha8.c`, and the S22 port's
   `panel-samsung-s6e3fac.c`.
   **[3P] Known gotcha from the S22 panel:** send DCS `0x53` *before* `0x51`, and send
   the DSC PPS once from `drm_dsc_config`.
3. **Bring up DSI0 + main panel alone** on native KMS. Milestone: Wayland on the inner
   screen.
4. **Write `panel-samsung-s6e3fab.c`** — cover panel, 832×2268, DSC 2×(416×42).
   Source: `.../S6E3FAB_AMB623ZF01/`. Display only — no touch driver for this screen.
5. **Dual DSI concurrently.** No mainline SM8350 device does this today, so budget real
   time. The DPU catalog (`dpu_7_0_sm8350.h`) has 4 DSC blocks and 4 INTFs, and the two
   panels have independent controllers, PHYs and TE lines, so the hardware is capable.
   Remember the main panel's `mipisel` GPIO (**TLMM gpio97**, drive high on power-on, low
   on power-off) in its `prepare()`/`unprepare()`.
6. **Leave the cover touchscreen disabled** — your requirement, and it saves work.
7. Fold-state → display switching, driven by the Phase 2 hall sensors.

**Exit:** both panels light up under DRM/KMS with correct colours and no tearing; main
screen runs a compositor; cover screen is display-only.

---

## Phase 5 — Goal 4 (Fedora)
~2–4 weeks, parallelisable with Phase 4

See [06-fedora-strategy.md](06-fedora-strategy.md). Build a Fedora aarch64 rootfs around
your own kernel RPM, with vendor firmware packaged or extracted via `droid-juicer`.

**Exit:** Fedora userspace, `dnf` works, a compositor starts on the main screen.

---

## Phase 6 — Goal 5 (4G LTE + hotspot)
~1–3 months, optional

1. `qcom,sm8350-mpss-pas` remoteproc + modem firmware from the `modem` partition.
2. `qrtr`, `qmi_wwan` / `rmnet`, ModemManager. Verify the modem comes online over QMI.
3. **IPA:** `qcom,sm8350-ipa` **is upstream** — this is the Fold 3's structural advantage
   over the S22 port, where missing SM8450 IPA is exactly what blocks mobile data.
4. SIM via `pm8350c` `ldo4`/`ldo5` (`vreg_l4c_uim1` / `vreg_l5c_uim2` in the Surface
   Duo 2 DT).
5. Hotspot: NetworkManager AP mode over `ath11k`, subject to QCA6490 AP support.

**Exit:** data session over LTE; a second device reaches the internet through the Fold 3.

---

## Deliberately out of scope

Cameras (no `camss` for SM8350, and unlock may disable them anyway), fingerprint, S Pen,
UWB, NFC, wireless charging, fast charging, DeX. Audio is not a stated goal but is
largely upstream (`wcd938x`, `wsa883x`, `cs35l41`) and would be comparatively cheap if
you want it.

---

## Critical path

```
Q1 unlockable? ──► Q2 shim loader ──► Phase 1 boot ──► Phase 2 platform ──┬─► Phase 3 charge/wifi ──► done (goals 1,2)
                                                                          ├─► Phase 5 Fedora ──────► done (goal 4)
                                                                          └─► Phase 4 panels ──► dual DSI ──► done (goal 3)
                                                                                                                  └─► Phase 6 modem (goal 5)
```

Goals 1, 2 and 4 are reachable in roughly the first third of the effort. Goal 3 is most
of the remaining two thirds, and nearly all of that is the three drivers in Phase 4.

---

*Moved here from `Hard Truths/02-upstream-status.md` on 2026-11-06: these are judgement calls, not verified facts, so they don't belong under that name. The evidence behind them is still in that file.*

## Appendix — goal-by-goal feasibility assessment

### Goal 1 — Charging ✅ likely

`MFD_MAX77705` and `CHARGER_MAX77705` are both upstream, and the Galaxy S22 port reports
MAX77705 USB-C hotplug and charging working. Gaps: no `sm5451` (fast charge), no
`s2miw04` (wireless), no `s2asl01` (dual-cell balancing). Basic wired charging should
come up with device-tree work plus possibly small driver fixes. **Open safety question
about the dual-cell pack — see [05-research-gaps.md](05-research-gaps.md) Q4.**

### Goal 2 — Wi-Fi + Bluetooth ✅ likely

QCA6490 shares PCI ID `0x1103` with `ath11k`'s WCN6855 path, and PCIe (`pcie0`) is
upstream. Two real dependencies:
- The chip's reported SoC hw version must be one `ath11k` accepts (else `-EOPNOTSUPP`).
- Firmware and the board file must be extracted from the device's own partitions; the
  Bluetooth MAC lives in `EFS`.

### Goal 3 — Both screens ⚠️ hardest, achievable

Needs, in order: `panel-samsung-s6e3xa2` (written, untested), `panel-samsung-s6e3fab`
(decoded, not written), then dual-DSI concurrent output with DSC — which no mainline
SM8350 device does today. The SoC-level display stack is already upstream.

Encouragingly, the hardware topology supports simultaneous output: separate DSI
controllers, separate PHYs, separate TE GPIOs, and 4 DSC blocks / 4 INTFs in the DPU
catalog. And `samsung,mipisel-gpio` — which first looked like it might be a lane mux
between the panels — turns out to be just a GPIO toggled with the main panel's power
sequence (see [01-hardware-inventory.md](Hard%20Truths/01-hardware-inventory.md) §2). So nothing known
rules out driving both screens at once; it is new work, not blocked work.

**Mitigation:** `simple-framebuffer` on `cont_splash_region` @ `0xE4000000` gives you a
working main-screen console immediately, with no display driver at all, exactly as
`sm8450-samsung-r0q.dts` does. Ship that in Phase 1 and treat native KMS as Phase 4.

Reported `simplefb` traps from the two Samsung precedents, worth knowing in advance:
the Tab S8 port says `simplefb` needs `clocks` and `power-domains` properties or the
bootloader's scanout gets torn down; the S22 port says `dispcc` had to be a **module**
rather than built-in, or the framebuffer came up garbled. On SM8350 the absence of a
dispcc driver is present and will be a module by default (`default m if ARCH_QCOM`),
which matches what the S22 port found necessary.

Your "cover screen, touchscreen off" requirement costs nothing — just don't enable the
cover's I²C touch node.

### Goal 4 — Fedora, as upstream as possible ✅ with custom work

See [06-fedora-strategy.md](06-fedora-strategy.md). Short version: an official Fedora KDE
Plasma Mobile aarch64 spin exists (F45 beta), and Pocketblue builds Fedora Atomic phone
images — but Pocketblue requires UEFI/U-Boot, which the Fold 3 does not have. Expect to
assemble a Fedora rootfs yourself around your own kernel package.

### Goal 5 — 4G LTE + hotspot ⚠️ plausible, better odds than expected

`qcom,sm8350-mpss-pas` **and** `qcom,sm8350-ipa` are both upstream. This matters: the
Galaxy S22 port has the modem online over QMI but **no mobile data, explicitly because
there is no SM8450 IPA driver in mainline**. SM8350 does not have that problem. With
modem firmware from the `modem` partition, `qrtr` + `rmnet`/IPA + ModemManager, data is
a realistic target. Hotspot is then ordinary `NetworkManager`/`hostapd` on top — subject
to QCA6490 AP mode working.

---

## Appendix — kernel version strategy

- **Don't** base on `sm8350-mainline` (6.7.0-rc3, stale).
- **Do** base on current mainline or the latest stable, and carry your work as a patch
  series on top. The Samsung precedents sit on 7.1.x–7.2.x, and the host here already
  runs Fedora 44 with a 7.2.4 kernel.
- Keep both panel drivers and the board DTS as clean, separately-upstreamable patches
  from day one. They are genuinely wanted upstream, and keeping them clean costs nothing
  if you do it from the start.
