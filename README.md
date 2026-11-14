# Fedora on the Samsung Galaxy Z Fold 3 (SM-F926B / `q2q`)

A mainline-Linux port effort for the Galaxy Z Fold 3, Snapdragon 888 (SM8350, Qualcomm
codename **lahaina**), targeting Fedora userspace on an as-upstream-as-possible kernel.

**Status (2026-11-11): Fedora 45 KDE Plasma Mobile runs on the inner screen, GPU
accelerated, with working touch.** Mainline boots to a Fedora root filesystem on
btrfs, the Adreno 660 renders under DRM/MSM (`GL_RENDERER FD660`), and the
S6E3XA2 inner panel runs under real KMS at 2208x1768 — DPU, DSI and the GPU all
on one DRM device, so KWin composites without a copy. Inner touch works, the
power and volume-down keys work, and the device boots with **no USB host
attached**.

Not working: WiFi (one step short — the PCIe endpoint never trains), charging
(deliberately — dual-cell topology with no mainline driver), the cover display,
modem, suspend, and the RTC cannot be set. Kernel updates still need a host,
because the kernel lives inside `boot.img`.

See **[HANDBOOK.md](HANDBOOK.md)** for orientation, current state, the
build/flash workflow, the tool reference and the hard safety rules. The
numbered files below are historical planning notes and some are now out of date
— the handbook is the current source of truth, and
[docs/17-gpu-display-bringup.md](docs/17-gpu-display-bringup.md) is the detailed
record of the graphics work.

### Go/no-go: **GO**
- ✅ **The device is unlockable** — `sys.oem_unlock_allowed = 1`, Knox intact
  (`warranty_bit = 0`). → [08-device-facts.md](Hard%20Truths/08-device-facts.md)
- ✅ **The bootloader problem is a scoped task** — a uniLoader port of roughly 60 lines
  across five files, plus three load addresses to measure.
  → [09-bootloader-plan.md](09-bootloader-plan.md)
- ✅ **`r08` is the right device tree for your unit** (`ro.revision = 9`) — the one all
  this analysis already used.
- ⚠️ **Turn off automatic system updates now.** You're on an unlockable bootloader;
  a newer one may not be.

Display: **done for the inner screen** as of 2026-11-11. The SM8350 display stack
(dispcc, DPU, DSI, PHY) was indeed fully upstream, and the inner panel driver lit
the glass on its first attempt. The cover panel's driver is decoded but not
written.

---

## Goals

| # | Goal | Verdict | Hardest part |
|---|------|---------|--------------|
| 1 | **Charging** | Very likely achievable | `max77705` is upstream; the dual-battery topology is not |
| 2 | **Wi-Fi + Bluetooth** | Likely achievable | QCA6490 needs firmware + board file pulled off the device |
| 3 | **Both screens** (cover display-only, touch on inner only) | **Inner screen done** (2026-11-11), cover outstanding | Cover panel driver; dual-DSI concurrency is untrodden |
| 4 | **Fedora, mostly upstream** | Largely answered | Fedora's own KDE Plasma Mobile disk image works as the base; it needs a handful of edits (see HANDBOOK §9), not a custom build |
| 5 | *(optional)* 4G LTE + hotspot | Plausible — better odds than you'd think | Needs modem firmware + QMI bring-up |

Goal 3's qualifier "cover screen with touchscreen off" is the one free win in the whole
project: the cover digitiser is a separate I²C controller, so you get that by simply not
enabling its device-tree node. With S-Pen support also dropped, that's **one** touch
driver to write instead of two, and no digitiser work at all.

## The three things that actually decide this project

1. **Samsung's ABL corrupts mainline device trees.** Samsung's bootloader merges its
   own overlay fragments into whatever DTB it selects. The Samsung DTS in this repo is
   itself one giant stack of `fragment@N { __overlay__ { ... } }` blocks — that *is* the
   mechanism, visible in our own source drop. You almost certainly need a shim
   bootloader (uniLoader) rather than booting mainline from ABL directly. See
   [03-boot-chain.md](03-boot-chain.md).

2. **SM8350's display stack is fully upstream** — dispcc (via the multi-SoC
   `dispcc-sm8250.c`), DPU, DSI controller and 5nm PHY, with `sm8350.dtsi` already
   wired correctly. **Confirmed on hardware 2026-11-11**: enabling
   `SM_DISPCC_8250` + `DRM_MSM_DPU`/`DSI`/`DSI_7NM_PHY` and adding board-level
   panel wiring was the entire kernel-side change. Only the **cover** panel
   driver is still missing. See
   [Hard Truths/02-upstream-status.md](Hard%20Truths/02-upstream-status.md) §3
   and [docs/17-gpu-display-bringup.md](docs/17-gpu-display-bringup.md).

   *An earlier revision of these docs called a missing `dispcc-sm8350` the project's
   critical path. That was wrong: I checked for a filename, a Kconfig symbol and a
   binding doc, and never checked which driver claimed the compatible.*

