# Fold 3 mainline port — handbook

Start here. This is the orientation doc; the numbered files are deeper dives.

**Device:** Samsung Galaxy Z Fold 3, SM-F926B, codename `q2q`, SoC SM8350
(Snapdragon 888, Qualcomm codename *lahaina*). Bootloader unlocked, Knox blown.

**Goal:** Fedora on an as-upstream-as-possible kernel.

---

## 1. Current status (2026-11-13)

Mainline Linux **boots to userspace** and you can get a shell over USB.

| area | state |
|---|---|
| boot chain | uniLoader shim in `boot`, carries kernel + DTB + initramfs. Since 2026-11-13 that kernel is a **loader**: it kexecs into `/boot/fold3/entries/<default>` with automatic fallback -- section 31 |
| console | USB serial gadget, `/dev/fold3` on the host. **Boots with no host attached** since the u_serial patch (section 12) |
| storage | UFS works; `sda19` = boot, self-flashable from the device |
| display | **real KMS** 2026-11-11: DPU + DSI + the S6E3XA2 panel, `card0` at 2208x1768. simpledrm and the bootloader framebuffer are gone. Panel orientation declared `LEFT_UP`, so the desktop is upright in portrait. **Blank/unblank works** since 2026-11-12 (the panel driver never sent display-on; section 18) |
| thermals | 29 TSENS zones |
| battery | fuel gauge reads %. **Charges at ~880 mA on a wall charger** since 2026-11-13: `fold3-charge.service` raises the bootloader's ~100 mA to 900 mA and picks the input limit from the detected charger type -- section 29. No PD/AFC fast charging |
| partitions | `sda37` (named `linux`) = 190.5 GiB carved for Linux |
| rootfs | Fedora 45 KDE Plasma Mobile, btrfs on `sda37`, **boots** |
| handoff | initramfs `switch_root`s into it; soft-fails to a shell |
| first boot | **reaches multi-user with a login prompt in ~23 s.** The old "19 min + emergency mode" was console backpressure, not the device -- see section 12 |
| setup wizard | **Plasma Setup completed** 2026-11-11; a real user account exists and Plasma Mobile runs GPU-composited |
| inner touch | **works** 2026-11-11: ST FTS9CU80F on `spi@990000`, `touch-work/fts9cu80f.c`. Needs GPI DMA built in, the s2dos05 rails, and a rail power cycle -- see section 14 |
| sub-PMIC | **s2dos05** on a bitbanged i2c bus (TLMM 76/77); mainline driver, owns the touch and inner-panel rails |
| keys | **power, volume-down and volume-up work.** Power/vol-down are `pmic_pwrkey`/`pmic_resin` on the PMK8350 PON; volume-up is a `gpio-keys` node on PM8350 `gpio6` (active low, PMIC pull-up), added 2026-11-12 |
| clock | RTC **reads** (`rtc0`, pmk8350) but **cannot be set**: the counter register is TZ-owned. Boots at 1970 and gets bumped to a filesystem timestamp. Needs NTP or an SDAM offset cell |
| WiFi | **works** since 2026-11-11 (S2MPB02-sub buck rails + upstream firmware; section 16 keeps the history). The phone is on the LAN and runs sshd -- section 20 |
| GPU | **works** 2026-11-11: `renderD128`, `GL_RENDERER FD660`, Mesa 26.2.3, GLES 3.2. Zap shader authenticated through Samsung's TZ first try. KWin composites on it -- **the UI is smooth** |
| sensors | **accelerometer, magnetometer, light work** 2026-11-12 through the SLPI + `hexagonrpcd` + `libssc`. **Auto-rotate works** 2026-11-13 (inner screen only) -- sections 19 and 25. Proximity enumerates but libssc cannot parse it; raw gyro unverified |
| Bluetooth | **works with WiFi on** since 2026-11-13: the generic WLAN board file was mis-driving the shared 2.4 GHz front end; the upstream ThinkPad X13s board file fixes both -- section 26 (22 is the history) |
| cover display | **works** 2026-11-12: S6E3FAB 832x2268 as `DSI-2`, a second output, no touch -- section 23. Stays on and unrotated; placed at x=1472 so the rotating inner screen never overlaps it |
| fold | **inner screen blanks when closed** 2026-11-13: AK09970 hall driver + a `fold_blank` knob in the inner panel driver -- section 28 |
| audio | **dropped 2026-11-13** (no working speaker on this unit). Was: silent. Sound card, ADSP and both CS35L41 amps come up and report healthy, but neither amp receives the I2S bit clock although the SoC pin outputs it (measured 2026-11-13). Probably hardware -- section 24 |
| modem | **LTE data works** 2026-11-13 (~14/9 Mbit/s): MPSS + IPA + ModemManager, EFS read-only. Data and SMS only, no calls -- section 27 |

---

## 2. The one idea that explains most bugs

Mainline assumes it owns hardware that **Samsung's firmware has given to the
secure world or a remote processor.** Every hard bug this project hit was a
variant of this:

- APSS watchdog at `0x17c10000` — reads abort from the non-secure world
- TLMM GPIOs — many are TZ-owned; touching them hangs the pinctrl probe
- `smp2p`, crypto BAM — owned by remote processors
- `qfprom` fuses — protected

**When something hangs with no error, ask who owns the registers before
anything else.**

---

## 3. How booting actually works, and why uniLoader exists

```
PBL -> XBL -> TZ/QSEE + AOP -> ABL (UEFI) -> boot partition -> kernel
```

There is **no fastboot on Samsung.** Flashing is Download Mode (Odin protocol,
driven by `heimdall`), or `dd` from a running system.

**The problem uniLoader solves.** Samsung's ABL does not simply hand our device
tree to the kernel. It merges its own overlay *fragments* into whatever DTB it
finds in the boot image — Samsung's own q2q DTS is ~266 `fragment@N {
__overlay__ }` blocks. Applied to a mainline DT, that corrupts it. We cannot
patch ABL: it is verified against Samsung's root-of-trust hash in QFPROM fuses,
which is what "Qualcomm Secure Boot" means here. That is separate from AVB, and
unlocking does not relax it.

**uniLoader** (github.com/ivoszbg/uniLoader) is a small bare-metal shim that
masquerades as an arm64 kernel Image. ABL loads and jumps to it without
inspecting the DTB it carries, so our mainline device tree reaches Linux
untouched. uniLoader then sets up a framebuffer, places the real kernel, DTB
and initramfs in memory, and jumps.

Consequences worth knowing:

- Our `boot.img` is **uniLoader with the kernel embedded inside it**, not a
  normal Android boot image.
- `CONFIG_TEXT_BASE` (where uniLoader relocates itself) must sit **outside every
  `no-map` reserved region** and **below ABL's own load area**. Getting this
  wrong cost many boots: inside a `no-map` region the DTB blocks that region's
  reservation and the kernel allocates into memory the secure world owns.
  Current value `0x9bb00000` is the one free 64 MiB gap that satisfies both.
- uniLoader **cannot read storage**, which is why the kernel must be embedded
  and why kernel updates need a host. See section 8.

---

## 4. Daily workflow

```sh
# build
./tools/build-kernel.sh            # kernel + DTB from kernel-work/ + dts-work/
./tools/build-busybox.sh           # initramfs (busybox + lrzsz)
./tools/build-busybox.sh --rootfs  # ...or the one that pivots into Fedora on sda37
./tools/assemble-boot.sh           # wrap into images/q2q-stage1-boot.img

# flash -- NO Download Mode needed, device flashes itself
python3 -I tools/selfflash.py images/q2q-stage1-boot.img

# reboot, then REPLUG THE CABLE (see gotcha below)
python3 -I tools/dev.py run 'reboot -f'

# talk to it
python3 -I tools/dev.py run 'dmesg | tail -40'
python3 -I tools/dev.py put  local/file /remote/path       # sha256-verified
python3 -I tools/dev.py putdir localdir  /remote/dir       # tar over base64
```

**Use `tools/dev.py`, not `tools/ser.py`.** `ser.py` waits a fixed `SER_WAIT`
seconds and prints whatever arrived, so anything slower than that silently
returns *truncated* output -- which has produced wrong answers more than once.
`dev.py` brackets every command with a unique marker and reads until the
closing marker, so output is either complete or an explicit timeout. It also
logs in by itself (`root` / `fold3`, from `ROOTPW` in `prep-rootfs.sh`), which
matters because **a fresh boot presents a login prompt**: earlier sessions only
ever saw an already-logged-in shell left behind by a previous session, so this
surfaced the first time the device was rebooted cleanly.

**Gotcha:** every reboot drops the USB gadget and it does **not** come back on
its own — the cable must be physically replugged. dwc3 has no VBUS/connector
awareness (no `usb-connector` node, no extcon). Unsolved.

**Gotcha:** use simple commands over the serial link. `&&`, `||` and
redirections get mangled by the tty and have produced wrong answers twice.

### Moving real amounts of data: use TWRP, not the serial console

The serial console exists because our kernel has no other output. It is not a
transport. For anything bigger than a kernel, reboot to TWRP and go through
adb, which is a root shell with the whole disk visible:

```sh
./tools/install-rootfs.sh        # 9.28 GiB rootfs -> sda37, ~4 min
./tools/flash-boot-adb.sh        # boot image -> sda19, seconds
```

**37 MiB/s** measured, against 2.33 MiB/s over serial — four minutes instead of
over an hour. `adb exec-in` is a raw binary pipe; plain `adb shell` is not and
will corrupt binary data.

Both scripts **re-read the live GPT and refuse to write** unless the target
entry has exactly the name, start LBA and end LBA we recorded when the carve
was made. That guard is not ceremony: a wrong index here is an unrecoverable
brick, because no public SM8350 Samsung Firehose programmer exists.

**Two traps in this path, both silent.** They are handled in the scripts, but
anyone writing a new `adb exec-in` pipeline will hit them again:

- **The block size must divide the file exactly.** The device's dd drops a
  final partial block. A 46370816-byte (44.22 MiB) boot image written with
  `bs=1M` landed exactly 44 MiB and left its last 233472 bytes stale — a 99%
  correct kernel image, which would have looked like a mysterious boot failure
  rather than a bad write. Use `bs=4096`; the disk is 4Kn anyway.
- **Never pass `iflag=`.** The device's dd is toybox 0.8.4-android and rejects
  `iflag=fullblock` outright, exiting 1 having written nothing. `adb exec-in`
  is one-way and **discards stderr**, so the failure is completely invisible:
  two flashes in a row changed nothing and appeared to succeed. Use
  `adb exec-out` when you need to see a command's output.

Hash-verify every write. Both traps produce a *partially* correct image, which
is much harder to diagnose after the fact than an outright failure.

### When Linux will not boot

```sh
# Download Mode: power off, hold Vol-Up + Vol-Down, plug USB in
heimdall flash --BOOT rescue/boot-stock-magisk.img    # back to Android
heimdall flash --BOOT golden/stage3-*/q2q-stage1-boot.img   # back to a known-good Linux
```

TWRP is in `recovery` and gives fast adb with root — the best environment for
anything touching partitions.

**Stuck in Linux and cannot power the phone off?** Our kernel has no
power-button handling, so Download Mode is the only exit. From there you can
force the *next* boot into TWRP by setting the BCB in `misc`:

```sh
heimdall flash --MISC rescue/misc-boot-recovery.img      # then it reboots to TWRP
adb shell 'dd if=/dev/zero of=/dev/block/sda10 bs=4096 count=256'   # CLEAR IT
```

**Clearing it is not optional.** The BCB persists, and leaving it set makes the
phone boot *only* recovery — the loop that cost an earlier session. Full
procedure, including the no-write key-combo alternative, in
`rescue/README-force-recovery.md`.

---

## 5. From zero: a fresh clone and a phone

Assumes an unlocked device and a Fedora host.

```sh
# 1. host tools
sudo dnf install heimdall android-tools gcc-aarch64-linux-gnu \
                 sysroot-aarch64-fc44-glibc lrzsz podman git

# 2. everything git does not track: kernel v7.2.15 + patches/ + the panel
#    driver at ./linux-fedora, uniLoader + our board file at ./uniloader,
#    busybox source, and the static lrz/lsz/kexec-load for the initramfs
./tools/setup-sources.sh

# 3. build
./tools/build-kernel.sh && ./tools/build-busybox.sh --rootfs && ./tools/assemble-boot.sh
for d in touch-work hall-work wifi-work cover-work; do make -C $d; done   # out-of-tree modules
#    assemble-boot.sh also needs two files from YOUR phone's stock boot image,
#    which are not in git (Samsung's, and per-firmware): the stock boot.img at
#    capture/backup-*/tier2-recovery/boot.img (step 4 makes it; the path is
#    STOCKBOOT in the script) and its ramdisk, unpacked with unpack_bootimg,
#    at images/stock-boot-ramdisk.img. So on a truly fresh clone, do step 4
#    before the assemble.

