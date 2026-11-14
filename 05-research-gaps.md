> **HISTORICAL** — written during planning, before any code existed. Parts are now wrong.
> See [HANDBOOK.md](HANDBOOK.md) for the current state.

# What I need from you

**Status as of 2026-11-06: both blocking questions are resolved. The project is viable.**

| Q | Topic | Status |
|---|---|---|
| Q1 | Unlockable? | ✅ **YES** — `sys.oem_unlock_allowed=1`, `warranty_bit=0` → [08-device-facts.md](Hard%20Truths/08-device-facts.md) |
| Q2 | Shim bootloader | ✅ **Scoped** — uniLoader port ≈60 lines + 3 addresses → [09-bootloader-plan.md](09-bootloader-plan.md) |
| Q3 | Camera on unlock | ⏸️ deferred by you |
| Q4 | Dual-cell safety | ✅ **Answered + verified on device:** both `enb` GPIOs rest ENABLED |
| Q5 | QCA6490 revision | ✅ **hw 2.0** (3 independent signals) → `WCN6855_HW20`, no code change |
| Q6 | Which touchscreen | ✅ **Moot** — internal screen only, no S Pen |
| Q7 | `mipisel` GPIO | ✅ resolved (just a power-sequence GPIO) |
| Q8 | Merged post-ABL DT | ✅ **captured** — 27,092 props, 36,153-line DTS |
| Q9 | Panel revision | ✅ **S6E3XA2** confirmed (main), S6E3FAB (cover) |
| Q10 | Audio amp | ✅ **cs35l41** ×2 (top+bottom), upstream |
| Q11 | QCA6490 in `linux-firmware` | ✅ **NO** — must extract from device |
| Q12 | UART test point | ⏹️ dropped by you |

**All of these are now closed** except the direct `soc_hw_version` register read (Q5 is
answered indirectly, to high confidence). Captures are in `capture/` — see
[Hard Truths/08-device-facts.md](Hard%20Truths/08-device-facts.md) §R2 for the results.

The one thing still worth doing: **reboot and run `dmesg | grep -i cnss` immediately**, to
read the QCA6490 `soc_hw_version` directly. Both the live ring buffer and
`/proc/last_kmsg` had already wrapped (`log_buf_len=256K`), so the boot-time probe
messages were gone.

---

## Original question detail

---

## Blocking — answer these before touching the device

### Q1. Unlockable? ✅ **RESOLVED — YES**
Read off your device: `sys.oem_unlock_allowed = 1`, `ro.boot.warranty_bit = 0`,
`ro.boot.flash.locked = 1`, bootloader `F926BXXSJJZH3`, Android 15, patch 2026-08-05.
The Tab S8's binary ceiling does not apply. Full capture in
[08-device-facts.md](Hard%20Truths/08-device-facts.md).

**One action falls out of this: turn off automatic system updates now.** You are on an
unlockable bootloader; a future one might not be. Pure downside risk.

### Q2. Shim bootloader ✅ **RESOLVED — scoped task, not a blocker**
Answered by reading the repos directly. Summary:

- **lk2nd:** ruled out. Newest target is msm8996.
- **U-Boot:** ruled out *for now*. `drivers/clk/qcom/` has sm8250 and sm8550 but
  **no sm8350 and no sm8450**; U-Boot skips the same two generations the kernel skips
  for `dispcc`. Also its test path is `fastboot boot`, which Samsung lacks.
- **uniLoader:** ✅ the answer. Qualcomm 64-bit targets need **no SoC-specific code**
  (`soc/qualcomm/` contains only `msm8916.c`, yet `board-r0q.c` and `board-gts8wifi.c`
  support SM8450). The r0q board file is **517 bytes** — essentially just a framebuffer
  descriptor. We already know ours: ARGB8888, 2208×1768, `0xE4000000`.
- **Fallback:** the Galaxy M52 port boots mainline through the *stock* chain with a DT in
  `vendor_boot`. Worth one experiment.