3. **Bootloader unlock is irreversible.** The Knox efuse blows permanently (yours is
   currently intact), and the Fold 3 generation was reported to disable its cameras on
   unlock. Cameras aren't among your goals, but it's a one-way door. See
   [03-boot-chain.md](03-boot-chain.md).

Problem 1 is solved on paper (uniLoader), problem 2 turned out to be mostly solved for us
already, and problem 3 is a decision rather than a risk. The real remaining work is
panels, touch, charging and Wi-Fi firmware — all per-device, none of it SoC enablement.

## Layout

**`Hard Truths/`** holds only what was verified from a primary source — the Samsung GPL
drop, the live kernel tree, or the device itself. Plans, estimates, strategy and
third-party reports live at the top level, because those change.

## Reading order

| File | What's in it |
|------|--------------|
| [01-hardware-inventory.md](Hard%20Truths/01-hardware-inventory.md) | Every chip, extracted from the Samsung DTS, with upstream driver status |
| [02-upstream-status.md](Hard%20Truths/02-upstream-status.md) | What SM8350 support exists in mainline today, and the precise gaps |
| [03-boot-chain.md](03-boot-chain.md) | Unlock, Odin, AVB/vbmeta, the ABL overlay problem, backups, brick risks |
| [04-roadmap.md](04-roadmap.md) | Phased plan, Phase 0 → 6, each with exit criteria |
| [05-research-gaps.md](05-research-gaps.md) | Question tracker — what's answered, what still needs root |
| [06-fedora-strategy.md](06-fedora-strategy.md) | Getting Fedora specifically, rather than postmarketOS |
| [07-build-workflow.md](07-build-workflow.md) | Toolchain, repo layout, build/flash/debug loop, getting a console |
| [08-device-facts.md](Hard%20Truths/08-device-facts.md) | **Real data read off your unit** over `adb` |
| [09-bootloader-plan.md](09-bootloader-plan.md) | The uniLoader port, file by file (Q2 resolved) |
| [10-battery-plan.md](10-battery-plan.md) | Dual-cell topology and a safe charging plan (Q4 answered) |
| [11-extraction-plan.md](11-extraction-plan.md) | **Everything to pull off the device**, in the right order |
| [12-wifi-qca6490.md](Hard%20Truths/12-wifi-qca6490.md) | QCA6490 under `ath11k` — probably not a port at all |
| `tools/00-collect-facts.sh` | Hardware facts; closes Q5/Q8/Q9/Q10 |
| `tools/01-backup-critical.sh` | **Run first after root.** `EFS`/`persist`/`modemst*` + recovery images |
| `tools/02-extract-firmware.sh` | Vendor firmware for the mainline kernel |
| [Hard Truths/13-panel-reference.md](Hard%20Truths/13-panel-reference.md) | **Both panels fully decoded** — modes, DSC, init sequences |
| [panel-work/](panel-work/README.md) | Panel driver (compiles clean) + decode artifacts |
| [uniloader-work/](uniloader-work/README.md) | uniLoader `q2q` port (builds) + derived load addresses |
| [14-flashing.md](14-flashing.md) | **How images reach the device without fastboot** + the rescue ladder |
| [dts-work/](dts-work/README.md) | `sm8350-samsung-q2q.dts` — Stage-1 board DTS (compiles) |
| `tools/extract-panel-cmds.py` | Decodes vendor DSI command streams out of a Samsung DTS |
| `tools/gen-panel-init.py` | Emits a mainline-idiom panel init function |

## Honest effort estimate

This is a **6–18 month** project for one person working evenings, and it is gated on
writing a clock-controller driver and two DSI panel drivers from scratch. The closest
precedent — a one-person Galaxy S22 port — reached working display, Wi-Fi, Bluetooth,
audio, GPU and charging, but still lists suspend, sensors and mobile data as broken.
Expect to land goals 1, 2 and 4 well before goal 3, and treat goal 5 as a stretch.

The good news: the Fold 3 is a *better* mainline target than the S22 in two specific
ways — SM8350 has an upstream IPA driver (the S22's SM8450 does not, which is what
blocks mobile data there), and both DSI controllers plus 4 DSC blocks are already
described in `sm8350.dtsi`.

## Next action

1. **Turn off automatic system updates.** Protects the unlock path.
2. **Download the full stock firmware archive** for `SM-F926B` + your CSC. No device
   access needed, and it's your only "reinstall everything" path.
3. **Unlock**, then flash TWRP to `recovery` (or a Magisk-patched `boot`).
4. **Immediately run `tools/01-backup-critical.sh`** — `EFS`, `persist`, `modemst*` are
   irreplaceable and not in any firmware download.
5. `tools/02-extract-firmware.sh`, then `tools/00-collect-facts.sh` (rooted).
6. *Then* start Phase 1.

See [11-extraction-plan.md](11-extraction-plan.md) for why backups come *after* unlock
(root requires it) and exactly what gets pulled.

**Panel work has started** — both panels are fully decoded and the main panel's driver is
written (never compiled, never run). See [panel-work/](panel-work/README.md). With the
SM8350 display stack already upstream, the panel drivers are the *only* thing between a
booting kernel and a lit screen.
