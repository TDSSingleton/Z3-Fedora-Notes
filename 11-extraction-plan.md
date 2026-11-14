> **HISTORICAL** — written during planning, before any code existed. Parts are now wrong.
> See [HANDBOOK.md](HANDBOOK.md) for the current state.

# Extraction plan — everything needed off the device

> ### ⚠️ Ordering correction to my earlier advice
> Earlier docs said *"back up `EFS` before unlocking."* **That is impossible, and I was
> wrong.** Reading `EFS` needs root (or TWRP), root needs an unlocked bootloader, and
> unlocking is the irreversible step. There is no way to read `EFS` on a locked Samsung.
>
> The real ordering is below. The saving grace: **unlocking factory-resets `userdata` but
> does not erase `EFS`, `persist` or `modemst*`.** So those survive unlock — the rule is
> to grab them *immediately after* gaining root, before any flashing experiments.

---

## 0. Correct order of operations

| # | Step | Needs | Reversible? |
|---|---|---|---|
| 1 | Unrooted facts | nothing | ✅ done → [08-device-facts.md](Hard%20Truths/08-device-facts.md) |
| 2 | **Download full stock firmware archive** | PC only | ✅ your restore path |
| 3 | Disable automatic system updates | — | ✅ protects the unlock path |
| 4 | **Unlock bootloader** | — | ❌ Knox efuse, `userdata` wiped |
| 5 | Flash TWRP to `recovery` (or Magisk-patched `boot`) | unlock | ⚠️ |
| 6 | **Back up `EFS` + friends — do this first, before anything else** | root/TWRP | — |
| 7 | Extract vendor firmware | root | — |
| 8 | Rooted facts collection | root | — |
| 9 | Verify every archive off-device, twice | — | — |
| 10 | *Then* start Phase 1 flashing | — | — |

**Step 2 matters more than it looks.** The stock firmware archive is your only
"reinstall everything" path, and it does *not* contain your per-device calibration —
which is exactly why step 6 is urgent. Get the archive with `samloader` / Frija /
`samfirm.js` for model `SM-F926B` and your CSC region. Match or exceed
`F926BXXSJJZH3`; **never a newer bootloader than you need** (see
[03-boot-chain.md](03-boot-chain.md)).

---

## 1. Tier 1 — irreplaceable. Lose these and the loss is permanent.

Per-device calibration and identity. **Not in any firmware download. Cannot be
regenerated.**

| Partition | Contents | Consequence if lost |
|---|---|---|
| `EFS` | IMEI, **Bluetooth MAC**, **Wi-Fi MAC**, per-device keys | No BT/Wi-Fi identity, no cellular identity. Unrecoverable. |
| `sec_efs` | Samsung extended EFS | Samsung-side identity data |
| `persist` | Sensor calibration registry, Wi-Fi/BT cal | Sensors mis-calibrated permanently |
| `modemst1`, `modemst2` | Modem NV (network settings) | Modem may not attach |
| `fsg`, `fsc` | Modem filesystem + checksum | Modem bring-up failures |

**Rules:** back these up before anything else once rooted; store three copies in
different places; verify SHA256 on every copy; **never write them again.** They are
read-once insurance.

`tools/01-backup-critical.sh` does this.

## 2. Tier 2 — recovery images

Lets you get back to a booting stock system without a full Odin flash.

```
boot  vendor_boot  dtbo  vbmeta  vbmeta_system  recovery  init_boot (if present)
up_param  param  keystorage  (Samsung-specific; capture if present)
```

Also capture the **partition table itself**, because partition node numbers are
device-specific and you must never hardcode them:

```bash
adb shell 'su -c "ls -l /dev/block/by-name/"'
adb shell 'su -c "cat /proc/partitions"'
adb shell 'su -c "sgdisk -p /dev/block/sda"'      # if available
```

## 3. Tier 3 — vendor firmware for the mainline kernel

A mainline kernel still needs Qualcomm's **signed** blobs, and most are not in
`linux-firmware`. On Qualcomm Android these live in two places.

> **Paths verified on-device 2026-11-07.** Two corrections to what this file originally
> guessed: the Wi-Fi firmware is in a **`qca6490/` subdirectory**, not the
> `/vendor/firmware` root; and the **modem image is in its own partition** mounted at
> **`/vendor/firmware-modem/image/`**, not in `firmware_mnt`. The first version of
> `02-extract-firmware.sh` missed the modem entirely because of that.

### `/vendor/firmware_mnt/image/` — remoteproc / subsystem images (apnhlos, 190 MiB)

These are the signed `.mbn`, or split `.mdt` + `.b00`…`.bNN` sets.

| Image | Needed for | Your goal |
|---|---|---|
| `adsp.*` | `qcom,sm8350-adsp-pas` — audio DSP, also gates some sensors | audio, sensors |
| `cdsp.*` | `qcom,sm8350-cdsp-pas` — compute DSP | general stability |
| `slpi.*` | `qcom,sm8350-slpi-pas` — sensor DSP, **GNSS** | sensors, GPS |
| `modem.*` (MPSS) | `qcom,sm8350-mpss-pas` | **Goal 5 — LTE.** ⚠️ NOT here — see `/vendor/firmware-modem/image/` (163 MiB `modem` partition) |
| `ipa_fws.*` | upstream `qcom,sm8350-ipa` | **Goal 5 — mobile data** |
| `a660_zap.*` | Adreno 660 zap shader (`gpu_zap_shader`) | **GPU — needed for any compositor** |
| `venus.*` / `iris` | hardware video codec | optional |

