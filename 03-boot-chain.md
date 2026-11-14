> **Still accurate.** This describes the boot chain and the ABL device-tree
> problem, which have not changed. The *plans* in later sections were overtaken
> by events — see [HANDBOOK.md](HANDBOOK.md) for what was actually built.

# Boot chain, unlocking, and how not to brick it

> **Read this before plugging the phone in.** Everything here is one-way or
> hard-to-reverse. The research is cheap; the device is not.

Sources are labelled. Items marked **[3P]** come from third-party ports (Galaxy S22,
Galaxy Tab S8+, Galaxy M52) and have **not** been verified on Fold 3 hardware. Items
marked **[LOCAL]** are verified from the Samsung source in this repo. Items marked
**[UPSTREAM]** are verified from git.kernel.org.

---

## 1. The Samsung boot chain

```
PBL → XBL (SBL) → TZ/QSEE + AOP → ABL (UEFI-based) → boot / vendor_boot → kernel
```

There is **no fastboot on Samsung**. `fastboot boot` does not exist. Flashing happens in
**Download Mode** (Odin protocol), and after first boot you can `dd` to partitions over
`adb`/`ssh`.

### The central problem: ABL rewrites device trees

**[3P]** The Galaxy Tab S8+ port states this plainly:

> *You cannot boot mainline Linux directly from Samsung's bootloader on this SoC.
> Samsung's ABL merges its own device-tree overlay fragments onto whatever DTB it
> selects, which corrupts a mainline device tree.*

It adds that fixing DTB *selection* (`qcom,msm-id` / `qcom,board-id`) does not help —
*"selection was never the problem; the overlay merge is."*

**[LOCAL] Our own source drop corroborates this.** `q2q_eur_openx_w00_r08.dts` is not a
normal board DTS. It is 17,889 lines of nothing but:

```dts
fragment@118 {
    target = <0xffffffff>;
    __overlay__ {
        ss_dsi_panel_S6E3FAB_AMB623ZF01_HD { ... };
    };
};
```

…roughly 266 such fragments, with a `__symbols__`/fixups table at the end mapping
fragment paths onto targets (`tlmm`, `cnss_pci`, `wlan`, `bluetooth`, …). That overlay
structure *is* the thing ABL merges. A mainline DTB has none of the nodes those fixups
point at, so the merge produces garbage.

### The workaround: a shim loader

**[3P]** Both the Galaxy S22 (`r0q`, SM8450) and Galaxy Tab S8+ ports use
**uniLoader** (`github.com/ivoszbg/uniLoader`): a small loader that embeds the kernel
Image, the DTB and the ramdisk, and *masquerades as a kernel image* so that ABL "only
ever sees 'a kernel'" and never touches the real DTB. The Tab S8 port notes `lk2nd` does
**not** support SM8450.

**Resolved — see [09-bootloader-plan.md](09-bootloader-plan.md) for the full plan.**
uniLoader has no SM8350 target today, but it needs **no SoC-specific code** for 64-bit
Qualcomm parts: `soc/qualcomm/` contains only `msm8916.c`, while `board-r0q.c` (Galaxy
S22) and `board-gts8wifi.c` (Tab S8) carry SM8450 support purely through tiny board
files. The r0q board file is 517 bytes — basically a framebuffer descriptor. A `q2q`
port is ≈60 lines across five files; the only unknowns are `TEXT_BASE`,
`PAYLOAD_ENTRY` and `RAMDISK_ENTRY`.

`lk2nd` is ruled out (newest target msm8996). U-Boot is ruled out for now — its
`drivers/clk/qcom/` has no `sm8350` **and** no `sm8450`, and its documented test path is
`fastboot boot`, which Samsung lacks.

Counter-example worth noting: the **Galaxy M52 5G** port (SM7325) boots through the
**stock** chain with no shim, using a mainline DT injected into `vendor_boot` via its own
`tools/vb_dtb.py`. So the stock path is not universally impossible — it may vary by SoC
or ABL version. Worth testing before committing to uniLoader.

---