# 4. BACK UP FIRST. Boot stock Android with root, then:
./tools/01-backup-critical.sh         # efs, persist, modem... irreplaceable
heimdall download-pit --pit rescue/stock.pit    # from Download Mode

# 5. first flash: Download Mode, then
heimdall flash --BOOT images/q2q-stage1-boot.img

# 6. after it boots, let udev give you a stable console path
sudo cp tools/99-fold3-gadget.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
#    replug -> /dev/fold3 appears
```

From here the loop is self-flash over the cable; step 5 is the only time you
need Download Mode for ordinary work.

**If you have nothing and want a known-good starting point**, flash
`golden/stage3-*/q2q-stage1-boot.img` — it is a verified booting image, and its
`MANIFEST.txt` lists every config decision baked into it.

---

## 6. Tools

| tool | what it does |
|---|---|
| `build-kernel.sh` | merges `kernel-work/q2q-stage1.config` onto Fedora's, builds Image + DTB |
| `build-busybox.sh` | static busybox + lrzsz into an initramfs. `--rootfs` packs the pivoting init |
| `assemble-boot.sh` | embeds payloads in uniLoader, wraps as an Android boot image |
| `selfflash.py` | flashes a boot image **from the device itself** over serial, sha256-verified. Probes for `base64`/`busybox` -- see the trap below |
| `dev.py` | **the one to use**: marker-framed `run`, auto-login, verified `put`/`putdir` |
| `serdrain.py` | passive reader that logs `/dev/fold3` to `capture/boot-logs/` across replugs. **Run it across every reboot** or the phone stalls on console backpressure; stop it before `dev.py` (section 20) |
| `gl-probe.py` | push to the device and run there to prove the GPU really renders |
| `ser.py` | superseded by `dev.py`; fixed-sleep reads, truncates silently |
| `pullrange.py` | pull a sector range off the device, verified against its own hash |
| `gpt.py` | parse a GPT. **Takes the block size** — this disk is 4Kn |
| `gptedit.py` | shrink `userdata`, append a partition. Works on local files only |
| `pit.py` | parse a Samsung PIT |
| `prep-rootfs.sh` | extract Fedora's rootfs and edit it to boot here (libguestfs, no root) |
| `install-rootfs.sh` | write it to `sda37` over adb, GPT-guarded, sha256-verified |
| `flash-boot-adb.sh` | flash a boot image from TWRP over adb, GPT-guarded |
| `build-kernel-modules.sh` | kernel + modules, staged for installing into the rootfs |
| `01-backup-critical.sh` | dump the irreplaceable partitions |
| `catch-panic.sh` | pull pstore (never once worked — see below) |

---

## 7. Hard rules

- **Never write `xbl`, `abl`, `tz`, `aop`, `devcfg`, `pmic`.** Unrecoverable —
  no public SM8350 Samsung Firehose programmer exists.
- **Never `heimdall flash --repartition`.** It rebuilds the GPT from the PIT,
  where `USERDATA` means "rest of disk", and would swallow `sda37`.
- **Never write back `efs`, `sec_efs`, `persist`, `modemst1/2`, `fsg`, `fsc`.**
  They hold IMEI and the BT/WiFi MACs and cannot be regenerated. Backed up in
  `capture/backup-*/tier1-irreplaceable/`, read-only forever.
- **Do not drive charging from our kernel.** The Fold 3 is a *managed
  dual-cell* system: `samsung,sec-dual-battery` over two `s2asl01` limiters
  (i2c 0x38/0x39) that mainline has no driver for. Corrected 2026-11-12: the
  phone is not charge-less -- the bootloader leaves the max77705 charging
  autonomously at its minimum step (~100 mA, 500 mA input), and the limiters
  keep a 900 mA per-cell cap by themselves. That is too little to gain under
  load; fill the battery powered off or from stock Android. Never claim the
  limiter enable pins (gpio 86/167) in DT.
- **Every RPMh regulator voltage must be on the driver's grid.** Mainline's
  PMIC5 LDOs step in 8 mV from a fixed base (`pmic5_pldo`: 1.504 V up), and a
  `min = max` that is not on a step cannot be applied. That fails the probe of
  the **whole PMIC's** regulators, not just the one rail -- and on PM8350C
  that removes the USB PHY and UFS supplies: no USB, no rootfs, black screen.
  This is what `pm8350c_l9` at Samsung's 2.900 V did, twice, on 2026-11-12;
  it looked like the rail killing the phone. 2.904 V boots fine. Check
  `(uV - range_min) % step == 0` against
  `drivers/regulator/qcom-rpmh-regulator.c` before adding any RPMh rail.
- **Decline OTA updates.** Newer firmware reportedly removes unlocking.

---

## 8. The failure that wasted the most time

**If boot output stops at a point that moves between runs, the screen has died
— the kernel has not.**

Three `late_initcall_sync` entries switch off hardware nobody claimed:

    clk.c:1558        clk_disable_unused()       -> display clocks
    pmdomain:1387     genpd_power_off_unused()   -> MMCX, the fb power domain
    regulator:6909    regulator_init_complete()  -> display rails

Our console runs on the **bootloader's** framebuffer and we deliberately never
claim its clocks (claiming them means reprogramming a live scanout — the same
reason `SM_DISPCC_8250=n`). So the kernel correctly decides they are unused and
powers them down, mid-boot, mid-sentence.

These three cmdline flags are **load-bearing**:

    clk_ignore_unused regulator_ignore_unused pd_ignore_unused

Remove any one and this comes back looking like a brand-new hang somewhere
unrelated.

**How to tell this apart from a real hang:** a real hang stops at the *same*
place every time — tlmm, smp2p and the crypto BAM all did. This one moves,
because whichever line was mid-print when the panel lost its clock is where
output appears to stop.

---

## 9. The root filesystem

Fedora Linux 45 **KDE Plasma Mobile**, aarch64, straight from Fedora's own
disk image — not a hand-built container. It lives on `sda37` as **btrfs** with
subvolumes `root`, `home` and `var`, compressed `zstd:1`.

### Why the handoff happens in the initramfs

`root=` on the kernel command line **does nothing here.** Our initramfs is
embedded inside uniLoader, so the kernel always unpacks it and runs its
`/init`; it never looks at `root=`. The pivot to the real filesystem is
therefore a userspace step, in `initramfs-work/init-rootfs.sh`, packed by
`tools/build-busybox.sh --rootfs`:

```
mount -t btrfs -o rw,subvol=root,compress=zstd:1 /dev/sda37 /newroot
mount -o move /dev /proc /sys  ->  /newroot/...
exec switch_root /newroot /sbin/init
```

Three deliberate choices in there:

- **It waits for `/dev/sda37`.** UFS probes asynchronously and the node does not
  exist the instant init starts.
- **It fails soft.** If the mount fails you land in a busybox shell on
  `ttyGS0`, not a reboot loop. On this device a reboot loop costs a physical
  cable replug, so "debuggable" is worth a lot.
- **It moves `/dev` across rather than letting systemd remount it.** systemd
  logs to `/dev/console` well before it would mount devtmpfs itself, and that
  window is the only output we would have if something went wrong in it.

Because btrfs has to be mounted with no module tree available, `BTRFS_FS=y`
and `ZSTD_COMPRESS=y` are **built in**, not modules.

### Modules, and why the kernel version is pinned

`tools/build-kernel-modules.sh` builds the module set (~1500 modules, 70 MB)
and stages it; `prep-rootfs.sh` installs it into the image at
`/lib/modules/<kernelrelease>`. Everything the rootfs needs to *boot* is
built in, so modules are for what comes later — DRM, WiFi, sound.

That path has to be stable, or the rootfs accumulates module trees for kernels
that no longer exist. Pinning it needs two things, and the second is not
obvious:

- `CONFIG_LOCALVERSION="-q2q"` with `LOCALVERSION_AUTO=n`, and
- the **environment variable** `LOCALVERSION` set — even to the empty string —
  at build time.

Without the second, `scripts/setlocalversion` appends `-dirty`, because our
tree is permanently modified: `build-kernel.sh` copies the board DTS into it on
every single build. An empty `.scmversion` file does *not* help; modern
setlocalversion no longer reads it. The deciding test is
`[ "${LOCALVERSION+set}" != "set" ]` near the bottom of that script, so merely
*setting* the variable is what counts. Both build scripts export it.

### What had to be changed in the stock image, and why

Edited with `libguestfs` as a normal user — no loop mount, no sudo. Note the
appliance is x86_64 while the image is aarch64, so guestfish's `command` fails
with "Exec format error": every change is a file edit, and you can never chroot
in and run `dnf` or `systemctl`.

| stock assumption | what it would do here | fix |
|---|---|---|
| fstab requires `/boot` (p2) and `/boot/efi` (p1) | we copy only p3, so `local-fs.target` never completes → emergency mode after 90 s | commented out |
| root password is `!`, no user account exists | a login prompt nothing can satisfy | password set |
| `plasma-setup.service` creates the first user graphically | needs a touchscreen we do not have | **NOT actually disabled** -- the `multi-user.target.wants` symlink is present in the image; see section 13 |
| `default.target` = graphical | Plasma before we know systemd starts at all | `multi-user.target` |
| `ModemManager` enabled | **AT-probes every tty, including `/dev/ttyGS0` — our console** | disabled |

That last one deserves its place: it would have corrupted the console exactly
when the console was the only way to find out why.

Deliberately left alone: `x-systemd.growfs` on `/`. The filesystem is 9.28 GiB
inside a 190.5 GiB partition and systemd grows it on first boot by itself, so
there is no manual `btrfs filesystem resize` step.

`tools/prep-rootfs.sh` does all of it and is re-runnable.

---

## 10. Things that do not work, and why

- **pstore/ramoops** — has never once returned our kernel's output, across
  dozens of attempts. The screen and the serial console are the only proven
  channels. Do not design around it.
- **The APSS watchdog** — unreachable. Both an MMIO poke from uniLoader and the
  in-kernel `qcom_wdt` driver abort on it.
- **Plymouth** — it grabs `/dev/console`, which here is `ttyGS0`, our only
  interactive channel, and draws its splash onto it forever. The port then
  emits an endless `\x1b[33m<square>` stream and ignores all input: no getty,
  no shell, no journal, and it looks exactly like a dead kernel even though
  systemd is running. Password prompts also go to the splash via
  `systemd-ask-password-plymouth` instead of the console. Always boot with
  `plymouth.enable=0`. It is costly too: a full-screen animation composited
  onto a 2208x1768 framebuffer. (It used to be worse: that composite went
  through simpledrm's `fb_deferred_io`. The panel now runs under DPU, but
  Plymouth still owns the console and still has to go.)
- **Kernel updates from the device** — the kernel lives inside `boot.img`
  because uniLoader cannot read storage, so `dnf` installing a kernel to
  `/boot` does nothing. This is the main blocker to daily use; see
  `fold3-chainloader-needed-for-daily-use` in the memory notes.

---

## 12. The console is not passive: drain it or the device stalls

**Always have a host process reading `/dev/fold3` for the whole boot**, not for
the log but for the device's own forward progress.

`ttyGS0` is a CDC-ACM gadget, and `console=ttyGS0` makes `/dev/console` resolve
to it -- so **userspace** console writes take the tty path, where
`gs_write_room()` returning 0 makes the tty layer block the writer forever.
Kernel `printk` was never the problem: `gs_console_write()` already drops into a
`[missed N bytes]` counter.

**Half of this is fixed** (`patches/0003-u_serial-drop-tty-writes-when-no-host.patch`,
2026-11-11). When no host is enumerated at all, the three tty write paths now
discard instead of filling the fifo, and **the phone completes a full boot with
nothing plugged in.** Before that, booting required a USB host to show up,
which is why every earlier boot was done cable-in.

**The other half is not fixed:** a host that enumerates but never *opens* the
port leaves `port_usb` set, the fifo fills for real, and writes block exactly as
before. So the rule above still stands in practice.

This faked two different bugs for two sessions:

- **A "19-minute boot."** The 2026-11-09 capture shows kernel timestamps at
  `1147 s` with systemd still in early sysinit. Drained, the same boot reaches a
  login prompt in ~105 s; `systemd-analyze blame`'s worst entry is 11.5 s.
- **Emergency mode**, by a chain that looks unrelated to the console:
  `/dev/disk/by-uuid/7481...` missed udev's 90 s device timeout ->
  `home.mount` + `var.mount` dependency failure -> `local-fs.target` failed ->
  its `OnFailure=` pulled in `emergency.target`.

**The tell:** tens of KB arrive in one burst the moment a reader attaches, and
timestamps jump. Passive silence is backpressure, not a dead kernel.

**Trap:** after a replug the node moves (`ttyACM0` -> `ttyACM1`). Opening a
stale `/dev/fold3` symlink captures nothing, silently.

---

## 13. Getting to the Plasma Setup wizard

Two independent bugs, both fixed persistently on `sda37`:

- **The clock failed PAM.** No RTC driver exists, so the clock boots stale (it
  read Sep 29 while the `plasma-setup` account's password-change date was
  Oct 28). PAM refused it -- `account plasma-setup has password changed in
  future` -- and `plasmalogin` idled forever without starting a session. The
  durable fix is `chage -d 2026-01-01 plasma-setup`, which holds regardless of
  the clock; `date -s` must be redone every boot.
- **`plasma-setup-bootutil` writes the wrong display manager's config.** It
  reports success against *SDDM* paths, but this image uses **plasmalogin**;
  `/etc/sddm.conf.d/` does not exist and `/etc/plasmalogin.conf.d/` was left
  empty, so the greeter came up instead of the wizard. Fixed by hand in
  `/etc/plasmalogin.conf.d/10-plasma-setup.conf`:

      [Autologin]
      User=plasma-setup
      Session=plasma-mobile.desktop

**The wizard is not drawn by the service.** `plasma-setup.service` only writes
autologin config. The wizard runs from an autostart entry in the `plasma-setup`
user's home (`/run/plasma-setup`, built by tmpfiles):
`.config/autostart/plasma-setup.desktop`. The display manager only has to
autologin that user into an ordinary Plasma session.

**Screen blanking: `prep-rootfs.sh` writes the wrong file.** It sets 24h idle
times in `/etc/xdg/powermanagementprofilesrc`, which **Plasma 6 ignores**. The
user's copy of that file holds only
`[Migration] MigratedProfilesToPlasma6=powerdevilrc`, and the live config is
`~/.config/powerdevilrc` with a different schema
(`[Battery][Display] TurnOffDisplayIdleTimeoutSec=`,
`DimDisplayIdleTimeoutSec=`, `[Battery][SuspendAndShutdown]
AutoSuspendIdleTimeoutSec=`). Exactly the same shape as the bootutil bug above:
success reported against paths nothing reads. To recover a blanked screen:

```sh
setpriv --reuid=1000 --regid=1000 --clear-groups \
  env XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 \
  kscreen-doctor --dpms on
```

**The "screen dark until reboot" bug was not powerdevil.** Until 2026-11-12
no recovery command could bring the panel back after any blank, because the
panel driver never sent display-on -- see section 18. The command above is now
only needed if something blanks the screen and you have no power key to hand.

`wayland-1`, not `-0`. Writing `/sys/class/graphics/fb0/blank` does nothing --
only DRM master can re-enable the output.

Also fixed: an empty `/etc/systemd/zram-generator.conf` removes a 45-52 s
`dev-zram0.device` dead wait, since our kernel has no ZRAM. And
`ARM_QCOM_CPUFREQ_HW` works -- EPSS is not secure-world protected, contrary to
the old config comment -- worth 2.2x under load.

---

## 11. Where things live

```
kernel-work/     our kernel config fragment
dts-work/        our board device tree
uniloader-work/  uniLoader board file + defconfig
initramfs-work/  init, busybox and lrzsz sources/binaries
rootfs-work/     Fedora rootfs image, staged edits, staged kernel modules
patches/         kernel patches (applied by tools/setup-sources.sh); userspace/ for the rest
tools/           everything above; setup-sources.sh recreates what git ignores
images/          the built boot image
golden/          known-good snapshots, each with a MANIFEST explaining it
rescue/          stock boot, TWRP, GPT backups, the PIT
capture/         device dumps: partition backups, logs, facts
docs/            deeper notes, numbered
SM-F926B/        Samsung's GPL source drop -- the single best reference
```

**Samsung's source drop has answered more hard questions than anything else.**
When mainline behaviour is baffling, grep `SM-F926B/Kernel/` before theorising.

---

## 12. Next steps

This is the only live roadmap. `04-roadmap.md` is pre-code planning and is
marked historical; `panel-work/README.md` holds the detail for the display work (item 6).

**Items 1-4 below were the roadmap as of 2026-11-09 and are all DONE.** Kept
only as a record of what the early blockers actually were:

1. ~~Recover the console / Plymouth owns ttyGS0~~ — fixed with
   `plymouth.enable=0`; see §10.
2. ~~Fix the ~19-minute boot~~ — it was never slow hardware. It was console
   backpressure (§12). Boot now reaches login in ~23 s, and
   `ARM_QCOM_CPUFREQ_HW` works (EPSS is not secure-protected, 2.2x faster).
3. ~~Graphical bringup~~ — done: `graphical.target`, autologin, Plasma Setup
   completed, and a real user account exists. See §13 and §17.
4. **uniLoader + a UFS driver** — the chainloader. Still open, and still the
   thing that turns this from a dev board into something that survives
   `dnf update`, because the kernel lives in `boot.img`.

5. ~~Inner touch~~ **done** (section 14). ~~Power key / RTC~~ **done**
   (section 17). ~~WiFi~~ **done** 2026-11-11 -- section 16.
6. ~~GPU + real display (DRM/MSM + the S6E3XA2 panel)~~ **DONE 2026-11-11.**
   KWin now composites on the Adreno 660 and the inner panel runs under KMS at
   2208x1768. See section 18. Orientation is declared (`LEFT_UP`) and
   blank/unblank works since 2026-11-12. What is left: the 7-8 s wake, the
   60/48 Hz modes, and the cosmetic DSI PLL warning.
7. ~~Finish WiFi~~ **DONE 2026-11-11.** It was the S2MPB02-sub buck rails
   plus upstream firmware; see the banner at the top of section 16.
8. The cover display's i2c touch (`touchscreen@49`, FTS9CU59, irq gpio34),
   after the display stack exists.
9. **Battery status reporting** (not charging) — requested 2026-11-11. The fuel gauge already reads percentage
   (`BATTERY_MAX17042`, read-only, see the status table), so the question is
   whether UPower/Plasma see it and what is missing for a correct battery
   indicator. Read-only work, no flash needed to investigate.

10. Charging. Deliberately last: the dual-cell topology has no mainline driver
   and getting it wrong has physical consequences. See §7.

**The current open list is section 21** (sensors/auto-rotate, the earpiece
speaker, screen wake, Bluetooth). Items 4, 8 and 10 above are still open too.

## 14. The inner touchscreen

Working since 2026-11-11. The driver logic was never the hard part -- five
*separate* preconditions each failed in a way that looked like a different bug,
and four of them produced a wrong answer rather than an error.

**The SPI bus did not exist.** `990000.spi` sat in
`/sys/kernel/debug/devices_deferred` with `geni_spi: Failed to get tx DMA ch`.
This SE has its FIFO disabled, so spi-geni-qcom takes the `fifo_disable == 1`
path and *requires* a GPI DMA channel -- deleting `dmas` does not help.
`gpi_dma0` ships `status = "disabled"` upstream. And `QCOM_GPI_DMA` must be
**`=y`**: the cmdline carries `deferred_probe_timeout=1`, so the deferred list
is flushed with `-ETIMEDOUT` one second after initcalls and a module loading
later can never satisfy it. The same reasoning forces `I2C_GPIO=y` and
`REGULATOR_S2DOS05=y`.

**The controller was unpowered** -- the ID read came back `00 00 00 00 00`,
with the transfer itself reporting success, which is the signature of a
floating MISO rather than a bus fault. Its rails come from a Samsung **s2dos05**
display sub-PMIC on a *bitbanged* i2c bus (TLMM 76 SDA / 77 SCL), not RPMh.
Both drivers are already upstream and `sdm845-samsung-starqltechn.dts` drives
the identical chip, so nothing had to be written. Child nodes must be named
exactly `ldo1`..`ldo4`/`buck` -- the driver matches on
`of_match_full_name`. `vdd` = ldo2 (1.8 V IO), `avdd` = ldo3 (3.0 V analog).

`ldo1`/`ldo4`/`buck` are the inner panel's rails that XBL left on and our
framebuffer is living off. They are declared `regulator-always-on` with **no**
voltage constraints: enough to stop anything disabling them, without
reprogramming a voltage under a display we cannot re-initialise.

**There is no reset pin.** The vendor's `stm_ts_reset()` is purely a rail power
cycle. XBL leaves both touch LDOs up, so on a warm boot the part is never
power-on-reset and answers with noise (`c5 9d f8 ad 85`). Cycle it: IO up, 1 ms,
analog up, 20 ms; down is analog, 4 ms, IO; 20 ms discharge between.

**A read has two shapes, and the bare-command sets differ between read and
write.** This produced the last round of noise:

| command | wire | payload offset |
|---|---|---|
| bare read (`87 A7 A4 FA FB`) | `[cmd..]` | `1 + clen` |
| anything else | `[0xC0][cmd]`, then `[0xD1][00][00]` | 4 |

With a 1-byte command the `0xD1` header carries `00 00`, **not** the command --
it already went out in the `0xC0` write. And the bare *write* set is
`A0 A2 A4 A7 FA FB D0`: `0x87` is bare for reads but not writes, `A0`/`A2`/`D0`
the reverse. A single shared predicate is wrong for both.

**Orientation.** The framebuffer is landscape on a portrait panel, so touch is
transposed relative to the image: `display_x = raw_y`,
`display_y = max - raw_x`, i.e. `touchscreen-swapped-x-y` +
`touchscreen-inverted-x`. Not `inverted-y` --
`touchscreen_apply_prop_to_x_y()` inverts in raw space and swaps *afterwards*.

Corner taps cannot establish this and wasted a round: with a landscape image on
a portrait panel, "top-left" means two different corners depending on which you
mean, and no rotation at all fits the tap sequence that produced. Use drags
(`dragtest.py`) -- a stroke carries its own direction.

Two traps worth remembering:

* The chip reports its own geometry via command **`0x23`** (11 bytes: X res big
  endian at `[0..1]`, Y at `[2..3]`, TX at `[8]`, RX at `[9]`) -- 4095x4095 on a
  34x42 grid. The vendor DT's `sec,max_coords` is overridden by this at runtime,
  so the DT value is not what stock uses either. We therefore set **no**
  `touchscreen-size-x/y`.
* Our chip answers ID `53 54 50 36 01` -- ASCII `"ST"` then `50 36`, but
  `STM_TS_ID0` is `0x48`. The vendor rejects only when **both** bytes differ
  (`&&`, not `||`). "Correcting" that to the `||` it looks like it should be
  rejects a perfectly live controller.

## 16. WiFi: everything except the link

> **RESOLVED 2026-11-11 -- WiFi works.** The link never trained because the
> QCA6490's core rails were off. On q2q the overlay
> (`q2q_eur_openx_w00_r08.dts`, fragment@189) overrides the generic lahaina
> cnss supplies: `vdd-wlan-aon` + `vdd-wlan-dig` come from **S2MPB02-sub
> BUCK1 (1.0125 V)** and `vdd-wlan-rfa2` from **BUCK2 (1.35 V)**, with
> `vdd-wlan-rfa1` on `pm8350c_s1` at 1.984 V. `sw-ctrl` and the antenna
> switch are deleted on this board, so the "PMU never reports ready" lead
> below was a dead end. Driver: `wifi-work/s2mpb02-regulator.c`. It also
> needs upstream linux-firmware, uncompressed -- Samsung's `amss20.bin`
> crashes under ath11k. **Lesson: for any q2q peripheral, read the overlay
> DTS, not just `lahaina.dtsi`.** The rest of this section is the record of
> the hunt and of the hypotheses that were closed.

Full write-up with code references in
[Hard Truths/12-wifi-qca6490.md](Hard%20Truths/12-wifi-qca6490.md) section 9.
Short version, from the 2026-11-11 attempt:

**The driver is free.** QCA6490 shares PCI ID `17cb:1103` with WCN6855, and
ath11k demultiplexes that ID by reading the chip's own version registers. This
silicon is major 2 / minor 0x00-0x01, which lands on `ATH11K_HW_WCN6855_HW20`
with **zero code changes**. Do not start from the QCA6390 entry; it is a
different PCI ID (`1101`) and the wrong starting point.

**Firmware is extracted and staged** at `/lib/firmware/ath11k/WCN6855/hw2.0/`:
`amss20.bin` renamed to `amss.bin`, plus `m3.bin`, `regdb.bin`, and one bare
BDF installed as `board.bin`. ath11k tries `board-2.bin` first and falls back to
`board.bin`, so **`ath11k-bdencoder` is not needed** for a first attempt. The
other three BDFs are parked in `.../hw2.0/alt/`. Note Fedora's own
`linux-firmware` already ships `WCN6855/hw2.0/*.xz` including a real
`board-2.bin.xz`; the uncompressed Samsung files win because the loader tries
the plain name first.

**What is proven working:** `pmr735a` RPMh block (pmic-id `"e"`, needed because
VDD_PMU_MX is S2E and we only had PMICs b and c); `wcn6855-pmu` binding
`pwrseq-qcom_wcn` with all ten input rails enabled; `pci-pwrctrl-pwrseq`
binding and powering the chip; `qcom-qmp-pcie-phy`; and the PCIe root port
enumerating as `0000:00:00.0 [17cb:010c]` with AER and PME. WLAN_EN (gpio64)
reads high and PERST# (gpio94) reads high, i.e. released.

**What fails:**

```
qcom-pcie 1c00000.pcie: Device not found
LnkSta = 0x1011     ->  DLActive = 0, LinkTraining = 0
```

Bus 01 scans empty; a forced retrain (Link Control bit 5) and
`echo 1 > /sys/bus/pci/rescan` both do nothing.

**Ruled out:** driver support; missing modules; probe ordering; power; missing
perst. **Still open, most likely first:** PERST# timing relative to rail
stability (spec wants >= 100 ms, and nothing currently enforces a gap between
the pwrseq power-on and qcom-pcie's PERST pulse); then rail *voltages* -- the
identities were copied from `sm8450-hdk`, which drives the same chip, but q2q's
vendor values differ (S2E is 1.0125 V against our `pmr735a_s2` constraint of
0.95-0.976 V; S1C is 1.984 V).

GPIOs freed for this and **all proven safe**: 64 (wlan-en), 65 (bt-en), 153
(sw-ctrl), 94 (perst), 95 (clkreq, TLMM function `pcie0_clkreqn`, *not* a plain
GPIO), 96 (wake).

## 17. Two traps that cost real time, and how to recognise them

### A silent device after reboot is a replug, not a hang

> **Update 2026-11-12:** with `tools/serdrain.py` reading the console, the
> gadget re-enumerated by itself on every reboot and no replug was needed
> (section 20). The text below still describes what you see WITHOUT a reader.

**This is the single most misleading failure mode on this phone.** Two known
facts compound: dwc3 has no VBUS/connector awareness, so the USB gadget never
re-enumerates by itself after a reboot; and an unread CDC-ACM console applies
backpressure that stalls every kernel write. Together the device looks
completely dead -- no `/dev/fold3`, no new output, the capture ending
mid-shutdown.

On 2026-11-11 this was misread as a TZ-protected-GPIO hang. A good DTS was
reverted and a fabricated `!! DO NOT !!` warning was written into `&tlmm`
claiming GPIOs 94/95/96 were secure-world owned. They are not; that exact DTB
had booted.

**The tell:** a drained log that ends in a *clean shutdown* with no new boot at
all. A genuine pinctrl abort leaves partial early output instead. Ask for a
replug before concluding anything, and check `uptime` once back -- a stalled
boot shows a huge uptime with userspace starting only seconds ago.

### The tools were written for Stage 1, and Stage 1 had busybox

`selfflash.py` ran `busybox base64 -d | busybox dd of=/dev/sda19`. That was
correct when the only shell on the device was the busybox initramfs. **The
Fedora rootfs has coreutils and no busybox at all**, so the receiver command
died instantly -- and then 61 MiB of base64 was read by *bash* as commands, one
"command not found" per 76-character line, for five minutes, writing nothing.
Nothing was flashed and nothing looked obviously wrong.

It now probes (`command -v base64`, else `busybox`) and prints which it picked.
The general lesson: **anything in `tools/` that predates the pivot into Fedora
may be assuming the busybox initramfs.** When a tool behaves strangely, check
what it assumes about the shell on the far end before debugging the device.

Related, same class: the device's dd is toybox in TWRP and coreutils in Fedora,
and they disagree about `iflag=` and about partial final blocks -- section 4.

### Two staleness traps that both cost a cycle on 2026-11-11

Neither produces an error. Both hand you a *complete-looking* artefact built
against the wrong config.

**1. `make modules` not finishing, so the previous stage gets pushed.**
`build-kernel-modules.sh` wipes and repopulates `rootfs-work/modules-stage`,
so a half-finished run leaves the PREVIOUS run's tree there -- 1586 modules, a
valid `modules.dep`, `depmod` exits 0, and every check short of a timestamp
passes. Pushing it bricked display, touch and PCIe at once. The script now
refuses to finish if any staged `.ko` is older than `arch/arm64/boot/Image`;
verify with that check, not with a file count.

**2. Out-of-tree modules are invisible to `modules_install`, and `make` will
not rebuild them when only the kernel config changed.** `touch-work/` is built
`M=$(CURDIR)` against the tree, so:

* `modules_install` does **not** include `fts9cu80f.ko`. It lives in
  `/lib/modules/<rel>/extra/`, so `rm -rf /lib/modules/<rel>` deletes it and a
  fresh `modules_install` does not bring it back. Reinstall it by hand and
  re-run `depmod` or udev will not autoload it.
* `make` in `touch-work/` sees unchanged sources and does nothing, happily
  leaving a `.ko` built against the old config. **Always `make clean` first**
  after a kernel config change, then confirm the `.ko` is newer than `Image`.

### A config change can invalidate EVERY installed module silently

Enabling `FTRACE`/`KPROBES` for the WiFi work changed the size of
`struct module`, and the entire installed module tree -- built against the
previous config -- stopped loading:

    module pci_pwrctrl_pwrseq: .gnu.linkonce.this_module section size must
    match the kernel's built struct module size at run time

**The kernel release and vermagic were identical** (`7.2.15-q2q`), so nothing
warned and the path `/lib/modules/7.2.15-q2q` was still "correct". Options that
add fields to `struct module` -- the tracing family, `MODULE_UNLOAD`,
`LIVEPATCH` and friends -- do this.

**It presents as three unrelated regressions at once**, which is what makes it
expensive to diagnose:

| symptom | actual cause |
|---|---|
| no PCI devices at all, not even the root port | `pci_pwrctrl_pwrseq` would not load, so the host never powered the endpoint |
| black screen, no Plasma, one login session | `msm`, `dispcc-sm8250`, `panel-samsung-s6e3xa2` would not load |
| no touch | `fts9cu80f` would not load |

**Do not grep for the wrong string.** This is *not* "disagrees about version of
symbol" and *not* "Unknown symbol" -- a check for those two reported zero
failures on a boot where nothing loaded at all. Use:

```sh
python3 -I tools/dev.py run 'dmesg | grep -iE "module .*:|struct module size"'
```

**Rule: any change to the kernel config means rebuilding and reinstalling the
module tree, not just reflashing the boot image.** That is the mirror image of
the trap below -- `build-kernel.sh` not building modules at all.

### Installing modules so udev will autoload them

A boot image flash carries `Image` + DTB only. For a driver that must come up
*during* boot without being insmodded by hand -- `msm`, `dispcc-sm8250`, the
panel -- the `.ko` has to be in `/lib/modules/<release>/` **and** `modules.dep`
has to know about it:

```sh
# resolve the closure rather than pushing all 87 MB of modules-stage
REL=7.2.15-q2q; M=rootfs-work/modules-stage/lib/modules/$REL
grep -E "^kernel/drivers/gpu/drm/msm/msm\.ko:" $M/modules.dep \
  | tr ' ' '\n' | sed 's/:$//' | sort -u
# push them at their real paths, then on the device:
python3 -I tools/dev.py run 'depmod -a 7.2.15-q2q'
```

`modinfo <mod>` returning "not found" on the device is the fast check that a
module never arrived. The display set was 13 modules, 2 MB.

### build-kernel.sh does not build modules

`tools/build-kernel.sh` produces **Image + DTB only**. Any newly enabled `=m`
driver does not reach the device from a boot-image flash.
`tools/build-kernel-modules.sh` builds and stages the tree, and it must be
pushed separately. This cost a whole cycle during WiFi bringup, presenting as
`qcom-pcie: cannot initialize host` -- which looked like a DT dependency
problem but was the PCIe host correctly deferring forever on a `pwrctrl` driver
that had never been installed. `modinfo <mod>` returning "not found" is the
fast check. Resolve the closure rather than pushing the whole tree:

```sh
REL=7.2.15-q2q
cd rootfs-work/modules-stage/lib/modules/$REL
grep -E "ath11k_pci\.ko|pci-pwrctrl-pwrseq\.ko" modules.dep | tr ' ' '\n' | sed 's/:$//' | sort -u
```

### deferred_probe_timeout was 1, and that was a trap of its own

It is now **60**. One second made the PCIe host stop waiting for the pwrctrl
and bind against an unpowered chip. The old value is also why GPI DMA,
`I2C_GPIO`, `REGULATOR_S2DOS05` and the PCIe PHY all had to be built in: a
module loading from userspace could never satisfy a deferred probe. Those
builtin choices are still correct, just no longer forced.

## 18. The GPU, and what is left for the real display

**The GPU works as of 2026-11-11, render only.** `/dev/dri/renderD128`,
`GL_RENDERER FD660`, Mesa 26.2.3, OpenGL ES 3.2, correct pixels read back, and
`/sys/kernel/debug/dri/1/gpu` showing `gpu-initialized: 1`, `revision: 660`
and fences retiring. Validate it with `tools/gl-probe.py` (pushed to the device
and run there) -- the Fedora Mobile image has no glmark2, no vulkan-tools and
no eglinfo, and there is no network on this phone, so the probe drives
libEGL/libGLESv2 through ctypes on a surfaceless display instead.

**It does not make the UI fast, and cannot.** KWin still composites 2208x1768
through `kms_swrast` on simpledrm. simpledrm has no render node and is not one
of Mesa's `kmsro` display drivers, and it cannot scan out an imported dmabuf at
all -- it memcpys from a shadow buffer. So there is no path for a
GPU-rendered buffer to reach the screen. The speed-up needs DPU + DSI + the
S6E3XA2 panel, which **replaces** simpledrm.

### What it took (all four of these were needed)

| piece | detail |
|---|---|
| `DRM_MSM=m`, KMS built out | `DRM_MSM_KMS` is its own symbol since v6.15 (`def_bool n`, select-ed by MDP4/MDP5/DPU). With MDP4/MDP5/DPU/DSI/DP/HDMI all `=n`, msm registers a render-only DRM device via `msm_gpu_probe()` and leaves simpledrm alone |
| two DT lines | `&gpu { status = "okay"; }` and a `firmware-name` on `&gpu_zap_shader`. `sm8350.dtsi` already had gpu, gmu, gpucc, adreno_smmu and both OPP tables |
| three firmware blobs in the **rootfs** | `/lib/firmware/qcom/a660_sqe.fw` and `a660_gmu.bin` (Samsung's own, **uncompressed** -- Fedora ships only `.xz` and `CONFIG_FW_LOADER_COMPRESS` is off), plus `qcom/sm8350/samsung/q2q/a660_zap.{mdt,b00,b01,b02}` |
| `separate_gpu_kms=1` | see below -- without it nothing happens at all |

### The module parameter that is not optional

```sh
insmod msm.ko separate_gpu_kms=1     # pinned in /etc/modprobe.d/msm-gpu.conf
```

`msm_gpu_no_components()` returns the `separate_gpu_kms` module parameter with
**no `CONFIG_DRM_MSM_KMS` guard**. So by default `adreno_probe()` calls
`component_add()` and waits for a KMS master that a GPU-only build never
creates. The failure is silent and looks like success: `3d00000.gpu` shows as
**bound** to the `adreno` driver, the driver prints *nothing whatsoever*, and
no DRM device appears. `ls /dev/dri` is the check.

Related: **never `rmmod msm` without `patches/0004`.** `adreno_remove()` read
`priv->kms_init` from drvdata, which is NULL on the component path -- and on
the other path `msm_gpu_init()` has overwritten drvdata with
`&gpu->adreno_smmu`, so it was reading the wrong struct either way. It oopses
and leaves the module unloadable, which costs a reboot and therefore a
physical replug. The patch mirrors `adreno_probe()`'s own condition instead.

### Three "traps" from the old version of this section that do not exist

1. ~~`adreno_smmu` fails with -110~~ -- that was `deferred_probe_timeout=1`
   expiring while `gpucc` is a module loaded from userspace. At 60 it binds;
   `3da0000.iommu` reports 7 context banks and 48-bit VA.
2. ~~the qfprom speed bin~~ -- a660.1 declares no `.speedbins`, so nothing
   reads the TZ-owned `speed_bin` nvmem cell. `a6xx_set_supported_hw()` treats
   `-ENOENT` as "this platform has no speedbin support, fine".
3. ~~AOSS/icc dependencies~~ -- the GMU node has no `qcom,qmp` and the GPU has
   no `interconnects`.

The one that was real: **`SM_DISPCC_8250` must stay out until the panel lands**
(the symbol is `SM_DISPCC_8250`, not `SM_DISPCC_8350`, which does not exist --
`dispcc-sm8250.c` handles `qcom,sm8350-dispcc`). Built in, it reprograms the
display clocks and destroys the live bootloader scanout.

`pil_gpu_mem` is inherited from `sm8350.dtsi` at `0x8b51a000` size `0x2000`,
byte for byte what Samsung's `lahaina.dtsi` reserves, so the zap shader lands
where this device's TZ expects it. Its one loadable segment is 1976 bytes.

### The display, as it actually landed

**The panel lit on the first attempt** and KWin composites on the GPU. The
decisive structural point:

```
msm_dpu ae01000.display-controller: bound ae94000.dsi (ops dsi_ops [msm])
msm_dpu ae01000.display-controller: bound 3d00000.gpu (ops a3xx_ops [msm])
[drm] Initialized msm 1.13.0 for ae01000.display-controller on minor 0
```

DPU binds the DSI *and* the GPU into **one** DRM device, so `card0` and
`renderD128` are the same device and `kwin_wayland` renders and scans out
without a copy. `separate_gpu_kms` must therefore be back to its default **0**,
and `/etc/modprobe.d/msm-gpu.conf` from the render-only stage is **removed**.
Check it with `/sys/kernel/debug/dri/0/clients`: kwin should appear on dev 128
(render) and as master on dev 0.

Config: `SM_DISPCC_8250=m`, and inside `DRM_MSM=m` the bools
`DRM_MSM_DPU=y`, `DRM_MSM_DSI=y`, `DRM_MSM_DSI_7NM_PHY=y`, plus
`DRM_PANEL_SAMSUNG_S6E3XA2=m`. The panel driver is **ours** and is **not**
upstream -- 7.2.15 ships no `s6e3xa2`, so it is an untracked file in the tree
with Kconfig/Makefile entries. An earlier version of this section claimed it
was upstream; it is not.

**Three pin numbers, all previously inside `gpio-reserved-ranges`:**

| pin | role | note |
|---|---|---|
| 24 | panel reset | vendor `qcom,platform-reset-gpio = 0x18`. `panel-work/display.dtsi` said **14**, which was wrong |
| 82 | panel TE | muxed to function **`mdp_vsync`**, not a gpio consumer -- TE reaches the DPU INTF in hardware. A command-mode panel has no timing of its own, so without this mux there is no vsync at all |
| 97 | mipi-sel | vendor `samsung,mipisel-gpio = 0x61`, on_val 1 |

The panel's own rails stay `regulator-always-on` with no voltage constraints,
so the driver's `regulator_bulk_enable()` is a no-op -- deliberate, because XBL
already powers the panel and only the reset pulse and init sequence were ever
in question. DSI supplies follow sm8350-hdk: `vdda` = `pm8350_l6` (L6B 1.2 V),
PHY `vdds` = `pm8350_l5` (L5B 0.88 V).

**One cosmetic error to ignore, and not to chase as a panel bug:**

```
DSI PLL(0) lock failed, status=0x00000000
dsi0_phy_pll_out_dsiclk already disabled / already unprepared   (+2 WARNs)
```

at ~6.07 s in `dsi_phy_driver_probe`. The PLL locks when the real modeset runs;
the connector comes up `connected`/`enabled` at 2208x1768 and the panel
lights. It is the handoff from the display clocks XBL left running. The
`Fixed dependency cycle(s)` lines between dpu/dsi/panel are ordinary
fw_devlink chatter.

### The panel never sent display-on (fixed 2026-11-12)

The vendor init stream ends at sleep-out and contains **no `0x29`**. Samsung
sends it as a separate command set, `samsung,display_on_tx_cmds`
(`f0 5a5a / 9f a5a5 / 29 / 9f 5a5a / f0 a5a5`), after the first frame. The
driver transcribed only the init stream, so the panel lit purely because XBL
had left display-on set -- and the first `unprepare` (`0x28`) turned it off
for good. Every DPMS off (power key, idle timeout) was a one-way trip that
looked like the screen dying until reboot.

Fix: an `.enable` hook in `panel-work/panel-samsung-s6e3xa2.c` that sends that
sequence. `drm_panel_enable()` then restores the backlight level by itself.
The panel still has **no reset line wired** (the real one is TLMM 14, untested)
and still runs on a never-power-cycled chip.

### What is still open on the display

0. **Waking from a blank takes 7-8 s.** Reported 2026-11-12, not measured.
   The panel's own share is ~250 ms of sleeps, so the rest is elsewhere.

1. ~~Panel orientation is not declared.~~ **DONE 2026-11-11:
   `DRM_MODE_PANEL_ORIENTATION_LEFT_UP`**, declared in
   `s6e3xa2_get_modes()`. Needs one reboot after pushing the panel module;
   it is a module, so this costs no boot-image flash.

   **Two traps here, both of which caught me.**

   *It cannot be reasoned out, only measured.* Described from the device's
   point of view the image looks like it needs `RIGHT_UP`, and the
   touchscreen's DT transform implies that same handedness. Both are
   misleading. The only reliable method is to apply a rotation and look at
   the glass:

   ```sh
   setpriv --reuid=1000 --regid=1000 --clear-groups \
     env XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 \
     kscreen-doctor output.DSI-1.rotation.left     # upright  -> LEFT_UP
   #                                      .right   # upside down
   ```

   Clear `~/.local/share/kscreen/` afterwards, or KWin's saved per-output
   config masks whether the kernel's declaration is working.

   *It composes with the touch transform, it does not replace it.* An earlier
   version of this section said the two had to change together or touch would
   break. That was wrong, and acting on it would have broken touch. They are
   rotations at two different layers:

   | transform | maps | layer |
   |---|---|---|
   | `touchscreen-swapped-x-y` + `touchscreen-inverted-x` (board DTS) | digitizer -> panel raster | the sensor is mounted rotated w.r.t. the display controller's scanout |
   | `LEFT_UP` panel orientation (panel driver) | panel -> device casing | KWin applies it to image *and* input together |

   Both are needed. Verified on hardware: with the rotation applied and the
   DT transform left in place, the image is upright **and** touch lands where
   you tap.
2. **Only 120 Hz and 96 Hz are advertised.** 60/48 Hz need the `0xb9` byte set
   to `0x01`, and `drm_panel` has no `mode_set` callback to select per-mode
   init from, so they are omitted rather than advertised-and-wrong.
3. The cover panel (`S6E3FAB_AMB623ZF01`, reset gpio 25, TE gpio 83) and then
   its i2c touch.
4. The cosmetic PLL warning above.

---

## 19. Sensors: the SLPI, and the two rails Android turns on

Nothing is on an AP bus. Every sensor sits behind the **SLPI** (Qualcomm
Sensor Core): two LSM6DSO IMUs on SSC I3C bus 1, and on SSC I2C buses 3/4/5/7
an ak0991x magnetometer, ak0997x digital hall, lps22hh barometer, stk3a9x
proximity and tcs3407 light sensor. Read them with
`ssccli --sensor accelerometer|magnetometer|light --timeout 5`.

### What it took

1. **`&slpi` with Samsung's signed `slpi.mdt`, and a moved memory region.**
   The image is linked at 0x88200000 and spans exactly 0x1600000 (22 MiB).
   Upstream's `pil_slpi_mem` is 21 MiB and abuts `pil_cdsp`, so it cannot fit;
   the DTS uses Samsung's own slot, `0x9c700000 + 0x1600000`.
   *Constraint:* ABL loads the uniLoader blob at 0x9bb00000 and the FDT the
   kernel keeps using stays inside it, just after the Image (0x9ec9d000 with a
   47.5 MiB Image). An Image under ~34 MiB would put the FDT inside this
   no-map region.
2. **`pm8350c_l2` (RPMh L2C, 1.8 V) always-on.** Vendor name `sensor_vdd`; it
   is also the I2C pull-up rail (`digital_hall` `pullup-supply`). Off, every
   I2C sensor driver blocks until the SLPI's watchdog kills the sensor PD:
   `SNS_SEE_P_x exceeded processing time limit for library 0x...`.
3. **S2MPB02-sub LDO9 (1.8 V) always-on.** Vendor name `subsensor_vdd`; it
   powers the IMUs. Off, libssc reports `No 'accel' sensor available` and the
   stk3a9x driver hangs the SLPI the same way.
4. **`hexagonrpcd`**, which serves the registry and config files the SLPI
   asks for over FastRPC (`/dev/fastrpc-sdsp`). Runs as
   `hexagonrpcd-sdsp.service`.

Both rails are held by Android's PIL node (`qcom,ssc@5c00000`,
`qcom,active-reg-names`). Mainline's `qcom_q6v5_pas` has no supply for them,
hence `regulator-always-on`. XBL leaves both off.

### Where the files come from

Everything lives under `/usr/share/qcom/sm8350/samsung/q2q/` on the phone:

| path | source |
|---|---|
| `sensors/config/*.json`, `sensors/sns_reg.conf` | Android `vendor`: ext4, **one linear extent** inside `super` (`sda26`) at sector 19785728, so `losetup -r -o $((19785728*512))` mounts it with no device-mapper. `/root/lp.py` parses the LP table |
| `sensors/registry/{registry/,sns_reg_version,sns_reg_config}` | `persist` (`sda5`), copied -- never write the partition |
| `dsp/` | the `dsp` partition (`sda17`) |
| `socinfo/` | hand-written: `hw_platform=MTP`, `soc_id=415`, `platform_version=65536`, `ssc_hw_rev=9` |

`hexagonrpc` (github.com/linux-msm) and `libssc` (codeberg, DylanVanAssche)
are built from source in `/root/src`; Fedora packages neither. Two local
changes:

* `hexagonrpcd/rpcd_builder.c`: `persist/sensors/registry` is mapped as a real
  directory. Samsung's SLPI opens `registry/../sns_reg_version`, which the
  stock mapping cannot resolve.
* `libssc`: `subdir('mocking')` and `subdir('tests')` commented out.

`hexagonrpcd` is **read-only**, so the SLPI can never regenerate its registry;
it must be the already-parsed one from `persist`.

### How the rails were found, and the mistake that hid them

`/root/sns-try '<egrep of registry files>' [secs]` restarts the SLPI against a
subset of the registry and prints `CRASH` or `ok`. Feeding it one driver at a
time separated "IMU alone is fine" from "every I2C sensor crashes", which
pointed at power rather than at files. (Stop `hexagonrpcd-sdsp.service`
first.)

PMIC state can be read directly:

* PM8350C over SPMI: `/sys/kernel/debug/regmap/0-02/registers`. LDO*n* is at
  `0xc000 + n*0x100`; `+0x46` bit 7 is enable, `+0x40/41` the voltage in mV.
* S2MPB02 over i2c: `i2cget -f -y <bus> 0x59 <reg>`. **LDO*n* CTRL is
  `0x1e + (n-1)`**; bit 7 enables, bits 6:0 select (600 mV + 12.5 mV steps for
  LDO1-5, 25 mV for LDO6-18).

That last line was wrong by one for most of a day (`0x1f + ...`, from counting
the `enum {` line). Every "enable" poke therefore hit the next LDO up, two
camera rails got switched on by accident, and two rails were wrongly ruled
out. **Check a register map against every known voltage, not one readback.**
What exposed it: Android's own kernel log
(`capture/facts-20261107-010152/logs/last_kmsg.txt`) prints the enabled
regulators at suspend, and that is ground truth for "what does Android turn
on".

I2C bus numbers shifted when the main-PMIC bus was added: `i2c-0` is the main
S2MPB02 (TLMM 78/79, vendor `/i2c@51`, deliberately bare -- no driver binds),
`i2c-1` is the sub S2MPB02 + s2dos05 (76/77), `i2c-2` the expander.

`wifi-work/s2mpb02-regulator.c` now registers **only** regulators the DT
describes. Several of that chip's LDOs (L6/L10/L15) feed the cover panel and
must stay exactly as the bootloader left them.

### Not done

* **Auto-rotate.** Fedora's `iio-sensor-proxy` 3.9 is built without SSC
  support. Source is at `/root/src/iio-sensor-proxy`; build with
  `-Dssc-support=true` and install over the packaged files (a `dnf` update
  will put the stock binary back).
* Proximity enumerates, but libssc 0.4.4 asserts in
  `libssc-sensor-proximity.c:98`.
* Raw gyro: `ssccli` has no option for it. Same chip as the accelerometer.
* libssc warns the firmware's mount matrix is all zero and falls back to
  identity; orientation will need checking once rotation is wired up.

---

## 20. SSH over WiFi, and a flash loop with no cable handling

```sh
ssh -i ~/.ssh/fold3_ed25519 -o IdentitiesOnly=yes root@192.168.11.131
```

`sshd` is enabled on the rootfs. The key is a dedicated passphrase-less one
for this development device; the address is a DHCP lease and may change. This
is far more robust than `tools/dev.py` right after boot, when console noise
mixes into the serial login prompt.

Flashing over it takes under a second instead of a minute over serial:

```sh
scp -i ~/.ssh/fold3_ed25519 images/q2q-stage1-boot.img root@192.168.11.131:/root/boot-new.img
# on the phone:
S=$(stat -c%s /root/boot-new.img)
dd if=/root/boot-new.img of=/dev/sda19 bs=4M conv=fsync
echo 3 > /proc/sys/vm/drop_caches
head -c $S /dev/sda19 | sha256sum      # must match the host's sha256sum
systemctl reboot
```

**Run `tools/serdrain.py` in the background across every reboot.** It reads
`/dev/fold3` passively into `capture/boot-logs/`, reopening after each
re-enumeration. With it running, three consecutive flash-reboot cycles on
2026-11-12 needed no replug and no button. Without a reader:

* `systemctl reboot` stalls in shutdown before `Rebooting.` -- the phone
  answers ping, refuses ssh, and keeps its USB device number;
* a boot that re-enumerates USB stalls for ~4 minutes at ~20 s uptime
  (`task kworker/... blocked for more than 10 seconds`) and comes up with WiFi
  and the serial login broken. That looks exactly like a bad image and is not.

Stop it before using `dev.py` or `sergrab.py`: two readers split the stream.
It never writes to the tty, because a write to a console nobody reads on the
far side blocks `close()` for 30 s.

Keep a copy of the last good boot image before every experimental flash. A
bad image is still a Download Mode + `heimdall flash --BOOT` trip.

### Do not hot-swap the USB gadget

Replacing the built-in `g_serial` with a configfs serial + network composite
on a running system (`echo gadget.0 > /sys/bus/gadget/drivers/g_serial/unbind`)
does enumerate on the host, but the process holding `ttyGS0` oopses and within
a minute all of userspace hangs; only a hard reset recovers it. USB networking
would have to come up before anything opens `ttyGS0` -- `USB_G_SERIAL=n` and a
configfs gadget built in the initramfs. Not done; WiFi SSH covers the need.

---

## 21. Open items (2026-11-12; superseded by section 30)

1. Auto-rotate -- section 19.
2. ~~Earpiece / call speaker~~ -- **CLOSED 2026-11-13**: the user confirmed this unit has no working speaker at all. Audio is dropped; section 24 stays as the record.
3. 7-8 s screen wake -- section 18.
4. **Bluetooth RF weakness -- the current priority** (section 22, "Next test").
5. ~~Which rail `pm8350c_l9` feeds~~ -- answered in section 22: grip sensor supply, never fatal.

---

## 22. Bluetooth: works, but nearly deaf

The BT half of the QCA6490 is up: `hci0` loads firmware, carries the phone's
factory address, is discoverable, and a laptop sees it by name.

### What it took

* **UART18** (vendor `qupv3_se18_4uart`, `0x890000`) with `&qupv3_id_2`
  enabled. TLMM 68 CTS / 69 RTS / 70 TX / 71 RX, freed from
  `gpio-reserved-ranges`. `sm8350.dtsi`'s own `qup_uart18_default` lists only
  68/69 and is replaced by `bt_uart_state`.
* **`aliases { serial1 = &uart18; }`.** Without a `serial` alias
  `qcom_geni_serial` refuses to probe: `890000.serial: Invalid line -19`.
  This board had no `aliases` node at all.
* A `bluetooth` child, `qcom,wcn6855-bt`, with **no `enable-gpios`** so that
  `hci_qca` goes through the power sequencer: the `wcn6855-pmu` node from the
  WiFi work already owns `bt-enable` (TLMM 65) and every rail. No kernel
  config change was needed.
* **Samsung's firmware.** The chip is ROM 2.0 (`SOC Version 0x400c0200`) and
  asks for `qca/hpbtfw20.tlv` + `qca/hpnv20.bin`. linux-firmware ships only
  the 21 series. Both files are in
  `capture/firmware-*/vendor_firmware/firmware.tar`; they go in
  `/lib/firmware/qca/` uncompressed (`CONFIG_FW_LOADER_COMPRESS` is off).
* **An address.** None is provisioned, so the controller comes up
  *unconfigured*: `btmgmt info` lists zero controllers and bluetoothd ignores
  it (`btmgmt config` shows it). `fold3-bt-addr.service` applies the factory
  address with `btmgmt public-addr`; it was copied once, read-only, from
  `efs` (`sda6`) `/bluetooth/bt_addr` into `/etc/bluetooth/fold3-bdaddr`.

To reload after changing firmware, without a reboot:

```sh
echo serial0-0 > /sys/bus/serial/drivers/hci_uart_qca/unbind
echo serial0-0 > /sys/bus/serial/drivers/hci_uart_qca/bind
```

### The open problem

A 12 s `btmgmt find` returns 0-2 devices at -101 to -106 dBm where a laptop
beside the phone sees 22, and the laptop hears the phone at -83 dBm. WiFi on
2.4 GHz from the same chip sits at -43 dBm. So the loss is specific to the BT
path and is about 40 dB each way -- roughly the isolation of one antenna
switch.

Tested and ruled out: WiFi radio off; `ath11k_pci` unloaded; and every
Android-always-on rail that can be switched live -- S2MPB02-sub LDO12 (2.9 V),
LDO18 (3.3 V) and buck-boost (3.3 V), S2MPB02-main buck-boost (3.5 V) and LDO8.

`pm8350c_l9` looked like the last missing rail, but it is not an RF supply
(next subsection). What is left, unconfirmed:

1. ~~Physical damage.~~ **Ruled out 2026-11-13**: BT is strong under stock
   Android (table below).
2. ~~An AP-controlled antenna switch in the vendor DT.~~ The overlay deletes
   them all (below).

### Checked 2026-11-13, host-side (phone was off)

* **The NVM is not the cause.** Samsung's HAL patches `hpnv20.bin` at load
  time from `/vendor/firmware/bt_nvm_loading.xml` (target `Q2`). Parsed the
  file (TLV: 4-byte header, then `u16 id, u16 len, u32, u32`, data) and
  compared: tags 36, 83 and 87 already hold the XML's values. Only two differ,
  both transmit-power trims: tag 50 bytes 110/111 (file `1c 26`, XML `16 20`)
  and tag 206 SAR backoff (file `80 50 50 50 50 50`, XML wants bytes 1/2/3/5 =
  `50 2e 48 38`). Those *lower* TX power on Android; neither can cost 40 dB,
  and none touches receive.
* **The vendor DT has no antenna switch to find.** The q2q overlay deletes
  `wlan-ant-switch-supply`, `qcom,sw-ctrl-gpio`, `qcom,bt-sw-ctrl-gpio` and
  `qcom,bt-vdd-asd-supply` outright (fragments 189 and 243). Nothing
  AP-controlled sits in the BT path on this board.
* WiFi reports `board_id 0xff`, i.e. generic board data -- irrelevant to BT
  with `ath11k_pci` unloaded, which was already tested.

### Measured under stock Android, 2026-11-13: the hardware is fine

Same phone, same spot, same laptop (`tools/bt-measure-android.sh`, rooted adb):

| state | phone RSSI at laptop | devices the phone finds in ~3 s |
|---|---|---|
| mainline Linux (2026-11-12) | -83 dBm | 0-2 |
| Android, as booted | **-29 dBm** | 13 |
| Android, WLAN half fully off (`WLAN_EN` low, S1C + S10B off) | -30 dBm | 13 |
| Android, airplane mode + BT | -35 dBm | 12 |
| Android, modem subsystem OFFLINE | -29 dBm | 12 |
| Android, modem OFFLINE + WLAN off + BT chip cold re-init | **-31 dBm** | 13 |

So it is **not antenna damage** -- about 54 dB is missing under Linux, and it
is something Android sets up. What Android does *not* need: the WLAN
firmware, Samsung's `bdwlan`, S1C (1.9 V), S10B, or the cellular radio being
on. With WLAN off the chip runs BT on S2MPB02-sub BUCK1 + BUCK2 alone.

What the Android BT HAL does at init (full log + the HAL binary are in
`capture/android-bt-20261113/`; `UpdateNewNvmFormat` was disassembled):

* same `hpbtfw20.tlv`, same `hpnv20.bin` (board id 0, no `.b00` file);
* NVM tag 35 byte 118 bit 2 is clear -> HAL logs "xPA supported conf from
  board" and does **nothing**: this board has an **external** BT PA/front
  end. Only the internal-PA case pokes the S3E rail through the TCS, so S3E
  is not needed (and stays forbidden, section 16);
* no `bt-fem-sel-gpio` in the q2q DT, and that ioctl is never called;
* XML overrides really applied: tag 50 bytes 110/111 and tag 206 (tags 36, 83
  and 87 are skipped by a length mismatch). `bt-work/hpnv20-android.bin` is
  the file with exactly those bytes, ready to drop in `/lib/firmware/qca/`;
* tag 27 (sleep): the HAL sets bit 0 of data byte **1**, the kernel's btqca
  sets bit 0 of data byte **0**. Sleep-related, unlikely to be RF.

Android's debugfs and `/dev/mem` are absent, so TLMM pin states and
modem-side (RPMh) rail votes could not be read there.

### ROOT CAUSE (2026-11-13): BT and the WLAN firmware fight over a shared front end

Measured under Linux, same day, logs and scripts in `capture/linux-bt-20261113/`:

| state | devices found (12 s) | best RSSI seen by phone |
|---|---|---|
| as booted, WiFi associated | 1-3 | -85..-100 |
| WLAN half powered down (WLAN_EN low), BT **not** re-initialised | 2 | -94 |
| WLAN half powered down, BT cold init | 14 | **-38** (laptop hears phone at -35) |
| ath11k unbound (WLAN_EN still high, no firmware), BT cold init | 14 | -37 |
| WiFi radio off (`nmcli radio wifi off`), BT cold init | 14 | -36, same 45 s later |
| any of the above, then WiFi back on | 3-4 | -85 |
| WiFi on, BT cold init | 3-15, varies | strong for seconds at best, weak within a minute |

* WiFi per-chain RSSI on 2.4 GHz is `[-79, -45]`: chain 0 is ~34 dB down and
  drops to -94 while BT holds the path. BT and WLAN chain 0 share one front
  end / antenna switch.
* BT claims it only at its own init (firmware + NVM download). The WLAN
  firmware claims it whenever its radio is up and never gives it back. With
  upstream `amss.bin` + the generic `board-id=255` board data there is no
  BT coexistence for this board, and chain 0 is not even usable for WiFi.
  Android's firmware with Samsung's `bdwlan` time-shares it properly.
* The old "ath11k unloaded, no change" result was true but incomplete: BT was
  never re-initialised afterwards, which is the half that matters.

Ruled out on the way, all with readback: every S2MPB02 rail set to Android's
exact register values (sub BB/L12/L18, main BB/L8/L11; register diff in the
capture dirs), and `pmr735a_l7` switched off through RPMh
(`bt-work/rpmh-poke/`, a one-shot module that writes a single VRM register).
`iw phy set antenna` is not supported by this chip (-95), so WiFi cannot be
pinned to chain 1 that way.

### Where this leaves Bluetooth

1. **Works today with WiFi off.** `nmcli radio wifi off`, then re-init BT:
   `echo serial0-0 > /sys/bus/serial/drivers/hci_uart_qca/unbind`, `bind`,
   `systemctl restart fold3-bt-addr.service`. Not automated yet.
2. **Untested: WiFi on 5 GHz.** The WLAN firmware may leave the 2.4 GHz
   front end alone when it is associated on 5 GHz.
3. **The real fix is on the WLAN side**: correct board data / coexistence.
   Samsung's `bdwlan.elf*` crashed upstream `amss.bin` on BDF apply and
   Samsung's `amss20.bin` asserts under ath11k (section 16); one of those two
   has to be made to work, or the coex/antenna fields carried into a board
   file upstream firmware accepts. ath11k sends no WMI coex config for
   WCN6855.

### Why Samsung's board data will not load under upstream firmware (2026-11-13)

Tools and logs: `bt-work/bdf/`.

* Samsung's `bdwlan.elf*` and the upstream entry we match
  (`...subsystem-device=0108,qmi-chip-id=2,qmi-board-id=255`) are the **same
  format**: ELF wrapper, one 58180-byte payload, same header template. Payload
  checksum is plain: xor of all 16-bit words == 0xffff, field at offset 0x0a.
* Upstream `amss.bin` RDDM-crashes ~0.3 s after the last BDF segment for
  **any** file that is not byte-identical to an upstream one: one flipped bit
  in a calibration table (checksum fixed), a flip in padding, even one
  changed character in the ELF symbol name with the payload untouched. Cold
  boot or warm rebind makes no difference.
* Reason: every upstream BDF (all 44 unique files in `board-2.bin`, and all
  22 in the first 2022 release) ends with a **32-byte trailer after the ELF
  section header table**. Samsung's files have none. It is not SHA-256 (or
  SHA3/BLAKE2s) of any structural slice of the file, so it is presumably
  keyed. The oldest upstream firmware (`...SILICONZ_LITE-3`, 2022-01) enforces
  it too.
* So "Samsung BDF crashes upstream amss" (section 16) was never about
  Samsung's content, and the 30-minute region bisect in `bisect.log` was
  measuring this check, not bad fields. No hybrid file can load either.

That leaves two ways to get correct coexistence:

1. **Samsung's `amss20.bin` under ath11k** -- it does not want the trailer,
   but asserts ~1.7 s after WMI init (section 16). Needs the RDDM dump and
   WMI/HTC debug logs from that window. This is the clean route.
2. Reproduce the trailer. Only possible if it is a keyed hash whose key sits
   in the firmware image; not attempted, and it means defeating a vendor
   integrity check on calibration data -- the user's call.

**Test rigs** (both leave the rootfs as it was):
`bt-work/bdf/bdtest.sh` serves a board file from tmpfs via
`firmware_class.path` and rebinds ath11k; `boottest.sh` / `/root/bdf-arm.sh`
+ `fold3-bdf-test.service` install a firmware set for exactly one boot,
log to `/root/bdf-test/results.log`, restore, and reboot if WiFi is dead.
Two traps: unbinding ath11k within ~10 s of a firmware crash NULL-derefs the
kernel (wait for "failed to load board data file"), and a hand-rolled
WLAN_EN/PERST# cold cycle does not bring the link back under pwrseq.

### What `pm8350c_l9` actually is

* In Qualcomm's reference boards it is the **SD-card VDD**
  (`&sdhc_2 { vdd-supply = <&pm8350c_l9>; }`, 2.95-2.96 V, with L6C as
  vdd-io). `sdhc_2` is disabled on q2q -- there is no SD slot.
* Samsung's overlay (`q2q_eur_openx_w00_r08.dts`, fragment@196) repurposes
  it: fixed 2.9 V, `regulator-always-on`, no consumer. That fragment sits
  between the sensor fragments and the grip-sensor ones.
* The two SX9360 grip (SAR) sensors have no supply in the DT and no regulator
  code in their drivers, so they depend on always-on rails. **Proven by
  toggling:** the *sub* grip sensor (0x28 on `i2c@a84000`) answers only while
  S2MPB02-sub LDO12 (2.9 V, also Android-always-on) is on.
* By symmetry L9C is almost certainly the *main* grip sensor's 2.9 V supply
  (sx9360 on the bit-banged bus at TLMM 10/11). That part is inference.

**L9C was never fatal.** The two dead boots were the off-grid voltage failing
the PM8350C regulator probe (section 7). Declared at 2.904 V it boots, the
rail is on, and the PMIC's VSET reads 2.960 V. Bluetooth reception with it on
is marginally better at best and still far below a laptop beside the phone,
so it is not the fix for the radio either.

---

## 23. The cover display

The cover panel (Samsung S6E3FAB / AMB623ZF01, 832x2268, command mode, DSC)
runs as a second output, `DSI-2`, next to the inner panel. It worked on the
first flash. By choice it has **no touch and no fold switching**.

* **Driver:** `cover-work/panel-samsung-s6e3fab.c`, out of tree (no Kconfig
  symbol, so no kernel config change). Install into
  `/lib/modules/<rel>/extra/` and `depmod`. It is the inner driver's sibling:
  the `hd120hs` init stream from `panel-work/decode-cover-s6e3fab.txt`, a real
  reset pulse, and display-on sent from `.enable`. Only 120 Hz is advertised
  (byte `0x60` is `0x20` for 120/96 Hz, `0x00` for 60/48 Hz).
* **This panel gets a true cold init.** The bootloader does not light it when
  the phone boots unfolded, unlike the inner panel.
* **DT:** `&mdss_dsi1` + `&mdss_dsi1_phy`. Reset is **TLMM 17** (the Samsung
  node's `qcom,platform-reset-gpio = 0x11`; 24/25 are the amps' i2c bus). TE
  is **TLMM 83**, the *secondary* vsync input, so the DSI endpoint carries
  `qcom,te-source = "mdp_vsync_s"`; without it the DPU would wait on the inner
  panel's TE. Both pins came out of `gpio-reserved-ranges`.
* **Rails:** S2MPB02-sub LDO6 (1.7 V), LDO10 (1.8 V), LDO15 (3.0 V). XBL
  leaves them on; they are declared `regulator-always-on` with **no voltage
  constraints**, and `wifi-work/s2mpb02-regulator.c` gained those three LDOs.
* **Resources:** each panel is 2 layer mixers + 2 DSC encoders in a merge
  topology. SM8350 has four DSC encoders, so both panels use all of them.

**Both panels are components of one DRM device.** If the cover panel module
or the updated `s2mpb02-regulator.ko` is missing, DSI1 defers forever and the
*inner* display never comes up either. Install both modules before flashing
a DTB that enables `mdss_dsi1`.

**Plasma mirrors by default.** On first seeing the second output KWin set the
inner panel to replicate the cover, so the inner screen showed the cover's
tall image. The kernel was fine. Undo it (as the session user, environment as
in section 13):

```sh
kscreen-doctor output.DSI-1.mirror.none output.DSI-2.mirror.none
```

Not done: 60/48 Hz modes, the cover touch (`stm_ts` at 0x49 on `i2c@88c000`,
irq TLMM 34, rails sub LDO8 + LDO14), and a lid switch from the hall sensors
(TLMM 26 and 80).

---

## 24. Audio: everything works except the bit clock reaching the amps

The card (`Samsung-Q2Q`, `qcom,sm8250-sndcard`), the ADSP and both CS35L41
amps probe; PipeWire sees a sink; a UCM profile is installed
(`audio-work/ucm2`). Nothing is audible. The earpiece is taken to be the "top"
amp (i2c 0x41, left slot): there are only two amps and no other codec.

Measured on 2026-11-13 while a tone played (`aplay -D hw:0,0`):

| where | what |
|---|---|
| SoC pad TLMM 125 | clean 1.532 MHz bit clock |
| SoC pad TLMM 128 | 47.9 kHz word clock |
| SoC pad TLMM 127 (vendor `pri_tdm_dout`) | data |
| both amps, PLL on LRCLK | locks, and only while a stream plays -- the word clock arrives |
| both amps, PLL on SCLK | never locks at any of the 64 supported rates |
| top amp told to echo RX1 on TX1 | never drives a bit onto SDOUT (TLMM 126) |
| amp fault flags | none |

The echo test is the conclusive one. The return net is connected -- the pad
follows its own pull while the amps are idle, and the amp pulls it flat low
when its hi-z is disabled -- yet with hi-z enabled it never drives at all: its
serial port never reaches a slot, which means it sees no bit clock. (The PLL
result alone is weaker: the vendor DT sets `cirrus,use-fsync-errata`, so
PLL-on-SCLK may be a known quirk of this chip revision.)

Ruled out: pin mux (ours matches the vendor's `pri_tdm_*` states pin for pin),
drive strength (8 mA tried), the vendor's `output-high` on clock and sync, and
every Android-always-on rail that can be switched live.

So the bit clock is lost between pad 125 and **both** amps. The likeliest
explanation is physical damage, which was already suspected on this unit; it
is not proven. Whether the speakers work under stock Android would settle it.

Measuring pins: `/root/pinfreq <gpio>...` on the phone is a small C program
that samples the TLMM input register through `/dev/mem` at ~4 MS/s and reports
frequency and duty -- enough to tell 1.5 MHz from noise. The python version
(`pinsample.py`) is too slow to resolve MHz and its "edges" figure misled me
into thinking an idle pin was clocking. Pulls, drive, function and OE can be
flipped live with `pinpull.py`, `pindrive.py`, `pinfunc.py`, `pinoe.py`.
`/root/earpiece-test.sh top|bottom` plays beeps on one amp, bypassing PipeWire.

---

## 25. Auto-rotate (2026-11-13)

KWin 6.8 reads `net.hadess.SensorProxy` over D-Bus directly; no QtSensors.
Fedora's `iio-sensor-proxy` has no SSC support, so a local build of the same
3.9 tag (`-Dssc-support=enabled`, source in `/root/src/iio-sensor-proxy`)
runs instead -- installed BESIDE the package, nothing packaged is overwritten:

| piece | where |
|---|---|
| binary | `/usr/local/libexec/iio-sensor-proxy-ssc` |
| unit drop-in | `/etc/systemd/system/iio-sensor-proxy.service.d/10-fold3-ssc.conf` (ExecStart swap, after `hexagonrpcd-sdsp`) |
| udev | `/etc/udev/rules.d/81-fold3-ssc-sensors.rules`: adds `ssc-accel` to `fastrpc-sdsp` and sets the mount matrix |
| local patch | `patches/userspace/iio-sensor-proxy-fold3-claim-race.patch` |

* **Mount matrix `0,1,0;-1,0,0;0,0,1`.** SSC reports the Android frame
  (upright = +Y); the proxy calls +Y "bottom-up"; and KWin maps
  normal/bottom-up/left-up to 0/180/90 degrees WITHOUT adding the panel's
  `LEFT_UP`. Upright therefore has to read "left-up". User-confirmed.
* KWin ignores the panel orientation because
  `drm_connector_set_panel_orientation` WARNs when called from
  `s6e3xa2_get_modes` (in every boot log). If that is ever fixed, redo the matrix.
* **Claim race (patched):** SSC discovery spins the main loop, a client claims
  the accelerometer before the device exists, and it is then never polled.
  Orientation stays "undefined" forever after any proxy restart under KWin.
* After a proxy restart KWin may say `Auto Rotate Policy: incapable`:
  `systemctl stop`, wait 4 s, `start`.
* Inner only: `kscreen-doctor output.DSI-1.autoRotatePolicy.always
  output.DSI-2.autoRotatePolicy.never`. The default `inTabletMode` never fires.
* The cover sat at x=1179, flush with the inner panel's PORTRAIT width; in
  landscape (1472 wide) the two overlapped. `output.DSI-2.position.1472,0`.
* No `ssc-proximity`: libssc asserts on its report and would kill the daemon.
* To test KWin without touching the phone, a mount matrix that routes Z into
  X or Y fakes any orientation. KWin ignores the sensor while DPMS-off.

## 26. Bluetooth and WiFi chain 0: the board file (2026-11-13)

Section 22's root cause was right (WLAN owns the shared 2.4 GHz front end);
the fix is the WLAN **board data**. Samsung's `bdwlan.elf` cannot load (the
upstream firmware demands a 32-byte trailer, section 22), so: diff Samsung's
payload against all 44 unique payloads in upstream `board-2.bin`, ignoring
calibration tables. On the config fields where Samsung differs from the
generic board-id=255 file (0x1d0, the 16-byte switch table at 0x1dd, 0x202,
0x3f, 0x450 ...), exactly one upstream board agrees with Samsung:
`17cb:0108 chip-id 2 board-id 140 variant LE_X13S` -- the same chip-on-board
reference family. It is an unmodified signed blob, so it loads.

`/lib/firmware/ath11k/WCN6855/hw2.0/board-2.bin` is now a single-entry file
holding that ELF under our board-id=255 key (`bt-work/bdf/mkboard2.py`; copy
in `wifi-work/board-2-fold3-x13s.bin`; original in `upstream/board-2.bin.full`).

| | generic | X13s |
|---|---|---|
| WiFi per-chain RSSI | -80 / -46 | -45 / -63 |
| BT scan, WiFi associated | 1-3 devices, -85..-94 | 10-13 devices, best -38..-55 |

Calibration is the ThinkPad's, not ours (the generic file's was not either).
The cleaner form is `qcom,calibration-variant = "HW_GK3"` in DT with the
stock `board-2.bin`. Lesson: when a vendor blob cannot be loaded, look for its
nearest signed relative before trying to patch or forge one.

## 27. Modem: LTE data (2026-11-13)

Works unattended: registered on the carrier's LTE network, ModemManager
`connected`, 13.7 Mbit/s down / 9.2 up, 0% loss. User-confirmed with WiFi off.
Data and SMS only -- no VoLTE on mainline and audio is dropped.

**Device tree** (`&mpss`, `&ipa`): firmware-name under
`qcom/sm8350/samsung/q2q/`. No memory relocation (modem.mdt = 0x8b800000 +
0xf600000, inside upstream's slot). The 7.2 `sm8350.dtsi` lacks
`memory-region = <&pil_ipa_fw_mem>` on the ipa node; added in the board DTS.

**Firmware:** `modem.*`, `modem_pr/`, `modemr.jsn` from partition `modem`
(sda18). **`ipa_fws.*` from partition `apnhlos` (sda23), NOT `/vendor/firmware`**
-- TrustZone rejects the vendor copy at `pas_init_image` with -22. Android
searches `firmware_mnt/image` first, so it never sees that copy.

**Userspace:**
* `rmtfs` (Fedora unit, `-r -P -s`): serves the real modemst/fsg partitions
  READ-ONLY. The modem cannot write the EFS; partition hashes are unchanged
  after many boots. Backups: `capture/backup-20261107-005831`,
  `capture/backup-modem-20261113-linux`.
* `tqftpserv` (Fedora package). **Without it the modem stays `offline`,
  refuses `online` with DeviceNotReady, and reports the cards absent.**
* `fold3-sim-primary.service`: the SIM tray is the modem's physical slot 2
  and Samsung's dual-SIM config provisions it as the SECONDARY subscription;
  ModemManager only drives the primary (`sim-missing`, or a hang). The service
  moves the USIM app to the primary session before ModemManager, every boot
  (read-only EFS means the modem forgets).
* NetworkManager GSM connection with the carrier's APN (taken from the
  network's own LTE attach parameters), IPv4 only (the network refuses IPv6),
  route metric 800 so WiFi wins. The user toggles mobile data from Plasma.

ModemManager adopts a qrtr modem only once IPA provides `rmnet_ipa0`; before
that `mmcli -L` is empty while `qmicli -d qrtr://0 ...` already works.

**Rules agreed with the user:** no writes to modem storage, no band / power /
carrier-config changes, no scan or retry loops, stop after a rejection, ask
for any PIN, and report anything that looks wrong from the operator's side.
Signal quality is poor indoors (RSRP -92..-100, SNR about -5 dB); unknown
whether that is the room or our RF path. Untested: SMS, hotspot, 5G.

## 28. Fold detection and blanking the inner screen (2026-11-13)

Requirement: inner screen dark when closed, and nothing else -- no window or
layout change, cover stays on. User-confirmed working.

    hinge magnet -> AK09970 digital hall (I2C 0x10, bus i2c-fold-hall on TLMM
    104/105, INT TLMM 80, high = closed) -> hall-work/ak09970-fold.c
    (input "fold-hall", SW_MACHINE_COVER) -> fold3-fold-watch.service ->
    /sys/bus/mipi-dsi/devices/ae94000.dsi.0/fold_blank -> DCS display-off/on

* TLMM 80 is NOT a dumb switch: it is the INT pin of the hall chip, which is
  silent until powered (main S2MPB02 `ldo8`, now a DT regulator) and
  programmed (CNTL1 02 24, THRESHOLD_Y 08 89 06 90, CNTL2 2a -- the vendor
  DT's values). Zero counts in `/proc/interrupts` was the tell. TLMM 26 and
  pm8350c gpio6 are the flip-cover halls.
* `SW_MACHINE_COVER`, not `SW_LID`: logind and Plasma act on SW_LID (suspend,
  blank everything), and suspend cannot be resumed here.
* KWin cannot blank one output: its DPMS protocol is per-output on paper but
  blanks all of them, and disable/enable swaps priority and moves the
  desktop. Hence `fold_blank` in `panel-work/panel-samsung-s6e3xa2.c`. The
  pipeline keeps rendering; the saving is the OLED.
* Modules: `ak09970-fold.ko` and `s2mpb02-regulator.ko` in
  `/lib/modules/<rel>/extra`, the panel in the module tree. Building ONE
  in-tree module alone leaves `depends:` empty -- run `make modules`.
* Adding the bus renumbered I2C: main pmic i2c-0, fold hall i2c-1, sub pmic
  i2c-2. Never hardcode bus numbers.

## 29. Charging (2026-11-13)

No kernel charger driver; `fold3-charge.service` (`rootfs-work/charge/`)
polls every 5 s and, while CHGIN is valid, writes the MAX77705 directly:

| | value | register |
|---|---|---|
| charge current | 900 mA (under either cell's 900 mA limiter cap) | CNFG_02 0xb9 [5:0] = mA/50 |
| input limit | DCP 1500, CDP 600, SDP/unknown 500 mA | CNFG_09 0xc0 [6:0] = mA/25 - 1 |
| charger type | chip's own BC1.2 result | usbc 0x25 reg 0x08 [1:0] |

Falls back to the bootloader's 100/500 outside 0..45 degC and on stop. Float
voltage untouched. Measured on a Samsung wall charger: +880..895 mA into the
battery, cells 481-493 / 421-434 mA, temperature flat. Not done: PD/AFC, a
long thermal soak, a PC port. `/root/chg-read.sh` prints a one-line snapshot.

## 30. Open items (2026-11-13)

1. ~~Chainloader~~ -- **done 2026-11-13**, section 31. The follow-up
   (booting stock Fedora kernels from `dnf`) is **parked by the user**:
   "for now, just take notes". Do not start it unasked.
2. Untested: hotspot, SMS, 5G, long charging soak.
3. 7-8 s screen wake (section 18); proximity in libssc; raw gyro.
4. Cleanups: `qcom,calibration-variant` instead of a replaced board-2.bin;
   a real charger driver; RTC cannot be set.

5. **Future work: Android/Linux selection at power-on** (discussed
   2026-11-13, nothing built). Section 32.
6. **Future work: USB file transfer (MTP) + SSH over the cable.** Needs
   `USB_G_SERIAL=n` and a composite gadget (ACM + MTP via FunctionFS/
   `umtp-responder` + NCM) created in the initramfs before anything opens
   `ttyGS0` -- never by swapping the live gadget (section 20). One flash.
   Until then: SFTP over WiFi.
7. `CONFIG_BT_RFCOMM` is off, so Bluetooth headsets have no microphone/call
   profile (HFP); A2DP playback works. Needs a kernel rebuild.
8. `fold3-boot status` showed `default: (embedded) [failed earlier:
   7.2.15-q2q]` on 2026-11-13 evening: the chainloaded entry failed or went
   unconfirmed on one boot. Not diagnosed.

Golden snapshots: `golden/stage10-modem-ipa-*`, `golden/stage11-fold-switch-*`,
`golden/stage12-chainloader-*`.

## 31. The chainloader: kexec from the embedded kernel (2026-11-13)

Problem (section 3): nothing between ABL and Linux can read storage, so the
kernel has to live inside `boot.img` and every kernel change is a flash.
Solution: the kernel inside `boot.img` stays as a fixed **loader**. Its
initramfs mounts the root filesystem and `kexec`s into a kernel stored there.
No bare-metal UFS driver, no new bootloader -- the loader is the kernel we
already boot, and kexec works on this SoC under Samsung's TZ/hypervisor.

    ABL -> uniLoader -> embedded kernel -> initramfs /init (init-rootfs.sh)
        -> /boot/fold3/entries/<name>/Image via kexec_file_load -> real boot

| file | meaning |
|---|---|
| `/boot/fold3/entries/<name>/{Image,initramfs,cmdline}` | one bootable kernel |
| `/boot/fold3/default` | entry booted every time |
| `/boot/fold3/next` | entry booted once (file removed before the jump) |
| `/boot/fold3/pending` | written before jumping to the default; `fold3-boot-ok.service` deletes it 45 s after multi-user. Still present at the next boot = that kernel never came up: default is renamed `default.failed` and the embedded kernel boots |

`fold3-boot status | next <e> | default <e> | embedded` manages it.

Facts that matter:
* `kexec_file_load` on arm64 reuses the RUNNING kernel's device tree, so the
  chainloaded kernel gets the q2q DTB from `boot.img` for free. A DT change
  still needs a flash; a kernel change does not.
* It takes a plain `Image`, not Fedora's compressed EFI `vmlinuz`.
* `bin/kexec-load` is ~100 lines against the kernel's nolibc (no static
  libc for aarch64 on the host). Trap: nolibc's syscall macros pin arguments
  to registers one at a time; a function call among the arguments clobbers
  them (`-EFAULT`). Pass plain locals.
* **GPI DMA has no shutdown hook.** Channels the loader kernel allocated stay
  allocated; the next kernel's `EV ALLOCATE` times out and the touchscreen
  (SPI over DMA) is dead. The loader unbinds `geni_spi`/`geni_i2c` devices
  before the jump. Expect the same class of bug from any other built-in
  driver that owns hardware state.
* The jump happens before any module loads, so remoteprocs, display and WiFi
  are still in bootloader state -- the chainloaded kernel boots as if cold.
  kexec from the full running system was deliberately NOT tried (running
  DSPs would refuse a second PAS load).
* The entry's initramfs must contain `/chained`, or the chainloaded kernel
  would chainload again. `initramfs-chained.cpio.gz` = loader initramfs +
  that marker (concatenated cpio archives).
* The embedded kernel still has `CMDLINE_FORCE`, so `cmdline` is ignored by
  our own builds. A kernel built without it will honour it.
* Modules for an entry go in `/lib/modules/<its release>` as usual.

Updating our kernel without a flash: build, copy `Image` (+ initramfs) into
a new entry, install its modules, `fold3-boot next <entry>`, reboot; if it is
good, `fold3-boot default <entry>`.

**Not solved:** a stock Fedora kernel from `dnf` still will not run this
phone -- it lacks our out-of-tree drivers (panels, touch, S2MPB02, hall) and
patches, and ships as compressed EFI `vmlinuz`. The chainloader removes the
flash, not the custom kernel. The next step toward real `dnf` kernels would
be: decompress vmlinuz in the loader, build our out-of-tree modules against
Fedora's kernel, and see what the stock kernel is missing.

## 32. Future work: choosing Android or Linux at power-on (2026-11-13)

Design notes only -- nothing here has been built or tested.

**What cannot work:** kexec from our running kernel into Samsung's. By then
the hardware is reconfigured and ABL's handoff (its device tree, command
line, ramdisk) is gone. Also not helpful: a separate kernel partition. ABL
only loads an Android boot image from `boot`/`recovery`; the only thing that
could read another partition is our own initramfs, which already reads
`/boot/fold3/entries`.

**Preferred: a stub in `boot.img` that chooses before any kernel runs.**
uniLoader already sits in that spot. If it picks Android it jumps to the
Android kernel with what ABL handed over, untouched; otherwise it starts our
loader kernel, which kexecs the real one as today.

* Space: stock kernel 54.7 MiB (uncompressed Image, boot header v3) +
  ramdisk 0.7 MiB leaves ~40.5 MiB of the 96 MiB partition. Our embedded
  kernel is 41.8 MiB, so it must be cut down to a loader (storage, display,
  keys, kexec). Not yet built or measured.
* Unproven 1: that ABL still prepares Android's DT/cmdline/ramdisk (from
  `vendor_boot`, `dtbo`) when `boot` holds our image. Test: dump what the
  stub receives in x0 and `/chosen`.
* Unproven 2: that Samsung's kernel boots when entered second-hand (load
  address, hypervisor/Knox). Test: a stub that unconditionally jumps to it.
* Selection input: volume-up is PM8350 GPIO 6, i.e. behind SPMI -- the stub
  needs a small SPMI read, or the Linux menu sets a flag it can read.
* Cost: an Android boot update (OTA, Magisk) overwrites `boot`; the combined
  image must be rebuilt afterwards.

Order: two flashes, one delta each -- dump the handoff, then the
unconditional jump. If Android boots that way the rest is plumbing.

**Fallback: swap `boot`.** A menu in our initramfs; choosing Android writes
the Magisk Android boot image (kept on the Linux rootfs) into `boot` and
reboots; a Magisk boot script in Android writes the Linux image back so the
next power-on lands in the menu. Uses only proven states; the risk is power
loss during the 96 MiB write (recover from TWRP/Download Mode).

**Rejected: Linux in `recovery`, BCB in `misc` as selector.** Works on paper
(both partitions are 96 MiB) but evicts TWRP, the rescue and fast-flash
channel.
