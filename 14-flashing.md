> **HISTORICAL** — written during planning, before any code existed. Parts are now wrong.
> See [HANDBOOK.md](HANDBOOK.md) for the current state.

# Getting images onto the device (no fastboot)

Samsung has **no fastboot**. `fastboot boot` does not exist, and `fastboot flash` is not
how these devices are written. That sounds like a problem and mostly isn't — we have
something better for iteration, and a bootloader-level backstop for rescue.

All facts below were read off your device or your captured images on 2026-11-07.

---

## 1. The three write paths

| Path | Needs | Use for |
|---|---|---|
| **`dd` over `adb` + root** | booted Android + root | **the iteration loop** — fast, no mode switching |
| **Download Mode + `heimdall`/`odin4`** | nothing but a bootloader | first install, and rescue when Android won't boot |
| **Custom recovery (TWRP)** | TWRP in `recovery` | rescue with a working `adb`, independent of `boot` |

### Tooling status on this host
```
adb              /usr/bin/adb            present
mkbootimg        /usr/bin/mkbootimg      present
unpack_bootimg   /usr/bin/unpack_bootimg present
avbtool          /usr/bin/avbtool  1.4.0 present
img2simg         /usr/bin/img2simg       present
heimdall         MISSING  -> `sudo dnf install heimdall`  (Fedora ships 2.2.2)
odin4            MISSING  -> XDA-distributed only, not packaged
fastboot         present but USELESS here
```

---

## 2. ✅ vbmeta needs nothing — it's already permissive

This was an open question and it's settled. Your live `vbmeta`:

```
avbtool info_image --image capture/backup-*/tier2-recovery/vbmeta.img
  Algorithm:   SHA256_RSA4096
  Flags:       3          <-- hashtree disabled AND verification disabled
```

Flags bit 0 is `HASHTREE_DISABLED`, bit 1 is `VERIFICATION_DISABLED`. Both set. The
Magisk unlock/root flow already did this, so **we do not need to build or flash a
`--flags 3` vbmeta** the way the Galaxy Tab S8 port had to. One less irreversible step.

### Why it's already circumvented, and stays that way

Three things combine, and together they take AVB out of the picture for good:

1. **`Flags: 3`** — verification and hashtree checks are both switched off.
2. **The bootloader is unlocked**, so ABL does not verify vbmeta's own signature. It
   can't: comparing `vbmeta` with `vbmeta_system` shows both signed with the *same* key
   (`25ebf9f3…`, `avbtool 1.3.0`) but with flags 3 and 0 respectively, and `vbmeta` still
   carries all of Samsung's original descriptors. So it is Samsung's vbmeta with the flags
   byte **patched and not re-signed** — the signature is now invalid and simply isn't
   checked. (Corroborated by the device having reported `verifiedbootstate=green` when we
   first read it locked, and `orange` now.)
3. **We only ever write `boot`.** vbmeta *does* carry a Hash descriptor for `boot`, but
   with verification disabled it isn't enforced.

### What vbmeta actually protects — a useful side-finding

```
Chain Partition:  recovery (RIL 6), dtbo (8), prism (13), optics (14)
Hash descriptors: abl, boot, hyp, tz
```

`abl`, `hyp` and `tz` being hash-protected here is independent confirmation of the
never-touch rule: those partitions sit in the AVB chain **and** the fuse-rooted Qualcomm
Secure Boot chain. Two separate reasons, same conclusion.

### The one scenario where it comes back

**Restoring full stock firmware via Odin.** A stock AP tar rewrites `vbmeta` with
Samsung's flags=0 version, verification switches back on, and an unsigned `boot` is
rejected again. If that happens, re-flash the permissive one — which is staged:

```bash
heimdall flash --VBMETA rescue/vbmeta-flags3.img     # or
odin4 -u rescue/vbmeta-flags3.tar                    # or dd, with root
```

`avbtool` 1.4.0 is also installed, so a fresh permissive vbmeta can be generated from
scratch (`avbtool make_vbmeta_image --flags 3 --output vbmeta.img`) if the backup is ever
lost. But the backup is the better option: it keeps Samsung's real descriptors.

So: **no, we don't need to do anything about vbmeta** — not now and not later, unless a
full stock restore puts it back.

---

## 3. ⚠️ The rescue path has a gap — fix it first