## 2. Unlocking

**[3P]** Procedure, from the Tab S8+ runbook (expect the Fold 3 to be similar, but
verify):

1. Enable *OEM unlocking* in Developer Options.
2. `adb reboot download`
3. At the blue warning screen: **long-press Volume-Up** → *Device Unlock Mode* →
   Volume-Up to unlock.
4. **The device wipes and reboots.**
5. Boot once through OOBE, then power off, to confirm the unlock "took".
6. Re-enter Download Mode with Volume-Up + Volume-Down while plugging in USB.

### Confirmed on your device

Read over `adb` on 2026-11-06 — see [08-device-facts.md](Hard%20Truths/08-device-facts.md):

```
sys.oem_unlock_allowed   1    ← unlockable ✅
ro.boot.warranty_bit     0    ← Knox intact (unlock will trip it)
ro.boot.flash.locked     1    ← currently locked
ro.boot.verifiedbootstate green
ro.bootloader            F926BXXSJJZH3   (Android 15, patch 2026-08-05)
```

The bootloader-binary ceiling that blocks unlocking on newer Tab S8 firmware **does not
apply here**. But that is a property of your *current* firmware: **disable automatic
system updates now**, because a future bootloader may close it.

### Irreversible consequences

- **Knox efuse blows permanently** (`warranty_bit` 0 → 1, currently 0). Samsung Pay, Secure Folder,
  Samsung Health and work profiles stop working forever, on any ROM, including stock.
  *(The two Tab S8 documents disagree about whether the trip happens at unlock or at
  first flash. Either way, assume it happens.)*
- **[3P] The cameras may die.** XDA reported that Samsung disables the cameras on the
  Galaxy Z Fold 3 / Flip 3 when the bootloader is unlocked. Cameras aren't in your goal
  list, and you'd be replacing Android anyway, but if you ever want this phone back as a
  phone, know this up front. **Research item Q3.**
- **[3P] Firmware version matters — but yours is fine.** The Tab S8 port reports a
  bootloader binary ceiling (binary 9 or lower unlockable; A/B from ~Feb 2026 closed it).
  Your device reports `sys.oem_unlock_allowed = 1`, so the path is open **today**. Don't
  update.
- **[3P] Never flash One UI 8 / Android 16 — and this is now stronger than "it relocks".**
  Reported policy: **from One UI 8.0 Samsung removed bootloader unlocking in all
  regions.** Your unlock path exists because you are on One UI 7 / Android 15. There is
  no reason to expect it to survive a major-version update, and the Fold 3 is past major
  updates anyway. Keep automatic updates off.

---

## 3. AVB / vbmeta

Repacked boot images fail Android Verified Boot unless you handle `vbmeta`. Reported
symptom: `ODIN MODE (AVB Fail)`, vbmeta hash mismatch.

**[3P]** The documented approach is to flash a verification-disabled vbmeta built with
`avbtool --flags 3`, in the same Odin session:

```
odin4 -a <boot.tar> -u vbmeta_disabled.tar
```

The uniLoader path reportedly leans instead on ABL's *"press power to confirm unverified
firmware boot"* prompt (which times out by itself). The Galaxy S22 port, flashing only
`boot` by `dd` after first install, does not mention vbmeta at all.

**Expect to need the disabled vbmeta at least once.** Confirm the Fold 3 behaviour.

---

## 4. Partitions

### Safe to write
`boot`, `vendor_boot`, `dtbo`, `vbmeta`, `recovery`, `userdata`, `system`

### Never write — bricks the device
`xbl`, `abl`, `aop`, `tz`, `pmic`, `devcfg`, `keymaster`, `uefisecapp`, and anything else
in the secure-world set. **[3P]** The Tab S8 runbook is explicit: *"Never flash
bootloader or secure-world partitions."*

### Back these up first, and never write them again

```
EFS         ← Bluetooth MAC + Wi-Fi MAC + IMEI-adjacent data. Losing this is unrecoverable.
sec_efs
persist     ← sensor calibration registry
modemst1, modemst2, fsg, fsc   ← modem NV
boot, vendor_boot, dtbo, vbmeta, recovery   ← so you can get back
```

