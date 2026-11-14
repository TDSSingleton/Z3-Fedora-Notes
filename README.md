# Fedora on the Samsung Galaxy Z Fold 3

Mainline Linux and Fedora 45 KDE Plasma Mobile on the **Galaxy Z Fold 3**
(SM-F926B, codename `q2q`, Qualcomm SM8350 / Snapdragon 888, *lahaina*).

The device runs a Fedora userspace on a near-upstream kernel (v7.2.15 plus the
patches in [`patches/`](patches/)): GPU-composited Plasma Mobile on the inner
folding panel, working touch, WiFi, Bluetooth, LTE data, sensors with
auto-rotate, the cover display as a second output, fold detection, and
charging. It is usable as a phone-shaped Linux computer, not as a phone.

This repository holds the **port**, not a distribution: a board device tree,
five out-of-tree drivers, seven kernel patches, the root filesystem edits, and
the host tooling to build, flash and debug the device over a USB serial
console. No prebuilt images and no vendor firmware are included — see
[Scope](#scope-and-what-is-not-here).

> **[HANDBOOK.md](HANDBOOK.md) is the source of truth.** It carries the current
> state, the build and flash workflow, the tool reference, the safety rules and
> a section-by-section record of every bring-up. This README is an index.

---

## Hardware status

| Subsystem | State | Notes |
|---|---|---|
| Boot chain | works | uniLoader shim in `boot`, carrying kernel + DTB + initramfs; kexec chainloader with automatic fallback |
| Inner display (S6E3XA2) | works | Real KMS, 2208×1768, DPU + DSI + panel driver; blank/unblank; orientation `LEFT_UP` |
| GPU (Adreno 660) | works | `GL_RENDERER FD660`, GLES 3.2 under Mesa; KWin composites on it |
| Inner touchscreen | works | ST FTS9CU80F over SPI — [`touch-work/`](touch-work/) |
| Cover display (S6E3FAB) | works | 832×2268 as a second DRM output, display-only — [`cover-work/`](cover-work/) |
| WiFi (QCA6490) | works | `ath11k`, upstream firmware; the device is on the LAN and runs `sshd` |
| Bluetooth | works | A2DP playback; no HFP (`BT_RFCOMM` off) |
| LTE data | works | MPSS + IPA + ModemManager, ~14/9 Mbit/s. Data and SMS only, no voice calls |
| Sensors | works | Accelerometer, magnetometer, light via SLPI + `hexagonrpcd`; auto-rotate on the inner screen |
| Fold switch | works | AK09970 hall sensor blanks the inner panel when closed — [`hall-work/`](hall-work/) |
| Charging | works | ~880 mA on a wall charger via `fold3-charge.service`. No PD/AFC fast charging |
| Battery gauge | reads | `max17042` percentage and current |
| Keys | works | Power, volume up, volume down |
| Storage, thermals | works | UFS; 29 TSENS zones |
| Cover touchscreen | not done | Separate I²C controller, deliberately deferred |
| Audio | dropped | Both CS35L41 amps probe healthy but never receive the I²S bit clock; measured as probable hardware failure on this unit |
| Suspend | unusable | No wakeup source exists; disabled in the kernel and the rootfs |
| RTC | read-only | The counter register is owned by TrustZone; needs NTP |
| USB after reboot | manual | The gadget does not re-enumerate; the cable must be replugged |
| Voice calls, cameras, S-Pen | out of scope | Cameras are disabled by the unlock itself |

Open items and untested areas are tracked in [HANDBOOK.md §30](HANDBOOK.md).

---

## How it works

Three facts explain most of the design, and most of the bugs.

**1. Samsung's bootloader corrupts mainline device trees.** ABL merges its own
overlay fragments — Samsung's `q2q` DTS is roughly 266 `fragment@N {
__overlay__ }` blocks — into whatever DTB it finds in the boot image. ABL
cannot be patched: it is verified against Samsung's root of trust in QFPROM
fuses, which unlocking does not relax. The port therefore boots through
[uniLoader](https://github.com/ivoszbg/uniLoader), a bare-metal shim that
masquerades as an arm64 kernel so ABL hands it control without inspecting the
device tree it carries. The board file is in
[`uniloader-work/`](uniloader-work/README.md).

**2. Mainline assumes it owns hardware that Samsung's firmware has given to the
secure world or to a remote processor.** The APSS watchdog aborts on any access
from the non-secure world; many TLMM GPIOs are TrustZone-owned and hang the
pinctrl probe; `smp2p`, the crypto BAM and the QFPROM fuses belong to other
masters. When something hangs with no error message, the first question is who
owns the registers.

**3. There is no fastboot.** Images reach the device through Download Mode
(Odin protocol, driven by `heimdall`), from `dd` inside TWRP over adb, or — in
normal development — by the device flashing its own `boot` partition over the
serial console. [14-flashing.md](14-flashing.md) covers the rescue ladder.

The SM8350 display stack (dispcc, DPU, DSI controller, 5nm PHY) was already
fully upstream, so the only kernel-side display work was the two panel drivers
and the board wiring. [docs/17-gpu-display-bringup.md](docs/17-gpu-display-bringup.md)
is the detailed record.

---

## Repository layout

| Path | Contents |
|---|---|
| [`HANDBOOK.md`](HANDBOOK.md) | Current state, workflow, tools, safety rules, bring-up record |
| [`dts-work/`](dts-work/README.md) | `sm8350-samsung-q2q.dts`, the board device tree |
| [`patches/`](patches/) | Kernel patches, applied by `tools/setup-sources.sh`; `userspace/` for the rest |
| [`panel-work/`](panel-work/README.md) | Inner panel driver and the vendor command-stream decode |
| [`cover-work/`](cover-work/) | Cover panel driver |
| [`touch-work/`](touch-work/) | Inner touchscreen driver |
| [`hall-work/`](hall-work/) | Fold-switch hall sensor driver |
| [`wifi-work/`](wifi-work/) | S2MPB02 sub-PMIC regulator driver and WiFi bring-up rigs |
| [`bt-work/`](bt-work/) | Bluetooth board-file tooling |
| [`uniloader-work/`](uniloader-work/README.md) | uniLoader `q2q` board file, defconfig and load addresses |
| [`initramfs-work/`](initramfs-work/) | `init`, the rootfs pivot, and the kexec loader |
| [`rootfs-work/`](rootfs-work/) | Services and helpers installed into the Fedora root filesystem |
| [`kernel-work/`](kernel-work/) | The kernel config fragment |
| [`tools/`](tools/) | Build, flash, extraction and debug tooling |
| [`golden/`](golden/) | Known-good snapshots — config, DTS, drivers and a `MANIFEST.txt` per stage |
| [`rescue/`](rescue/) | The force-recovery procedure, the stock PIT, restore scripts |
| [`Hard Truths/`](Hard%20Truths/) | Only what was verified from a primary source |
| [`docs/`](docs/) | Deeper notes: stage inventory, partition table, display bring-up |

`Hard Truths/` holds findings confirmed against the Samsung GPL drop, the live
kernel tree or the device itself. Plans and estimates live elsewhere, because
those change.

The numbered files at the top level
([03-boot-chain.md](03-boot-chain.md), [04-roadmap.md](04-roadmap.md),
[05-research-gaps.md](05-research-gaps.md),
[06-fedora-strategy.md](06-fedora-strategy.md),
[07-build-workflow.md](07-build-workflow.md),
[09-bootloader-plan.md](09-bootloader-plan.md),
[10-battery-plan.md](10-battery-plan.md),
[11-extraction-plan.md](11-extraction-plan.md)) are **pre-code planning notes,
kept as a record.** Several have been overtaken by what the hardware actually
did; the handbook supersedes all of them.

---

## Building

Requires an unlocked SM-F926B and a Fedora host. Full instructions, including
the first flash and the console setup, are in [HANDBOOK.md §5](HANDBOOK.md).

```sh
sudo dnf install heimdall android-tools gcc-aarch64-linux-gnu \
                 sysroot-aarch64-fc44-glibc lrzsz podman git