**Your `recovery` partition is stock Samsung recovery, not TWRP.** Checked by unpacking
the captured image: no `twrp`/`teamwin` strings, just stock. Stock Samsung recovery gives
no root shell and only limited `adb`, so it is **not** a useful rescue environment.

That means today, if a bad `boot` stops Android from booting, your only way back is
Download Mode + Odin/heimdall. That works, but it's slow and needs the host set up.

**TWRP is optional, not a prerequisite.** An earlier draft of this file recommended
flashing it before experimenting; that over-stated things. Download Mode is already a
complete rescue path and it cannot be taken away from us, because it lives in ABL/XBL
which we never write.

What's actually worth doing instead — and it costs no writes at all — is **proving the
Download Mode path works before we need it**:

```bash
sudo dnf install heimdall      # Fedora ships 2.2.2
# power off; hold Vol-Up + Vol-Down; plug in USB; expect the blue "Downloading..." screen
heimdall detect                # READ-ONLY
heimdall print-pit --no-reboot # READ-ONLY, dumps the partition table
```

If those two read-only commands work, the rescue path is verified rather than assumed,
and TWRP becomes a pure convenience. `rescue/restore-boot.sh` automates the restore both
ways and refuses to run if the rescue image's hash doesn't match.

**When TWRP would be worth the tangent:** if Download Mode turns out flaky (heimdall has
a mixed record on recent Samsungs), or if we end up iterating enough that 30 seconds vs a
few minutes per failure actually adds up. Revisit then, not now. Note also that the stock
vbmeta carries a *Chain Partition* descriptor for `recovery`, so replacing recovery is
not entirely free of thought — whereas `boot` is.

### The rescue ladder, worst case downward
1. Bad `boot` → Android won't start → no `adb`
2. → **Download Mode** (Vol-Up + Vol-Down + USB) → `heimdall`/`odin4` → restore.
   **This is the real path, and it always exists** because Download Mode lives in
   ABL/XBL, which we never write. That is the whole reason the "never touch
   `xbl`/`abl`/`tz`/`aop`" rule matters — see
   [09-bootloader-plan.md](09-bootloader-plan.md).
3. → *(optional)* **TWRP** (Vol-Up + Power) → `adb` → `dd` — faster, if you install it.

Ready to go, in `rescue/`:

| File | For |
|---|---|
| `boot-stock-magisk.img` | `dd` / `heimdall flash --BOOT` |
| `boot-stock-magisk.tar` | `odin4 -a` |
| `boot-stock-magisk.tar.md5` | Odin GUI |
| `restore-boot.sh` | automates both routes; verifies hashes; refuses on mismatch |

All built from the captured `boot` and round-trip verified; SHA256 `2e56945e…` matches the
backup manifest. It is the **Magisk-patched** boot, so restoring it returns a *working
rooted Android* — which is exactly what you want from a rescue image.

---

## 4. The iteration loop — use the **`recovery`** slot, not `boot`

An earlier version of this file had us writing `boot` every attempt. That works, but it
puts the working system at risk on every iteration, and a failure then needs a Download
Mode rescue. Better:

**Write experiments to `recovery` (`/dev/block/sda20`, 96 MiB) and leave `boot` alone.**

| | |
|---|---|
| `boot` | stays the working rooted Android — **never written** |
| `recovery` | the experiment slot |
| test | `adb reboot recovery`, or Vol-Up + Power |
| failure | hold Power ~10 s, boot normally, Android + `adb` are back |
| Download Mode | **never needed in the normal loop** |

We lose stock Samsung recovery, which costs nothing: it has no root shell and only
limited `adb`, so it was never a useful rescue environment (§3). It is backed up, and
`tools/flash-experiment.sh --restore` puts it back.

`tools/flash-experiment.sh` does the whole cycle: size check against the partition, push,
device-side hash verify, `dd`, read-back verify, and only then reboot. It refuses to
reboot on any mismatch.

### It is not actually slow — measured on this device

```
adb push   37.2 MB/s   (32 MB in 0.86 s)
UFS write  744 MB/s    (32 MB in 0.043 s)
```

A ~30 MB image lands in **well under a second**. The reboot dominates, so an iteration is
roughly **15–20 s**, nearly all of it waiting for the device to come back. There is no
meaningful win left in avoiding the write.

### Two faster approaches, both checked and ruled out

- **kexec from running Android** — would skip the reboot entirely. Dead: Samsung's
  `q2q_eur_openx_defconfig` sets **none** of `CONFIG_KEXEC*`, and the config has 6
  RKP/`uh_*` hits confirming Samsung's hypervisor is active, which blocks replacing the
  running kernel anyway. Doubly out.