**[3P]** Both Samsung precedents call out `EFS`/`persist` backup as the first step, and
the M52 port pulls the Bluetooth address out of `EFS` at install time. Make these
backups from a working stock system, verify their checksums, and store them off-device
in at least two places.

---

## 5. Firmware extraction

A mainline kernel still needs Qualcomm's signed firmware blobs, and they are **not** all
in `linux-firmware`. **[3P]** The M52 port copies them read-only off the phone's own
partitions:

| From partition | Firmware |
|---|---|
| `apnhlos` | ADSP, GPU zap shader, IPA, Venus/iris |
| `vendor` | Bluetooth firmware, sensor configs |
| `modem` | Modem (MPSS) image |
| `persist` | Sensor registry |
| `EFS` | Bluetooth MAC address |

The Wi-Fi board file (`board-2.bin` / BDF) for QCA6490 likewise comes from the device.
Mobian's **`droid-juicer`** (`gitlab.com/mobian1/droid-juicer`) automates extracting
vendor firmware at boot and is what Pocketblue recommends for this.

Pull all of this **before** wiping Android.

---

## 6. Recommended order of operations

> **Corrected 2026-11-06.** An earlier version of this list said to back up `EFS`
> *before* unlocking. **That is impossible:** reading `EFS` needs root (or TWRP), root
> needs an unlocked bootloader, and unlocking is the irreversible step. The saving grace
> is that unlocking factory-resets `userdata` but **does not erase `EFS`, `persist` or
> `modemst*`** — so they survive, and the rule becomes "grab them the moment you have
> root, before anything else." Full detail in
> [11-extraction-plan.md](11-extraction-plan.md).

1. ✅ **Done** — unrooted facts captured ([08-device-facts.md](Hard%20Truths/08-device-facts.md)).
   `sys.oem_unlock_allowed = 1`, so the unlock path is open.
2. **Download the full stock firmware archive** for `SM-F926B` + your CSC
   (`samloader` / Frija / `samfirm.js`). This is your only "reinstall everything" path,
   and it needs no device access. Do it now.
3. **Disable automatic system updates.** Protects the unlock path.
4. ✅ **Done** — the shim-loader question is resolved on paper
   ([09-bootloader-plan.md](09-bootloader-plan.md)).
5. **Unlock.** Knox efuse blows; `userdata` is wiped; `EFS`/`persist` survive.
6. Flash TWRP for `q2q` to the **recovery** slot (a `q2q` TWRP exists, credited to
   @Azkali), or a Magisk-patched `boot`. Keeping TWRP permanently in `recovery` gives you
   a rescue path that doesn't need Odin every time.
7. **Immediately: `tools/01-backup-critical.sh`** — `EFS`, `sec_efs`, `persist`,
   `modemst1/2`, `fsg`, `fsc`, plus the recovery images. Verify hashes, copy off-device
   twice. **Do this before any other flashing.**
8. `tools/02-extract-firmware.sh` — vendor firmware (§5).
9. `tools/00-collect-facts.sh` again, now rooted — closes Q5, Q8, Q9, Q10 and yields the
   uniLoader load addresses.
10. Only then start iterating on `boot`.

---

## 7. Iteration loop once it boots

**[3P]** From the Galaxy S22 port — this is the pattern to copy, because it avoids Odin
entirely for day-to-day work:

```bash
sha256sum boot.img
adb push boot.img /tmp/boot.img
adb shell 'sha256sum /tmp/boot.img'                      # must match
adb shell 'readlink -f /dev/block/by-name/boot'          # CHECK before writing
adb shell 'dd if=/tmp/boot.img of=/dev/block/by-name/boot bs=4096 && sync'
adb shell 'dd if=/dev/block/by-name/boot bs=4096 count=24576 | sha256sum'   # read back
adb reboot
```

Verify the hash both before and after writing, every time. The partition node number is
device-specific — resolve it by name, never hardcode it.
