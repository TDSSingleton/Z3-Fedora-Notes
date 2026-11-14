> **HISTORICAL** — written during planning, before any code existed. Parts are now wrong.
> See [HANDBOOK.md](HANDBOOK.md) for the current state.

# Getting Fedora specifically

You asked for **Fedora**, with as much upstream as you can afford. Those two goals pull
in opposite directions on a phone, so this document is about picking the least-bad
combination.

The awkward fact: essentially all mobile-Linux tooling is built around postmarketOS
(Alpine) or Debian (Mobian). Fedora's phone story is real but thin, and the one project
that fits Fedora-on-phones properly has an entry requirement the Fold 3 does not meet.

---

## 1. What actually exists (verified 2026-11-06)

### Fedora KDE Plasma Mobile Spin — official ✅
`fedoraproject.org/spins/kde-mobile/download/` ships **Fedora KDE Plasma Mobile Spin 45**
(BETA, release date 2026-11-03) with real aarch64 artifacts:

| Artifact | Size |
|---|---|
| `Fedora-KDE-Mobile-Live-45-1.4.aarch64.iso` | ~2.5 GiB |
| `Fedora-KDE-Mobile-Disk-45-1.4.aarch64.raw.xz` | ~2.8 GiB |

This is an official Fedora deliverable with a mobile shell (Plasma Mobile), and it is the
best evidence that "Fedora on a phone screen" is a supported idea. But the page names **no
target hardware** — it assumes a generic UEFI aarch64 machine and Fedora's own kernel. It
will not boot on a Fold 3 as-is.

### Pocketblue — the right shape, wrong requirements ⚠️
`pocketblue.github.io` — Fedora Atomic for phones. Images are built from upstream
Silverblue/Kinoite as **OCI containers**, using OSTree + bootc. Per-device directories
(`devices/<vendor>-<codename>/`) with a `build` script, `disk.yaml` partition layout,
`artifacts.sh` and `device.conf`. Kernels are packaged to Fedora **COPR**, preferably via
**ARKify**. Vendor firmware is either packaged to COPR or extracted at boot with
**`droid-juicer`**.

Supported devices: Xiaomi Pad 5/6, OnePlus 6/6T, Poco F1, Orange Pi 3 LTS — i.e. SDM845
and friends. **No SM8350 device.**

**The blocker:** Pocketblue requires a device to meet *both* criteria —

> *It can run the upstream Fedora kernel or has an actively maintained mainline kernel
> fork* **and** *it has a working UEFI implementation (U-Boot is preferred).*

Its flashing model is: flash U-Boot to the Android `boot` partition, then flash
`fedora_esp.raw` and `fedora_rootfs.raw`.

The Fold 3 has **no UEFI and no U-Boot port**, and (per
[02-upstream-status.md](Hard%20Truths/02-upstream-status.md)) no actively maintained SM8350 mainline
fork either — `sm8350-mainline` is stuck at 6.7.0-rc3. So the Fold 3 fails both halves
today.

**And U-Boot is further away than I first assumed.** Its `drivers/clk/qcom/` — which
U-Boot's own phone docs name as the way to check SoC support — has `clock-sm8250.c` and
`clock-sm8550.c` but **nothing for sm8350 or sm8450**. So Option B below is not "flash
U-Boot", it's "write a Qualcomm clock driver for U-Boot first". That re-prices it
substantially.