> The `a660_zap` blob is easy to overlook and the GPU will not come up without it.
> Grab it deliberately.

Upstream convention places these under `/lib/firmware/qcom/sm8350/`.

### `/vendor/firmware/` — peripheral firmware

| Files | For |
|---|---|
| `qca6490/` → `amss20.bin`, `m3.bin`, `regdb.bin`, `bdwlan.elf{,1,2,10}` | **Wi-Fi (QCA6490)** → see [12-wifi-qca6490.md](Hard%20Truths/12-wifi-qca6490.md) §6 |
| `hpbtfw20.tlv`, `hpnv20.bin`, `bt_nvm_loading.xml` | **Bluetooth** (`hci_qca`; `hp` = WCN6855 family, rom_ver 0x20) |
| touch controller firmware (STM `stm_ts`) | inner-screen touch |
| `cs35l41`/amp tuning blobs, if present | audio |

Also sweep `/vendor/etc/wifi/`, `/vendor/lib/firmware/`, `/odm/firmware/`, and
`/mnt/vendor/persist/` — Samsung scatters things.

**Licensing:** these are Qualcomm's, **not redistributable.** A Fedora image cannot ship
them; that's what `droid-juicer` is for ([06-fedora-strategy.md](06-fedora-strategy.md)).

`tools/02-extract-firmware.sh` does this.

## 4. Tier 4 — hardware facts (the open research questions)

Answers the questions that are still open, and produces values the port needs.

| Want | Where | Closes |
|---|---|---|
| **Which main-panel DDIC is fitted** — `S6E3XA1` vs `S6E3XA2` | `/sys/class/lcd/panel/lcd_type`, `window_type`, `SVC_OCTA` | **Q9** — decides which panel driver you write |
| **QCA6490 `soc_hw_version` major/minor** | `dmesg \| grep -i cnss`, `/sys/kernel/debug/cnss2/*` | **Q5** — zero code vs. small patch |
| **Merged post-ABL device tree** | `dtc -I fs -O dts /sys/firmware/devicetree/base` | **Q8** — shows what ABL does to a DTB |
| **`bat_enb` GPIO default states** | `/sys/kernel/debug/gpio` | **Q4** — validates the charging plan |
| **uniLoader load addresses** | `/proc/iomem`, `/proc/cmdline`, boot image header | the 3 unknowns in [09-bootloader-plan.md](09-bootloader-plan.md) |
| Audio amp variant | `dmesg \| grep -iE 'cs35l41\|tas256\|sma130'` | Q10 (not a goal) |
| Stock boot image header | `unpack_bootimg` on the dumped `boot` | `mkbootimg` args: header version, page size, `os_version`, `os_patch_level` |
| Full `dmesg` | — | reference for every subsystem's init order |

`tools/00-collect-facts.sh` does this.

### Why the merged device tree (Q8) is worth the effort
It is the single best piece of evidence for the ABL problem. Comparing Samsung's
**source** overlay (`q2q_eur_openx_w00_r08.dts`, 266 `fragment@N` blocks) against the
**merged result** ABL actually hands the kernel shows precisely which nodes ABL injects
and rewrites. That directly informs whether the uniLoader shim is strictly necessary or
whether the M52-style `vendor_boot` DT injection could work.

Also check what ABL does to `/memory` — U-Boot's docs and the S22 port independently
report Samsung bootloaders emitting bogus or zero-sized memory nodes.

## 5. Tier 5 — reference material already in hand

No extraction needed; noted so it isn't re-derived:

| Source | Use |
|---|---|
| `SM-F926B/Kernel/drivers/clk/qcom/dispcc-lahaina.c` | register reference (upstream dispcc already covers SM8350) |
| `.../techpack/display/msm/samsung/S6E3XA2_AMF755ZE01/` | main panel DCS init sequences |
| `.../techpack/display/msm/samsung/S6E3FAB_AMB623ZF01/` | cover panel DCS init sequences |
| `.../drivers/battery/limiter/s2asl01_limiter/` | dual-cell topology → [10-battery-plan.md](10-battery-plan.md) |
| `.../drivers/net/wireless/cnss2/` | QCA6490 power sequencing, firmware names |
| `.../arch/arm64/boot/dts/vendor/qcom/lahaina.dtsi` | SoC-level nodes (wlan node at `:5381`) |

---

## 6. Verification discipline

Extraction is worthless if the archive is silently corrupt, and you only find out when
you need it.

1. **Hash on the device, hash on the host, compare.** Every image.
2. **Check sizes against `/proc/partitions`.** A short `dd` is the classic silent failure.
3. **Never `dd` a Tier-1 partition in the write direction.** Read-only, always.
4. **Store off-device in at least two places**, one not on the work machine.
5. **Keep a plain-text manifest** — partition name, size, SHA256, date, device serial.
   Future-you will not remember which dump came from which flash state.

The scripts write a `MANIFEST.txt` with hashes for exactly this reason.

---

## 7. Scripts

Run in order, after root:

| Script | Purpose | Root? |
|---|---|---|
| `tools/00-collect-facts.sh` | Tier 4 — hardware facts, all open questions | partial (runs unrooted too) |
| `tools/01-backup-critical.sh` | **Tiers 1 + 2 — run this FIRST after root** | yes |
| `tools/02-extract-firmware.sh` | Tier 3 — vendor firmware | yes |

All three write into a timestamped directory with a `MANIFEST.txt`. None of them write
to the device.
