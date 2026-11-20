# Running Fedora's own kernel, and taking its updates

Status: **prep.** The audit and the two tools are real and were run against a
real Fedora kernel, and the one claim the whole approach rests on is now
verified on the device (§1). Not yet built: the module set, the payload
initramfs, the install hook. No Fedora kernel has been booted on this phone.

Picks up the loose end at the bottom of [HANDBOOK](../HANDBOOK.md) section 31:
the chainloader removed the *flash* from the loop, but the kernel it boots is
still ours. This is about making the kernel it boots come from `dnf`.

---

## 1. The question, answered

> Can every out-of-tree thing this phone needs be a loadable module, so that a
> stock Fedora kernel can drive it?

**Yes, for the kernel we boot. No, for the kernel we flash — and that is fine,
because they are two different kernels and only one of them changes.**

The chainloader already splits them (section 31):

    ABL -> uniLoader -> LOADER kernel (ours, in boot.img, never changes)
                            -> kexec -> PAYLOAD kernel (today ours; this doc makes it Fedora's)

Everything that cannot be a module lives in the **loader**, which is flashed
once and does not follow Fedora's update cycle. The payload is where `dnf`
lands, and the payload needs nothing built in that Fedora does not already
build.

### The load-bearing fact

`patches/0001-qcom_scm-sec-wdog-deactivate.patch` is the one patch that can
never be a module: it adds an SCM call to `drivers/firmware/qcom/qcom_scm.c`,
and `CONFIG_QCOM_SCM` is a `bool`. Without it the bootloader's secure watchdog
bites ~3 s into boot and the phone resets. It looked like the thing that makes
this whole idea impossible.

It is not, because **the watchdog is disabled in TrustZone, not in the
kernel.** The loader calls SCM 01/07 at `qcom_scm_probe`, TZ turns the
watchdog off, and `kexec` does not reset the SoC — so the payload kernel
starts with the watchdog already off and never needs to make the call. Fedora's
unpatched `qcom_scm` simply ignores the `qcom,disable-sec-wdog` property in our
DT.

**Verified 2026-11-16.** Built our own kernel with 0001 reverted (nothing else
changed; the control was the same tree *with* 0001, built minutes apart),
installed it as the payload entry `nowdog`, `fold3-boot next nowdog`, rebooted.

    SECWDOG count this boot:  0          (the control's Image contains 2)
    marker:                   fold3: this is a CHAINLOADED kernel
    graphical.target:         18.3 s
    display:                  card0-DSI-1 + card0-DSI-2
    wlp1s0 / sshd:            up

The `SECWDOG` strings are the proof of identity, not just a log line: of the
four entries on the phone only `nowdog`'s Image contains none of them, so a
boot reporting zero of them in `journalctl -k` cannot be any other kernel.

So the payload survived the watchdog window *without ever making the SCM call*,
and did so for a full desktop session. **The loader's TrustZone watchdog
disable persists across kexec, and a stock Fedora kernel does not need patch
0001.** That was the one thing that could have killed this whole approach.

---

## 2. What the audit says

`tools/fedora-kernel-audit.sh` compares a stock Fedora config against
`linux-fedora/.config` and classifies every symbol this phone needs. Run it
again on every kernel bump:

    ./tools/fedora-kernel-audit.sh --from-phone        # fetch + audit
    ./tools/fedora-kernel-audit.sh                     # re-audit newest saved

Configs are kept in `kernel-work/fedora-configs/`.

Against **7.2.11-300.fc45.aarch64** (installed on the phone, 2026-11-16):

> **no blockers: every symbol this phone needs is reachable as y/m or
> out-of-tree.**

The shape of the delta:

| class | count | meaning |
|---|---|---|
| ok | 55 | Fedora builds it, `y` or `m`. Nothing to do. |
| extra | 6 | in-tree source, tristate, Fedora just does not enable it |
| shadow | 5 | Fedora builds it, but we carry a patch against it |
| hazard | 3 | present in Fedora and *dangerous here* |
| debug | 7 | diagnostics we lose; comfort, not correctness |

Fedora's aarch64 kernel is friendlier than expected: 4K pages like ours,
`MODVERSIONS=n` (so no symbol-CRC matching, only vermagic), `MODULE_SIG_FORCE=n`,
and `SM_DISPCC_8250=m` — which is the module-not-builtin we actually want
(HANDBOOK 17: a built-in dispcc garbles the bootloader framebuffer handoff).

### 2.1 The six `extra` modules

In-tree sources, `tristate`, Fedora does not enable them. Built out-of-tree
against Fedora's `kernel-devel`, installed into `/lib/modules/<rel>/extra/`:

| module | source in the kernel tree | why we need it |
|---|---|---|
| `pinctrl-sm8350` | `drivers/pinctrl/qcom/pinctrl-sm8350.c` | TLMM. No pinmux, no phone. |
| `qnoc-sm8350` | `drivers/interconnect/qcom/sm8350.c` | NoC bandwidth; probes defer without it |
| `gpucc-sm8350` | `drivers/clk/qcom/gpucc-sm8350.c` | Adreno clocks |
| `sec-core` | `drivers/mfd/sec-common.c` + `sec-irq.c` | Samsung PMIC core |
| `sec-i2c` | `drivers/mfd/sec-i2c.c` | its I2C glue |
| `s2dos05-regulator` | `drivers/regulator/s2dos05-regulator.c` | panel rails |

`PINCTRL_SM8350` and `SM_GCC_8350=m` together are the sharp end: Fedora has
**no** SM8350 pin controller and a **modular** global clock controller, so both
must be in the payload's initramfs before UFS can probe. See §4.

### 2.2 The five `shadow` modules

Fedora builds these, we patch them, so our build has to win:

| module | patch | note |
|---|---|---|
| `qcom-camss` | 0010, 0012 | SM8350 support + the GDSC clock-park fix |
| `imx258` | 0011 | `reset-gpios` |
| `max17042_battery` | 0005 | status from current with no supplier |
| `max77705_charger` | 0008, 0009 | current setters, AICL wrap |
| `u_serial` | 0003 | drop TTY writes with no host |

`depmod`'s search order decides, and **kmod's default loses**. Its built-in
search string is exactly `"updates built-in"` (depmod.d(5)) -- `extra` is not in
it. Fedora ships no `/etc/depmod.d` file and there is no `/usr/lib/depmod.d`,
so a patched module in `extra/` that also exists under `kernel/` is silently
beaten by Fedora's copy: nothing warns, the driver just behaves unpatched.
`rootfs-work/modules/depmod-fold3.conf` (-> `/etc/depmod.d/fold3.conf`,
`search extra updates built-in`) fixes it. This has never bitten us only
because every module we ship in `extra/` today has no in-kernel counterpart. `u_serial` is the awkward one — it is
linked into `usb_f_acm`/`usb_f_serial`, not a module of its own, so shadowing it
means shipping our own `usb_f_acm.ko`. If that turns out to be a fight, the
alternative is to drop `console=ttyGS0` from the payload's cmdline and keep the
serial console only on the loader; we have ssh and the screen.

### 2.3 Our own drivers — already modules

`fts9cu80f` (touch), `ak09970-fold` (hall), `s2mpb02-regulator`,
`panel-samsung-s6e3fab` (cover) already build out-of-tree and are already
installed into `extra/` on the phone. Two are not yet:

* `panel-samsung-s6e3xa2` (inner panel) is copied *into* the tree by
  `setup-sources.sh` and needs `patches/0007` for its Kconfig/Makefile hookup.
  Moving it out-of-tree — exactly like the cover panel — deletes patch 0007.
* `camcc-sm8350` is ours and lives in the tree. It *is* reproducible --
  `camera-work/install-camcc.sh` copies the driver and its bindings header in
  and patches `drivers/clk/qcom/Kconfig` and `Makefile`, idempotently -- but
  **`setup-sources.sh` never calls it**, so a fresh checkout followed by
  `setup-sources.sh` + `build-kernel.sh` silently produces a kernel with no
  camera clocks. Fixed 2026-11-16 by calling it from `do_kernel()`. Moving the
  driver out-of-tree later would remove the Kconfig/Makefile surgery
  altogether.

### 2.4 Patches the payload does not need

| patch | disposition |
|---|---|
| 0001 qcom_scm sec-wdog | **loader only.** Survives kexec in TZ state (§1). |
| 0002 q2q boot markers | drop. `init/main.c` printks, loader keeps them. |
| 0003 u_serial | shadow module, or drop `ttyGS0` from the payload (§2.2) |
| 0004 adreno kms-less | drop. Historical; the panel runs under real KMS. |
| 0005 max17042 | shadow module |
| 0006 sm8250 two cs35l41 | drop. No working speaker on this unit. |
| 0007 panel Kconfig hookup | drop, replaced by the out-of-tree build (§2.3) |
| 0008, 0009 max77705 | shadow module. 0008 also touches `include/linux/power/max77705_charger.h`, shared with the MFD — check the struct layout before trusting a shadow build against Fedora's `max77705.ko`. |
| 0010, 0011, 0012 camera | shadow modules |

So the payload's irreducible built-in patch set is **empty**, and the loader
keeps exactly two patches that matter: 0001 and (if we keep `ttyGS0`) 0003.

---

## 2.5 One thing Fedora's kernel fixes for free

Our Stage-1 config never enabled `CONFIG_NF_TABLES` or
`CONFIG_NETFILTER_NETLINK`, so `firewalld` cannot open a `NETLINK_NETFILTER`
socket and exits 3 on every boot -- which is the whole reason this phone
reports `systemctl is-system-running` = `degraded`. There is no firewall and no
backend for one; even the legacy `ip_tables` path is absent from the module
tree. Fedora ships `NF_TABLES=m`, `NETFILTER_NETLINK=y`, `NF_TABLES_INET=y`, so
a Fedora payload gets a working firewall backend with no work at all. Found
2026-11-16; the decision about whether we want a firewall is separate and still
open.

## 3. The hazards Fedora's kernel brings

Our config turned these off. Fedora's does not, and the payload will have them.

1. **`CONFIG_SUSPEND=y` and `CONFIG_HIBERNATION=y`.** Suspend on this phone is
   unrecoverable: no wakeup source exists, and it looks exactly like the device
   having died for good (HANDBOOK 22). We disabled it *in the kernel*; with
   Fedora's kernel the only defence is the rootfs one. Before the first Fedora
   payload boot, verify `systemctl mask sleep.target suspend.target
   hibernate.target hybrid-sleep.target suspend-then-hibernate.target` and the
   logind/powerdevil settings are all in place — the kernel is no longer a
   backstop.
2. **`CONFIG_QCOM_WDT=m`.** Our DT deliberately has **no** watchdog node,
   because reading `0x17c10000` from the non-secure world takes a synchronous
   external abort and panics init. The node's absence is what protects us, not
   the config. Never add it.
3. `CONFIG_KEXEC_SIG=y` and `SECURITY_LOCKDOWN_LSM=y` are inert: we do not boot
   via EFI, so lockdown stays off, and the payload never loads another kernel.
   They would bite only if Fedora's kernel became the loader.

---

## 4. The payload's initramfs is the real work

Our chained initramfs mounts root with zero modules — `init-rootfs.sh`'s own
error message says *"is BTRFS_FS built in"*. That assumption holds only for our
kernel. A Fedora payload needs, loaded before root can be mounted:

    gcc-sm8350            (SM_GCC_8350=m -- the global clock controller!)
    pinctrl-sm8350        (extra/)
    qnoc-sm8350           (extra/)
    phy-qcom-qmp-ufs
    ufshcd-core, ufs_qcom

`BTRFS_FS` and `BLK_DEV_SD` are built in on Fedora, so those are free.

What the phone already has for either route (checked 2026-11-16): `gcc`,
`make`, `python3`, `zstd`, `dracut 111`, `/usr/bin/kernel-install` and its
`/usr/lib/kernel/install.d/` hook directory. Missing: `dkms`, `kernel-devel`
(the `build` symlink in `/usr/lib/modules/7.2.11-300.fc45.aarch64/` dangles),
and `/etc/depmod.d/` exists but is empty.

Two ways. **Decided 2026-11-16: host-built.** Fedora's kernel is the payload,
but the module set and the initramfs are produced on the host like everything
else in this repo, and pushed. The consequence is explicit and has to stay
written down: **`dnf update kernel` alone is not enough.** It leaves a kernel
with no matching modules, which boots to a black screen with no touch and no
WiFi -- and the `pending`/`default.failed` fallback does *not* catch that,
because that kernel boots fine. The host step is mandatory, and a Fedora entry
must never be made the `default` until it has been booted once via `next`.

* **dracut on the phone**, driven by `kernel-install`. A
  `/usr/lib/kernel/install.d/` plugin runs on every `dnf` kernel transaction:
  `unzboot.py` the new `vmlinuz`, build the module set, let dracut generate a
  hostonly initramfs with `--add-drivers`, append the `/chained` marker, write
  `/boot/fold3/entries/<rel>/`, `fold3-boot next <rel>`. A kernel update then
  becomes `dnf update && reboot`, which is the actual goal. Costs: a toolchain
  and `kernel-devel` on the phone, DKMS specs per module, and dracut's output
  is much larger and less predictable than our 2 MB cpio.
* **Host-built**, as everything else in this repo: cross-compile the module set
  against a downloaded aarch64 `kernel-devel`, bake the boot-critical ones into
  our own busybox initramfs with a fixed `insmod` list, push the entry over
  ssh. Deterministic and it matches the existing workflow, but a `dnf` kernel
  update on its own then produces an entry with **no modules** — it would boot
  to a black screen with no touch and no WiFi, which the `pending`/
  `default.failed` fallback does *not* catch, because that kernel boots fine.

---

## 5. Order of work

1. ~~**Prove §1.**~~ **Done 2026-11-16** -- see §1. The `nowdog` entry was
   removed afterwards so nobody can make a kernel without 0001 the default;
   its Image is kept in `golden/stage13-fedora-prep-*/Image-nowdog`. Its
   control `curtree` (the current tree *with* 0001) is still an entry on the
   phone, unbooted. `default` was never changed and remains the embedded
   kernel. Note the phone keeps RUNNING `nowdog` until its next reboot --
   deleting an entry does not disturb a kernel already in RAM.
2. **Panel done 2026-11-16.** `panel-samsung-s6e3xa2` now builds out-of-tree
   from `panel-work/` (`make -C panel-work`), `patches/0007` is deleted, the
   copy step is gone from `setup-sources.sh` and the symbol is gone from
   `q2q-stage1.config`. Verified equivalent to the in-tree build before
   switching: same vermagic, same aliases, same `depends`, identical set of
   required kernel symbols. The `select DRM_DISPLAY_DSC_HELPER` that 0007
   carried is not missed -- `drivers/gpu/drm/msm/Kconfig` selects it too, and
   Fedora ships it `=y`.

   **camcc deliberately only half-done.** `camera-work/out/Makefile` builds
   it out-of-tree (it needs `-I` into `drivers/clk/qcom` for eight private
   headers, and stages its own bindings header), but `SM_CAMCC_8350=y` and
   `install-camcc.sh` are untouched, so the loader kernel still has it built
   in. Flipping it to a module changes when the clock provider appears
   relative to camss, on a camera that was only just won; that flip belongs
   with the first Fedora payload boot, not before it.
3. Build the six `extra` modules against Fedora's `kernel-devel`, load them on
   our *running* kernel where possible to shake out obvious breakage.
4. Build the five `shadow` modules. `/etc/depmod.d/fold3.conf` is **already
   installed** on the phone (2026-11-16) and verified not to disturb the four
   modules already in `extra/`; confirm `modinfo -F filename` resolves to
   `extra/` for each new one. The `fold3-boot` guard (§6) is in place too.
5. Solve the initramfs (§4), then boot 7.2.11 as a payload entry via
   `fold3-boot next`, with the embedded kernel as the fallback it already is.
6. Only then automate (`kernel-install` plugin / DKMS) and only then take
   7.3.3, which `dnf` is already offering.

## 6. The guard: `fold3-boot` refuses a default it cannot survive

Done 2026-11-16. The `pending`/`default.failed` machinery catches a kernel that
**fails to boot**. It cannot catch what Fedora's kernels bring: one that boots
perfectly into a system with no display, no touch and no WiFi, because its
modules were never built. `pending` is deleted on schedule, the boot counts as
a success, and the phone is a brick with a backlight.

**Checking that `/lib/modules/<release>` exists does not work** -- and this is
the hole in the obvious design. A Fedora kernel installs its own module tree
from the RPM, so the directory is present and complete *as far as Fedora is
concerned*, while every driver this phone needs is absent. The test has to be
something only our host step could have produced, so it is an explicit
sentinel: `/lib/modules/<release>/extra/.fold3-ready`.

* `fold3-boot default <e>` **refuses** (exit 2, writes nothing) -- it is sticky.
* `fold3-boot next <e>` **warns and proceeds** -- it is one-shot with the
  fallback underneath, which is exactly how a new kernel should be tried.
* `-f`/`--force` overrides; `fold3-boot ready <release>` writes the sentinel.
* `status` now prints each entry's release and module state.

An entry's release comes from its `release` file, or is parsed out of the
Image's `Linux version` banner and cached there (the Image is uncompressed, so
the banner is plain text in it -- the same property that identified the test
kernel in §1).

All four paths were tested in a sandbox copy of the script against fake
entries, so the live `/boot/fold3` was never written to:

    with module set,    default  -> exit 0, default written
    without, default             -> exit 2, default UNCHANGED
    without, next                -> exit 0 with a warning
    without, default -f          -> exit 0, overridden

`7.2.15-q2q` was marked ready, since that module set is complete and running.

## 7. Trap: `systemctl reboot` does not reboot

Measured during the §1 test, because it cost ~8 minutes of believing the test
kernel had failed.

`systemctl reboot` over ssh started the shutdown at **17:42:52** and the system
did not actually go down until **17:50:13** -- 7m20s later, then 4 seconds to
finish. What held it:

    17:42:52  systemd-logind: reboot requested ... The system will reboot now!
    17:42:52  ModemManager, crond: shutting down
              ... 7 minutes of nothing ...
    17:48:49  ksmserver-logout-greeter[54117]: ...
    17:50:13  the real shutdown, 4 s
    17:51:46  next boot

**Plasma's `ksmserver-logout-greeter` intercepts it** and the shutdown blocks
on the on-screen session dialog. `sshd` is stopped almost immediately, so for
those seven minutes the phone **answers ping and refuses port 22** -- which is
indistinguishable from "the new kernel booted and then died", and is exactly
how it was misread here. `fold3-boot status` cannot help: the kernel still
running is the old one.

Before concluding anything about a payload kernel from a silent phone:

* ping first. Ping + port 22 refused = *still shutting down*, not a failed boot.
* the screen is authoritative -- there may be a dialog waiting for a tap.
* for an unattended reboot use `systemctl reboot -i` (ignore inhibitors), or
  `sync` then `reboot -f`, not a bare `systemctl reboot`.

## 8. Tools added for this

| tool | what it does |
|---|---|
| `tools/unzboot.py` | Fedora's `vmlinuz` (PE/zboot, zstd) -> plain arm64 `Image` for `kexec_file_load`. Verified on 7.2.11: 17 MB in, 78 MB `Image` out, `ARMd` magic, correct version string. |
| `tools/fedora-kernel-audit.sh` | the §2 classification, re-runnable per kernel. Exits 2 on a blocker. |

### Trap, for whoever reads `zboot-header.S` next

The `"zimg"` tag is at offset **0x04**, not 0x08. `struct
linux_efi_zboot_header` in `include/linux/efi.h` begins `msdos_magic;
reserved0; zimg[4]`, which reads as 0x08 — but the assembly that actually
emits the header spends a single `.long` on the DOS signature. Parsing by the
C struct gets a payload offset of 17226275 out of a 17340776-byte file and
looks *almost* plausible. Trust the `.S`.