### Fedora ARM proper ❌
The Fedora ARM wiki scopes aarch64 to servers, SBCs and IoT, with a single kernel for all
devices. There is a Fedora *Mobility* SIG, but no phone rootfs for Qualcomm devices. The
substantial Fedora/Qualcomm work (Hans de Goede's) targets **X1 laptops**, not phones.

---

## 2. Three ways to get there

> ### Fedora's stock aarch64 kernel is already most of the way there
> Checked against `kernel-ark` (`redhat/configs`) on 2026-11-07. Fedora's aarch64
> config already sets:
>
> | Symbol | Fedora | Why it matters |
> |---|---|---|
> | `CONFIG_ARCH_QCOM` | `y` | Qualcomm platform |
> | `CONFIG_SM_DISPCC_8250` | **`m`** | the multi-SoC driver that covers **SM8350** display clocks |
> | `CONFIG_DRM_MSM` | `m` | |
> | `CONFIG_DRM_MSM_DSI` | `y` | |
> | `CONFIG_BACKLIGHT_CLASS_DEVICE` | `y` | |
> | `CONFIG_REGULATOR_S2DOS05` | **not set** | our panel rails — needs enabling |
>
> `SM_DISPCC_8250=m` is a happy accident: the Galaxy S22 port found a *built-in* dispcc
> garbled the bootloader framebuffer handoff, and Fedora's default is already a module.
>
> So the delta from Fedora's own config is: **flip on `REGULATOR_S2DOS05`, add the panel
> driver, ship a DTB.** That is a far lighter COPR kernel than "bespoke config", and it
> makes Option A below meaningfully cheaper than when this file was first written.
>
> Also confirmed at **v7.2.15** specifically (Fedora 44 *and* 45's base): `dispcc-sm8250.c`
> still claims `qcom,sm8350-dispcc`, and `CONFIG_SM_DISPCC_8250` is still titled
> "SM8150/SM8250/SM8350 Display Clock Controller".

### Option A — Hand-rolled Fedora rootfs on your own kernel ⭐ recommended
Bring the device up with your own kernel (Phases 1–4), then put a stock Fedora aarch64
rootfs on it.

- Start from the **`Fedora-KDE-Mobile-Disk-45` aarch64 raw image** (userspace is already
  mobile-shaped) or a minimal Fedora aarch64 base tarball.
- Package *your* kernel as an RPM, build it in **COPR** (keeps `dnf` coherent, matches
  what Pocketblue does anyway, and means you are not hand-installing kernels forever).
- Vendor firmware via `droid-juicer` — it extracts from the device's own partitions, so
  you dodge the redistribution problem entirely. **This is now mandatory, not optional:**
  upstream `linux-firmware` has no `QCA6490` directory at all (it ships IPQ5018, IPQ6018,
  IPQ8074, QCA2066, QCA6390, QCA6698AQ, QCN9074, WCN6750, WCN6855), so your Wi-Fi
  firmware and board file can only come off your own phone and cannot be redistributed in
  an image.
- `boot` partition holds your kernel + DTB (+ shim loader); rootfs lives on `userdata`.

**Why this one:** it's the only option that works with the Fold 3's actual boot chain, it
gets you real Fedora with real `dnf`, and every piece of it is reusable later if you do
pursue Options B or C. It is also how both Samsung precedents structure their installs,
just with Fedora substituted for Alpine.

**Cost:** you own the integration. No one else is testing this combination.

### Option B — Port U-Boot, then use Pocketblue properly
Get U-Boot running on SM8350/`q2q`, flash it to `boot`, and you meet Pocketblue's
criteria. Then add `devices/samsung-q2q/` and inherit their whole build/flash pipeline.

**Why consider it:** this is the *architecturally correct* answer and the only one that
makes the Fold 3 a first-class Fedora device with images other people could install. It
also solves the ABL/DTB problem permanently and more cleanly than a shim loader —
U-Boot would own the device tree.

**Cost: higher than it first looked — I checked.** U-Boot has **no SM8350 clock driver**
(`drivers/clk/qcom/` jumps sm8250 → sm8550), so this means writing one *there* as well as
in Linux. Its documented bring-up path is also `fastboot boot u-boot.img`, and Samsung has
no fastboot, so even testing is awkward.

Two things that do make it more attractive later: U-Boot's phone docs ask for exactly
what we have — a `simple-framebuffer` with a reserved-memory region labelled
`cont_splash` — and they independently warn that *"ABL is known to sometimes give bogus
entries in the memory node"*, corroborating the S22 port's `/memory` size-0 finding.
**Park it until after Phase 4.**

(Note: the Linux-side display clock controller is *already* upstream for SM8350, so there
is no clock-tree knowledge to be gained "for free" from Phase 4 any more — U-Boot's
`clock-sm8350.c` would be work from scratch. That makes Option B slightly less attractive
than an earlier revision of this file suggested.)

### Option C — postmarketOS first, Fedora second
Bring hardware up under postmarketOS (where `pmbootstrap` and all the mobile tooling
lives), then swap the rootfs for Fedora once the kernel and device tree are solid.

**Why consider it:** every precedent — Galaxy S22, Tab S8+, M52 — did it this way, so
tooling, docs and community help all align. `pmbootstrap` genuinely accelerates the
boot/iterate loop.

**Cost:** it isn't Fedora, so it's a detour from your stated goal; and some pmOS-specific
packaging work gets thrown away at the end.

---

## 3. Recommendation

**Option A, with Option C's tooling where convenient, and Option B kept on the table.**

Concretely:

1. **Phases 1–2: don't commit to a distro at all.** Use a minimal initramfs. Distro
   choice is irrelevant while you're debugging whether the kernel boots, and arguing
   about it early is wasted motion.
2. Borrow `pmbootstrap` if it speeds up the early loop. Using a tool is not adopting a
   distro.
3. **From Phase 3 onward, target Fedora directly** (Option A) — your kernel as a COPR
   RPM, Fedora KDE Mobile aarch64 as the rootfs, `droid-juicer` for firmware.
4. **Re-evaluate Option B after Phase 4.** With the device booting and the panels working,
   "make the Fold 3 a real Pocketblue device" becomes a credible finish rather than a
   gamble — though U-Boot would still need an `sm8350` clock driver written from scratch.

## 4. On "as much upstream as we can afford"

Worth being blunt about the tension: **none of the Samsung mainline ports are actually
pure mainline.** All three precedents ship out-of-tree drivers and patches — that's not
sloppiness, it's what porting a phone means.

For the Fold 3 the irreducible out-of-tree set is roughly:

| Component | Upstreamable? |
|---|---|
| `panel-samsung-s6e3xa2` | ✅ yes, panels are routinely accepted |
| `panel-samsung-s6e3fab` | ✅ yes |
| `sm8350-samsung-q2q.dts` | ✅ yes, following `sm8450-samsung-r0q.dts`'s precedent |
| STM `stm_ts` touch driver (inner screen only) | ⚠️ maybe — depends on quality and maintainer appetite |
| Dual-battery / `s2asl01` | ⚠️ hard |
| `max77705` Type-C/PD additions | ⚠️ probably, as fixes to the existing driver |
| Vendor firmware blobs | ❌ never |

The best way to maximise upstream content is to **write the first four as clean,
submittable patches from the beginning** rather than as device-specific hacks you intend
to clean up later. The clock driver especially: it benefits every SM8350 device, which
means real reviewers will engage with it, which means it gets better. That is the single
highest-leverage upstream contribution available in this project.