- **uniLoader loading the payload from storage** — would let us flash the loader once and
  then update only the kernel. Not supported: every payload option in uniLoader's Kconfig
  `depends on EMBED_LINUX`, so kernel + DTB + ramdisk are always linked into the loader
  image. Would require writing a storage driver for uniLoader.

Recorded so nobody re-investigates.

### Header version caveat for the recovery slot
Stock `boot` is **header v3**; stock `recovery` is **header v2** (with
`kernel_addr 0x8000`, `ramdisk_addr 0x2000000`). If ABL is strict about this for the
recovery slot, build the experiment image as v2 and mirror those values. If it just parses
`header_version` from the image, v3 is fine. First attempt settles it — try mirroring v2.

## 5. Writing `boot` directly (first install, or if you prefer)

Root is available right now, so this needs no special mode at all.

```bash
# verified on this device: boot -> /dev/block/sda19, 100663296 bytes (96.0 MiB)
adb shell 'su -c "readlink -f /dev/block/by-name/boot"'    # ALWAYS resolve by name

sha256sum boot.img
adb push boot.img /data/local/tmp/boot.img
adb shell 'sha256sum /data/local/tmp/boot.img'             # must match the host hash

adb shell 'su -c "dd if=/data/local/tmp/boot.img of=/dev/block/by-name/boot bs=4096 && sync"'

# read back and compare BEFORE rebooting
adb shell 'su -c "dd if=/dev/block/by-name/boot bs=4096 count=24576 2>/dev/null | sha256sum"'

adb reboot
```

Rules: hash before *and* after every write; resolve the partition by name, never hardcode
`sda19`; and write **only** `boot`.

## 6. Size budget

| | bytes | |
|---|---|---|
| `boot` partition | 100,663,296 | 96.0 MiB — hard ceiling |
| stock kernel | 57,393,664 | 54.7 MiB (Samsung's, with everything built in) |
| stock ramdisk | 768,290 | 750 KiB |
| uniLoader itself | 63,568 | 62 KiB |

A mainline `Image` is far smaller than Samsung's 54.7 MiB, so loader + kernel + DTB +
initramfs fits comfortably. Still worth asserting before each flash.

## 7. Building the image

```bash
# real payloads into the loader, then build uniLoader (see uniloader-work/README.md)
gunzip -c arch/arm64/boot/Image.gz        > uniloader/blob/Image
cp sm8350-samsung-q2q.dtb                   uniloader/blob/dtb
cp initramfs.cpio.gz                        uniloader/blob/ramdisk
./uniloader-work/install.sh "$PWD/uniloader" --build

# wrap it as a boot image, PRESERVING the stock header values
mkbootimg --header_version 3 \
          --os_version 11.0.0 \
          --os_patch_level 2026-08 \
          --kernel uniloader/uniLoader \
          --ramdisk <stock ramdisk from the captured boot.img> \
          -o boot-q2q.img
```

`os_version 11.0.0` and `os_patch_level 2026-08` were read from your stock header — copy
them exactly. Note the stock `boot` is **header v3**; the stock `recovery` is an older
header version, so don't assume they match.

> Your captured `tier2-recovery/boot.img` is the **Magisk-patched** boot, not pristine
> stock. That is good for rescue — restoring it returns a *working rooted Android*. If you
> ever need true stock, that comes from the firmware archive.

## 8. First boot — what to expect

The screen is the only output we'll have. uniLoader paints a `simplefb` console at
`0xe4000000` (2208×1768 ARGB8888). So:

- **Text on the inner screen** → uniLoader ran. Load addresses were right.
- **Samsung's "unverified firmware" prompt, then nothing** → ABL accepted the image but
  uniLoader didn't get far. Most likely `TEXT_BASE`/`PAYLOAD_ENTRY`
  ([uniloader-work/README.md](uniloader-work/README.md)).
- **Straight back to Download Mode or a bootloop** → ABL rejected the image. Check the
  arm64 header and `mkbootimg` arguments.
- **Nothing at all, no backlight** → go to the rescue ladder; don't flash again blind.

There is no UART (see [05-research-gaps.md](05-research-gaps.md) Q12), so `ramoops` is the
other thing worth enabling early — the `q2q` DTS already declares a node, and it survives
a reboot.
