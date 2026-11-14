# Captured device facts

Read off **your actual unit** over `adb`. **Round 1** 2026-11-06 (locked, unrooted);
**Round 2** 2026-11-07 (unlocked, rooted) in §R2 below. This supersedes assumptions
elsewhere in these docs.

```
serial                              <redacted>
ro.product.model                    SM-F926B
ro.product.device                   q2q
ro.board.platform                   lahaina
/sys/devices/soc0/machine           LAHAINA
/sys/devices/soc0/soc_id            415
/sys/devices/soc0/revision          2.1          ← SoC rev, not WiFi chip rev
/sys/devices/soc0/hw_platform       MTP
/sys/devices/soc0/platform_version   65536
/sys/devices/soc0/raw_id             309
/sys/devices/soc0/raw_version        3
ro.revision                         9            ← board hardware revision
ro.bootloader                       F926BXXSJJZH3
ro.build.version.release            15           (Android 15 / One UI 7)
ro.build.version.security_patch     2026-08-05
ro.boot.dtb_idx                     0
ro.boot.dtbo_idx                    2
ro.boot.verifiedbootstate           green
ro.boot.flash.locked                1            ← currently locked
ro.boot.warranty_bit                0            ← Knox INTACT
sys.oem_unlock_allowed              1            ← UNLOCKABLE ✅
knox.kg.state                       Completed
ro.oem.key1                         MWD
```

## What this settles

### ✅ The device is unlockable (Q1 closed)
`sys.oem_unlock_allowed = 1` and `warranty_bit = 0`. The bootloader-binary ceiling that
worried me on the Tab S8 does not apply here — the unlock path is open. **The project is
viable.**

### ✅ `r08` is the authoritative device tree for this unit (Q9 narrowed)
`ro.revision = 9`, and the board DTS revision ranges are:

| DTS | `dtbo-hw_rev` | `..._end` | Main panels offered |
|---|---|---|---|
| `r01`, `r02` | 0x1, 0x2 | same | S6E3XA1 (+ S6E3FA7, S6E3HA9) |
| `r03`–`r07` | 0x3–0x7 | same | S6E3XA1, **S6E3XA2** |
| **`r08`** | **0x8** | **0x20** | S6E3XA1, **S6E3XA2** |

Revision 9 falls only inside `r08`'s range (8–32). So
**`q2q_eur_openx_w00_r08.dts` is the correct reference** — which is the file all the
hardware analysis in [01-hardware-inventory.md](01-hardware-inventory.md) was done
against. Nothing to redo.

`r08` still offers *both* `S6E3XA1` and `S6E3XA2` as main-panel options, so **which DDIC
is actually fitted remains open** and needs root (`/sys/class/lcd/panel/lcd_type` is not
world-readable). Given rev 9 is late, `S6E3XA2` is the likely one — but write the driver
only after confirming.

### ⚠️ Decline all further OTA updates, starting now
You are on Android 15 with the 2026-08-05 patch and the unlock path **open**. A future
bootloader could close it — that is exactly what happened on the Tab S8 (binaries A/B,
~Feb 2026), and the S22 port warns that newer Samsung firmware relocks the bootloader.
The Fold 3 is past major-version updates, so the risk is modest, but it is pure downside.
**Turn off automatic system updates before you do anything else.**

## Useful values for the port

| Value | Use |
|---|---|
| `soc_id = 415` | SoC ID for SM8350 — relevant to `qcom,msm-id` and ABL DTB matching |
| SoC revision `2.1` | Matches upstream `sm8350.dtsi` (v2 silicon) |
| `hw_platform = MTP` | Matches the DTS `QCOM,LAHAINA-MTP` compatible |
| `dtb_idx=0`, `dtbo_idx=2` | Which DTB/DTBO ABL picked — evidence for how its selection works |
| `cont_splash_region @ 0xE4000000`, 35 MiB | `simple-framebuffer` base, and uniLoader's framebuffer address |

## Still needs root

| Question | What to read |
|---|---|
| **Q5** — QCA6490 SoC hw version (decides `ath11k`) | `dmesg \| grep -i cnss`, `/sys/kernel/debug/cnss2/` |
| **Q9** — which main panel DDIC is fitted | `/sys/class/lcd/panel/lcd_type`, `window_type` |
| **Q10** — which audio amp is populated | `/sys/class/..`, `dmesg \| grep -iE 'cs35l41\|tas256\|sma130'` |
| **Q8** — post-ABL merged device tree | `dtc -I fs -O dts /sys/firmware/devicetree/base` |
| uniLoader load addresses | boot image header + `/proc/iomem` |
| dual-cell `bat_enb` GPIO default states | limiter sysfs / GPIO state (see Q4) |