./tools/setup-sources.sh        # kernel v7.2.15 + patches, uniLoader, busybox, lrzsz
./tools/build-kernel.sh
./tools/build-busybox.sh --rootfs
./tools/assemble-boot.sh        # -> images/q2q-stage1-boot.img
```

The assemble step also needs two files from the target phone's own stock boot
image, which are per-firmware and not redistributable; the handbook says where
they come from.

Each `golden/stage*/` directory records the exact config, device tree and
driver sources behind a verified boot, with a `MANIFEST.txt` explaining the
decisions baked into it. Start from the newest one rather than from scratch.

---

## Safety

Porting to this device involves irreversible steps and a few genuinely
unrecoverable ones. The full list is [HANDBOOK.md §7](HANDBOOK.md); the
essentials:

- **Unlocking is a one-way door.** The Knox efuse blows permanently, and this
  device generation disables its cameras on unlock.
- **Never write `xbl`, `abl`, `tz`, `aop`, `devcfg` or `pmic`.** There is no
  public SM8350 Samsung Firehose programmer, so a bad write here is a brick
  with no recovery path.
- **Never `heimdall flash --repartition`.** It rebuilds the GPT from the PIT,
  where `USERDATA` means "the rest of the disk", and swallows the Linux
  partition.
- **Back up `efs`, `sec_efs`, `persist`, `modemst1/2`, `fsg` and `fsc` before
  anything else, and never write them back.** They hold the IMEI and the
  Bluetooth and WiFi MAC addresses, they are in no firmware download, and they
  cannot be regenerated.
- **Do not drive charging from a custom kernel.** The Fold 3 is a managed
  dual-cell system behind two `s2asl01` limiters that mainline has no driver
  for.
- **Every RPMh regulator voltage must land on the driver's grid.** An off-grid
  `min = max` fails the probe of the *entire* PMIC's regulators — which can
  take the USB PHY and UFS supplies with it and looks exactly like dead
  hardware.
- **Decline OTA updates.** Newer firmware is reported to remove unlocking.

---

## Scope, and what is not here

- **No images.** Boot images, root filesystem images and partition dumps are
  not committed; they are built by the tooling.
- **No vendor firmware.** Qualcomm and Samsung blobs are not redistributable
  and must be extracted from the device ([`tools/02-extract-firmware.sh`](tools/02-extract-firmware.sh)).
- **No per-device data.** EFS, `persist` and GPT dumps carry identifiers unique
  to one handset and are excluded by `.gitignore`.
- **No Samsung GPL drop.** `SM-F926B/` keeps only the README files; the source
  itself is retrievable from opensource.samsung.com and has answered more hard
  questions than any other reference in this project.
- The upstream trees (`linux`, `linux-fedora`, `uniloader`) are git submodules
  pinned to upstream commits; every local change lives in `patches/` or a
  `*-work/` directory.

Driver and device-tree sources carry their own SPDX headers (GPL-2.0 for the
drivers, BSD-3-Clause for the device tree), consistent with the Linux trees
they derive from. There is no repository-wide license file yet.

## Provenance

This port was produced with heavy use of AI assistance, under human direction
and against real hardware — every "works" in the table above was confirmed on
the device. [AUTHOR NOTES.md](AUTHOR%20NOTES.md) has the author's own account of
how it came about.