Full file-by-file port plan, including the exact Kconfig stanzas, in
[09-bootloader-plan.md](09-bootloader-plan.md). The only genuine unknowns are
`TEXT_BASE`, `PAYLOAD_ENTRY` and `RAMDISK_ENTRY`.

---

## High value — needed early, answerable from the device

### Q3. Does unlocking the Fold 3 really disable the cameras?
**[3P]** XDA reported Samsung disables cameras on Fold 3 / Flip 3 on bootloader unlock. I
only saw the headline, not the article body, and I don't know whether later firmware or a
workaround changed it. Cameras aren't in your goals, but confirm you're willing to accept
it — along with the permanent Knox trip — before unlocking.

### Q4. Dual-cell charging ✅ **ANSWERED** → [10-battery-plan.md](10-battery-plan.md)
Short version: it is **not** reverse engineering — the full GPL source and register map
for `s2asl01` are in your own drop, so it's a port. And of your two interim options,
**"leave it to the hardware" is the safe one; "disable the smaller battery" is the
dangerous one** (the charger would still push a 4400 mAh pack's current into one ~2100 mAh
cell, with that branch's thermal shutdown unconfigured).

Plan: both cells connected, limiters untouched, **charge current capped at 500 mA–1 A**,
temperature limiting working before unattended charging.

**One thing still to check on-device:** the power-on default state of the `bat_enb` GPIOs.
Everything above assumes they come up enabled. `tools/00-collect-facts.sh` captures it.

### Q5. What SoC hardware version does your QCA6490 report? 🔑 **needs root**
Yes — this is the Wi-Fi chip. Not readable unrooted (I tried; `dmesg` and the `cnss2`
debugfs nodes are root-only). Captured by `tools/00-collect-facts.sh`.

**Why it matters:** `ath11k` has **no `qca6490` entry**, but QCA6490's PCI ID (`0x1103`)
is the one `ath11k` calls `WCN6855`. It then picks `hw_rev` from the chip's reported
version, and anything unexpected gets `-EOPNOTSUPP`:

- major 2, minor `0x00`/`0x01` → `WCN6855_HW20`
- major 2, minor `0x10`/`0x11` → `HW21` / `QCA2066_HW21` / `QCA6698AQ_HW21`
- otherwise → **unsupported**

Determines whether Goal 2 is "configure it" or "write driver support". The S22 port
reports `ath11k` Wi-Fi working with Samsung's firmware/board file, which is encouraging.
Readable from stock Android's logs or from the downstream `cnss2` driver's output
(`dmesg | grep -i cnss`).

### Q6. Which touchscreen ✅ **MOOT — simplified**
Your answer ("internal screen is the only target, S-Pen discouraged") removes the
ambiguity entirely. Taking the original goal together with this:

- **Main (internal) panel:** display **+ touch**. Driver needed: `stm,stm_ts_spi` (SPI).
- **Cover panel:** **display only**, touch node left disabled. Your original spec.
- **S Pen / `wacom,w90xx`:** dropped. Not built.
- **Fingerprint (`goodix`):** already out of scope.

Net effect: **one** touch driver instead of two, and no digitiser work. I'll still confirm
the SPI/I²C↔panel mapping from the rooted dump, but it no longer gates anything — if the
mapping turns out reversed, it's a one-line device-tree change.

### Q7. What is `samsung,mipisel-gpio`? ✅ **RESOLVED — no action needed**
Answered locally by reading the Samsung source; it needed no device access after all.

It is **TLMM `gpio97`**, driven **high** during the main panel's power-on sequence and
**low** during power-off (`techpack/display/msm/dsi/dsi_panel.c:532` and `:652`, parsed
at `ss_dsi_panel_common.c:5375`). Almost certainly a lane-switch/redriver *enable* on the
flex crossing the hinge.

It is **not** a mux arbitrating between the two panels — the two displays have separate
DSI controllers, separate PHYs and separate TE GPIOs, which is not how you'd wire a 2:1
mux. In a mainline panel driver it's one `gpiod` toggled in `prepare()`/`unprepare()`.

**Impact: Goal 3 is less risky than it first looked.** Nothing known now rules out
driving both screens simultaneously.

## Useful — can wait, but cheap to collect in Phase 0

### Q8. Dump the post-ABL device tree from the running device
```bash
adb shell 'su -c "find /sys/firmware/devicetree/base -type f" '   # or pull the whole tree
dtc -I fs -O dts /sys/firmware/devicetree/base > q2q-merged.dts
```
This shows the **merged result** of ABL's overlay application — i.e. exactly what the
bootloader hands a kernel. Far more useful than the source overlay for understanding what
ABL does to a DTB, and directly informs the Q2 decision.

### Q9. Which panel revision? 🟡 **half-answered**
`ro.revision = 9` on your device, and only `r08` covers revision 9 (its range is
0x8–0x20). **So `q2q_eur_openx_w00_r08.dts` is authoritative** — which is the file all
the analysis in these docs already used. Nothing to redo.

Still open: `r08` offers *both* `S6E3XA1` and `S6E3XA2` as main-panel options, and
`/sys/class/lcd/panel/lcd_type` is not world-readable. `S6E3XA2` is likely given the late
board revision, but **confirm before writing the panel driver** — the init sequences
differ.

### Q10. Which audio amp is populated? 🔑 **needs root** (and audio isn't a goal)
The DTS lists `cirrus,cs35l41`, `ti,tas256x` and `sma1305` because Samsung ships regional
variants; only one is fitted. Only matters if you want audio (not a stated goal), and
only `cs35l41` is cleanly upstream.

### Q11. QCA6490 in `linux-firmware`? ✅ **RESOLVED — no, it isn't**
You offered to help; I could check this myself. The full `ath11k/` firmware directory
upstream is:

```
IPQ5018  IPQ6018  IPQ8074  QCA2066  QCA6390  QCA6698AQ  QCN9074  WCN6750  WCN6855
```

**No `QCA6490`.** Consequences:
- Wi-Fi firmware **and** the board file must be extracted from your device's own
  `vendor` / `apnhlos` partitions. Do this in Phase 0, before wiping.
- It is **not redistributable**, so a Fedora image can't ship it. This is exactly what
  `droid-juicer` solves (extract at first boot) — see
  [06-fedora-strategy.md](06-fedora-strategy.md).
- Interesting detail: `QCA2066` and `QCA6698AQ` *are* shipped, and both are handled by
  `ath11k`'s WCN6855 sub-version switch — the same code path QCA6490 lands in. So the
  driver framework is there; it's the firmware that has to come off your phone.

### Q12. UART test point ⏹️ **DROPPED** per your call
Agreed, and no explicit reports found. This does raise the stakes on the other consoles,
so Phase 1 now leans on, in order: `simple-framebuffer` at `0xE4000000` → USB gadget +
SSH → `ramoops`/pstore (the `q2q` DTS already declares a `ramoops` node, which survives
reboots and will capture panics you never see).

---

## What I can do without you

For the record, these need no input from you and I can proceed on them whenever you want.
(Q7 above was one of these — already done.)

- ~~Scope the `dispcc-sm8350.c` port~~ — **done, and it turned out to be unnecessary:**
  `qcom,sm8350-dispcc` is already handled by the multi-SoC `dispcc-sm8250.c`.
- Extract both panels' full DCS init sequences from
  `techpack/display/msm/samsung/S6E3{XA2,FAB}_*/` into a form a DRM panel driver can use.
- Draft `sm8350-samsung-q2q.dts` (Phase 1 minimal version) from `sm8450-samsung-r0q.dts`.
- Map the I²C/SPI bus assignments for `max77705`, `s2dos05`, the touch controllers and
  the hall sensor out of the DTS, so the device tree is ready to go.
- Diff the `r01`–`r08` board DTS files to see what changes between hardware revisions.

Say which of these you want first and I'll start.