`tools/00-collect-facts.sh` captures all of it in one pass once you have root. It needs
root, so it runs **after** unlocking — which is fine, because unlock wipes `userdata` but
leaves `EFS`, `persist` and the hardware itself intact. See
[11-extraction-plan.md](../11-extraction-plan.md) §0 for the corrected ordering.


---

# §R2 — Rooted capture, 2026-11-07

Device state changed: **unlocked and rooted.**

```
ro.boot.flash.locked        0          (was 1)
ro.boot.verifiedbootstate   orange     (was green)
ro.boot.warranty_bit        1          (was 0 -- Knox now permanently tripped)
sys.oem_unlock_allowed      1
su -c id -u                 0          Magisk 31100
ro.bootloader               F926BXXSJJZH3   (unchanged -- no firmware drift)
```

Captures live in `capture/backup-20261107-005831/` (1.8 GB, partitions) and
`capture/facts-20261107-010152/` (logs, merged DT, boot header).

## Panels — Q9 CLOSED, two independent ways

The kernel command line, which **ABL itself sets**, names both panels outright:

```
msm_drm.dsi_display0=ss_dsi_panel_S6E3XA2_AMF755ZE01_QXGA:
msm_drm.dsi_display1=ss_dsi_panel_S6E3FAB_AMB623ZF01_HD:
msm_drm.lcd_id=811044        sec_common_fn.lcd_id=811044     (main)
msm_drm.lcd_id1=811043       sec_common_fn.lcd_id1=811043    (cover)
```

And the merged post-ABL DT agrees: the primary display's
`qcom,dsi-default-panel` phandle resolves to a node labelled
`ss_dsi_panel_S6E3XA2_AMF755ZE01_QXGA`.

| | fitted DDIC | runtime ID | sysfs |
|---|---|---|---|
| Main (inner) | **S6E3XA2_AMF755ZE01** | `0x811044` → `SDC_811044` | `/sys/class/lcd/panel` |
| Cover | **S6E3FAB_AMB623ZF01** | `0x811043` → `SDC_811043` | `/sys/class/lcd/panel1` |

**The panel driver in `panel-work/` targets the correct DDIC** (XA2, not XA1).
Also settles which sysfs node is which screen.

## Wi-Fi / Bluetooth — Q5 answered to high confidence (indirect)

```
PCI 0000:01:00.0   vendor 0x17cb  device 0x1103  revision 0x01
platform device    b0000000.qcom,cnss-qca6490
BT regulators      b2e5510.bt_qca6490  (bt-vdd-dig / bt-vdd-aon / bt-vdd-rfa2)
rails confirmed    io 1.8V  rfa1 1.984V  dig 1.0125V  aon 1.0125V  rfa2 1.35V
```

Device ID `0x1103` is the one `ath11k` handles on its WCN6855 path. **Three independent
signals all indicate hardware revision 2.0:**

1. `/vendor/firmware/qca6490/` contains **`amss20.bin` and no `amss.bin`**. Downstream
   `cnss2/pci.c` selects `amss20.bin` only when
   `device_version.major_version == FW_V2_NUMBER` (== 2).
2. Bluetooth firmware is **`hpbtfw20.tlv` + `hpnv20.bin`**. Upstream `btqca.c` builds
   `qca/hpbtfw%02x.tlv` with the `hp` stem for `QCA_WCN6855`/`QCA_QCA2066`, so these are
   rom_ver `0x20`.
3. PCI config revision byte is `0x01`.

Major version 2 is the branch `ath11k` supports; minor `0x00`/`0x01` maps to
`ATH11K_HW_WCN6855_HW20` — **no driver changes**. Still *indirect*: `ath11k` reads
`soc_hw_version` from TCSR, which we have not read directly. The clean confirmation is a
reboot plus an immediate `dmesg | grep -i cnss`; the ring buffer had already wrapped
(`log_buf_len=256K`) on both the live log and `/proc/last_kmsg`.

## Battery — Q4 CLOSED, and it validates the safe plan

The limiter driver logs, repeatedly (92 samples) on a booted, working device:

```
s2asl01_check_status [MAIN LIMITER]: enb = 0,  det = 0
s2asl01_check_status [SUB LIMITER]:  enb = 0,  det = 0
```

`enb` is active-low, and the phone runs normally in this state, so **both cells rest in
the ENABLED state.** With no driver touching those GPIOs — which is what a mainline
kernel does — both cells stay connected in parallel. That is exactly the
"leave it to the hardware" option, and it is now evidence-backed rather than assumed.
See [`../10-battery-plan.md`](../10-battery-plan.md).

Live `power_supply` nodes confirm the DTS-derived topology: `max77705-charger`,
`max77705-fuelgauge`, `max77705-otg`, `mfc-charger` (wireless), `s2asl01-limiter-main`,
`pogo`, `battery`, `ac`, `otg`.

## Audio — Q10 answered
`cs35l41` dominates dmesg (154 hits) vs `tas256x` (4). Note the *firmware* files are
named `cs35l40-{top,bot}-dsp1-spk-prot.wmfw` — Samsung's naming, same Cirrus family.
Two amps (top + bottom). `CONFIG_SND_SOC_CS35L41` is upstream. Haptics firmware
`cs40l25a*` also present (not upstream; upstream has `cs40l50`).

## Boot image header — for `mkbootimg`

```
magic            ANDROID!
header_version   3            <- v3 has NO load-address fields; ABL fixes them
kernel_size      57393664     (54.73 MiB)
ramdisk_size     768290       (750.3 KiB)
os_version       11.0.0       <- PRESERVE these two verbatim when repacking
os_patch_level   2026-08
header_size      1580
```

So `TEXT_BASE` / `PAYLOAD_ENTRY` / `RAMDISK_ENTRY` for uniLoader **cannot** come from the
boot header. `/proc/iomem` and `/proc/cmdline` are captured for that work instead.

## Kernel command line — notable entries

```
console=null                              <- no console; needs CONFIG_CMDLINE_FORCE
log_buf_len=256K                          <- why dmesg wraps; raise it
firmware_class.path=/vendor/firmware_mnt/image
androidboot.bootdevice=1d84000.ufshc
cpuinfo.chipname=SM8350
androidboot.verifiedbootstate=orange
kpti=off   panic=4   swiotlb=2048
video=vfb:640x400,bpp=32,memsize=3072000
```

## Merged post-ABL device tree — Q8 captured
27,092 property files → `capture/facts-*/dt/q2q-merged-postabl.dts` (36,153 lines).
Confirms ABL merges **all** the overlay fragments: all three panel nodes
(`S6E3XA1`, `S6E3XA2`, `S6E3FAB`) are present in the live tree, with selection done by
phandle and command line. `/proc/iomem` shows `0af00000-0af1ffff : af00000.qcom,dispcc`,
confirming dispcc's base address.

## Firmware locations — verified (Q11 extended)

| What | Path on device | Destination |
|---|---|---|
| Wi-Fi | `/vendor/firmware/qca6490/` — `amss20.bin`, `m3.bin`, `regdb.bin`, `bdwlan.elf{,1,2,10}` | `/lib/firmware/ath11k/WCN6855/hw2.0/` (rename `amss20.bin`→`amss.bin`; wrap BDFs into `board-2.bin`) |
| Bluetooth | `/vendor/firmware/` — `hpbtfw20.tlv`, `hpnv20.bin`, `bt_nvm_loading.xml` | `/lib/firmware/qca/` |
| GPU | `a660_gmu.bin`, `a660_sqe.fw` (+ `a660_zap.{mdt,bNN}` in `firmware_mnt/image`) | `/lib/firmware/qcom/` |
| IPA | `/vendor/firmware/ipa_fws.{mdt,bNN,elf}` | `/lib/firmware/qcom/sm8350/` |
| remoteproc | `/vendor/firmware_mnt/image/` — `adsp.*`, `cdsp.*`, `slpi.*`, `modem.*`, `evass.*` | `/lib/firmware/qcom/sm8350/` |
| Touch / pen | `fts9cu80f_q2.bin`, `fts9cu59_q2.bin`, `wez01_q2.bin` | per-driver |

**Neither the Wi-Fi nor the Bluetooth firmware is in `linux-firmware`** — it ships only
`ath11k/WCN6855/hw2.0|hw2.1` (no QCA6490 dir) and `qca/hpbtfw21.tlv`/`hpnv21.*` (the 2.1
variants, not our 2.0). Both must be extracted, and neither is redistributable.
