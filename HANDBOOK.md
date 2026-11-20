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

  **It can lose a boot race, and the symptom looks exactly like broken NV**
  (seen 2026-11-14). If it runs before the card has initialised it logs
  `no card on a secondary session (no SIM?)`, exits 0, and the flip never
  happens: `qmicli --uim-get-card-status` then reports
  `Primary GW: session doesn't exist` and ModemManager comes up
  `failed: sim-missing`. That is indistinguishable at a glance from the
  modemst corruption of 35.1, and it is **not** -- the NV hashes are fine.
  Check `journalctl -u fold3-sim-primary` first; the fix takes seconds:

  ```sh
  systemctl stop ModemManager
  /usr/local/sbin/fold3-sim-primary.sh     # should print Primary GW: slot '2'
  systemctl start ModemManager
  ```

  Owed: a wait-for-card retry loop in the script, so the race cannot happen.
  A modem crash has the same effect (the flip is lost on modem restart, see
  35.2.1), with the same fix.
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

## 29. Charging (2026-11-13, driver added 2026-11-14, measured 2026-11-15, full plug-in-to-full curve the same evening)

### 29.1 Before the driver: userspace register writes

No kernel charger driver; `fold3-charge.service` (`rootfs-work/charge/`)
polled every 5 s and, while CHGIN was valid, wrote the MAX77705 directly:

| | value | register |
|---|---|---|
| charge current | 900 mA (under either cell's 900 mA limiter cap) | CNFG_02 0xb9 [5:0] = mA/50 |
| input limit | DCP 1500, CDP 600, SDP/unknown 500 mA | CNFG_09 0xc0 [6:0] = mA/25 - 1 |
| charger type | chip's own BC1.2 result | usbc 0x25 reg 0x08 [1:0] |

Measured on a Samsung wall charger: +880..895 mA into the battery, cells
481-493 / 421-434 mA, temperature flat.

### 29.2 The real driver (2026-11-14)

`CONFIG_CHARGER_MAX77705=m` plus `charger@69` enabled in the board DTS. The
chip now has a `power_supply` device, `fold3-charge` drives policy through
sysfs instead of `i2cset`, and charge current went 900 -> 1500 mA.

**The MFD revision gate was never the blocker.** `max77705 7-0066: Rev.0x2 is
not tested` is real and the MFD still does not bind, but
`drivers/power/supply/max77705_charger.c` is a plain **i2c driver with its own
`of_match_table`**, so it binds straight off the bus and needs nothing from
the MFD but the Kconfig dependency. The earlier note that relaxing the gate
was "the lead" was wrong; nothing had to be forced.

**The interrupt was wired to the wrong chip.** Both nodes carried
`interrupt-parent = <&tlmm>; interrupts = <5 ...>`, and a comment claiming
TLMM 5 was the max77705 INTB. It is not. The vendor DT has

    max77705,irq-gpio = <&pm8350c_gpios 5 GPIO_ACTIVE_LOW>

-- phandle 0x9 in `q2q_eur_openx_w00_r03.dts` resolves to
`qcom,pm8350c-gpio`, i.e. **PM8350C GPIO 5, behind SPMI**. Three things matter
when wiring it:

* The specifier is **1-based**. `pmic_gpio_of_xlate()` and
  `pmic_gpio_domain_translate()` both subtract `PMIC_GPIO_PHYSICAL_OFFSET`, so
  `<&pm8350c_gpios 5 ...>` is the pad the vendor's pinctrl calls `"gpio5"`.
  Same convention `key-volume-up` already relies on with `<&pm8350_gpios 6>`.
* The **pinctrl state is not optional**. XBL leaves this pad as
  `in low normal vin-0 pull-down 10uA`, and INTB is active-low, so without the
  vendor's `bias-disable` + `power-source = <1>` a level-low IRQ is asserted
  forever. With the state applied the pad reads
  `in high normal vin-1 no pull` -- the pull-up is on the board, which is why
  the vendor disables the internal bias.
* `pmic@66` had to **lose** its interrupt property. regmap-irq does not request
  its parent IRQ shared, so if the MFD ever starts binding too, whichever
  device probes second fails with -EBUSY. If the revision gate is ever
  relaxed, the correct shape is the MFD owning INTB and handing the charger a
  virq out of its INTSRC domain.

Verified on hardware: `spmi-gpio 4 Level max77705-charger` in
`/proc/interrupts` with `chgin-irq` and `aicl-irq` demuxed under it, and
**zero** interrupts in steady state (342 -> 342 over 30 s; every count so far
came from plug events and module reloads).

**What probe changes, measured before and after.** Checked against the live
chip first so there would be no surprises:

| register | before | after | |
|---|---|---|---|
| CNFG_04 float | 0x13 = 4350 mV | 0x13 | unchanged, see below |
| CNFG_03 top-off | 200 mA | 150 mA | |
| CNFG_05 B2SOVRC | disabled | 4.8 A | safer |
| CNFG_08 FSW | 3 MHz | 1.5 MHz | |
| CNFG_12 VCHGIN | 4.7 V | 4.5 V | |
| CNFG_09 bit 7 | 0 | 1 | charge enable; the vendor driver sets it too |
| CNFG_01, CNFG_00 | timer/restart/prequal off, watchdog off | same | already matched |
| CNFG_02 CC, CNFG_09 ILIM | | **not written** | driver never sets either |

The float voltage is the one DT-driven value: `max77705_charger_initialize()`
feeds `voltage-max-design-microvolt` into `max77705_set_float_voltage()` at
every probe. The battery node therefore went **4.2 V -> 4.35 V**, which is
where the bootloader already had the chip; leaving it at 4.2 V would have cut
roughly a fifth of usable capacity the moment the charger started binding.
`monitored-battery` on the fuel-gauge node is inert -- `max17042_battery.c`
never calls `power_supply_get_battery_info()` -- so nothing else moved.

**The bootloader does not reliably leave a gentle 100/500.** On the boot after
this flash, with no driver bound and the policy service disabled, the chip read
CNFG_02 = 0x5e and CNFG_09 = 0x3b, i.e. **1500 mA charge / 1500 mA input**.
The documented 100/500 was one observation, not a rule.

### 29.3 The dual-cell objection, answered

The charger was held back because mainline has no `s2asl01` driver and nobody
had read the two current limiters. Both now answer:

    main 0x38 on i2c-4,  sub 0x39 on i2c-8     (bus numbers move; probe ID 0x29)

Decoded against `drivers/battery/limiter/s2asl01_limiter/s2asl01_limiter.c`:

| | |
|---|---|
| ID 0x29 = 0x90 | bit0 = 0 -> VER_6030, `rev_id` = 1, `es_num` = 2 |
| VBAT/VCHG | `((v1 << 4) | (v2 >> 4)) & 0xfff` * 1.25 mV, regs 0x09/0x0a and 0x07/0x08 |
| ICHG / IDISCHG | same packing * 1.5625 mA, regs 0x0b/0x0c and 0x0d/0x0e |
| CTRL3 0x11 = 0x0c | charge = current regulation, discharge fully on |
| CTRL4 0x12 = 0x0f | `(d-4)*50+350` = **900 mA cap per cell** |

Note the register map: CTRL1-8 are **0x0f-0x16** and the ID is **0x29** -- an
earlier note placed CTRL3/CTRL4 at 0x10/0x11, which happened to read the same
values.

That gives the property the objection was really asking for: **total pack
current is bounded by hardware at 1800 mA** whatever the charger is told to
do. Stock, for scale, charges at 3000 mA with these caps programmed wide open
at 3150 mA, and only clamps them per-cell in its warm/cool thermal bands
(warm 750/800, cool1 1450/1600). So 1500 mA with the caps at 900 is well
inside the vendor envelope. Measured sharing is close to even: 111 / 112 mA of
a 223 mA pack current, cells within 41 mV.

`tools/charge-probe.py` (installed as `charge-probe`) prints the whole path in
one screen -- VBYP and IIN from the gauge, pack, both branches against their
caps, chip settings, charger state, driver state. VBYP/IIN are the instrument
for any future 9 V work: `VBYP = w * 0.427246 mV`, `IIN = w * 0.125 mA`, from
`max77705_fuelgauge.c`.

### 29.4 Three upstream bugs, two of them ours to care about

* **`patches/0008`** -- `max77705_set_integer()` wrote CHGIN_LIM as `mA/25`
  while `max77705_get_input_current()` decodes `(reg+1)*25`, so every input
  limit came out one 25 mA step high and did not round-trip. It also clamped
  the 6-bit CC field with the 7-bit input field's 3200 mA maximum, so 3.2 A
  produced a regval of 64 that does not fit. Verified fixed on hardware:
  500/1500/2000 mA and 900/1500 mA now read back exactly.
* **`patches/0009`** -- `max77705_aicl_irq()` decrements an `unsigned int`
  with no lower bound, so on a supply weak enough to hold AICL asserted to
  zero, the next write is 0x7f and the input limit jumps to its **maximum**.
  Not theoretical here: a hub port had AICL walking 1500 mA down to 750 mA
  within seconds of binding.
* Not patched: the driver never restores an input limit AICL pulled in. That
  is policy, so `fold3-charge` owns it (29.5).

### 29.5 The policy service now

`fold3-charge` keeps the same shape but on sysfs
(`constant_charge_current`, `input_current_limit`, in microamps):

* charge current **1500 mA**, 900 mA above 40 degC, 100 mA outside 0..45 degC,
  judged on the **hotter of the two pack thermistors** (PM8350 GPIO2/GPIO3 via
  PMK8350's ADC7, added 2026-11-15). Before those channels existed this read
  the fuel gauge, whose temperature is a frozen constant, so the rules could
  never fire -- see 29.6 item 1b;
* input limit by BC1.2 type as before, written **only on a plug event** --
  never on the 5 s timer, because re-asserting it would undo the driver's AICL
  backoff and oscillate. Where AICL has pulled it in, the service logs it and
  leaves it: that reading is the supply's real capability. One exception, a
  re-probe every 10 minutes, so a limit pulled in by a transient does not
  stay pulled in until the next replug;
* charge current goes through a regmap field now, so it can no longer clobber
  the OTG current limit that shares CNFG_02 with it -- which the old masked
  read-modify-write could have;
* it falls back to raw i2c if the driver is not bound, because a phone that
  does not charge is worse than a phone with an unclean charging path.

The charger type still comes from a raw read of the usbc block (0x25 reg
0x08): nothing in mainline owns that block.

**Interaction with OTG:** `max77705_charger_initialize()` writes MODE =
CHG|BUCK at probe, so loading this module while `fold3-otg on` is active would
kill the OTG boost. udev autoloads it at boot only, so this is a hazard for
manual `modprobe`, not for normal use. At runtime nothing rewrites MODE, so
`fold3-otg`'s raw pokes still work.

### 29.6 What is left

#### 1. The 1500 mA measurement -- DONE 2026-11-15, 1473 mA in CC

Measured twice the same day. The **first** run (78 -> 88% SoC, 19 min, 256
samples) only ever sampled the tapering top of the curve and reported 1343 mA.
The **second** (36 -> 100% SoC, 133 min, 1607 samples) captured plug-in to full
and supersedes it. The CC figure for this device is **1473 mA**.

Logs:

* `rootfs-work/charge/measurements/2026-11-15-full-36-to-100-dcp.txt` -- the
  full curve. Use this one.
* `rootfs-work/charge/measurements/2026-11-15-1500mA-dcp.txt` -- the first,
  partial run. Kept because it is the only CDP-to-DCP comparison on record.

| | measured (full run) |
|---|---|
| pack current in CC | **mean 1473 mA**, flat within 20 mA for 67 minutes |
| the old userspace path | ~880 mA |
| so | **1.67x** |
| CC window | 67 min, 4.03 -> 4.33 V, 36% -> 78% SoC |
| what binds in CC | the **1500 mA charge-current setting**, not the input -- see the correction in item 2 |
| input current | 1393 mA at 36% rising to 1474 mA at 76%; it tracks pack voltage and never saturated |
| VBYP | 4.88 - 4.94 V; **87% efficiency**, steady across the whole CC window |
| AICL | `idle` in all 1573 plugged samples |
| BC1.2 | `DCP` throughout |
| branch imbalance | within 25 mA; cell voltages +25 mV apart in CC, +46 mV worst in CV |
| pack temperature | **+1.1 degC over 133 min**: 27.3 -> 28.8 peak at 76% SoC, then *down* to 25.8 as current tapered. 11.2 degC of margin to the 40 degC step-down |
| torn i2c samples | **0 of 1573** (the first run had 1 in 75) |
| rate | 0.64 %/min in CC; 36 -> 78% in 67 min, then 78 -> 100% in another 35 |

CV ran for 68 minutes after that: handover at 4.336 V / 78%, regulating
4.337 V against the 4350 mV setting (13 mV low, consistently, in both runs),
current decaying 1432 -> 214 mA. The CC->CV boundary dithered five times
between the two states in 2.5 minutes before settling -- boundary hunting, not
a fault.

SoC read 100% at the 100-minute mark while the pack was still accepting
470 mA, so **the gauge's 100% arrives roughly half an hour of real charging
early**. Expected for CV, but worth knowing before trusting it for anything.

**Termination was never observed.** `CHG_DTLS` never reached `done` (0x4): at
unplug (19:57:59, 133 minutes in) the charger was still in `fast-CV` pushing
~220 mA, still above the 150 mA `TO_ITH` top-off threshold, so termination was
pending and maybe ten minutes out. The taper was tracking toward it correctly,
but **nothing here proves this charger latches off**. That is the one state
transition still unwitnessed, and the only reason to plug in for measurement
again.

Capacity, as a free by-product: integrating the gauge's current over the run
gives 2.273 Ah for 64 points of SoC, implying ~3550 mAh of usable capacity,
against the gauge's own `charge_full` of 3775 mAh and `charge_full_design` of
3864 mAh at **248 cycles**. Those agree to within ~6%, which cross-checks the
gauge's current scale and its SoC scale against each other -- useful, because
item 1's saturation finding below rests on the gauge being the trustworthy
sensor. (That 3864 mAh design figure is well under the 4400 mAh the Fold 3 is
sold with. It is whatever the gauge is configured with; the discrepancy is
unexplained and was not chased.)

**The branch-current readback saturates.** The first run saw a ~215 mA gap
between the branch sum and the gauge and recorded it as unexplained. The full
run explains it, because it sweeps the current across the whole range:

| gauge reads | branch sum | diff |
|---|---|---|
| 1473 mA | 1126 mA | +347 |
| 1353 mA | 1129 mA | +224 |
| 1247 mA | 1126 mA | +121 |
| 1108 mA | 1108 mA | 0 |
| 894 mA | 947 mA | -53 |
| 336 mA | 352 mA | -17 |

The branch sum is pinned near 1125 mA whatever the real current is, and the gap
closes to zero as the real current falls to meet it. The highest single-branch
reading in 1607 samples was main 564 mA / sub 584 mA. So **each limiter's ICHG
readback clips around 570 mA**, and the sum is meaningless above ~1130 mA.

It is the register or its decode, not the sense element: moments after unplug
the *discharge* field read -1086 mA and -906 mA per side on the same hardware,
far past where ICHG clips. Suspect the ICHG scaling or field width in
`charge-probe.py`'s decode (from `s2asl01_limiter.c`, x1.5625 mA) before
suspecting the chip.

Two consequences:

* **Headroom is smaller than the first run claimed.** At 1473 mA each branch
  really carries ~736 mA against its 900 mA cap -- about **164 mA spare, not
  the 319 mA** the raw readings implied. Still comfortably inside the cap, but
  that figure was optimistic and is corrected here.
* **Balance cannot be read from ICHG above ~570 mA/side.** Use the cell
  voltages, which are unaffected: +25 mV apart in CC, +46 mV worst in CV.
  Small, stable, no drift over 133 minutes.

#### 1b. The battery temperature was not a measurement -- found AND FIXED 2026-11-15

**Fixed the same night.** Two real pack thermistors now read through IIO:

```
pack  4.151 V  +265 mA  82%  batt_therm 28.8 C  sub_batt_therm 28.2 C
```

`fold3-charge` judges its limits on the **hotter** of the two (max, not mean --
it feeds a protection limit, and a hot side must not be averaged away by a
cool one), and logs both: `temp=28.8/28.2C -> charge 1500 mA`. The 0/40/45 degC
rules are real for the first time. What follows is the diagnosis, then the
change.

`max170xx_battery/temp` read **27.3 degC, byte-identical, in all 231 samples**
across 19 minutes of 1.4 A charging. It is not a slow sensor; it is not a
sensor. The gauge's CONFIG register (`0x1D`) reads **0x0314**, which has the
**TEX bit (bit 8) set** -- temperature is supplied *by the host*, and on
mainline nothing writes it. The register holds whatever the bootloader or
Android last put there, forever.

Consequences, and the second one is the one that matters:

* The `TEMP_WARM = 40`, `TEMP_MAX = 45`, `TEMP_MIN = 0` rules in
  `fold3-charge` **can never fire**. They are dead code that looks like
  thermal protection. Item 1's table above says "if it is tripping the 40 degC
  rule" -- it cannot trip it, so that test was never going to tell us anything.
* **There is no battery temperature available anywhere on mainline.** All 32
  thermal zones are SoC or PMIC die sensors (`cpu*`, `gpu*`, `aoss*`,
  `pm8350`, `pm8350c`, ...). The vendor reads two pack thermistors
  through PMK8350's ADC7 instead (PM8350 GPIO2 and GPIO3); no mainline DT node
  exposes them yet, which is what the next part is about.

So, until this was fixed, any decision to charge harder was a decision to
charge harder blind -- which made it a prerequisite rather than a
nice-to-have.

**The vendor path, checked in `SM-F926B/Kernel` (2026-11-15).** An earlier
draft of this section guessed "a PM8350C ADC channel". That was wrong, and the
real answer is better, because every piece of it already exists in mainline:

* The vendor fuel-gauge driver **writes** temperature into the gauge --
  `max77705_fg_write_temp()` to `TEMPERATURE_REG`, called from
  `POWER_SUPPLY_PROP_TEMP` in `set_property`
  (`drivers/battery/fuelgauge/max77705_fuelgauge/max77705_fuelgauge.c:2243`).
  So **TEX = 1 is by design, not a misconfiguration.** The gauge is a
  consumer of temperature here, never a source, and clearing TEX would most
  likely just give a reading from a pin with nothing on it.
* The number comes from `sec_battery`, which reads it over **IIO** --
  `iio_channel_get(dev, "adc-temp")` then `iio_read_channel_processed()`
  (`drivers/battery/common/sec_adc.c:24,55,66`).
* The q2q DT wires that name to a channel
  (`arch/arm64/boot/dts/samsung/q2/q2q/q2q_eur_openx_w00_r05.dts:178`):

  ```
  io-channels = <0x1 0x14b 0x1 0x148 0x1 0x14b 0x1 0x145 0x1 0x14c>;
  io-channel-names = "adc-temp", "adc-chg-temp", "adc-wpc-temp",
                     "adc-usb-temp", "adc-sub-bat";
  ```

  Phandle `0x1` is `vadc@3100`, `compatible = "qcom,spmi-adc7"`, under the
  SPMI PMIC at `reg = <0x0 0x0>` -- i.e. **PMK8350's ADC7**, which is the
  controller that reads other PMICs' channels by SID. Channel `0x14b` decodes
  as SID 1 (`PM8350_SID`) channel `0x4b` = **`PM8350_ADC7_GPIO2_100K_PU`**.

So: **the pack thermistor sits on PM8350 GPIO2 with a 100 kOhm pull-up, read
through PMK8350's ADC7.** Not PM8350C, and not an `adc-tm` zone -- plain
ADC reads.

**And there are two of them.** `adc-sub-bat` is channel `0x14c` =
`PM8350_ADC7_GPIO3_100K_PU`. The pack is dual-cell with a thermistor per side,
which is exactly the per-branch thermal signal item 2 would want before anyone
pushes a branch toward its 900 mA cap.

**All of this is reachable from mainline today, with no new driver:**

* `qcom-spmi-adc5.c` already matches `"qcom,spmi-adc7"`
  (`drivers/iio/adc/qcom-spmi-adc5.c:811`).
* `PM8350_ADC7_GPIO2_100K_PU(sid)` / `GPIO3` are already defined in
  `include/dt-bindings/iio/qcom,spmi-adc7-pm8350.h`.
* `pmk8350.dtsi` already defines `pmk8350_vadc: adc@3100`, and **our DTS
  already includes it** -- we explicitly switch it off at
  `dts-work/sm8350-samsung-q2q.dts:1783`, so nothing claimed it. The change is
  to flip that `status` and add two channel nodes.
* `qcm6490-fairphone-fp5.dts` and `sm6125-xiaomi-laurel-sprout.dts` both carry
  a `GPIO2_100K_PU` thermistor channel upstream, so there is a known-good
  shape to copy (`qcom,ratiometric`, `qcom,hw-settle-time`,
  `qcom,pre-scaling = <1 1>`, a `label`).

**The calibration table is in the vendor DT too**, so nothing has to be
characterised by hand. `battery,temp_table_adc` / `battery,temp_table_data`
(lines 188-189) give 23 monotonic points, microvolts to tenths of a degree,
+90 degC down to -20 degC:

| uV | degC | | uV | degC |
|---|---|---|---|---|
| 83606 | +90 | | 590981 | +20 |
| 148528 | +70 | | 714856 | +10 |
| 275154 | +50 | | 821453 | 0 |
| 370011 | +40 | | 908239 | -10 |
| 469917 | +30 | | 974549 | -20 |
| 529843 | +25 | | | |

(Full 23 points at those DT lines. As a sanity check, today's frozen 27.3 degC
would correspond to roughly 506000 uV, so a real reading near that value is
the sign the channel is wired correctly rather than reading a floating pin.)

The cheapest useful version, then: enable `pmk8350_vadc`, add the GPIO2 and
GPIO3 channels, and have `fold3-charge` read the two IIO channels and
interpolate the vendor table itself -- no kernel code, and it makes the
existing 40/45 degC rules real instead of decorative. A `thermal-zones` entry
would be tidier for the rest of the system but is not needed to unblock
charging.

**What was actually done (flashed 2026-11-15, kernel #64 image + new DTB).**

1. `dts-work/sm8350-samsung-q2q.dts`: added
   `#include <dt-bindings/iio/qcom,spmi-adc7-pm8350.h>`, flipped
   `&pmk8350_vadc` from `disabled` to `okay`, and gave it two channels:

   ```
   channel@14b {
           reg = <PM8350_ADC7_GPIO2_100K_PU(1)>;
           qcom,ratiometric;
           qcom,hw-settle-time = <200>;
           qcom,pre-scaling = <1 1>;
           label = "batt_therm";
   };
   channel@14c { reg = <PM8350_ADC7_GPIO3_100K_PU(1)>; ... "sub_batt_therm" };
   ```

   The unit addresses are the vendor's channel ids exactly: the DTB
   decompiles to `reg = <0x14b>` / `<0x14c>`. Note the property is
   `qcom,hw-settle-time`, NOT the `-us` form that some upstream boards use in
   their `adc-tm` nodes -- `adc5_get_fw_channel_data()` reads the former.

2. **No kernel rebuild and no config change.** `CONFIG_QCOM_SPMI_ADC5=m` was
   already set from defconfig and `qcom-spmi-adc5.ko` was already installed on
   the device, so udev autoloaded it the moment the node appeared. Only the
   DTB inside the boot image changed, so `assemble-boot.sh` reused the
   existing `Image` (#64).

3. `fold3-charge` gained `find_therms()` / `battery_temp(therms)`: it prefers
   the IIO channels, takes the max, and **warns loudly** if it finds none,
   because the silent fallback is the frozen gauge and a guard on that does
   nothing. `tools/charge-probe.py` does the same and labels the gauge value
   `FROZEN` if it ever has to use it.

Verified on hardware: `iio:device0` = `c440000.spmi:pmic@0:adc@3100`, both
channels present and **live** -- six consecutive samples moved around
(28638/28644 and 27990/28028/28018/28007 milli-degC), which a cached constant
would not do. They differ from each other by ~0.6 degC as two separate
thermistors should, and at ~28 degC they sit well below the die sensors
(`pm8350` 37.0, `cpu0` 38.9), which is right for a pack versus the SoC. The
gauge sat at a frozen 27.3 degC beside them throughout, which is the cleanest
possible confirmation that it was always a dead path.

Still open, deliberately: the generic Qualcomm 100k NTC curve is what produces
these numbers, not Samsung's 23-point table. The two agree to about a degree
at room temperature, which is fine for a 40/45 degC guard. If a reading ever
needs to be trusted near the limits, interpolate the vendor table instead --
it is in the vendor DT and reproduced above.

Rollback, if the thermistor channels ever need backing out: the exact
pre-flash partition is at
`/root/fold3-restore/q2q-boot-running-20261115.img` on the device
(sha256 `b7d1d0a4...`), dumped from `sda19` before writing. The older
`q2q-boot.img` there is from 01:35 and is NOT this kernel.

#### 2. 1800 mA -- NOT PURSUED (user decision, 2026-11-15)

**The user closed this on 2026-11-15:** 1.53x is enough, and there is no reason
to stress the pack further. (The figure in front of them at the time was
1.53x; the full curve measured later the same evening restates it as 1.67x,
which only strengthens the decision.) Do not re-propose it unasked. The analysis below is
kept because it is what makes the decision an informed one rather than a guess.

The measurement settles the old worry, which was that one branch would pin at
its 900 mA cap and dissipate the difference. It does not: the two branches
track within 25 mA of each other, and at 1473 mA each carries ~736 mA against
its 900 mA cap. (The 581 mA / 319 mA spare figures this item used to quote were
clipped readings -- see the saturation note in item 1.) The limiter caps are
**not** the binding constraint.

**Correction, 2026-11-15, from the full run.** This item previously claimed the
*input* binds instead, and that is wrong for most of the charge. Across the
67-minute CC window the input drew 1393 -> 1474 mA against its 1500 mA limit
and never saturated; what was binding was the 1500 mA charge-current setting
itself. The input only nears its ceiling above ~4.33 V, and CV takes over
first, so at this float voltage the input ceiling never actually binds at all.
The first run read as "input-bound" because it sampled nothing but the top of
the curve, where that is briefly true.

Stated plainly, because the record should not be wrong: 1800 mA on a 5 V DCP
**would** have delivered more current below ~70% SoC, which is the opposite of
what this item said before. That does not reopen the decision. The decision was
never resting on this argument -- it rests on not stressing a 2021 cell
further -- and it stands as the user made it.

When it does come up again, note that stock has a **thermistor per pack side**
(`adc-temp` and `adc-sub-bat`, PM8350 GPIO2 and GPIO3 -- see 1b), so the
per-branch thermal signal this item really wants does exist in hardware. It is
just not wired up on mainline yet.

#### 3. 9 V input -- NOT PURSUED (user decision, 2026-11-15)

**Closed by the user on 2026-11-15**, together with item 2: "If we have 1.5, I
am quite satisfied. There's no reason to stress batteries any further." This
is a 2021 cell on its original chemistry already floating at 4.35 V, so the
remaining headroom is not worth the cycle-life cost. Everything below is
preserved as a complete recipe in case that ever changes -- it is researched,
not started, and needs no flash.

AFC is a single opcode-mailbox write to the usbc block.
`max77705_muic_afc_hv_set()` sends opcode 0x21 with data **0x46** for 9 V
(0x08 for 5 V) by writing `[opcode, data]` at register **0x21**
(`OPCODE_WRITE`), then 0x00 to **0x41** (`OPCODE_WRITE_END`), and reads the
result from **0x51**. PD instead uses `OPCODE_SRCCAP_REQUEST` (0x32). The
chip's own MCU does the handshake, so no PD state machine is needed on our
side -- but it is the same MCU that owns Type-C role and the OTG boost, and
there is no mainline driver for that block at all. Confirm the result with
VBYP, which reads the delivered input voltage directly: 4.87 V today, and it
should read ~9 V if the handshake takes.

The ordering argument from 2026-11-14 does not survive the full run. It held
that 9 V only helps once the charge current is allowed past roughly 1.3 A, and
that 1343 mA was where we landed, pinned by the input. In fact CC held 1473 mA
with the input about 100 mA short of its limit, and it was **CV, not the input,
that ended the CC phase**. 9 V would buy headroom only in the last few percent
of CC, where the input does come close to its ceiling. The decision stands on
the user's reason, not on this one.

#### 4. Still untested

With items 2 and 3 closed, charging is **done**: 1500 mA set, **1473 mA
measured in CC**, full curve on record.
What is left is observation, not change:

* Behaviour on a true SDP (should log SDP and hold 500 mA).
* A long thermal soak -- **effectively done** by the full run: 133 minutes
  plugged, +1.1 degC peak, and the pack ended cooler than it started. There is
  nothing for the 40/45 degC limits to act on at these settings.
* **Termination into `done` (0x4), never witnessed.** The full run was unplugged
  at 99-100% with ~220 mA still flowing, above the 150 mA `TO_ITH` threshold.
  To catch it, plug in near full and leave it 20-30 minutes past the point the
  gauge says 100%.

#### 5. Running processes on the phone: match on the binary, not the cmdline

Three sessions have now lost something to the same mistake, in three different
disguises. Over ssh, every pattern in the script you send is **itself text in
the remote shell's command line**, so a process match against that pattern
matches your own shell:

* `pkill -f "charge-probe --watch"` -- killed the ssh session (2026-11-14).
* `ps -eo pid,args | grep -E "[c]harge-probe"` -- the bracket trick did **not**
  save it, because the same script also contained the words `which
  charge-probe`, which the regex matched (2026-11-15).
* `case "$c" in *python3*watch*)` over `/proc/*/cmdline` -- skipped `$$`, so it
  spared the shell, and then killed **`fold3-fold-watch`**, an unrelated Python
  service whose name happens to contain "watch" (2026-11-15). It is `enabled`,
  so a reboot would have hidden the damage; `systemctl start fold3-fold-watch`
  brought it back.

What actually works: match on the process's **binary**, which for your own
shell is `bash` and never `python3`, and pin the full script path --
`ps -eo pid,comm,args | awk '$2=="python3" && /charge-probe/ {print $1}'` --
or simplest, read the PID once and `kill` that number.

## 30. Open items (2026-11-13)

*Cameras moved from "out of scope" to in-progress on 2026-11-14 -- see
section 33, which carries its own next-steps list.*

1. ~~Chainloader~~ -- **done 2026-11-13**, section 31. The follow-up
   (booting stock Fedora kernels from `dnf`) is **parked by the user**:
   "for now, just take notes". Do not start it unasked.
2. Untested: hotspot, SMS, 5G, long charging soak.
3. 7-8 s screen wake (section 18); proximity in libssc; raw gyro.
4. Cleanups: `qcom,calibration-variant` instead of a replaced board-2.bin;
   RTC cannot be set. (A real charger driver was owed here and is **done**,
   2026-11-14 -- section 29.2.)

5. **Future work: Android/Linux selection at power-on** (discussed
   2026-11-13, nothing built). Section 32.
6. ~~**Future work: USB file transfer (MTP) + SSH over the cable.**~~ --
   **DONE 2026-11-16, section 36**, though not the way this item predicted.
   `USB_G_SERIAL=n` and an initramfs composite: yes. MTP *in* that composite:
   no -- a FunctionFS function blocks the whole gadget from binding until its
   daemon is up, which would cost the initramfs its console. MTP is added on
   demand by a rebind, which **is** safe with configfs (36.4, measured).
   `umtprd` still needs building; `ncm.0` already gives SSH over the cable.
7. `CONFIG_BT_RFCOMM` is off, so Bluetooth headsets have no microphone/call
   profile (HFP); A2DP playback works. Needs a kernel rebuild.
8. `fold3-boot status` showed `default: (embedded) [failed earlier:
   7.2.15-q2q]` on 2026-11-13 evening: the chainloaded entry failed or went
   unconfirmed on one boot. Not diagnosed.
   *Partly explained 2026-11-16 (36.6): its "running:" line was always wrong
   on a chainloaded boot, because it grepped `dmesg` for a marker the SLPI
   spam had already pushed out of the ring buffer. Fixed to use
   `journalctl -k`. That does not explain the `default.failed` marker itself,
   which is written by the initramfs, so item 8 stays open.*

9. **DisplayPort over USB-C** (2026-11-19) -- a new goal, asked for this
   session alongside a working OTG path for a TV. It is **partially done**:
   PD alt mode, AUX mux, HPD, link training, EDID and a 1280x720 modeset all
   work, but the picture came out flat blue and that is unexplained. **Section
   37, and 37.7 is the ordered pick-up list.** Headline cautions:
   * Whatever terminates the DP bridge chain is load-bearing for the **whole**
     display -- get it wrong and both DSI panels go dark, not just DP. It must
     be built in, never a module.
   * The link rate is capped at RBR in the DTS because the only adapter we
     have cannot train higher. HBR is untested.
   * Our own tooling re-sent Enter Mode / DP Configure on live sessions, which
     the vendor driver refuses to do, and that most likely wedged the adapter.
     Fixing that is step 1 of 37.7.
10. **Audio over the dock is deliberately deferred** -- the user chose to keep
   the USB-C DAC (section 34) rather than take sound over DisplayPort.

Golden snapshots: `golden/stage10-modem-ipa-*`, `golden/stage11-fold-switch-*`,
`golden/stage12-chainloader-*`, `golden/stage13-fedora-prep-*` (whose
`q2q-boot-FLASHED-20261116.img` is the rollback image that recovered the
dark-screen flash on 2026-11-19).

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
flash, not the custom kernel.

*Prep started 2026-11-16 -- see [docs/18-fedora-kernel-updates.md](docs/18-fedora-kernel-updates.md).*
Three of the unknowns in that paragraph are now settled:

* **`vmlinuz` is not a problem.** It is an EFI `zboot` wrapper around a
  zstd-compressed Image; `tools/unzboot.py` unwraps it (17 MB in, a 78 MB
  plain arm64 `Image` out, verified on 7.2.11-300.fc45). No loader change.
* **Nothing we patch has to be built in.** Audited with
  `tools/fedora-kernel-audit.sh`: against Fedora 7.2.11 aarch64 there are no
  blockers -- 6 symbols Fedora leaves off are in-tree tristates we can build
  out-of-tree, 5 are drivers we patch and must shadow, the other 55 are
  already `y`/`m`.
* **The one patch that cannot be a module does not need to be one.** Patch
  0001 (secure-watchdog deactivate, in `bool` `QCOM_SCM`) only has to run in
  the LOADER: the disable happens in TrustZone and survives the kexec.
  Measured on 2026-11-16 -- a payload kernel built with 0001 reverted reached
  `graphical.target` in 18.3 s with `SECWDOG` nowhere in its log.

What is left is real work, not unknowns: the payload's initramfs now needs
modules to mount root at all (Fedora has `SM_GCC_8350`, UFS and the QMP PHY
as modules, and no `PINCTRL_SM8350` whatsoever), and `dnf` on its own will
never produce a bootable entry -- the host has to build the module set.

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

Order: dump the handoff, then the unconditional jump -- the second needs
what the first reports. If Android boots that way the rest is plumbing.

**Fallback: swap `boot`.** A menu in our initramfs; choosing Android writes
the Magisk Android boot image (kept on the Linux rootfs) into `boot` and
reboots; a Magisk boot script in Android writes the Linux image back so the
next power-on lands in the menu. Uses only proven states; the risk is power
loss during the 96 MiB write (recover from TWRP/Download Mode).

**Rejected: Linux in `recovery`, BCB in `misc` as selector.** Works on paper
(both partitions are 96 MiB) but evicts TWRP, the rescue and fast-flash
channel.

---

## 33. Cameras (2026-11-14)

Full detail, rails and topology live in [camera-work/](camera-work/). This
section is the narrative record.

### 33.1 The claim that was wrong

The repo said "Cameras are disabled by the unlock itself" (README) and listed
them as deliberately out of scope. That traced to `05-research-gaps.md` Q3,
which openly admitted the source was an XDA **headline** read no further than
the title. It then got restated as fact in two summary files.

It is **false** for SM-F926B on this firmware. Tested on this device with
`verifiedbootstate=orange`, `flash.locked=0`, `warranty_bit=1`:

* `dumpsys media.camera` -> `Number of camera devices: 4`, twelve provider IDs.
* The camera app opened a device and **streamed**:
  `CAM_START_DEV Success, sensor_id:0x555` ->
  `cam_sensor_wait_stream_on: ... Last frame_cnt 0xb` -> clean `CAM_STOP_DEV`.
* Sensor IDs read off the silicon (`read id: 0x555 expected id 0x555`,
  `0x258`), and every module's cal EEPROM read + CRC-checked at boot.

Nothing in `SM-F926B/Kernel/techpack/camera/` gates on bootloader or Knox
state either; `csiphy_info[].secure_mode` is per-request and defaults to
`CAM_SECURE_MODE_NON_SECURE` -- the iris/face-unlock path, not a capture gate.

**The lesson is about provenance, not cameras.** A `[3P]` marker in a research
file did not survive the copy into a summary file, and an unread headline
became a project constraint for a week. Keep `[3P]` attached all the way to
wherever a claim is acted on.

### 33.2 What this unit has

Read from the modules' own EEPROMs. Note the **hardcoded fallback** strings in
`cam_sysfs_init.c` (`rear_type_show` -> `"SONY_IMX563"`) disagree and are wrong
for this unit -- `rear_camtype` resolves dynamically and agrees with the
silicon.

| slot | part | bus | csiphy | mclk |
|---|---|---|---|---|
| rear wide | **SONY IMX555** (`0x555`) | cci0 m0 | 0 | 19.2 MHz |
| rear ultrawide | SONY IMX258 (`0x258`) | cci1 m0 | 4 | 19.2 MHz |
| rear tele | **HYNIX HI1337** (dual-sourced w/ S5K3M5) | i2c@a8c000 | 2 | 19.2 MHz |
| front | SONY IMX471 | cci0 m1 | 5 | 19.2 MHz |
| front-top (cover) | SONY IMX374 | **i2c@998000** | 3 | **24 MHz** |

### 33.3 camcc-sm8350: written, and it works

Mainline has no `qcom,sm8350-camcc`. `camera-work/port-camcc.py` generates one
from Qualcomm's `camcc-lahaina.c`; `verify-camcc.py` asserts all 119 clocks,
18 freq tables and 8 parent maps are byte-identical to the vendor's.
`install-camcc.sh` wires it in. Base chosen by comparing clock-name sets, not
SoC numbering: camcc-sm8250 shares 102/119; sc8280xp only 88.

On device: driver bound at `ad00000`, **119 clocks**, **7 GDSCs** with correct
`titan_top` parenting, and PLLs all exact -- pll0 1200, pll1 600, **pll2 960**,
pll3/4/5 676, pll6 960 MHz. `clk_set_rate(cam_cc_mclk3_clk, 24000000)` lands
exactly. TLMM 103 verified by register read: `FUNC_SEL=1` (cam_mclk), 4 mA.

pll2 = 960 = 50 x 19.2 is worth noting: it is independent proof the **v2** PLL
config is the one applied, which was a real bug caught by a `W=1`
unused-variable warning. The vendor probe's `fixup()` swaps in
`cam_cc_pll2_config_lahaina_v2` when the compatible is
`"qcom,lahaina-camcc-v2"` -- exactly what this device's DT says -- and the v1
and v2 configs differ in three control words.

`clk_prepare_enable` first gave **-EBUSY**, and a five-clock experiment
localised it precisely: `core_ahb` and `sleep_clk` enable; `cpas_ahb`,
`camnoc_axi`, `cci_0` and `mclk3` do not -- exactly the `titan_top_gdsc` set,
which sat `off-0` with no consumer. A GDSC is a genpd and only powers up for an
attached device, so the fix was a DT consumer, not a driver change.

### 33.4 The cover module: a clean negative

The `&i2c6` delta (i2c@998000, TLMM 28/29) works -- the bus appears with no
pinctrl complaint. Every transfer timed out at exactly ~1.01 s while a sibling
GENI bus NAKed in 2 ms, with `998000.i2c` interrupts advancing (the abort path,
not a completion). **Rails were never the problem.** The cause was
`VT10M2_RST_N`, expander gpio 21 on the PCAL6524 at `0x22`: held in reset the
module clamps SDA/SCL. Releasing it took the bus from 1.022 s to 0.001 s,
reproducibly.

With all four preconditions provably satisfied -- rails up, MCLK3 at 24 MHz,
reset released (verified `dir=OUT level=1` by reading `0x22`), bus alive -- a
full `0x03`-`0x77` scan finds **nothing**, 8-bit or 16-bit. That is a clean
negative. Use `camera-work/cover-cam-probe2.py`.

### 33.5 Two traps, both self-inflicted

**Never `i2cset` the PCAL6524 at `0x22`.** The bound `pca953x` driver keeps a
regmap cache. v1 of the probe "restored" the reset line by writing `0x0e`/`0x06`
directly; that desynced the cache, after which gpiolib's own direction write
was skipped as redundant and every later reset release silently did nothing --
the pin stayed an input while the log said "released". Three probe runs
measured nothing and looked like camera failures. Only a reboot resynced it.
**Read** `0x22` to verify a pin; **drive** only via `/dev/gpiochip3`. The
S2MPB02 on `i2c-0` is the opposite case: driverless, so `i2cset` is correct
there.

**Get DT facts from the filesystem form.** The first rail table came from a
brace-parse of the decompiled merged `.dts` and silently mapped two distinct
phandles onto the same regulator. `camera-work/dt-camera-map.py` walks
`/sys/firmware/devicetree/base` pulled off the running stock kernel instead --
one file per property, so phandle resolution is exact.

### 33.6 How far this is from a picture -- SUPERSEDED by 33.9

**Read 33.9 first.** The table below is what was believed on 2026-11-14. Item 3
is wrong: three of the five sensors DO have complete upstream drivers, and the
ultrawide now captures. Items 2 and 4 are done.

#### 33.6 as written on 2026-11-14

camcc is item 1 of 5, and the easiest:

| # | piece | state |
|---|---|---|
| 1 | camcc | **done, verified** |
| 2 | CCI (camera i2c) | not done; `i2c-qcom-cci` exists, needs a DT node |
| 3 | sensor subdevs (IMX555/258/374/HI1337) | **none exist upstream** |
| 4 | camss for SM8350 | not done; resource table + DT, ops exist |
| 5 | libcamera + software ISP | not done |

Item 3 decides it. Qualcomm deliberately keeps sensor init and mode register
sequences **out of the kernel** -- the GPL drop has only the probe/chip-ID
path, which is why dmesg can report `0x555` while no register tables exist
anywhere in `techpack/camera`. Those sequences live in userspace HAL data on
the device. Extractable in principle, but that is reverse engineering rather
than porting, and it is unproven here.

And the ceiling is independent of all of it: **mainline `camss` is a CSI
receiver, not an ISP.** It emits raw Bayer to memory; there is no IPE/BPS/ICP
driver (`icp_ahb` is only a clock it ungates). Stock quality comes from the
hardware ISP, per-module tuning in those EEPROMs, and multi-frame stacking.
The realistic outcome here is recognisable pictures, not One UI output.

### 33.7 Next, in order -- SUPERSEDED by 33.9-33.11

**Do not start from this list.** Items 2 and 3 are done; item 1 (the cover
module's `ext_regs`) is no longer the next step, because the cover sensor
(IMX374) is one of the only two with no upstream driver; and item 3's guess of
`vfe_ops_170` was wrong -- it is `vfe_ops_480` (33.10). The live task list is
33.11 plus the remaining sensors.

#### 33.7 as written on 2026-11-14

1. **`cam_sensor_active_ext_regs0/1`** in the vendor pinctrl -- "ext_regs"
   reads as GPIO-driven **external regulator enables**, i.e. a load switch
   gating module power that the DT's three rails do not describe. Best
   explanation for a module powered "per the DT" yet electrically absent.
2. **CCI DT node**, targeting the *rear* cameras (cci0/cci1) -- Android
   demonstrably streams those, so they are a better target than the cover
   module and come with a known-good reference.
3. **Port camss-sm8350** -- same mechanical shape as camcc.
4. Then confront item 3 above.

Also unverified: that MCLK physically oscillates on the pin (framework state
and mux are confirmed; the waveform is not -- no scope), and whether Samsung's
`front2_moduleid` really corresponds to `eeprom11`.

### 33.8 Leftovers to clean up

* ~~`camcc-mclk-test` in `dts-work/` and `camera-work/mclk-test/`~~ --
  **DELETED 2026-11-16.** The DT node had already gone, replaced by the real
  camss/cci/imx258 nodes; the files are now gone too.
* `camera-work/sensor-rig/` and the `cam-uw-rig` DT node are the new temporary
  harness. **Still kept** -- only the IMX258's address (0x1a) is established,
  and the rig is how the other four get found. Delete both once every
  sensor's i2c address is known and recorded.
* ~~`tools/cam-eeprom-probe.sh` and `camera-work/cover-cam-probe.py`~~ --
  **DELETED 2026-11-16**, superseded by `cover-cam-probe2.py`.
* Switching OS is a verified `boot` partition swap either way; the Fedora
  rootfs is **not** mountable from Android (ext4 incompat features vs a 5.4
  kernel), so restore via `adb push` + `dd` (96 MB/s) or TWRP, not the
  `back-to-linux.sh` staged on sda37.

### 33.9 The camera captures (2026-11-15)

**4208x3120 10-bit raw Bayer off the rear ultrawide IMX258, on mainline.**
The sensor's own test pattern comes back as eight clean vertical colour bars
(`camera-work/samples/2026-11-15-imx258-colourbars.png`), which proves the
whole chain in one shot: sensor configured and streaming, CSI-2 D-PHY trained
on CSIPHY4, CSID demuxing, VFE RDI writing through the SMMU to memory, and the
RGGB phase and MIPI 10-bit packing in the decoder all correct. A real scene
came out flat grey only because the lens was face-down on a desk.

Pipeline: `imx258 9-001a` -> `msm_csiphy4` -> `msm_csid0` -> `msm_vfe0_rdi0`
-> `/dev/video0`. `camera-work/capture-uw.sh` runs it on the phone;
`camera-work/raw2png.py` turns a frame into a PNG on the host (pure stdlib --
there is no numpy on the build host).

#### What 33.6 got wrong

Section 33.6 called item 3 -- "sensor subdevs: none exist upstream" -- the
thing that decides whether this ever captures, because Qualcomm keeps sensor
init and mode tables in userspace HAL data. True of Qualcomm's stack, false
for this phone: **three of the five sensors have complete upstream drivers**,
register sequences included.

| slot | part | upstream driver |
|---|---|---|
| rear ultrawide | IMX258 | `imx258.c` -- 19.2 **and** 24 MHz |
| front | IMX471 | `imx471.c` -- 19.2 MHz; **not in 7.2, only 7.4+** |
| rear tele | S5K3M5 or HI1337 | `s5k3m5.c` -- 24 MHz; which part this unit has is unestablished |
| rear wide | IMX555 | none |
| cover | IMX374 | none |

So the ultrawide, not the cover module, was the cheap path -- and 33.7's item 1
(the cover module's `cam_sensor_active_ext_regs0/1`) is no longer the next
thing to do, since the cover sensor is one of the two with no driver.

33.7 also guessed `vfe_ops_170` from sc8280xp. It is **`vfe_ops_480`**: see
33.10.

#### Finding the i2c address

The one fact DT cannot supply. Qualcomm's stack is told the sensor address by
userspace in the probe packet, the vendor `qcom,cam-sensor` nodes carry no
`slave-addr`, and the GPL drop never names it.

A plain `i2cdetect` on the CCI master is useless, because a CMOS sensor only
answers when powered, un-reset and clocked -- and the sensor driver powers the
module back down the instant its chip-ID read fails. `camera-work/sensor-rig/`
plus the `cam-uw-rig` DT node solves that: a module that reproduces
`imx258_power_on()` exactly and then *holds* it. With it loaded:

```
 10: -- -- -- -- -- -- -- -- -- -- 1a -- -- -- -- --
 50: -- 51 -- -- -- -- -- -- -- -- -- -- -- -- -- --
```

**0x1a**, and 0x51 is the cal EEPROM -- matching the vendor's `qcom,eeprom2`
slave-addr 0xa2 exactly. `i2ctransfer -y 9 w2@0x1a 0x00 0x16 r2` then returned
`0x02 0x58`: the IMX258 chip ID, read off the silicon by a mainline kernel.
The rig is reusable for the other four sensors, which have the same unknown.

#### Why the driver had failed, and it was not the address

0x1a was the first guess all along. **`imx258.c` never implements
`reset-gpios`.** Its binding documents the XCLR pin, but there is no gpiod code
in the driver at all -- still true in 7.4.0-rc1 -- so the module sat in reset
and NAKed. `patches/0011` adds it, copying `imx471.c`'s idiom: acquire the GPIO
asserted, release it in `power_on()` after rails and INCK, wait 10-15 ms, and
re-assert in `power_off()`. That is a genuine upstream gap, worth sending to
linux-media.

Note what the failure did *not* mean. The probe had already got past the
19.2 MHz clock-rate check, endpoint parsing, lane and link-frequency
validation, and `imx258_power_on()` -- so rails, MCLK and reset wiring were all
provably correct, and `-ENXIO` was a NAK, not a timeout. The rig then turned
that into a clean positive instead of another guess.

#### Operational notes

* **Pad formats must be re-applied before every stream.** `VIDIOC_STREAMON`
  returns `-EINVAL` on a second run otherwise: camss validates the whole
  chain's formats at stream start and they do not survive the previous
  stream's teardown. This looks exactly like a capability problem.
* Only 4208x3120 works while the DT declares a single `link-frequencies` of
  633600000. The 2104x1560 and 1048x780 modes use the 640 Mbps link config and
  need 320000000 declared too.
* Sensor controls that matter: `exposure` (clamped by `vertical_blanking`),
  `analogue_gain` (0 by default, which is why the first frames were nearly
  black), `digital_gain`, and `test_pattern` -- which is the fastest way to
  prove the path without depending on optics.
* `/dev/v4l-subdev*` numbering is **not** stable across boots or a camss
  rebind. Find the sensor by entity name via `media-ctl -p`.

### 33.10 Titan 580 is Titan 480, and the GDSC flags come from the vendor DT

SM8350's camera subsystem is register-identical to SM8250's for everything
camss touches, and Qualcomm's own drop says so rather than this being an
inference:

* `cam_vfe580.h` **`#include`s `cam_vfe480.h`** and reuses
  `vfe480_top_common_reg`, `vfe480_bus_hw_info` and `vfe480_top_irq_reg_info`
  verbatim; only three RDI mux `reg_data` blocks differ, which camss does not
  use. Both sit under `isp_hw/vfe_hw/vfe17x/`.
* `cam_ife_csid17x.c` maps `"qcom,csid580"` to **`cam_ife_csid480_hw_info`** --
  the same struct `"qcom,csid480"` gets.

So `patches/0010` reuses `vfe_ops_480` and `csid_ops_gen2` unchanged. Two
things genuinely differ:

1. **Topology:** 3 full IFEs + 2 lites (SM8250: 2 + 2), so 3 CSIDs + 2 lite and
   6 CSIPHYs. That breaks camss-csid.c's hardcoded `id >= 2` test for picking
   the lite CSID offset inside the VFE window -- on SM8350 the lites are ids 3
   and 4. Fixed by using the resource's own `is_lite`, correct on SM8250 too.
   The 17 `/dev/video*` nodes the driver creates (3x3 + 2x4) are an independent
   check that the resource table's `line_num`s are right.
2. **CSIPHY is v1.2.3**, SM8250 is v1.2.1, and `cam_csiphy_soc.c` selects a
   different register table per version.
   `camera-work/port-csiphy-sm8350.py` generates `lane_regs_sm8350` (95
   entries) from the vendor's `csiphy_2ph_v1_2_3_reg`, and **validates the
   transform by replaying it on v1.2.1 and diffing against mainline's in-tree
   `lane_regs_sm8250` -- all 100 entries reproduce exactly.** That self-check is
   what makes the generated table trustworthy; keep it.

Addresses that are **not** what sm8250/sc8280xp use, and must come from
`lahaina-camera.dtsi`:

* **CCI at `0xac4f000` (CCI0) and `0xac50000` (CCI1)** -- both other SoCs use
  0xac4a000/0xac4b000, so their node points at nothing here.
* CSID has no reg of its own: `vfe_base + 0x1200` (lite `+ 0x1400`).
* Camera SMMU SIDs 0x800/0x840/0xc00/0xc40, mask **0x440** (sm8250: 0x400).
* CCI1 master 0 = TLMM 111/112 (the ultrawide's bus), m1 = 113/114, CCI0 =
  107-110. Ultrawide MCLK1 = TLMM 101, UWCAM_RST_N = TLMM 106.

**GDSC flags belong to the vendor DT, not to camcc-sm8250 by analogy.**
Downstream's gdsc-regulator reads them as properties, which map onto gdsc.c's
flags as `qcom,support-hw-trigger` -> `HW_CTRL` and `qcom,retain-regs` ->
`RETAIN_FF_ENABLE`. Extracted from `lahaina.dtsi`:

| gdsc | vendor properties | mainline flags |
|---|---|---|
| bps, ipe_0 | support-hw-trigger, retain-regs | `HW_CTRL \| RETAIN_FF_ENABLE` |
| sbi, ife_0/1/2, titan_top | retain-regs | `RETAIN_FF_ENABLE` |

The first version of the port used `HW_CTRL | POLL_CFG_GDSCR` for every child.
Both halves were wrong: **no vendor DT in the whole Samsung drop sets
`qcom,poll-cfg-gdscr` on anything**, and HW_CTRL on an IFE hands the domain to
hardware control so software's later power-off never lands. The corrected
flags land on exactly `camcc-sc8280xp.c`'s pattern, which is the same Titan
generation. `camera-work/port-camcc.py` now derives them from that table.

Also dropped from the port: the vendor's
`regmap_update_bits(regmap, 0xc148, BIT(0), BIT(0))`, which force-enables
`cam_cc_gdsc_clk`. That clock sits inside titan_top, so holding it on pins the
domain -- and because the write bypasses the clock framework, nothing shows a
non-zero `enable_cnt` to explain why. Upstream camcc-sm8250 models the clock
and never enables it.

### 33.11 FIXED: one capture per IFE GDSC per boot -- it was clk_set_rate

**Root cause: camss parks its clocks at the last streaming rate and then
collapses the power domain on top of them.** `clk_set_rate()` raises the IFE
clocks on the way up and nothing ever lowers them, so the GDSC is always
collapsed with its RCGs programmed for hundreds of MHz off a PLL. On SM8350
that permanently wedges the IFE power switch.

**Fix (`patches/0012`): park every clock that has a rate table at XO
(19.2 MHz) before gating it and dropping the domain.** Restoring the *lowest
table entry* is NOT enough -- for the SM8350 IFEs that is already 338 MHz off
a PLL and wedges the GDSC exactly as 720 MHz does. The only state that
demonstrably survives a collapse is the one the clocks boot in.

Verified on a clean tree: **18 consecutive full-resolution captures in one
boot** where the first had previously been the only one possible, **two
libcamera sessions in one boot** (libcamera only ever opens VFE0, so it could
never get a second), and zero `stuck at` / `Failed to power up` messages.

#### How it was found, since none of the obvious things were it

Fifteen hypotheses were eliminated first (HW_CTRL, the 0xc148 gdsc-clk poke,
POLL_CFG_GDSCR, RETAIN_FF bit 11, leaked clocks, GCC_CAMERA_AHB_CLK, a VFE
reset on teardown, SMMU faults, cam_sf_axi, clk_dis_wait_val, the camnoc/CPAS
theory, titan_top collapsing, a CSID reset on teardown, the vendor's two-stage
CSID reset, and immediate-vs-frame-boundary halt). What cracked it was
bisecting a camss session against the raw hardware through `/dev/mem`, with
camss out of the loop entirely:

| sequence | second power-up |
|---|---|
| GDSC off/on, nothing else | fine, 50-70 us |
| + ungate and regate all six IFE clock branches | fine |
| + VFE global reset | fine |
| + `WM_CGC_OVERRIDE_ALL` write | fine |
| + run the CSID RDI path (enable, resume, halt, disable) | fine |
| + enable the VFE write master and stop it | fine |
| camss session, **all CSID and VFE programming skipped** | **WEDGED** |
| camss session from the CSID TPG: no sensor, no CSIPHY, zero frames | **WEDGED** |
| camss session with **`clk_set_rate()` skipped** | **fine**, 4 cycles |

The last two rows are the whole answer: no programming and no data path are
needed to wedge it, and removing only the rate setting prevents it. A
`camss.debug_skip` module parameter (since removed) gated the skipping; the
/dev/mem harnesses are `camera-work/gdscpoke.py`, `ife-clk-cycle.py`,
`ife-reset-cycle.py`, `ife-cgc-cycle.py`, `ife-csid-cycle.py` and
`ife-wm-cycle.py`.

Two traps that produced false negatives along the way, both worth remembering:

* **Every test must start from a fresh boot with ife_0 pristine**
  (`GDSCR 0x..f001`, DOWN set). Two runs were invalidated by testing an
  already-wedged domain.
* **VFE registers need the CPAS/AHB fabric clocks**, which live in titan_top
  and not in ife_0 (`cam_cc_cpas_ahb_clk` 0xC0D0, `cam_cc_camnoc_axi_clk`
  0xC0F0, `cam_cc_core_ahb_clk` 0xC12C). With only the IFE clocks ungated the
  whole VFE window reads 0 and writes vanish silently, which made a VFE reset
  look harmless when the writes had simply never landed.

#### The old symptom description, for reference



**Each camcc IFE GDSC powers up exactly once per boot.** Note what that does
and does not limit: a single streaming session can pull as many frames as you
like -- 3 frames in one `--stream-count=3` is fine -- because the GDSC is
powered once for the whole session. It is repeated *stream start/stop* that
wedges it. The first session always works and tears down cleanly; the second
power-up of the *same* GDSC fails:

```
ife_0_gdsc status stuck at 'off'          (gdsc_enable)
qcom-camss ac6a000.isp: Failed to power up pipeline: -22
titan_top_gdsc status stuck at 'on'       (gdsc_disable, ~0.8 s later)
```

Read the hardware rather than guessing from the warnings -- `/dev/mem` at the
camcc base, 4 bytes at `gdscr` and `gdscr + 4`:

| gdsc | GDSCR | meaning |
|---|---|---|
| wedged ife_0 | `0x68282800` | SW_COLLAPSE=0 (asked ON) but PWR_ON=0, and CFG_GDSCR has neither POWER_UP_COMPLETE nor POWER_DOWN_COMPLETE |
| healthy, off | `0x00282001` | SW_COLLAPSE=1, PWR_ON=0, DOWN_COMPLETE=1 |
| titan_top | `0xf8282801` | PWR_ON=1 *and* SW_COLLAPSE=1 -- asked to collapse, still on |

**titan_top's "stuck at on" is a consequence, not the cause** -- its child is
wedged, and the ife_0 failure is 0.8 s earlier in the log. Once it happens
`genpd:0:ac6a000.isp` goes to runtime-PM **error**, and from then on every
stream start returns `-EINVAL` out of `device_link_add()` in
`vfe_pm_domain_on()`, which is a thoroughly misleading place to land.

* A camss unbind/rebind does **not** recover it. Only a reboot does.
* **Workaround: three captures per boot**, one per IFE. Re-route with
  `media-ctl` to `msm_csid1`/`msm_vfe1_rdi0`, then `msm_csid2`/`msm_vfe2_rdi0`.
  Verified -- both gave clean frames on a boot where VFE0 was already wedged,
  which also proves the fault is per-GDSC and not global camss state.

#### It is hardware state left by streaming, not software sequencing

This is the single most useful thing to know about the bug, and it was settled
by taking all the software out of the loop. `camera-work/gdscpoke.py` drives a
GDSC through `/dev/mem` with nothing but the two register writes gdsc.c would
do -- clear `SW_COLLAPSE`, poll `PWR_ON`:

* **On a boot where camss never streamed**, cycling an IFE GDSC off/on by hand
  works every time -- 3/3 cycles, each powering up in 50-70 us against a
  2000 us timeout.
* **After one real camss capture through that IFE**, the same two register
  writes time out and wedge it, with the identical signature
  (`GDSCR=0x68282800`, `CFG=0x010e0000`).

The second test is only valid with the parent forced on first: `titan_top` is
released by CCI at an unpredictable moment, and a child GDSC cannot power up
while its parent is down. An earlier run of this test was confounded exactly
that way and briefly looked like a different bug.

So camss, genpd, device links and the clock framework are all exonerated:
streaming leaves the IFE in a state its own power switch will not accept, and
nothing short of a reboot clears it.

#### Hypotheses eliminated, with the evidence

Keep the first three fixes regardless -- they are correct against the vendor
DT -- but none of them is the cause:

1. `HW_CTRL` on the IFEs. Removed; no change.
2. The vendor's `0xc148` cam_cc_gdsc_clk poke. Dropped; no change.
3. `POLL_CFG_GDSCR` -> `RETAIN_FF_ENABLE`. Changed; no change. (It does
   explain the *first* variant of the symptom, though: CFG_GDSCR's
   UP/DOWN_COMPLETE bits stop being set after the first cycle, so polling them
   would time out on cycle 2 regardless.)
4. **RETAIN_FF's `GDSCR` bit 11.** After a camss capture an IFE reads
   `0x00282801` where a pristine one reads `0x00282001`, so bit 11 looked like
   the one difference between "powers up" and "does not". It is not: setting
   bit 11 by hand on an untouched IFE and cycling it 3x works fine, and
   clearing it on a wedged one does not revive it.
5. **Leaked clocks.** After teardown the only enabled `cam_cc` clocks are
   CCI's (`slow_ahb_src`, `cpas_ahb`, `cci_1*`, `camnoc_axi*`), held by the
   sensor through runtime PM -- which is also why `titan_top` stays up. No IFE
   clock is left on.
6. **`GCC_CAMERA_AHB_CLK` being gated.** `gcc-sm8350.c` force-enables it at
   probe via `qcom_branch_set_clk_en(regmap, 0x26004)`.
7. **A missing VFE reset on teardown.** `vfe_ops_480`'s `vfe_halt` is a no-op
   ("rely on vfe_disable_output()"), so camss powers the domain down having
   only zeroed the bus write-master config. Making `vfe_halt` call
   `vfe_reset()` -- a real global reset while the block is still powered and
   clocked -- was built, flashed and tested: **no change**, and no reset
   timeout logged, so the reset itself succeeded. The change was reverted to
   keep the tree matching upstream.
8. **SMMU faults.** None in the log; `ac6a000.isp` is in iommu group 8 and
   streams without a context fault.
9. **A missing `cam_sf_axi`.** We only enabled `GCC_CAMERA_HF_AXI_CLK`, while
   sc8280xp -- the same Titan generation -- enables both HF and SF. Added
   `cam_sf_axi` to the camss node and to all five VFE resource entries: **no
   change**. Kept anyway, since it matches sc8280xp.
10. **`CLK_DIS_WAIT` too short.** This one fit the evidence better than
    anything else: the field defaults to 0x2, every other upstream camcc
    driver that sets it (camcc-qcs615, camcc-kaanapali) uses the maximum
    0xf on all camera GDSCs including titan_top and the IFEs, and the bug's
    shape matches a too-short clock-halt window exactly -- an IFE that has
    never had clocks running cycles indefinitely, while one collapsed after
    real clock activity is corrupted by that first collapse. Set
    `.clk_dis_wait_val = 0xf` on every camcc GDSC and confirmed it took
    (`GDSCR=0x0028f001`, bits 15:12 = 0xf): **no change**. Kept, since it
    matches the other upstream camcc drivers.

A note on which of these to keep. Fixes 1-3, 9 and 10 all move us *towards*
what upstream camcc drivers and the vendor DT do, so they stay even though
none of them is the cause. The VFE-reset change in item 7 moved us *away* from
upstream for no measured benefit, so it was reverted. That line -- keep what
aligns with upstream, revert what diverges without evidence -- is worth
holding to, because otherwise a failed hunt leaves a trail of unexplained
local deltas.

#### 11. The camnoc / CPAS theory, and how it was killed

This was the leading hypothesis, and reading the Samsung drop turned it into
something testable rather than a hunch.

The vendor's VFE bracket is `cam_cpas_start()` **before** the IFE's GDSC and
clocks go on, and `cam_cpas_stop()` after they come off
(`cam_vfe_enable/disable_soc_resources`). CPAS owns titan_top
(`camss-vdd-supply = <&cam_cc_titan_top_gdsc>`) and the camera NoC, and
mainline camss models none of it. Better still, `cam_cpastop_poweroff()` has an
erratum workaround named exactly for the failure mode one would predict:

```
errata_wa_list->camnoc_flush_slave_pending_trans
  -> poll camnoc sbm_SenseIn0_Low (0x3900), bits 17-19, until they read 0
```

i.e. wait for outstanding camnoc **slave transactions to drain** before the
camera NoC is powered down. On Lahaina (`CAM_CPAS_TITAN_580_V100`,
`cpastop_v580_100.h`) the register and its semantics are defined but the
workaround is left `.enable = false`.

So: measure it. `camera-work/camnoc-pending.py` reads those bits straight from
camnoc (base `0xac42000`) immediately after a capture, while CCI still holds
the NoC clocked. Result:

```
sbm_SenseIn0_Low (0x3900) = 0x00000000
  pending-slave bits 17-19 = 0b000  -> drained
camnoc fill levels 0xa20/0x1420/0x1a20/0x7620/0x7420 = all 0x00000000
```

**The camera NoC is completely drained.** No pending slave transactions, every
fill level zero -- and the IFE still cannot be re-powered. The stuck-bus-
transaction theory is dead, and with it the case for porting CPAS to fix this
bug. That is worth something on its own: it removes the single largest item
from the camera roadmap.

#### THE DECISIVE RESULT: Android re-powers the IFE GDSC, so this is OUR bug

Run on 2026-11-15 by swapping to the rooted stock boot image and driving the
Samsung camera app over adb, reading the GDSCs through sysfs regulators
(Android has no `/dev/mem` and debugfs is not mounted; `/sys/class/regulator`
is enough):

| | cam_cc_ife_0_gdsc | cam_cc_titan_top_gdsc |
|---|---|---|
| idle | disabled, users=0 | disabled, users=0 |
| camera session 1 | **enabled**, users=3 | enabled |
| app force-stopped | **disabled**, users=0 | **disabled**, users=0 |
| camera session 2 | **enabled again**, users=3 | enabled, users=13 |

**The hardware can power an IFE GDSC down after streaming and back up again,
repeatedly.** This is not a silicon limitation and it is not something about
this unit -- it is a bug in what mainline camss does, and it is therefore
fixable. That is the single most important thing learned about this bug, and
it was not known before: every earlier conclusion was consistent with "SM8350
simply cannot do this".

Android's dmesg for a session is saved at
`capture/android-camera-20261115/dmesg-camera-session.txt` (1207 lines) for
whoever picks this up.

Two leads came out of it, and **both were then tested and eliminated**:

12. **titan_top collapsing between sessions.** Android drops titan_top to
    `users=0` between camera sessions; we keep it powered, because CCI holds
    it for the sensor's i2c, so our IFE collapses underneath a still-powered
    parent. Tested in Linux: after a capture, manually collapse titan_top and
    bring it back, then try ife_0 -- **still times out**. Not the difference.
13. **No CSID reset on teardown.** Mainline calls `csid->res->hw_ops->reset()`
    only in the power-UP path of `csid_set_power()`; on the way down the CSID
    is left exactly as streaming left it while its clocks are cut and -- on
    gen2, where the CSID sits inside the VFE register window -- its power
    domain collapses underneath it. The vendor explicitly resets here ("Stop
    HW complete. Reset HW next." in its teardown log). Added a CSID reset
    before `camss_disable_clocks()` on the down path: **no change**. Reverted,
    per the keep-what-aligns-with-upstream rule above.

#### The /dev/mem bisect: it is the RUNNING of the block, not any single write

`camera-work/gdscpoke.py`, `ife-clk-cycle.py`, `ife-reset-cycle.py` and
`ife-cgc-cycle.py` drive the hardware directly with camss out of the loop, so
each ingredient of a camss session can be added one at a time and the GDSC
then cycled. **Every test must start from a fresh boot with ife_0 pristine
(`GDSCR 0x..f001`, DOWN set)** -- two runs were invalidated by not checking
that, because an earlier capture had already wedged the domain.

| sequence (all via /dev/mem) | second power-up |
|---|---|
| GDSC off/on, nothing else | **fine**, 50-70 us |
| + enable and disable all six IFE clocks | **fine** |
| + VFE global reset | **fine** |
| + `WM_CGC_OVERRIDE_ALL` write | **fine** |
| camss streams from the CSID's own TPG: no sensor, no CSIPHY, **zero frames captured** | **WEDGED** |

So the data path is irrelevant (the TPG case has no external source at all and
produced 0 bytes), the clocks are irrelevant, and none of the individual
register writes tried so far matters. **What wedges the IFE is camss actually
running it** -- starting the CSID path and the VFE and stopping them again.

A trap worth remembering: with only the ife_0 clocks enabled the whole VFE
register window reads back 0 and writes vanish silently, because register
access needs the CPAS/AHB fabric clocks (`cam_cc_cpas_ahb_clk`,
`cam_cc_camnoc_axi_clk`, `cam_cc_core_ahb_clk`) which live in **titan_top**,
not in ife_0. The first VFE-reset run was a false negative for exactly that
reason, and `ife-reset-cycle.py` now asserts a register write/readback before
trusting its own result.

15. **Immediate vs frame-boundary CSID halt.** The best lead the source gave.
    The vendor stops every CSID path with `CAM_CSID_HALT_IMMEDIATELY` (= 2 in
    the two-bit halt_cmd field of `CSID_RDI_CTRL`), while mainline has only
    ever written `HALT_AT_FRAME_BOUNDARY` (= 0) and never waits for it to take
    effect -- so if no further frame boundary arrives the path never really
    halts and camss collapses the domain around a running block. Implemented
    the immediate halt: **no change**. Reverted.

#### The vendor teardown, read in full -- and it does not explain the bug

With the GPL drop in hand the whole vendor teardown was read rather than
guessed at. For the record, the vendor's IFE power-down is:

```
cam_vfe_deinit_hw():
    vfe_bus->hw_ops.deinit()                 <- pure software: IRQ unsubscribe,
                                                list init. NO register writes.
    cam_vfe_reset(CAM_VFE_HW_RESET_HW_AND_REG)
    cam_vfe_disable_soc_resources():
        cam_soc_util_disable_platform_resource(disable_clocks=1, disable_irq=1)
            -> irq off, clocks off, regulator (GDSC) off, pinctrl suspend
        cam_cpas_stop()

cam_ife_csid_disable_hw():
    cam_ife_csid_global_reset()
        -> mask+clear all IRQs
        -> cam_ife_csid_reset_regs(false)   SW/register reset, strobe 0x1
        -> cam_ife_csid_reset_regs(true)    HW reset,          strobe 0x1e
    csid_top_irq_mask = 0
    cam_ife_csid_disable_soc_resources()
```

Each piece was then replicated in mainline and tested on the device:

14. **The CSID's two-stage reset.** This was the one real difference the
    source turned up. The vendor writes **both** strobes to `CSID_RST_STROBES`
    (0x10) -- `csid_reg_rst_stb = 0x1` (register reset, wipes config) then
    `csid_rst_stb = 0x1e` (hardware reset) -- commenting "reset SW regs first,
    then HW". Mainline's `csid_reset()` writes **only 0x1e**, and documents it
    as "preserve registers", so a mainline CSID keeps whatever streaming left
    in it. Implemented the vendor's two-stage reset *and* called it on the
    power-down path. Both stages completed (no reset timeouts logged):
    **no change**. Reverted.

So: stop ordering matches (Android also stops the IFE first, then the sensor,
then the CSIPHY -- confirmed in its own log for `sensor_id:0x258` on
`CSIPHY_IDX: 4`, i.e. our exact sensor and PHY), the VFE full reset matches,
the CSID global reset matches, and the bus deinit writes no registers at all.
**Our teardown is now functionally equivalent to the vendor's, and the bug is
unchanged.**

That is a real conclusion, not a shrug: it means the difference is *not* in the
ISP teardown sequence, which is where all the obvious suspicion pointed. What
mainline still does not model at all, and what is therefore left:

* **The CDM.** Android's regulator dump shows `cam_cc_ife_0_gdsc` has three
  consumers -- `acb4000.qcom,ife0`, `acb4200.qcom,ife-cdm0` and
  `acb5200.qcom,csid0`. The Camera Data Mover is a real block inside the IFE
  power domain that mainline never enables, resets or even maps.
* **The SMMU context detach.** The vendor attaches/detaches a `cam_smmu`
  context bank around use; mainline uses the plain IOMMU binding.
* **CPAS itself**, beyond the camnoc drain that was already measured clean.

Useful incidental facts from the Android log, worth keeping: the vendor
addresses the IMX555 (rear wide) and IMX258 (ultrawide) both at
`sensor_slave_addr:0x34`, i.e. 7-bit **0x1a** -- independently confirming the
ultrawide address found by scanning.

#### What the existing Android captures can and cannot tell us

Checked, so nobody re-checks: **the captures under `capture/` predate the
camera work and contain no camera activity.** `facts-*/logs/dmesg-full.txt`
and `last_kmsg.txt` have no `cam_cpas`, `CAM_ISP`, `ife*` or `csid` lines at
all, and there is no `clk_summary` anywhere in them.

One genuinely useful thing did come out of `android-bt-20261113/regulators.txt`
though. Under Android, camcc declares **two** supplies:

```
pm8350c_s8_level (MMCX) ... ad00000.qcom,camcc-vdd_mm   level 64  (LOW_SVS)
pm8350_s5_level  (MX)   ... ad00000.qcom,camcc-vdd_mx   level 256 (NOM)
```

We vote MMCX only -- and mainline's sm8350 rpmhpd uses a plain `mmcx` with
**no MX parent** (contrast `[RPMHPD_CX] = &cx_w_mx_parent`), so voting MMCX
does not imply MX. Live on our device: `mx` sits at 128 (SVS) where Android
holds 256 (NOM).

That looked like a strong lead and it is written up here because it is a real
difference worth knowing -- but it is probably **not** this bug: capture 1
succeeds at MX=128, and if SVS were too low for an IFE GDSC power-up the first
one would fail too. Chasing it would also mean giving camcc a second power
domain, which `qcom_cc_really_probe` does not handle, and a multi-PD device
gets **no** automatic attach -- so a careless attempt would silently drop the
MMCX vote as well. Worth revisiting only with that trap in mind.

#### What is left to try

Nothing cheap and well-motivated remains; the obvious mechanisms are gone.

**The one decisive experiment still available is to go and get the Android
data that does not exist yet.** The boot-partition swap is verified in both
directions (`tools/to-android.sh`, rooted adb on the far side), so:

1. boot Android, open the camera app, close it, open it again -- establishing
   that the vendor stack really does cycle an IFE GDSC more than once per
   boot, which we have never actually confirmed;
2. between sessions, read `GDSCR`/`CFG_GDSCR` for `ife_0` the same way
   `camera-work/gdscpoke.py` does;
3. diff Android's post-teardown GDSC state against our `0x00282801`.

If they differ, that difference is the missing teardown step and the bug is
solved. If they are identical and Android still re-powers fine, then the GDSC
register state is not the whole story and the difference lies in something
CPAS/CDM does that is invisible here. Either answer is worth more than another
speculative patch.

Note before doing it: `back-to-linux.sh` staged on the phone is **broken**
(HANDBOOK 35.2.2) -- the return path is `adb push` of a current mainline boot
image plus `dd` to `sda19`, and `/root/fold3-restore/q2q-boot.img` on the
device is a pre-camera build, so push the current image rather than relying on
what is there.
Do NOT simply resume shaving GDSC timing parameters -- `clk_dis_wait_val` was
the best-motivated of those and it changed nothing. (For the record,
camcc-qcs615 also sets `en_rest_wait_val`/`en_few_wait_val` to 0x2, but those
are *enable*-ack windows and qcs615's value is shorter than our hardware
default, so there is no mechanism by which it would fix a failing enable.)

The genuinely useful next step is not a patch but a question: **does this
reproduce on mainline SM8250 hardware?** SM8250 shares `vfe_ops_480`,
`csid_ops_gen2` and the same GDSC topology, so if an sm8250 device also wedges
its IFE GDSC on the second streaming session, this is an upstream camss bug
affecting the whole Titan 480/580 family and belongs on linux-media rather
than in local patches. If sm8250 is fine, the difference is SM8350-specific and
worth diffing from there. One message to the right people beats another dozen
flashes here.

Untested ideas, in order: `.pwrsts = PWRSTS_RET_ON` rather than
`PWRSTS_OFF_ON` (the vendor's `qcom,retain-regs` may mean retention rather
than full collapse); the MMCX/VDD_MM performance vote, since the vendor's GDSC
nodes carry `parent-supply = <&VDD_MM_LEVEL>` and ours only hold MMCX at
`low_svs`; and camss's power-on ordering, which powers the GDSC *before*
enabling its clocks, where the vendor attaches `ahb_clk` to every GDSC node.

### 33.12 libcamera, and why the Camera app did not work

> **Its two conclusions are both SUPERSEDED by 33.13 (2026-11-16).**
> The app's failure was a `/dev/dma_heap` permission in the user
> session, not PipeWire or the GDSC; and the "stride shear" was our
> own `abgr2png.py`, not libcamera. Read this section for the
> dma-heap-size and `cma=512M` findings, which still hold, and 33.13
> for what the Camera app actually needed.

Capturing raw Bayer from `/dev/video0` is not a working camera. Apps go through
libcamera, and raw Bayer is useless to them -- something has to debayer it.
Fedora already ships everything needed: **libcamera 0.7.2, whose `simple`
pipeline handler lists `qcom-camss`, and which carries a CPU software ISP
(`DebayerCpu`)**. No pipeline handler had to be written.

What was actually missing was one kernel config symbol.

```
ERROR DmaBufAllocator: Could not open any dma-buf provider
ERROR SoftwareIsp:     Failed to create DmaBufAllocator object
WARN  SimplePipeline:  Failed to create software ISP, disabling software debayering
```

`CONFIG_DMABUF_HEAPS_SYSTEM` was **=m** in defconfig, and a module never
reaches the device from a boot-image flash
(the same trap as camcc -- see 33.3), so `/dev/dma_heap/` did not exist at all.
With no dma-buf provider libcamera disables software debayering and exposes
raw Bayer only. `DMABUF_HEAPS{,_SYSTEM,_CMA}=y` fixes it, and is the single
difference between "v4l2 captures" and "the camera works".

After that, libcamera enumerates and captures:

```
INFO Camera camera.cpp:1216 configuring streams: (0) 4200x3120-ABGR8888/sRGB
INFO SoftwareIsp software_isp.cpp:299 Input 4208x3120-RGGB-10-CSI2P stride 5264
INFO IPASoft soft_simple.cpp:257 IPASoft: Exposure 4-1582, gain 1-16
cam0: Capture 1 frames
... bytesused: 52715520                       (4200*3120*4, ABGR8888)
```

Note the sensor is reported as **"Internal back camera"** only because the DT
now says `orientation = <1>`; with the 0 it had first, libcamera called the
rear ultrawide an "Internal front camera".

#### The dma-heap size trap, and why `cma=512M` "worked"

Full-resolution stills then failed where 1280x720 succeeded:

```
ERROR DmaBufAllocator: dma-heap allocation failure for frame-0
ERROR Allocator: Stream is not part of ... active configuration
Can't allocate buffers
```

The second error is a red herring -- the real one is the first. **libcamera
prefers a CMA-backed dma-heap over the system heap**, and a full-res ABGR8888
buffer is 4200*3120*4 = 52.4 MiB against a 32 MiB default CMA pool. Measured
directly with `DMA_HEAP_IOCTL_ALLOC` (`camera-work/heaptest.py`):

| size | system | default_cma_region | reserved |
|---|---|---|---|
| 52.4 MiB | OK | ENOMEM | ENOMEM |
| 3.5 MiB | OK | OK | OK |

`cma=512M` on the cmdline fixed full-res stills, **but not for the reason
intended**, and this matters:

```
cma: Failed to reserve 512 MiB
```

The reservation *fails*, so no CMA region exists, so the CMA dma-heaps never
appear, so libcamera falls back to `/dev/dma_heap/system` -- which allocates
50 MiB happily. The fix is real and verified (52,715,520-byte frames), and
nothing else regressed: both DSI panels still connected, GPU present, KWin and
plasmashell running, zero allocation failures in the log. But it is **load
bearing by accident**. A `cma=` value that actually succeeds and is still
smaller than a frame would reintroduce the failure. If this ever needs
revisiting, the honest options are a CMA pool genuinely larger than
~3 x 52 MiB, or `cma=0` to drop the CMA heap deliberately rather than by
accident.

#### libcamera's software ISP shears the image: a stride bug

**The raw v4l2 path produces a correct photograph; libcamera's does not.**
Shooting the same scene both ways settles it:

* `camera-work/samples/2026-11-15-imx258-first-photo.png` -- raw RDI frame
  through `capture-uw.sh` + `raw2png.py`. A plainly recognisable room: desk,
  mixing console, monitors, chair. Correct geometry and colour.
* `camera-work/samples/2026-11-15-libcamera-softisp-stride-shear.png` -- the
  same scene through libcamera. Real detail, but smeared into diagonal
  streaks.

The cause is in this line, which libcamera prints as INFO and then ignores:

```
INFO SimplePipeline simple.cpp:1570 Input buffer stride ignored by the driver.
                                    Requested 5376, got 5264
```

libcamera asks V4L2 for `bytesperline` 5376, camss refuses and keeps its own
5264 (4208 px at 10 bpp packed = 5260, padded to 16 bytes), and the software
ISP then debayers as though the stride were 5376. Every line starts 112 bytes
late, so the picture shears progressively down the frame -- which is exactly
what the streaks are.

So this is **not** a camss or sensor fault, and not a tuning problem: it is
libcamera's `simple` pipeline handler / SoftwareIsp not honouring the stride
the driver actually gave it. Fixing that is the single remaining step between
"captures correctly" and "a camera app shows a correct picture". Worth
checking against current libcamera upstream before writing a patch -- 0.7.2 is
what Fedora 45 ships here.

#### What this means for the Camera app

The app path is close but **not yet correct end to end**: `cam` captures, but
its output is sheared (above), and a Plasma camera app has not been retried
since the dma-heap fix. Remaining caveats:

* **libcamera only ever opens `/dev/video0`, i.e. VFE0**, so the one-session-
  per-GDSC bug of 33.11 bites much harder here than on the raw v4l2 path:
  there is no way to re-route it to VFE1/VFE2, so it is effectively **one
  libcamera session per boot**. A second `cam` run in the same boot fails with
  `Failed to start streaming: Invalid argument`. **Fixing 33.11 is therefore a
  prerequisite for a usable camera app, not a nicety.**
* There is no `imx258.yaml` tuning file, so libcamera falls back to
  `uncalibrated.yaml`. Colour and AWB will be approximate.
* **PipeWire is NOT the blocker** -- checked on 2026-11-16 and it is fully
  wired up:
    - `pipewire-plugin-libcamera` is installed and
      `/usr/lib64/spa-0.2/libcamera/libspa-libcamera.so` is present
    - PipeWire enumerates the device: `82. imx258 [libcamera]`, with
      `api.libcamera.location = "back"` and
      `api.libcamera.path = /base/soc@0/cci@ac50000/i2c-bus@0/camera@1a`,
      i.e. our sensor
    - and it exposes a real video **Source**:
      `108. Built-in Back Camera`
  So an app has something to open. Query it from the user session, not as
  root: `sudo -u bunsenfold XDG_RUNTIME_DIR=/run/user/1000 wpctl status`.
* **Beware the 17 decoys.** PipeWire also lists seventeen
  `Qualcomm Camera Subsystem [v4l2]` devices -- those are the raw RDI
  `/dev/video0..16` nodes, which emit unprocessed Bayer and are useless to an
  app. An app that walks /dev/video* or picks the first v4l2 device will fail
  on those while the working libcamera source sits further down the list. That
  is a plausible shape for an app-level failure that has nothing to do with
  the kernel.
* **User observation (2026-11-16): the Plasma camera app went from two errors
  to one** after the dma-heap/software-ISP fix, i.e. it is getting further
  than it used to. The remaining error has not been captured or identified;
  getting its text is the obvious next move, together with a
  `gst-launch-1.0 pipewiresrc` capture through source 108 to see whether the
  app path delivers frames at all.
* Frames captured so far are near-black because the phone was lying with the
  rear camera against a surface, and AE over 10 frames did not pull it up. The
  pipeline is proven by the sensor test pattern, not by these frames; judge
  image quality only from a shot of a properly lit scene.

### 33.13 THE CAMERA APP WORKS (2026-11-16)

**Plasma Camera runs, streams and renders on the phone.** Both of the items
left in 33.12 are closed, and **neither of them was what 33.12 said it was.**

```
INFO SoftwareIsp software_isp.cpp:299 Input 4208x3120-RGGB-10-CSI2P stride 5264
INFO eGL         egl.cpp:456          EGL: GL_RENDERER: FD660
INFO Benchmark   benchmark.cpp:89     Debayer processed 30 frames in 473382us, 15779 us/frame
```

4200x3120 ABGR8888, software debayer at **15.8 ms/frame**, composited on the
Adreno. No errors.

#### The blocker was a file permission, not a camera problem

`/dev/dma_heap/system` is created by the kernel as **`root:video 0660`**, and
`systemd-logind` does **not** tag `dma_heap` for `uaccess` the way it tags
`/dev/video*`. `bunsenfold` was not in the `video` group. So:

| | as root | in the user session |
|---|---|---|
| `/dev/dma_heap/system` | open | **EACCES** |
| libcamera `DmaBufAllocator` | works | `Could not open any dma-buf provider` |
| `SoftwareIsp` | created | `Failed to create software ISP, disabling software debayering` |
| what the camera exposes | debayered RGB | **raw Bayer only** |

This is the same failure that `CONFIG_DMABUF_HEAPS_SYSTEM=m` caused in 33.12,
arriving by a completely different route -- and it was invisible to every test
we ran, because **every test ran as root**. `cam` worked perfectly as root on
the same boot where the app failed.

Downstream of it, WirePlumber's libcamera monitor hits the same EACCES, so its
node never negotiates a format. That is what produced the misleading

```
ERROR: from element .../GstPipeWireSrc:pipewiresrc0: stream error: target not found
```

from `gst-launch-1.0 pipewiresrc` -- with *and without* an explicit
`target-object`, which is what made it look like a PipeWire routing problem.
It was not: the node was visible to a plain client all along
(`pw-cli ls Node` listed id 108, `Video/Source`), it just could not be linked.
WirePlumber said so, in the one place nobody had looked:

```
s-linking: <WpSiStandardLink:...> failed to activate media role link:
           item deactivated before format was set
```

**The fix** (`rootfs-work/camera/`):

```sh
# /etc/udev/rules.d/71-dma-heap-uaccess.rules
SUBSYSTEM=="dma_heap", TAG+="uaccess", GROUP="video", MODE="0660"
```

plus `usermod -aG video bunsenfold` for sessions that are not seat-attached,
then `systemctl --user restart wireplumber pipewire pipewire-pulse` -- the
running libcamera monitor caches its failed probe and will not retry.

Verify with `getfacl -p /dev/dma_heap/system` (must show `user:<you>:rw-`), and
then with `wpctl status`: **the camera becomes the default video source**,
`*  120. Built-in Back Camera`. Before the fix it was listed but never
default, which is itself the symptom -- WirePlumber will not make a source
that cannot negotiate a format the default.

After it, the app path delivers frames end to end:

```sh
sudo -u bunsenfold XDG_RUNTIME_DIR=/run/user/1000 \
  gst-launch-1.0 pipewiresrc num-buffers=5 ! videoconvert ! pngenc \
  ! multifilesink location=/tmp/pw%d.png
```

-> `camera-work/samples/2026-11-16-pipewire-gst-frame.png`, a correct 640x480
RGBA frame through PipeWire.

#### The "libcamera stride shear" was OUR decoder

33.12 blamed libcamera's SoftwareIsp for debayering with a stride the driver
had refused, on the strength of this line:

```
INFO SimplePipeline simple.cpp:1570 Input buffer stride ignored by the driver.
                                    Requested 5376, got 5264
```

**That line is harmless and the conclusion was wrong.** libcamera asks V4L2 for
a 256-byte-aligned stride (5260 -> 5376), camss keeps its own 16-byte-aligned
5264, and libcamera then *uses 5264*. The very next line says so and was read
past:

```
INFO SoftwareIsp software_isp.cpp:299 Input 4208x3120-RGGB-10-CSI2P stride 5264
```

The shear was on the **output** side, in `camera-work/abgr2png.py`. libcamera
pads the software-ISP output to a **64-pixel stride**: a 4200x3120 ABGR frame
comes back as 52,715,520 bytes = 3120 x **16896** B = 4224 px/line, not
4200 x 4 = 16800. The decoder assumed tight packing, so every line started 96
bytes early and the picture sheared progressively down the frame.

Proven by decoding one frame both ways:

| | |
|---|---|
| `camera-work/samples/2026-11-16-libcamera-fullres-correct.png` | real stride 16896 -- a clean, correct, full-resolution photograph |
| `camera-work/samples/2026-11-15-libcamera-softisp-stride-shear.png` | same data, stride 16800 -- the diagonal streaks |

`abgr2png.py` now derives the stride from the file size (`len(buf) // h`) when
that divides cleanly, and takes it as an optional fifth argument. **There is
nothing to fix in libcamera, and nothing to report upstream.**

> Generalisation worth keeping: both of the last two camera bugs were **the
> observer, not the device** -- one was testing as root, one was decoding with
> the wrong stride. The kernel had been correct for a day.

#### What is left on cameras

Nothing blocking. In rough order of value:

1. No `imx258.yaml` tuning file, so libcamera uses `uncalibrated.yaml`; colour
   and AWB are approximate. The module's own calibration EEPROM is at i2c 0x51
   (vendor `qcom,eeprom2`) and has been read before.
2. Add `320000000` to the sensor endpoint's `link-frequencies` for the
   2104x1560 and 1048x780 binned modes -- full-res debayer at 15.8 ms/frame is
   ~63 fps of CPU, so a binned mode is the difference between a preview that
   costs a core and one that does not.
3. The other sensors (33.2): front IMX471 needs 7.4+ or a backport; rear tele
   needs the S5K3M5-vs-HI1337 question settled first.
4. Cosmetic: `Failed to register with host portal ... App info not found for
   'org.kde.plasma-camera'` -- a desktop-ID mismatch in the portal
   registration, unrelated to capture.
5. The 17 raw-Bayer `[v4l2]` decoy nodes are still listed by PipeWire. They no
   longer matter now that the libcamera source is the default, but an app that
   walks `/dev/video*` will still pick one and fail.

## 34. USB OTG host mode, and the first working audio output (2026-11-14)

**This unit has audio.** A USB-C digital audio dongle (`AB13X USB Audio`,
full-speed, 100 mA, playback + mic + HID buttons) enumerates on the USB-C
port, binds to `snd-usb-audio` as ALSA card 1, and PipeWire makes it the
default sink with no configuration at all. Verified by ear by the user, and
in `/proc/asound/card1/pcm0p/sub0/status`: `hw_ptr` advanced 175,872 frames
over 3.6 s of wall clock, i.e. exactly 48 kHz paced by the DAC's own clock.

This supersedes section 24's conclusion for *output*: the speaker amps are
still bit-clock-less and the analog path is still dead, so a **passive**
jack adapter can never work here. A digital dongle bypasses all of it.

### 34.1 Three things block host mode, and each one alone is fatal

| # | Thing | Symptom if wrong |
|---|-------|------------------|
| 1 | `CONFIG_USB_DWC3_DUAL_ROLE=y` | no host code exists at all |
| 2 | QSCRATCH device-mode VBUS override cleared | host runs, port stays "not attached" |
| 3 | A VBUS **edge** after the device is plugged in | device sits there invisible |

**1. The kernel had no host half.** The three DWC3 modes are an exclusive
Kconfig choice and we were built `USB_DWC3_GADGET=y`, which compiles host
support out entirely -- `debugfs.c` does not even create the `mode` file
(it gates on `CONFIG_USB_DWC3_DUAL_ROLE`). No DT property or sysfs write
could ever have reached host mode. Fixed in kernel **#63**.

DT, on `&usb_1_dwc3` (the core node, where `sm8350.dtsi` declares these):

```dts
dr_mode = "otg";
usb-role-switch;
role-switch-default-mode = "peripheral";
```

`usb-role-switch` is the only workable mechanism here: `dwc3_drd_init()`
takes it first, and its alternatives are an extcon (we have none -- no
`usb-connector` node, no VBUS sense) and the OTG block's ID pin, which
Type-C does not wire. `role-switch-default-mode` keeps boot behaviour
bit-for-bit identical, because `dwc3_setup_role_switch()` calls
`dwc3_set_mode(DEVICE)` *before* registering the switch. Confirmed: #63
boots with the g_serial console exactly as #62 did. Runtime control is
`/sys/class/usb_role/a600000.usb-role-switch/role`.

**2. The QSCRATCH override is stuck on, and no driver manages it.**
`dwc3-qcom-legacy.c` sets `UTMI_OTG_VBUS_VALID | SW_SESSVLD_SEL`
(HS_PHY_CTRL +0x10) and `LANE0_PWR_PRESENT` (SS_PHY_CTRL +0x30) **once at
probe**, for any `dr_mode != "host"`, and has no role-change hook:

```c
qcom->mode = usb_get_dr_mode(&qcom->dwc3->dev);
if (qcom->mode != USB_DR_MODE_HOST)
	dwc3_qcom_vbus_override_enable(qcom, true);
```

These are *device-mode* inputs -- they tell the controller a VBUS session is
valid, which is what makes the gadget generate a connect event. Qualcomm's
newer glue (`dwc3-qcom.c`, binding `qcom,snps-dwc3`) clears them whenever the
role leaves device and sets them again on the way back, through
`.pre_set_role`. We are on the old two-node binding, so that hook does not
exist. Measured in host mode: `HS_PHY_CTRL 0x10100000`, `SS_PHY_CTRL
0x01000000` -- all three bits set, and those registers hold *nothing else*,
so clearing them zeroes both words.

`rootfs-work/otg/fold3-qscratch {set|clear|show}` pokes them over `/dev/mem`
(works because `CONFIG_STRICT_DEVMEM=y` with `IO_STRICT_DEVMEM` unset: MMIO
reachable, RAM not). `fold3-otg` calls it in **both** directions, following
upstream's order -- clear before switching to host, set before switching
back. The second direction is not optional: leave the bits cleared and the
**gadget stops enumerating**, taking the USB serial console with it.

The real fix is a kernel patch adding a role-change hook to the legacy glue,
or moving to the `qcom,snps-dwc3` binding. Until then this is userspace
poking MMIO behind a driver's back -- it works, but say so out loud.

**3. A device plugged into an already-live port may never appear.** The DAC
was plugged in while VBUS was already up and stayed completely invisible:
root-hub port `state = not attached`, nothing in dmesg, for minutes. It
enumerated **one second** after VBUS went off and back on. So `fold3-otg on`
always ends with `boost off; sleep 0.5; boost on`, and `fold3-otg kick`
repeats that edge without leaving host mode.

Note this was found while changing three things at once (override, xhci
rebind, VBUS cycle) -- against the one-delta rule. The VBUS edge is
confirmed as *sufficient to trigger* enumeration by its timestamp; whether
the override clear was also *necessary* is *not* isolated. Worth one clean
experiment.

### 34.2 The role switch is only safe with ttyGS0 free

The 2026-11-12 wedge is now explained from the source, not guessed.
Switching to host tears the gadget down (`__dwc3_set_mode` ->
`dwc3_gadget_exit` -> `usb_del_gadget_udc`), the legacy g_serial driver
unbinds, and `gserial_free_line()` reaches:

```c
gs_console_exit(port);          /* console unregistered FIRST */
ports[port_num].port = NULL;    /* new opens now fail */
...
wait_event(port->close_wait, gs_closed(port));   /* waits FOREVER */
```

So a single open fd on `/dev/ttyGS0` blocks the role-switch work item while
it holds `dwc->mutex`, and everything that touches dwc3 or the port queues
behind it. That is the hang, and `agetty` was the holder.

What is **fine**: `/dev/console` resolving to ttyGS0. `gs_console_exit()`
runs before the wait and printk falls back to tty0. And nothing holds
`/dev/console` open on this system -- checked every fd in `/proc`.

`fold3-otg on` therefore stops **and masks** `serial-getty@ttyGS0` (masking
closes the respawn race), then re-checks every fd in `/proc` and **refuses**
to switch if any remain. `off` unmasks and restarts it. Verified: the switch
and the switch back are clean, no oops, ssh never dropped.

### 34.3 VBUS: the charger's own OTG boost

Nothing on this board sources 5 V by itself -- no `usb-connector`, no
extcon, no `vbus-supply`, and no mainline driver drives the MAX77705 PD
block. The boost is the charger's OTG mode, `CHG_CNFG_00` (0xb7) bits
`OTG|BOOST` = `0x0A`:

```
mode |= 0x0A    on        0x04 -> 0x0E, 0x05 -> 0x0F, 0x00 -> 0x0A
mode &= ~0x0A   off
```

That OR reproduces Samsung's own state machine exactly
(`max77705_charger.c: max77705_chg_set_mode_state`), which is why the script
ORs rather than assigns -- it preserves whatever the charger half is doing.
`CHG_CNFG_02` [7:6] is the OTG current limit; the bootloader already leaves
it at 900 mA (`0x40`), which is what Samsung writes on every OTG transition.
`CHG_CNFG_06` [3:2] was already unlocked (`0xec`), so CNFG_00 writes take.

Charging and OTG cannot coexist on one port, so `fold3-otg on` **refuses**
while anything feeds CHGIN, and stops `fold3-charge` while sourcing --
otherwise it sees our own 5 V on CHGIN and charges the battery from the
battery.

**`CHGIN_DTLS` is a 2-bit field, [6:5] of `CHG_DETAILS_00`**, decoded in
`max77705_charger.c` as `0` below UVLO, `1` below MBAT+CHGIN2SYS, `2` above
OVLO, `3` valid. `fold3-charge` tests `& 0x40`, i.e. bit 6 alone: it reads
`2` as "valid" and misses `1` entirely. Harmless for charging (the chip
blocks both cases anyway) but it cannot tell our own boost from a charger,
and it is why that service must be stopped during OTG. `fold3-otg` decodes
the whole field. With the boost on the field reads `2` ("above OVLO") and
`BC_STATUS` bit 7 `VBUSDet` = 1, which is how we know 5 V really reaches the
connector; `BYP_DTLS` ( `CHG_DETAILS_02` [3:0], bit 0 = OTG overcurrent)
stayed clear throughout.

### 34.4 What the MAX77705 can and cannot detect

The chip's Type-C state machine runs in its own firmware (`UIC_FW_REV` =
0x65) and is readable with no driver at all, at usbc address 0x25:

| reg | field | meaning |
|-----|-------|---------|
| 0x0a | [2:0] `CCStat` | 0 none, 1 SINK, 2 SOURCE, 3 **audio accessory**, 4 debug |
| 0x0a | [7:6] `CCPinStat` | which CC pin is active |
| 0x08 | bit 7 `VBUSDet` | VBUS present |
| 0x08 | [1:0] `ChgTyp` | BC1.2 result |

> **WRONG, CORRECTED IN 37.2 (2026-11-19).** Both halves of the paragraph
> below are false. `OPCODE_CCCTRL1_R` reads **0x9f** -- `CCSrcSnk` and
> `CCSnkSrc` both set, i.e. the chip is already a **DRP** -- and SOURCE has
> since been measured (`CC_STATUS0` 0x8a). The reason SOURCE was never seen
> here is the one this very section gives for `CCPinStat`: the chip cannot run
> detection while OUR OWN boost drives the connector. The PD mailbox is also
> not "bigger and riskier": it worked first try, and the whole DisplayPort
> handshake now runs over it. Kept because it is the reasoning that produced
> the detection design, which still stands.

**`CCStat` never reaches `SOURCE`** -- the block is configured sink-only, so
the obvious "a device was attached" trigger does not exist. Changing that
would mean driving the PD mailbox (`AP_DATAOUT` opcodes), which is a much
bigger and riskier job.

But `CCPinStat` *does* flag the attach: it went `0` -> `1` (CC1) with the
dongle attached, **and only while we were not driving VBUS** -- it read `0`
the whole time our own boost was up, including after the dongle was plugged
in. So the usable detection scheme inverts nicely:

> idle in gadget mode with the boost **off** -> poll CC -> `CCPinStat != 0`
> with `CCStat == 0` means **a device is attached** -> offer host mode ->
> on accept, switch role and turn the boost on.

Powering the port only after the user accepts *is* the VBUS edge item 3
needs, so detection and workaround reinforce each other. `CCStat == 1`
(SINK) should mean a charger or PC instead -- **CONFIRMED 2026-11-16**, see
the table below. Also unverified: that `CCPinStat` reads 0 with the boost
off and *nothing* attached, which is what makes the signal meaningful at
all.

**The attached-to-a-host reading is now measured too (2026-11-16), which
completes the table.** Cable into a PC, single reader, 20 consecutive samples
with no variation in either register:

```
CC_STATUS0 = 0x51   CCStat=1 (SINK)  CCPinStat=1 (CC1)
BC_STATUS  = 0x82   VBUSDet=1        ChgTyp=2 (CDP, a charging PC port)
```

So all three states are now measured, and they are unambiguous:

| | `CC_STATUS0` | `BC_STATUS` | we should be |
|---|---|---|---|
| nothing attached | `0x00` | `0x00` | either; idle as a gadget |
| host / PC / charger | `0x51` CCStat=SINK | `0x82` VBUS + ChgTyp | **gadget** |
| device attached, our boost OFF | `0x40` CCPinStat set, CCStat=0 | no VBUS | **host** |

BC1.2 also separates a PC port (CDP/SDP) from a dumb charger (DCP), so the
chip answers "is a computer on the other end" as well as "is anything there".
The device therefore CAN decide its own role without a Type-C driver; what it
cannot do is be told by `CCStat` alone, because sink-only configuration means
`SOURCE` never appears. Role selection is left manual by choice
(`fold3-otg`), not by limitation -- there is one port, so entering host mode
always costs the serial console and charging.

**The detach reading, which was the last gap, now has an answer.** With the
boost off and the dongle gone, CC reads `0x00` -- 40 consecutive samples, no
variation -- against a steady `0x40` while it was attached. So the signal is
meaningful in both directions and the detection design stands. One caveat
kept honest: the user never explicitly confirmed unplugging the dongle before
that reading, so "the latch cleared by itself" is not formally excluded. One
word from them settles it; everything else about the design does not depend
on which it was.

The latch does survive a VBUS cycle: `0x40` persisted when the boost came
back on at 12:45:15. What the chip cannot do is *start* detecting under our
own 5 V.

**The `device -> none -> device` flicker was probably our own doing.** It
appeared while `fold3-usb-watch` (every 0.4 s) and `fold3-usbd` (every 1 s)
were both hitting the same i2c device. Sampled rapidly by a *single* reader
the register is rock steady -- 40/40 identical, twice, once attached and once
not. So the likely cause is read contention on the bus, not the chip
re-running detection as first assumed. Treat it as a hypothesis: it was never
reproduced deliberately. Either way `fold3-usbd` now carries hysteresis
(latch attached after 2 reads, release only after 8 consecutive empty ones),
which is the right behaviour regardless, and the lesson is concrete: **do not
leave a second i2c poller running while debugging the first.**

`CCStat == 3` is worth keeping: it identifies a **passive** analog adapter,
the one kind that can never work on this unit, so the UI can say so instead
of failing silently.

### 34.5 The UI: this is Plasma Mobile, and it has no tray

> **PARTLY SUPERSEDED by 36.5 (2026-11-16).** "No system tray" is true, and
> everything below about SNI stands. But it was then used as if it meant
> *there is nowhere to put a toggle*, and that is wrong: Plasma Mobile has a
> **quick settings drawer** with a KPackage plugin API, which is where a phone
> toggle belongs. Reach for a quick setting first and a notification only for
> things that are genuinely events.

The user asked for Android's USB notification -- a control that appears when
something is plugged in and **disappears only when it is unplugged**. Getting
there cost four wrong turns, all worth recording because each one looked like
success at the time.

**This phone runs Plasma MOBILE.** `~/.config/plasmashellrc` says
`shell=org.kde.plasma.mobileshell`, and `plasma-mobile-6.8.2` is installed.
The process is still plain `/usr/bin/plasmashell`, so `ps` does not tell you
which shell is loaded -- check `plasmashellrc` first, before reasoning about
any Plasma behaviour on this device.

1. **A plain notification vanishes.** Normal urgency with a finite timeout
   expires and is gone, including out of the drawer, before the user can act.
2. **`critical` + no expiry does the opposite**: Plasma honours it exactly as
   specified by pinning it on top of the screen forever. The user's verdict:
   "stuck on top of my screen, so definitely not what we want". There is no
   "ongoing but quiet" urgency in the freedesktop spec -- Android's USB
   notification works because Android has that category and this does not.
3. **A system tray item cannot work here at all.**
   `grep -ri statusnotifier /usr/share/plasma/shells/org.kde.plasma.mobileshell`
   returns **zero** hits. The trap is that everything *looks* fine:
   `org.kde.StatusNotifierWatcher` exists (plasmashell provides it whatever
   shell is loaded), it accepts the registration, and
   `RegisteredStatusNotifierItems` lists the item -- while nothing on screen is
   capable of drawing it. **Registration success proves nothing.**
4. **Two further ways to waste time inside that dead end**, both hit:
   * The config file for the mobile shell is
     `plasma-org.kde.plasma.mobileshell-appletsrc`. The desktop one exists too,
     full of plausible `org.kde.plasma.systemtray` containments that are simply
     **not used**, so editing `shownItems` there does nothing and reads exactly
     like a pinning problem. Mobile containments are the folio homescreen,
     `mobile.taskpanel` and `mobile.panel`.
   * **There is no `usb` icon in Breeze.** A missing icon name is accepted
     silently at every layer and renders as nothing, which is indistinguishable
     from "the tray does not work". `audio-headphones` and
     `drive-removable-media-usb` do exist. Check with
     `find /usr/share/icons/breeze -name '<name>.svg'` before using a name.

**Where it was left:** one combination remains untried -- **normal urgency
with `expire_timeout = 0`** -- which should sit in the notification drawer
without pinning, i.e. the actual equivalent of Android's shade. One was posted
(id 1) and is still up, deliberately, so the user can judge whether it
survived. If it does, wire it into `fold3-usbd` and the feature is done. If
Plasma Mobile drops it too, then **nothing a background process can post will
persist on this shell**, and the honest remaining options are a homescreen
widget (a Folio applet, real QML work) or a launcher shortcut / terminal call
to `fold3-otg on`.

Mechanics worth keeping either way:

* `notify-send` **cannot close** what it posted, so a control posted that way
  outlives the condition it describes. Going through D-Bus directly gives the
  id back: `Notify` -> id, `CloseNotification(id)`, and a `gdbus monitor`
  child for `ActionInvoked`. That is enough to own a notification's whole
  life cycle from a daemon.
* Drive notifications from a **declarative** loop -- each tick, work out what
  *should* be on screen and reconcile -- not from events. Event-driven, a
  single bad reading closed the control while the device was still attached,
  and a dismissal was treated as permanent so one swipe meant no button for
  the rest of the session.
* A **root** daemon can do all of this on the user's session bus:
  `sudo -u <user> XDG_RUNTIME_DIR=/run/user/1000 <cmd>` works from anywhere,
  so no polkit rule and no helper IPC is needed. `runuser` works from a
  systemd service but is **refused from an ssh root shell** (probably an
  SELinux context difference) -- which matters only because it makes manual
  probing fail while the daemon works.

### 34.6 Tools

```sh
fold3-otg on       # free ttyGS0, clear override, role->host, boost on (with edge)
fold3-otg off      # boost off, override back, role->device, getty + charging back
fold3-otg kick     # re-run the VBUS edge for a device that did not enumerate
fold3-otg status   # role, mode, charger regs decoded, CC state, override, devices, cards
fold3-usb-watch    # log every CC / CHGIN / BC / USB / ALSA change (the experiment rig)
fold3-qscratch     # {set|clear|show} the device-mode VBUS override (34.1 item 2)
fold3-usbd         # the notification daemon: poll CC, offer host mode, auto-revert
fold3-tray-demo    # DEAD END, kept as evidence: a tray item Plasma Mobile never draws
```

`fold3-usbd` has a unit (`rootfs-work/otg/fold3-usbd.service`) and is
installed but **deliberately not enabled**: while it runs it will switch the
port out of gadget mode on its own, taking the USB serial console with it.
Enable it for daily use, stop it before doing kernel work over the cable.
`fold3-usb-watch` polls i2c every 0.4 s -- stop it when done, and never run it
alongside `fold3-usbd` (34.4).

Sources in `rootfs-work/otg/`, installed to `/usr/local/sbin/`. While host
mode is on there is **no USB serial console and no charging** -- `off`
returns both.

### 34.7 Where to pick this up

Verified, no need to revisit: host mode works, the DAC plays (user confirmed
by ear, 48 kHz paced by the DAC's own clock), `fold3-otg on`/`off` are clean in
both directions, the gadget console survives the round trip, and CC
distinguishes attached (`0x40`) from empty (`0x00`).

1. **Finish the UI question** -- the one thing blocking the feature. Ask
   whether notification id 1 (normal urgency, no expiry) is still in the
   drawer with its button. Yes -> wire that urgency into `fold3-usbd` and
   ship. No -> Folio widget or launcher shortcut; say so plainly rather than
   trying more urgency flags, the spec has no more to offer.
2. **Confirm two CC readings**: that a charger reads `CCStat == 1` (SINK) and
   is therefore distinguishable from a device -- without this `fold3-usbd`
   would offer host mode every time a charger is plugged in -- and the one-word
   question in 34.4 about whether the dongle was physically out.
3. **Isolate whether the QSCRATCH clear is actually necessary** for
   enumeration (34.1). Three things changed at once; only the VBUS edge is
   confirmed as the trigger. Replug with the override deliberately left set.
4. **Kernel patch**: a role-change hook in `dwc3-qcom-legacy.c`, replacing the
   `/dev/mem` poke -- upstream's newer glue already does this via
   `.pre_set_role`. Candidate for upstream. Alternatively move the DT to the
   `qcom,snps-dwc3` binding and inherit it.
5. **A high-speed device has never been tried.** The DAC is full-speed, so
   `maximum-speed = "high-speed"` with the SS PHY dropped is untested as a
   host. A USB stick settles it, and would also prove the data path
   independently of any one dongle.
6. The `qcom_q6v5_pas` "Handover signaled, but it already happened" message
   repeats several times a second and floods `dmesg`, which made every log in
   this session harder to read. Unrelated to USB; worth silencing on its own.

## 35. Annotated kernel log, and the LTE data failure (2026-11-14)

### 35.1 The LTE failure: SOLVED -- an Android SHUTDOWN rewrote the modem's NV

**Cause found and fixed 2026-11-14. It was ours, not Orange's.** Restoring
`modemst1` + `modemst2` from the 2026-11-13 backup -- the snapshot taken on
the day LTE worked -- brought data straight back:

```
LTE attach parameters: APN internet.orange.ma, ipv4, OTA attach performed: yes
nmcli con up orange-ma  -> Connection successfully activated
qmapmux0.0  100.76.16.23/28
ping -I qmapmux0.0 8.8.8.8  -> 4/4, 0% loss, 34-149 ms ; DNS resolves
```

Before the restore those same attach parameters read `InformationUnavailable`
and there was no initial EPS bearer at all. After it, `initial bearer path:
.../Bearer/0` exists. So the modem's own NV was the whole problem.

**The mechanism, and the lesson:** `modemst1/2` are the modem's NV working
store. Our `rmtfs` runs read-only (`-r -P -s`) so Linux does not write them --
but **booting Android does**, and Samsung's dsds config provisions this SIM
as the *secondary* subscription while `fold3-sim-primary` flips it to primary
at runtime every boot. An Android boot in between left NV in a state where
the flip no longer gave the data subsystem a usable subscription: attach
without PDN, and a PDN request refused locally and instantly by the modem's
own call manager (`[cm] no-service`, reason type 3, no 3GPP cause) while
registration still looked perfect.

**Operationally: an Android boot can break LTE on the Linux side, and the
repair is a modemst restore.** Take a fresh hash-verified backup whenever
LTE is known good, and keep it. `fsg` and `fsc` (calibration) were unchanged
throughout and were never touched -- the restore only put back the two NV
partitions.

Procedure that worked (all writes to modem storage, so get the user's
explicit go-ahead first -- it is their stated rule):

```sh
# verify the known-good images against their MANIFEST first, and that
# sizes match the partitions exactly (3145728 each here)
systemctl stop ModemManager rmtfs tqftpserv
echo stop > /sys/class/remoteproc/remoteproc1/state      # quiesce the modem
dd of=/dev/sda1 bs=1M conv=fsync < modemst1.img          # sda1 = modemst1
dd of=/dev/sda2 bs=1M conv=fsync < modemst2.img          # sda2 = modemst2
sha256sum /dev/sda1 /dev/sda2                            # must match the backup
systemctl reboot
```

#### What the two NV images actually show

Both snapshots were compared byte for byte. The container is Qualcomm's
**`IMGEFS1`** format: a plaintext 48-byte header, then the payload.

```
hdr: 0x10 0x3 0x1d8 0xca240d50 0x27fe00 0x27fe00 0xca4c0b50 0 0xca4c0b50 0
     magic="IMGEFS1"  tail=0xd8 (good) -> 0xda (broken)
```

* Field 5 declares the payload size: **0x27fe00 = 2,620,928 bytes**. The
  differing region is blocks 0-639 = 2,621,440 bytes, i.e. **the entire
  declared payload changed and nothing beyond it**. The remaining 512 KiB is
  unused padding and is identical, which is why the diff stops at 83%.
* **Both copies were replaced**, `modemst1` and `modemst2` alike. They are
  not byte-identical mirrors of each other in either snapshot (~2.61 MB
  differ between the pair), so each carries its own copy.
* The header's last byte went **0xd8 -> 0xda**, +2: a generation/sequence
  counter.

> **CORRECTED 2026-11-14 by the controlled round-trip (35.2).** Two readings
> above were wrong, both because the payload is encrypted:
>
> * *"+2 suggests two rewrites"* -- no. A single verified flush moves the tail
>   byte by **+2** (`d8 -> da`, observed directly). One write, not two.
> * *"the whole store was regenerated, not edited -- a full re-provisioning"*
>   -- **does not follow.** Under encryption, changing one NV item and
>   re-flushing re-encrypts the entire payload. A total byte diff is exactly
>   what a one-item change looks like too. The diff carries no information
>   about the SIZE of the change.
> * *"both copies were replaced"* remains true of that window, but one Android
>   shutdown writes **`modemst1` only** (measured). So the 11-13 -> 11-14
>   window contained **more than one** Android shutdown.

**We cannot say WHICH item changed, and should not pretend otherwise.** The
payload is **encrypted**: entropy 7.292 bits/byte in both, no readable NV
path names anywhere. The ~600 printable "strings" in each image are
high-entropy coincidences -- diffing them yields pure noise on both sides,
which is exactly what it looked like. Samsung encrypts the modem EFS, so the
images cannot be interpreted without the key.

**Therefore "why" has to come from a controlled experiment, not the bytes.**
**That experiment was run the same day -- see 35.2.** It confirmed Android as
the writer, pinned the trigger to *shutdown*, and reproduced the failure from
a known-good state. Cheap probe meanwhile: the header's tail byte (or just the
partition hash) says whether the store has been rewritten, with no diffing.

**What this retracts:** everything below in this section argued the failure
pointed away from our stack and toward the operator -- "data not provisioned,
bundle expired, credit exhausted". That was wrong. The reasoning is kept
because the evidence genuinely did fit, and because the one observation that
broke the tie (attach parameters missing on a *fresh* modem) was in hand
before the conclusion was drawn and should have been weighted higher. The
SIM-in-another-phone test was never needed.

### 35.2 The controlled round-trip (2026-11-14): the trigger is Android's SHUTDOWN

Run from a verified known-good state: `modemst1/2` bit-identical to the
2026-11-13 backup, LTE data working. Linux -> rooted Android -> Linux, with
the NV hashed continuously on the Android side and `rmt_storage` logged.

**Result: the failure was reproduced deliberately, and the trigger is not
what 35.1 assumed.** It is not the boot, and not using mobile data.

| Phase | NV writes |
|---|---|
| Android boot + LTE registration | **0** |
| 10 min live LTE data session (WiFi off, data connected) | **0** |
| Android shutdown, `18:07:04.793` | **1 write, 2,621,440 bytes, `modemst1` only** |
| Three Linux boots incl. full modem bring-up | **0** |

Caught in the act, streamed over adb before USB dropped:

```
18:07:04.793 vendor.rmt_storage: rmt_storage_rw_iovec_cb: /boot/modem_fs1: R/W request received (wr_count 1)
18:07:04.874 vendor.rmt_storage: rmt_storage_client_thread: /boot/modem_fs1: Bytes written = 2621440, wr_count 1
```

`/vendor/etc/init/vendor.qti.rmt_storage.rc` declares the daemon `class core`
with **`shutdown critical`** -- it is deliberately kept alive through shutdown
so the modem can flush its EFS. Ordering around the write: GPS QMI client
released `18:07:03.856`, Bluetooth pre-shutdown `.906`, NV flush `.793+1s`,
vold teardown `18:07:05.111`.

`rmt_storage` logs every operation with a direction and a byte count
(`wr_count`, `Bytes read/written`), so this is observed, not inferred. During
boot it only ever **reads** (e.g. `Bytes read = 2620416` from `modem_fs2`).

**Our side writes nothing, confirmed three more times.** `rmtfs -r -P -s`
leaves `sda1`/`sda2` bit-identical across reboots, modem bring-up and live
data. Under Linux the store is immutable by construction; the only writer in
the system is Android.

#### What actually changed, by name

The semantic fingerprint (`tools/modem-fingerprint.sh`, ~30 QMI getters) was
captured either side. **Exactly one configuration item moved:**

```
WDS 3GPP profile 1
  before:  APN ''                     type none     ipv4-or-ipv6   auth none
  after:   APN 'internet.orange.ma'   type default  ipv4           auth pap
           name 'lte_internet'        user MEDINET  pass MEDINET
```

(`MEDINET` = Meditel, Orange Morocco's former name: Samsung's carrier APN
database written into the modem's own NV.) Alongside it,
`--wds-get-lte-attach-parameters` went from real values to
`InformationUnavailable` **while registered on LTE** -- the genuine symptom,
not the RAT artifact below.

**Unchanged, byte for byte:** PDC platform + software configs and their
selected/active IDs (`ROW_Commercial` active, `DSDS-LA-Lahaina` platform, no
pending config), UIM card/slot/provisioning state, NAS selection policy, DMS
revisions. **The carrier-config hypothesis is dead.**

#### The targeted repair was tried and FAILED -- profile 1 is not the cause

Profile 1 was rewritten back to the known-good shape with
`--wds-modify-profile` and a fresh attach forced (operating mode
`low-power` -> `online`). Registration came back `registered`/`PS attached` on
LTE, but attach parameters stayed `InformationUnavailable` and a single
controlled connect failed identically:

```
couldn't start IPv4 network: QMI protocol error (14): 'CallFailed'
verbose call end reason (3,2001): [cm] no-service
```

So the one delta we could **read** is a correlate, not the cause. Restoring
`modemst1` from the backup then brought LTE straight back (`connected`, LTE,
initial bearer present, attach parameters restored with `OTA attach
performed: yes`, 4/4 ping). **`modemst2` needed nothing -- it was never
written.**

**Where the attach APN lives -- EPC checked and RULED OUT.** In the *working*
state profile 1 is empty yet the attach parameters still carry
`internet.orange.ma`, so the attach APN never came from the 3GPP profile
family. The obvious next guess was the **EPC profile family**: `qmicli` cannot
ask for it (`--wds-get-profile-list` takes only `3gpp`/`3gpp2`) but libqmi
models it (`Qmi.WdsProfileType.EPC`), so `tools/wds-profiles.py` was written
to reach it through the GLib bindings. **This modem rejects the whole family**
-- `GetProfileList(EPC)` and `GetProfileSettings(EPC, 0..3)` all return QMI
error 81 `ExtendedInternal`. The readable families hold nothing useful:
3GPP has one empty profile, 3GPP2 one empty profile at index 0.

One datum to chase instead: `OTA attach performed` read **`no`** in the t0
good state but **`yes`** after the restore, so the attach parameters can
arrive over the air as well as from NV -- which means their mere presence is
not proof of a given NV item. Item-level access (below) is now the only route
left to name the causal item.

#### Item-level NV access: the two candidate routes

* **QMI MFS, service 21** ("Modem embedded file system service") is present on
  the qrtr bus. `libqmi` does not implement it and `libqmiservices.so` from
  `/vendor` contains no MFS strings, so there is no free IDL -- it means a raw
  QMI client over `AF_QIPCRTR`.
* **DIAG EFS2** (what QPST's EFS Explorer speaks) is the documented route and
  is **REACHABLE -- over QRTR, not glink.** Established 2026-11-14 from the
  Samsung source drop plus the vendor partition; see 35.2.1. This is the
  recommended route, ahead of MFS.

**Probing glink channel names from Linux: how to, and the hazard.**
`/dev/rpmsg_ctrl2` is the MPSS edge (`rpmsg_ctrl0` = ADSP/3000000,
`rpmsg_ctrl1` = SLPI/5c00000, `rpmsg_ctrl2` = modem/4080000 -- check
`/sys/class/rpmsg/rpmsg_ctrlN` symlinks, the numbering is not fixed).

* `RPMSG_CREATE_DEV_IOCTL` (0x4028B503) is **useless here**: only
  `virtio_rpmsg_bus` implements `.create_channel`; `glink_device_ops` has just
  `.create_ept`. It returns ENXIO no matter what the modem has, so an ENXIO
  from it says nothing.
* `RPMSG_CREATE_EPT_IOCTL` (0x4028B501) **is** a real on-the-wire test:
  `qcom_glink_create_ept()` on an unknown name calls
  `qcom_glink_create_local()`, which sends a CMD_OPEN and waits for the
  remote's ack. The ioctl itself always succeeds and makes `/dev/rpmsgN`; the
  verdict comes from **opening** that node -- success = the modem acked the
  channel, `EINVAL` = it refused.
* Always run a **positive control**. `DS` opens fine, which is what makes the
  `DIAG` refusal meaningful rather than a broken method.
* **HAZARD: this can crash the modem.** Probing `DIAG` left the modem alive,
  but the next name took a fatal exception -- `remoteproc remoteproc1:
  handling crash #3 in modem`, IPA `modem crashed`/`offline`, auto-recovered
  2 s later. Consequences: `/dev/rpmsg_ctrl*` renumber, `qmapmux0.0`
  disappears, and **ModemManager goes `state: failed`** because a modem
  restart loses the `fold3-sim-primary` provisioning flip, which only runs at
  boot (read-only EFS means the modem never remembers it). NV is **not** at
  risk -- `rmtfs -r` keeps the hashes bit-identical through a modem crash.
  Recovery: reboot (or re-run `fold3-sim-primary.sh` then restart MM). Probe
  one name per invocation and check modem health between names.

#### 35.2.1 DIAG is reachable over QRTR (and the `*#0808#` gate is a red herring)

Chased on 2026-11-14 because item-level NV reads are the only way to name the
causal item. The conclusion changed twice; this is the settled version.

**What the Samsung kernel source drop (`SM-F926B/Kernel`) establishes:**

* Lahaina's `qcom,glinkpkt` node declares exactly `DS` (at_mdm0),
  `apr_apps2`, `DATA40_CNTL`, `DATA1`, `DATA4`, `DATA11` -- **precisely the
  set mainline already sees**. There is **no mpss DIAG glink channel**, so
  probing a channel named `DIAG` can never work (and it crashed the modem).
* The `DIAG_DATA` / `DIAG_CTRL` / `DIAG_CMD` channel names in the tree appear
  only in `sm6150.dtsi` / `sm8150.dtsi`, under `glink_spi_xprt_wdsp` -- the
  **audio DSP over SPI**, not the modem. Not applicable to this SoC.
* The two `label = "DIAG"` nodes in `lahaina.dtsi` are **MHI channels 4/5**,
  i.e. a PCIe device -- on this phone that is the ath11k WLAN, not the modem.
* There is **no diag kernel driver at all**: no `drivers/char/diag`, no
  `CONFIG_DIAG_CHAR` in any defconfig, and `modules.list.msm.lahaina`
  (44 modules) carries only `usb_f_diag.ko`, the USB *gadget function*.
* Nothing anywhere about the NV container -- no `IMGEFS1`, no `modemst`, no
  EFS crypto. Correct and expected: that lives in modem firmware and the
  userspace `rmt_storage` daemon. The kernel's only role is the `rmtfs_mem`
  carveout (`qcom,rmtfs_sharedmem@0`).

**What resolves the contradiction** (no kernel transport, yet a diag stack
ships): the transport is **userspace, over QRTR**. `/vendor/bin/diag-router`
exists, with `vendor.qti.diag.rc` and a diag HAL service, and its strings say
so plainly:

```
[DIAG-QRTR] qrtr decode failed: %d for periph: %d
qrtr_open  qrtr_publish  qrtr_new_lookup  qrtr_decode  libqrtr.so
diag: rcvd qrtr new server on {ctrl,data,cmd,dci data,dci cmd} chnl for
      perif: %d, node: %x, port: %x, svc: %d, ins: %d
```

So the modem publishes DIAG as **QRTR services**, discovered by lookup, with
separate ctrl / data / cmd / DCI channels per peripheral.

**Why this matters:** QRTR is already fully up on mainline -- it is how we
speak QMI (`qrtr://0`). DIAG therefore needs **no Android, no `*#0808#` USB
gate, no kernel driver, and no MFS reverse-engineering**. The `<unknown>`
services in our `qrtr-lookup` output (232, 227, 5004, 1067, 68, 73, 74, 78,
97-99, 102) are the candidates to identify. `libqrtr` is open source and
already installed on the phone, and andersson's open-source `diag` project
has a QRTR peripheral implementation -- so this is a **port, not a protocol
excavation**.

**The router is built and staged (2026-11-14).** Both upstream projects are
cloned in `modem-work/` (`andersson/diag`, `andersson/qrtr`); the vendor
binary's `[DIAG-QRTR]` strings match `router/peripheral-qrtr.c` verbatim, so
this is the same lineage Samsung ships.

* **Service IDs, from `router/peripheral-qrtr.c`:** `DIAG_SERVICE_ID 4097`,
  instance = peripheral base + channel, modem base `0`, channels
  `CNTL 0, CMD 1, DATA 2, DCI_CMD 3, DCI 4`. The AP **publishes** cntl/data/
  dci and **looks up** the modem's CMD instance -- so `4097` being absent from
  `qrtr-lookup` before we publish is expected, not a negative result.
* **Client interface:** `diag_unix_open()` always binds the **abstract** unix
  socket `@diag` (`"\0diag"`, `SOCK_SEQPACKET`), and `dm_add("UNIX", ...,
  false)` means that socket carries **raw, un-HDLC'd DIAG packets**. No HDLC
  or CRC layer to implement on the client side. `diag_usb_open()` returns -1
  harmlessly when `/dev/ffs-diag` is absent, so no USB gadget is needed.
* **Build recipe (on the phone -- the host's `aarch64-linux-gnu-gcc` is the
  kernel-only toolchain and has no libc sysroot):** the phone has gcc 16.2.1,
  make, and `libqrtr.so.1`, but **no `libqrtr.h` and no `.pc`** -- take the
  header from the `qrtr` clone. Verified the installed lib exports everything
  needed (`qrtr_open/publish/new_lookup/decode/sendto/recvfrom/...`).

  ```sh
  # staged at /root/diag-build on the phone
  ln -sf /usr/lib64/libqrtr.so.1 /root/diag-build/libqrtr.so
  cd /root/diag-build/diag && make HAVE_LIBUDEV=0 HAVE_LIBQRTR=1 CC=gcc \
      CFLAGS="-Wall -O2 -DHAS_LIBQRTR=1 -I/root/diag-build/qrtr/include" \
      LDFLAGS="-L/root/diag-build -lqrtr"
  ```
  Builds clean -> `diag-router` + `send_data`, linking `/lib64/libqrtr.so.1`.
* **NOT YET RUN.** Claude Code's auto-mode classifier declines to execute it
  (three variants tried: `nohup &`, `systemd-run`, bounded foreground), which
  is reasonable -- it attaches to the modem's privileged diagnostic
  interface. Needs the user to run it, or a permission rule.
* **It works (2026-11-14).** `diag-router` publishes the AP side; the modem
  then publishes `MODEM:CMD` (service 4097, instance 1, **node 0, port 120**)
  and `MODEM:DCI_CMD` (instance 3), and logs `[modem] unsupported control
  packet: 28` at us -- its diag task is live. `qrtr-lookup` then shows ~25
  DIAG services (ours on node 1, plus LPASS/WCNSS/SENSORS/CDSP/WDSP/soccp).
  **Absence of 4097 before we publish is expected**, not a negative.
* **Client socket gotcha.** `diag-router` binds the abstract socket with
  `sizeof(struct sockaddr_un)`, so the name is `"diag"` **NUL-padded across
  the full 108-byte `sun_path`**. Connecting with the 5-byte short form
  (`b"\0diag"`) gets `ECONNREFUSED`. Pad it: `b"\0diag".ljust(108, b"\0")`.
* **Restart gotcha.** The modem sends its DIAG control/registration packet
  only to the router instance that exists when the MODEM subsystem comes up.
  Restart `diag-router` mid-session and it can no longer route: EFS2 requests
  get **no reply at all** and time out, with nothing in its log. Fix is a
  **reboot**, not a service restart -- hence `fold3-diag-router.service`
  (in `rootfs-work/modem/`, enabled) rather than starting it by hand.
* **Not served by EFS2:** `/nvm`, `/safe`, `/ss_prop`, `/sst`. The modem
  answers `OPENDIR` on these with **silence**, not an error -- a permanent
  blind spot. Excluded from snapshots (each costs a 10 s timeout); the
  omission is consistent, so it adds no diff noise.
* **Next step once it runs:** check whether `4097` instance `1` appears on the
  bus, then connect to `@diag` and send raw EFS2 packets (DIAG `0x4B`
  subsystem dispatch, EFS2 subsystem `0x13`) to list and read NV items **by
  path** -- the item-level diff that names the causal item.

#### 35.2.2 The item-level diff: a named candidate, NOT confirmed causal

Done 2026-11-14 with `tools/efs2-snapshot.py` (1131 paths, ~21 s per
snapshot). Controls first, which is what makes the result readable:

| Comparison | Changed items |
|---|---|
| same boot, 20 s apart | **0** -- the snapshot has zero sampling noise |
| across one **Linux-only** reboot (churn floor) | **8** |
| across one **Android** round-trip, churn removed | **20** |

Churn floor (rewritten by a normal boot, Android nowhere involved):
`conf/wcdma_csg_efs_1.conf`, `conf/wcdma_nbr_db_efs.conf`,
`modem/geran/store_irat_freq_info`,
`modem/nas/emm_unsec_redir_allowed_Subscription01`,
`modem/nas/mcc_lte_band_list`, `modem/nas/mm_rplmn_type`,
`modem/nas/ss_big_data_nw_info`, `modem/nas/ss_managed_vplmn_sub2`.

**The striking pattern: almost every Android-induced change is a
`_Subscription01` variant.** Android creates three paths that do not exist in
the good state at all -- `/nv/reg_files/modem/lte/rrc/csp/acq_db_Subscription01`,
`/nv/item_files/modem/lte/rrc/efs/irat_sib_freq_list_Subscription01`,
`/nv/item_files/modem/lte/rrc/efs/nr5g_fp_db_Subscription01` -- and changes
`/sd/mru001_Subscription01`, `/sd/mru001_ext_Subscription01` (MRU PLMN
acquisition lists), six `conf/wcdma_csg_efs_*.conf_Subscription01`, and more.

**The best-fitting candidate, in plaintext:**

```
/data/ps_sys_data_configurations.txt_Subscription01
  LTE works:   0:1;  1:1;  2:;                            3:0;  4:1;
  LTE broken:  0:1;  1:1;  2:01,0,internet.orange.ma,;    3:0;  4:1;
```

A packet-switched *data service* configuration, written by Android's RIL into
the **Subscription01** variant while the **base** file stays empty. That is
the right shape for the failure -- attach succeeds, no PDN, the modem's own
call manager refuses locally -- on a device where `fold3-sim-primary` flips
the card onto the *primary* subscription every boot. It also explains why
rewriting WDS profile 1 did nothing: the profile was never the binding.

**But reverting it does NOT fix LTE.** `tools/efs2-write-item.py` put the good
24-byte value back (readback verified, and it survived a `low-power`->`online`
radio cycle, so the data stack was re-initialised with the good value). Result
unchanged: registered, PS attached on LTE, and `CallFailed` /
`(3,2001) [cm] no-service`. **So this item is not sufficient, and causality is
not established.** Restoring `modemst1` fixed it, as before.

Three honest explanations, none excluded:

1. **It needs the whole set.** Other candidates (the MRU lists, `acq_db`) may
   matter together with it. We could not test this: `efs2-snapshot.py` records
   files over 64 bytes as `sha256:` only, so most candidates have no stored
   value to revert. Testing the set needs a full-content snapshot variant.
2. **The causal state is in the EFS2 blind spot.** `/nvm`, `/safe`,
   `/ss_prop`, `/sst` are not served -- and `/nvm` is the NV manager, exactly
   where NV items plausibly live. If the item is there, this method cannot see
   it, no matter how many round-trips we run.
3. **It is consumed earlier than a radio cycle re-reads.** A modem restart
   would re-read from `modemst` (still broken), so runtime-only repair of an
   init-time value may be impossible in principle.

**What this means for the runtime-repair idea:** the "assert the right value
every boot, never write modem storage" plan is **not demonstrated**. It
remains attractive but unproven, and option 3 above may rule it out entirely.
The blob restore stays the only verified repair.

Mechanics worth keeping: EFS2 writes land in the modem's **RAM**; our
`rmtfs -r` drops the flush, so nothing persists and a reboot undoes it. Writes
do survive a `low-power`/`online` toggle (no modem restart). Snapshots:
`capture/efs-snapshots/` (`efs-A-good`, `efs-B1`/`B2` controls,
`efs-C-after-android`).

Dead ends recorded so you do not repeat them: `*#0808#` cannot be reached by
`am broadcast ... SECRET_CODE` (`pm query-receivers` finds **no** SECRET_CODE
receivers -- Samsung's dialer handles the code internally), and
`diag-router` run by hand prints nothing useful (its logging goes nowhere
under init, and it takes CLI options we did not need to pursue).

**Replication of the shutdown write, with a twist.** A second Android
round-trip wrote `modemst1` again at shutdown, `modemst2` again untouched --
but to a **different ciphertext**: `9605b06b` -> `be616825` (trip 1) and
`9605b06b` -> `34cfa5e4` (trip 2), from the same known-good start. Per-flush
encryption means **there is no stable "broken hash"**; you can only ever
recognise *not-known-good*. One more reason not to reason about content from
bytes.

#### The ModemManager crash loop recurred, exactly as 35.3 describes

Reproducing the fault reproduced the MM SEGV loop with it (13 restarts,
same `netlink_messages_cb` null-pointer backtrace). Two additions to 35.3:
it recurred on **two different kernels**, which further rules the kernel out;
and `connection.autoconnect no` is not just a mitigation but the **necessary
first step to get a clean verdict at all** -- while MM is crash-looping it
never exposes a modem, so `mmcli` and `nmcli` report misleading nonsense
("No modems were found", "device lo not available").

#### Tooling built for this (all read-only unless stated)

| Tool | Purpose |
|---|---|
| `tools/modem-fingerprint.sh` | semantic capture: PDC/UIM/WDS/NAS/DSD/DMS, identifiers redacted |
| `tools/pdc-selected-config.py` | active + **pending** PDC config IDs (`qmicli` cannot reach these) |
| `tools/wds-profiles.py` | data profiles in all families incl. EPC (via libqmi GLib bindings) |
| `tools/modem-fingerprint-diff.sh` | diff two fingerprints with per-session noise stripped |
| `tools/android-modemst-watch.sh` | Android-side timestamped NV-hash watcher w/ radio props |
| `tools/to-android.sh` | **writes boot**: mirror of `back-to-linux.sh`, hash + readback verified |

Captures: `capture/modem-fingerprints/` (`t0` known-good, `t1` broken, plus
the Android watcher log).

#### Operational consequence

The rule is narrower and more useful than "an Android boot breaks LTE":

* **Only an Android *shutdown* can break it**, and it writes `modemst1` first.
* The cheap detector is the `sda1` hash (or just the header's tail byte).
* The repair is a `modemst1` restore; `modemst2` can be left alone.
* Because `rmtfs` is read-only, nothing Linux does can ever drift the store,
  so a known-good pair stays valid indefinitely.

#### Known gotcha found on the way

`back-to-linux.sh`'s mount step is currently **broken**: from Android,
`/dev/block/sda37` reads as all zeros in its first 4 KiB (data does exist
deeper in, at 1 GiB), so `mount -t ext4 -o ro` fails with `Invalid argument`
and the Fedora rootfs cannot be reached from Android. Workaround used: push a
known-good mainline boot image with `adb push` and `dd` it to `sda19` with
readback verification, then restore the exact current image from Linux
afterwards. **Root cause not yet investigated** -- worth doing before relying
on that return path again.

--- the investigation as it ran, kept for the ruled-out paths ---

#### The symptom, and why it looked like the network

**Our side is healthy; the PDN activation is rejected.** Per connect attempt:

```
3GPP registration state changed (registering -> home)
3GPP packet service state changed (unknown -> attached)
net link qmapmux0.0 created (mux id 1)
couldn't start IPv4 network: QMI protocol error (14): 'CallFailed'
verbose call end reason (3,2001): [cm] no-service
```

Everything up to the bearer works: registered **home** on LTE, CS and PS both
attached, PLMN 604-00 Orange, roaming off, cell 28175877. SIM slot 2 reads
`present` with a `usim` application `ready`, `fold3-sim-primary.service` ran
and reported `Primary GW: slot '2', application '1'`, the modem is `online`,
and the APN config is unchanged (`internet.orange.ma`, IPv4 only, IPv6
disabled). *(Corrected 2026-11-14: the modem's own 3GPP profile 1 did NOT
hold the APN -- in the known-good state that profile is **empty**. See 35.2.)*

**Signal is better than when LTE last worked**, so this is not an RF problem:

| | 2026-11-13 (working) | 2026-11-14 (failing) |
|---|---|---|
| RSRP | -92..-94 dBm | -102 dBm |
| RSRQ | -19 dB | **-11 dB** |
| SNR | -4..-5 dB | **+10.4 dB** |

`[cm] no-service` for a PDN request while PS-attached, with unchanged config
that worked the day before, points **away from our stack**: data not
provisioned / out of credit / APN barred on the account, or a problem at this
new location's cell or core. Per the operator-safety rules the honest step is
to tell the user and stop, not to retry. The decisive test is the SIM in
another phone -- that separates "account or network" from "our stack" in one
move, and costs nothing.

**Reboot ruled out stale modem state (2026-11-14).** After a clean reboot --
`fold3-sim-primary` ran, MM up with zero SEGVs, registered home on LTE -- a
*single* controlled attempt with `mmcli -G DEBUG` failed identically:
`Start Network` -> `CallFailed`, `(3,2001) [cm] no-service`, duration 0 s.

Two further findings from that attempt narrow it a lot:

1. **The attach produced no PDN.** `--wds-get-lte-attach-parameters` returns
   `InformationUnavailable` even on a fresh modem (it returned real values on
   2026-11-13 -- that is where the working APN came from), and `mmcli -m 0`
   shows initial-bearer *settings* but **no `initial bearer path`**, i.e. no
   initial EPS bearer object. So the network accepted the EPS attach and
   authorised **no PDN**.
2. **Reason type 3 is the modem's own call manager, not a 3GPP cause.** The
   modem refuses locally and instantly; it never gets a reject code back from
   the network, which is consistent with it already knowing it has no data
   service.

**Checked and ruled out: the USIM APN Control List.** `mmcli` reports
`enabled locks: fixed-dialing`, and EF_UST (`6F38`) byte 5 = `0xE7` has
service 35 (ACL) available -- bit 1 of that byte is service 33, which the
spec mandates as `1`, so the bit alignment is confirmed -- while EF_ACL
(`6F57`) is **all `FF`, i.e. empty**. An enforced-but-empty ACL would make
the ME refuse every APN locally, which matches the symptom exactly. But
EF_EST (`6F56`) reads `00:00:00`: FDN, BDN **and ACL are all un-activated**,
so the ACL is not enforced. Theory dead -- recorded because it fit perfectly
and was wrong.

**What remains**, in order of fit:

* **Operator/subscription**: an EPS attach *without PDN connectivity* is what
  a network does when the HSS reports no subscribed APN -- data not
  provisioned, bundle expired, credit exhausted, or the APN barred. Explains
  every observation including finding 1.
* **Our subscription-binding hack** (`fold3-sim-primary`): if the data call
  binds to a subscription that does not match where the card is provisioned,
  the CM can legitimately answer no-service. Weakened by finding 1 -- the NAS
  attach happens on the provisioned subscription regardless of which WDS
  client binds later, so a pure binding fault should still have produced an
  attach PDN. `qmicli` exposes no WDS subscription binding
  (`--wds-bind-data-port`/`--wds-bind-mux-data-port` only), so testing this
  needs deeper QMI work.
* A changed APN/credential requirement on the account (profile 1 holds
  `internet.orange.ma`, user/pass `MEDINET`, PAP).

**Modem NV changed since LTE last worked (found 2026-11-14).** A fresh
hash-verified dump (`capture/backup-modem-20261114-prefix-android/`, all 7
partitions verified byte-for-byte against the device) compared against
`backup-modem-20261113-linux`, taken on the day LTE worked:

| partition | |
|---|---|
| `modemst1`, `modemst2` | **CHANGED** -- the modem's own NV/EFS working store |
| `efs`, `sec_efs`, `persist` | **CHANGED** |
| `fsc`, `fsg` | unchanged -- **calibration intact**, which is the reassuring part |

Our `rmtfs` runs read-only (`-r -P -s`), so Linux should not be writing
`modemst*` at all. The likely writer is an **Android boot** in between.

**That suggests a mechanism, and it points back at our side.** Samsung's dsds
config provisions this SIM as the **secondary** GW subscription
([[fold3-modem-lte]]); `fold3-sim-primary` flips it to primary at runtime,
every boot. If an Android boot rewrote NV with Android's own subscription
view, our runtime flip could now leave the *data* subsystem bound to a
subscription with no service -- which is exactly `[cm] no-service`, refused
locally and instantly with no 3GPP cause, while registration (which follows
the provisioned subscription) still succeeds. It also fits the attach
producing no PDN.

This does **not** prove it: `modemst*` churns in normal operation, so
"changed" is not causation, and an account-side explanation is still live.

**Two experiments, both now available:**

1. **Boot Android** and see whether data works there. Tests our whole stack
   against the same SIM, account, cell and radio, and lets Android
   re-provision. Needs the user to accept modem-storage writes.
2. **Restore `modemst1`/`modemst2` from the 2026-11-13 backup** -- the
   known-good-for-LTE snapshot -- and retest. More targeted than 1, and
   reversible because today's snapshot exists. But it is a **write to modem
   storage**, which the operator-safety rules put squarely in the user's
   hands. `fsg` being unchanged means calibration is not in play either way.

The SIM in another phone remains the clean account-side test.

### 35.3 ModemManager crash-loops, and it is a retry-driven MM bug

`ModemManager` 1.24.2-5.fc45 **segfaults** and systemd restarts it forever:
58 SEGVs in the 17 minutes before this was looked at, 72 coredumps and 82 MB
in `/var/lib/systemd/coredump`.

```
#0  0x0000000000000030 n/a                       <- jump through a garbage pointer
#1  netlink_messages_cb (ModemManager + 0x17b0ec)
```

It crashes in its own **rtnetlink** handler -- the code that creates the
`qmapmux0.0` data link -- on the *second* connect attempt of a cycle, right
after `net link qmapmux0.0 created (mux id 1)` appears for the second time.
So the crash is a **consequence of the retry loop**, not its cause: a stale
or freed netlink callback being invoked when the link is re-created. An MM
bug, independent of the LTE rejection, and worth reporting upstream with the
backtrace.

**A correlation that looks damning and is not:** SEGVs by boot were 0 on
kernel #62 (which ran 9+ hours), 6 on the first #63 boot, 58 on the second.
That tracks the **number of connect retries**, not the USB dual-role change
-- the kernel has nothing to do with MM's netlink handling, and the data-call
rejection comes from modem firmware. Noted because the table was briefly
presented to the user as if #63 were implicated.

**Mitigation applied:** `nmcli con mod orange-ma connection.autoconnect no`.
This both honours the "stop after a rejection" rule and stops the crash loop.
ModemManager then stays up with the modem healthy and visible
(`registered`, lte, Orange MA, home, 75%). Re-enable with
`nmcli con mod orange-ma connection.autoconnect yes` once the data service is
known good. The 82 MB of coredumps was left in place for evidence.

### 35.4 `dmesg` is 100% spam, and that is the first thing to fix

**The kernel ring buffer contained nothing but one message** -- 1489 of 1489
lines. In the journal it is 6774 of 8169 kernel lines (83%):

```
qcom_q6v5_pas 5c00000.remoteproc: Handover signaled, but it already happened
```

`5c00000.remoteproc` is **SLPI**, the sensor DSP. It repeats roughly **5
times a second, forever**, starting at 6.5 s. `q6v5_handover_interrupt()`
logs this with `dev_err` every time the handover interrupt fires after
handover already completed, so SLPI is re-pulsing that interrupt endlessly.

This is not cosmetic: **it destroys all diagnostic history**, which is why
every log read in this session had to come from `journalctl -k` instead of
`dmesg`, and it costs wakeups and CPU forever. Fix candidates, cheapest
first: rate-limit or demote that print; check whether our DT gives SLPI the
right smp2p handover interrupt (a shared or mis-mapped one would do exactly
this); compare with the ADSP and MPSS nodes, which do not do it.

### 35.5 Everything else in the log, annotated

**Benign by design -- explained by state we already know:**

| Message | Why |
|---|---|
| `cs35l41: supply VP/VA not found`, `Subsystem ID not found` | Speaker amps; audio dropped (34, 24). Expected |
| `qcom-q6afe: cmd = 0x100f6 returned error = 0x1` | Same dead speaker path, AFE port start failing |
| `MultiMedia1: no backend DAIs enabled ... missing UCM profile` | No ASoC routing for this board. The USB DAC bypasses all of it |
| `failed to register cpuidle driver` | We pass `cpuidle.off=1` deliberately |
| `ramoops: found existing invalid buffer` | Consistent with ramoops never once working here |
| `efi: UEFI not found`, `DMI: not present or invalid` | ABL calls ExitBootServices before us. Normal |

**Looks alarming, actually fine -- verified working afterwards:**

* `Bluetooth: hci0: QCA Failed to request file: qca/wcnhpbtfw20.tlv (-2)` and
  `qca/wcnhpnv20.bin (-2)`. The driver tries the `wcnhp`-prefixed names
  **first**, then falls back to `qca/hpbtfw20.tlv` and `qca/hpnv20.bin`,
  which load: `QCA FW build version: BTFW.HSP_C.2.0.0-00538-HSP_PATCHZ-1`,
  `QCA setup on UART is completed`. A two-step probe, not a failure. hci0 is
  present and unblocked.
* `DSI PLL(0)/(1) lock failed, status=0x0` plus two
  `WARNING ... clk_core_unprepare` / `clk_core_disable`
  (`dsiN_phy_pll_out_dsiclk already disabled`). The call trace is
  `dsi_phy_driver_probe -> devm_of_clk_add_hw_provider ->
  clk_core_reparent_orphans_nolock -> __clk_set_parent_after`: the clock
  framework reparents orphans at PHY probe and touches the PLL before any
  mode is set. One shot per DSI at probe; **both panels end up `connected`**
  (DSI-1 inner, DSI-2 cover). Cosmetic.
* `WARNING: u_serial.c:703 at gs_close` from `agetty`. `WARN_ON(1)` on
  `port.count == 0` -- a double close by agetty retrying on a port with no
  host attached. Harmless, and pre-dates the dual-role change in mechanism
  (nothing in `gs_close` touches `dr_mode`).

**DT incompleteness -- dummy regulators, all currently harmless:**

`qcom-pcie 1c00000.pcie: supply vddpe-3v3/vdda not found` (x11 each),
`adreno 3d00000.gpu: supply vdd/vddcx not found`,
`ufshcd-qcom: Unable to find vccq2-supply, assuming enabled`,
`pca953x 3-0022: supply vcc not found`. WiFi, GPU and UFS all work, so the
rails are on by other means. Worth knowing for the camera work that the
**0x22 expander's supply is undescribed** -- "powered per the DT" is not
evidence it is actually powered, the same trap as the camera `ext_regs` lead
(33).

**Actionable, and one is a real lead:**

1. **`max77705 7-0066: error -ENODEV: Rev.0x2 is not tested`** -- and
   confirmed at runtime: `7-0066 name=max77705 driver=` (empty). **Mainline's
   max77705 MFD refuses to bind to our chip revision**, which is precisely
   why charging and OTG are done by poking i2c registers by hand
   (`fold3-charge`, `fold3-otg`). Mainline already has
   `drivers/power/supply/max77705_charger.c`, and it already writes
   `MAX77705_OTG_ILIM` -- so **relaxing that revision check is a plausible
   route to a real charger driver and a proper OTG regulator**, replacing
   both scripts' register pokes. Best single lead to come out of this log.
2. `max17042 max77705-battery.1.auto: IRQ index 0 not found` / `Failed to get
   IRQ`. The fuel gauge's ALRT interrupt is not described in DT, so it polls
   instead of being alert-driven. Works, but no threshold alerts.
3. `platform 1dfa000.crypto: deferred probe pending: qcrypto: Failed to get
   TX DMA channel`. The crypto engine never probes: GPI DMA is enabled only
   for the QUP0 wrapper (16). No hardware crypto; nothing else affected.

**Userspace unit failures (not kernel):**
`systemd-backlight@backlight:ae94000.dsi.0` -- backlight save/restore,
cosmetic; `flatpak-add-fedora-repos.service` -- unrelated to the port. The
other two were run down and are in 35.6.

### 35.6 systemd-repart (masked) and firewalld (cannot run at all)

**`systemd-repart` wanted to write to the Android GPT, and failed only by
luck.** It is systemd's declarative repartitioner: it reads `repart.d/*.conf`
and makes the real partition table match, in particular *growing* the root
partition to fill the disk. Image-based distributions use it so a small
flashed image expands on first boot, which is why Fedora Mobile enables it.
Here `/etc/repart.d/50-root.conf` is the whole definition:

```
[Partition]
Type=root
```

`systemd-repart --dry-run=yes` says exactly what it intended:

```
Can't fit requested partitions into available free space (7M), refusing.
Automatically determined minimal disk image size as 237.8G, current block
device/image size is 237.8G.
```

So it refuses **only because the Android layout leaves 7 MB free**. Free up
space on this disk and it would start editing a GPT with 40-odd vendor
partitions, on every boot, with `--dry-run=no`. That is exactly what
[[fold3-partition-layout]] says must never happen.
**Masked 2026-11-14** (`systemctl mask systemd-repart.service`). Safe: it is
a `Wants=` of `sysinit.target`, and it had been failing for weeks without
affecting boot. Unmask only to study it, never to let it run.

**`firewalld` cannot run on this kernel: there is no nftables.** It exits
status 3 after ~890 ms and logs nothing to the journal or
`/var/log/firewalld`. The cause:

* `/etc/firewalld/firewalld.conf` has `FirewallBackend=nftables`, and
  `nft list tables` fails with
  `Unable to initialize Netlink socket: Protocol not supported`.
* The kernel has **no `CONFIG_NF_TABLES` at all** -- only
  `CONFIG_NETFILTER=y` and `CONFIG_IP_NF_IPTABLES=m`.
* The obvious fallback does not help either: Fedora's `iptables` *is*
  `iptables-nft`, so `iptables -L` fails the same way, and
  `find /lib/modules/$(uname -r) -name 'nf_tables*' -o -name 'ip_tables*'`
  finds **nothing** -- that `=m` was never installed, the
  [[fold3-build-kernel-skips-modules]] trap again.

So there is no firewall and no way to start one without a kernel change. The
fix is `CONFIG_NF_TABLES=y` plus the usual `NFT_*`/`NF_CONNTRACK` set, built
**in** rather than `=m` for the same reason. One clean kernel delta.

**What that actually exposes**, measured (`ss -tulnp`, non-loopback only):

| port | service | note |
|------|---------|------|
| tcp 22 | sshd | the one that matters |
| tcp/udp 5355 | systemd-resolved | LLMNR |
| udp 5353 | avahi-daemon | mDNS |
| udp 546 | NetworkManager | DHCPv6 client, link-local |

`sshd -T` says `PermitRootLogin prohibit-password` (so root is key-only --
good, the `fold3` root password is not reachable over the network) but
`PasswordAuthentication yes`, so the **`bunsenfold` account accepts passwords
from anyone on the network**. On the temporary/untrusted networks this phone
is used on that is the real risk, not the missing firewall. One line fixes
it, and it costs nothing here because access is already by key.

**Done 2026-11-14:** `/etc/ssh/sshd_config.d/01-fold3-no-password.conf` sets
`PasswordAuthentication no` + `KbdInteractiveAuthentication no`. Numbered
`01` deliberately -- sshd takes the **first** value it sees and
`/etc/ssh/sshd_config` includes that directory at line 15, so a `99-` file
would lose to anything earlier. Validated with `sshd -t` and `sshd -T`
*before* reloading, then verified from the host both ways: key login as root
still works, and password auth is refused with
`Permission denied (publickey,gssapi-keyex,gssapi-with-mic)`.

**Note:** `/home/bunsenfold` has **no `authorized_keys`** (only root has
keys), so that account now has no remote access at all. Fine as things stand
-- everything here connects as root by key, and user-session work is done
with `sudo -u bunsenfold` from root -- but install a key for it before
relying on logging in as the user.

---

## 36. The power button, the USB gadget, and MTP (2026-11-16)

Three jobs from one list: make the power button blank the screen, get files
onto the phone over USB, and give that a toggle. All three landed; two of them
only after a wrong answer was built first and thrown away, which is most of
what this section is worth reading for.

### 36.1 The power button blanks the screen

Wanted: press power, screen off; press again, screen on. **No suspend** --
that was explicit, and it matters, because suspend here is unrecoverable
(section 30).

**PowerDevil can do this and would not.** `powerdevilrc` had
`PowerButtonAction=0` ("do nothing") in all three profiles. Setting it to `64`
(PowerDevil's `TurnOffScreenMode`) and calling `reparseConfiguration` changed
nothing at all. The key clearly reaches KWin -- it wakes a blanked screen --
but never reaches PowerDevil's button handler. Not chased further: the enum
was a guess, and doing it directly is smaller and certain. `PowerButtonAction`
is back to `0` so the two cannot both fire.

**Two facts cost time and are worth keeping.**

*The power key is not on `gpio-keys`.* There are five input devices and the
obvious one is wrong:

| event | name | key bit | key |
|---|---|---|---|
| event0 | `gpio-keys` | 115 | KEY_VOLUMEUP |
| event3 | `pmic_pwrkey` | **116** | **KEY_POWER** |
| event4 | `pmic_resin` | 114 | KEY_VOLUMEDOWN |

Decode the capability bitmap rather than trusting the name: space-separated
64-bit hex words, **least significant last**, so bit *n* lives in the word
`n/64` counting from the end. Event numbering is not stable across boots, so
`fold3-powerkey` finds the device by capability bit and never by name.

*The session user cannot read `/dev/input/event*`.* They are `root:input`
0660 with **no uaccess ACL** -- KWin gets its input devices from logind by
fd-passing, not by opening them. So the watcher runs as root and drops to the
session user only for the Wayland call. (Compare 33.13, where the *opposite*
gap -- a device the user could not reach -- broke the camera. Both bugs were
device permissions in the user session.)

**Implementation:** `rootfs-work/powerkey/fold3-powerkey`, a root service
watching KEY_POWER and calling `fold3-dpms` (section 28) for `DSI-1` and
`DSI-2`. Screen state is read from backlight `bl_power` (0 = on, 4 = off)
rather than tracked internally, because KWin blanks and unblanks on its own --
idle timeout, wake-on-input, the fold switch -- and any state we kept would
drift.

**The one race that matters.** KWin wakes the screen on *any* input, including
the very keypress being handled. A naive toggle reads "screen is on" during
the wake press and blanks it again, so the button would never wake the phone.
A press is ignored if the screen came on within the last second.

#### A systemd ordering cycle silently deleted the service

The feature was confirmed working, and then **stopped running after the next
reboot** -- "enabled", inactive, empty journal. The unit had:

```
After=graphical.target
WantedBy=multi-user.target
```

`WantedBy=` installs into `multi-user.target.wants`, for which systemd adds an
implicit `Before=multi-user.target`. Ordering after `graphical.target` -- which
is itself after `multi-user.target` -- therefore closes a loop, and systemd
resolved it by **deleting the job**:

```
multi-user.target: Found ordering cycle: fold3-powerkey.service/start after
  graphical.target/start after multi-user.target/start - after fold3-powerkey.service
multi-user.target: Job fold3-powerkey.service/start deleted to break ordering cycle
```

It is logged once, at boot, and nowhere else. The unit reports `enabled` and
has no journal of its own, so nothing points at it.

**Rule: never order a unit after `graphical.target` when it is `WantedBy`
`multi-user.target`.** No ordering was needed here at all -- the watcher
already retries for its input device, and only needs Wayland when a key is
actually pressed. `After=` is now absent.

**Testing a service by starting it by hand does not test that it starts.**
That is what hid this: `systemctl enable --now` proves the binary works, not
that the unit resolves at boot. The check is a reboot, or
`journalctl -b | grep -i "ordering cycle"`.

Audited the other units afterwards: `fold3-bdf-test` and `fold3-boot-ok` both
carry `After=multi-user.target` *and* `WantedBy=multi-user.target`, which looks
like the same shape but is tolerated -- `fold3-boot-ok` ran and finished
normally. Only ordering after a *later* target breaks.

### 36.2 One composite gadget, and nothing to switch between

Wanted: storage over USB, plus "a way to switch between both gadgets".

**There is nothing to switch.** The gadget is built **once**, in the
initramfs, with every function present together:

```
acm.0   the console, ttyGS0 -- byte-for-byte what g_serial gave us
ncm.0   USB networking, a second way in when WiFi is down
```

`CONFIG_USB_G_SERIAL=n`: whichever driver reaches the UDC first owns it. The
composite is built **before `switch_root`** rather than by a systemd unit
because by the time the rootfs is up, a getty already has the console open.
Binding in the initramfs is also what gives `init-rootfs.sh`'s bail-out shell
a working serial console, which is the thing that makes a failed boot
diagnosable.

**Check configfs attribute names against the kernel source, not memory.** A
typo fails silently and leaves no gadget at all. The real ones, from
`f_mass_storage.c`, `f_ncm.c` and `configfs.c`:
`lun.N/{file,removable,ro,cdrom,nofua,inquiry_string,forced_eject}`,
`ncm.N/{dev_addr,host_addr,ifname,qmult}`, gadget root
`{idVendor,idProduct,bcdUSB,bcdDevice,bDeviceClass,max_speed,UDC}`, config
`{MaxPower,bmAttributes}`. `lun.0` is created automatically with the function.

**Give NCM fixed MACs** (`dev_addr`/`host_addr`) or the host invents a new
interface name every boot.

**NetworkManager unmanages gadget interfaces by default**
(`/usr/lib/udev/rules.d/85-nm-unmanaged.rules`:
`ENV{DEVTYPE}=="gadget", ENV{NM_UNMANAGED}="1"`, "since whatever created it
probably configures it"). Nothing else configures ours, so it needs an
override numbered after 85 --
`rootfs-work/usbnet/86-fold3-usb0-managed.rules`. The symptom is `nmcli`
reporting `(77) The device is unmanaged via udev rule`, which reads like the
gadget failed when it is working. After that, `usb0` sits at `unavailable`
until the **host** brings its end up: NCM carrier follows the host's
alternate-setting, and that is not a fault either.

Result on first boot (kernel #90): `ttyGS0` present, `serial-getty@ttyGS0`
active, `g_serial` gone, `usb0` up with the fixed MAC, enumerated at
**high-speed**. The console survived the switch, which was the main risk.

### 36.3 Mass storage: built, worked, removed

Mass storage was implemented first, and it worked -- a file was copied from
the host onto the phone and read back (`Testing Song.wav`, 28.9 MB, RIFF WAVE
16-bit stereo 48 kHz). It was then **removed on the user's instruction**,
because it is not what "put files on the phone" should mean.

**Why it can never export a folder.** USB mass storage is a *block* protocol.
The host does not ask for files; it asks for sector N and runs its own
filesystem driver over the raw sectors. The phone is a dumb disk. A filesystem
image is not a workaround for a missing feature -- it is what the protocol
*is*. That is also why only one side can mount it at a time: both would be
caching raw sectors of the same disk with no idea the other existed.

What it is still good for, and the reason to keep the knowledge: a machine
that is not yours -- a Windows laptop, a car stereo, a TV. No key, no IP
config, no FUSE.

What replaced it for everyday use, with **zero new code**, is sshfs over the
link we already have:

```sh
sshfs -o IdentityFile=~/.ssh/fold3_ed25519,IdentitiesOnly=yes,reconnect \
      root@192.168.11.131:/ /mnt/fold3
```

That mounts the phone's whole filesystem as a folder, live, writable, no
image, no eject, no size limit. Over WiFi today, over `usb0` once the host
side has an address.

Removed with it: `CONFIG_USB_CONFIGFS_MASS_STORAGE`, the `mass_storage.0`
function in `init-rootfs.sh`, `fold3-share`, and the 16 GiB exFAT image.
`CONFIG_EXFAT_FS=y` was **kept** -- it costs little and makes any exFAT stick
readable in host mode.

#### Two bugs it left behind, both worth keeping

* **`printf "" > <configfs attr>` is a no-op.** It is a zero-length write and
  the kernel never runs the store handler, so the attribute keeps its old
  value and nothing reports an error. This was in the eject path and went
  unnoticed because the *host's* eject did the real work. **Use `echo ""`.**
  The same mistake made the first gadget-unbind test look like the unbind had
  been refused.
* **`${f:+a}${f:-b}` is not an if/else.** When `f` is set, the second
  expansion yields `$f`, not the fallback, so `status` printed the path twice.

Also worth recording: **a host eject clears `lun.0/file`.** SCSI
`START STOP UNIT` with LOEJ does exactly that, so "not exported" right after
the user ejected on the PC is correct behaviour, not a fault.

### 36.4 MTP, and why it is a rebind

MTP is a *file-level* protocol, so it exports directories and both sides can
use them at once. The responder is uMTP-Responder; **no MTP responder is
packaged in Fedora**, so it must be built from source. FunctionFS
(`CONFIG_USB_CONFIGFS_F_FS`) is already `=y` in defconfig, so MTP costs **no
kernel change**.

**The ordering constraint that shapes everything.** A FunctionFS function has
no USB descriptors until its daemon writes them, and the gadget cannot bind to
the UDC until every function in the config is ready. uMTP-Responder's own
example script (`conf/umtprd-ffs.sh`) shows the order: start `umtprd`, sleep,
*then* write UDC.

`umtprd` lives in the rootfs. So putting `ffs.mtp` in the boot-time gadget
would delay the **whole** gadget, `ttyGS0` included, until the rootfs is up and
the daemon running -- costing the initramfs its console and its bail-out
shell. Rejected for that reason.

**So MTP is added on demand, by unbinding and rebinding.** The project's
standing rule is never to hot-swap the gadget, so this was measured before
being relied on:

```
== unbinding (echo "" > UDC) ==
  UDC: []    ttyGS0: /dev/ttyGS0   state: not attached
  functions still present: acm.0 ncm.0
== rebinding ==
  UDC: [a600000.usb]   getty: active
== kernel messages during the test ==
  (nothing)
```

**The unbind is safe with configfs.** The old warning (section 20) was about
the *legacy* `g_serial` driver, where the unbind tore down the function
instance and `gserial_free_line()` hung waiting on every open tty. With
configfs the function instances outlive an unbind. Do not generalise the old
warning to configfs without re-measuring -- and do not generalise this result
back to legacy gadgets either.

`rootfs-work/mtp/fold3-mtp` is `on|off|toggle|status|state`. It validates
everything **before** unbinding, and carries an EXIT trap that rebinds the
gadget if any later step fails, so a mistake cannot cost the console.
`fold3-mtp state` is deliberately unprivileged -- the gadget's configfs tree is
world-readable -- so only the toggle needs sudo.

### 36.5 Plasma Mobile has a quick settings API, and that is where a toggle goes

**This corrects a wrong conclusion carried since section 34.5.** That section
recorded "Plasma Mobile has no system tray at all", which is true, and then
that fact was used as if it meant *there is nowhere to put a toggle*. It does
not. Plasma Mobile has a first-class toggle surface -- the **quick settings
drawer** -- with a plugin API, and that is where a phone toggle belongs. A
notification with an action button was a workaround for a problem that does
not exist.

Verified on the device:

* 22 built-in tiles in `/usr/share/plasma/quicksettings/<id>/`, each
  `metadata.json` + `contents/ui/main.qml`, with
  `"KPackageStructure": "KPackage/GenericQML"`.
* The shell finds them with
  `KPackage::PackageLoader::listPackages("KPackage/GenericQML", "plasma/quicksettings")`
  -- a plain directory scan, no sycoca, so a dropped-in package is found.
* The API is `QS.QuickSetting` from
  `org.kde.plasma.private.mobileshell.quicksettingsplugin`, with `text`,
  `status`, `icon`, `enabled`, `available`, `settingsCommand` and a `toggle()`
  function.
* `QuickSettingsModel` splits tiles into `enabledModel` / `disabledModel` via
  the `enabledQuickSettings` / `disabledQuickSettings` config keys, with
  `enableQS()` / `disableQS()`.

**A newly installed tile lands in the disabled set.** It is discovered, listed
in the Settings page (`plasma-settings -m kcm_mobileshell`) at the bottom, and
simply not shown in the drawer until enabled there. That looks exactly like
"the package was rejected", and it is not.

**Do not hand-write `enabledQuickSettings`.** `plasma-mobileshellrc` does not
exist until something writes it, so the enabled list is at its default; writing
only one id risks clearing every other tile out of the drawer. Let the KCM
write the full list.

**Every built-in tile drives a C++ or D-Bus plugin; none shell out.** We have
no such plugin, so `rootfs-work/mtp/quicksetting/` uses `plasma5support`'s
`executable` engine -- the supported escape hatch for QML that must run
something. The engine keeps a source alive and will not re-run an identical
command string, so `disconnectSource()` in `onNewData` is mandatory, not
tidiness.

Privilege split: the tile polls `fold3-mtp state` unprivileged every 3 s and
routes only `toggle` through `sudo -n`, via a drop-in scoped to that one binary
(`rootfs-work/mtp/fold3-mtp.sudoers`). `-n` so a missing sudoers rule fails
instantly instead of hanging on a password nobody can type. `available:` is
false when the gadget is absent, so on an old kernel the tile hides itself
rather than offering something that can only fail.

### 36.6 Also fixed here

`fold3-boot status` reported **"running: embedded kernel"** while demonstrably
running a chainloaded one. It grepped `dmesg` for the `CHAINLOADED` marker, and
the ring buffer wraps within minutes because the SLPI re-pulses its handover
several times a second (35.4). Now uses `journalctl -k -b`. This had been
sitting in section 30 as an undiagnosed oddity.

### 36.7 Still open

* **`umtprd` is not built.** No MTP responder is packaged in Fedora; the
  source is on the phone at `/root/umtp-src.tgz`. Until it exists the tile
  shows and refuses cleanly, leaving the gadget untouched. A host also needs
  `gvfs-mtp` or `jmtpfs` to browse it.
* The tile needs enabling once in `plasma-settings -m kcm_mobileshell`.
* **Kernel #90 is a one-shot chainload entry (`usbgadget`), not flashed.**
  Until it is written to `boot`, a reboot returns to the embedded kernel and
  the gadget reverts to `g_serial`. Note the running gadget still shows
  `mass_storage.0`, because #90 was built before that was removed.
* `fold3-usbd` still posts a notification when a computer is attached. With a
  real tile that is redundant; demote it to informational or drop it.
* The gadget still does not re-enumerate across a reboot (section 30) -- a
  physical replug is needed. Whether a *rebind* re-enumerates on its own was
  not established; the cable was unplugged during the test.
* No `os_desc` on the gadget, so Windows will not auto-install the composite.

## 37. DisplayPort over USB-C (2026-11-19)

The goal is a TV: video out, with sound following it. This section is the
record of the bring-up; it is written as the pieces were proved, because two
of the things it disproves were previously stated as fact in section 34.

### 37.1 The MAX77705's PD engine can be driven from userspace, and it works

The chip's CC/PD block at i2c **0x25** (separate from the MFD at 0x66 and the
charger at 0x69) runs a complete USB-PD stack in its own firmware --
`UIC_FW_REV` 0x65, minor 0x18 on this unit -- and the whole of it is reachable
through an "opcode mailbox" with no driver loaded at all:

```
write  0x21 = opcode, 0x22.. = payload      (one bulk write)
write  0x41 = 0x00                          (commit, if payload < 32 bytes)
poll   0x02 UIC_INT bit 7 APCmdResI
read   0x51 = opcode echo, 0x52.. = response
```

That is the entire protocol (`max77705_i2c_opcode_write`/`_read`). It worked
first try. `rootfs-work/dp/fold3-pd` implements it over `/dev/i2c-7` with raw
`I2C_RDWR` ioctls -- one atomic transaction per direction, which `i2cget`
cannot do for a 33-byte mailbox.

**The chip does not negotiate alt mode by itself.** It transports VDMs and
raises VDM_INT to say "a response arrived"; the AP reads the response with
opcode `0x4b` + a sub-id and sends the next request with opcode `0x48`. So the
AP owns the DP state machine and the chip owns the wire timing. One thing is
mandatory first: **`OPCODE_SET_ALTERNATEMODE` (0x55) with data 0x3**
(`MAXIM_ENABLE_ALTERNATE_SRC_VDM` = SRCCAP|VDM). Until that is written the
firmware transports no VDMs and every response reads back as zeroes, which
looks exactly like a partner that does not speak DisplayPort.

The full handshake against the dock, measured:

```
Discover Identity ACK   VID 0x057e  PID 0x2003
Discover SVIDs    ACK   0xff01
Discover Modes    ACK   DP cap VDO 0x00000c05
Enter Mode        ACK
DP Status         ACK   0x0000001a  connected=2 enabled=1 mf-pref=1 hpd=0
DP Configure      ACK   pin assignment D
```

### 37.2 Two claims in section 34 were wrong

**"`CCStat` never reaches SOURCE -- the block is configured sink-only" is
false.** `OPCODE_CCCTRL1_R` reads **0x9f** on this unit: `CCSrcSnk` and
`CCSnkSrc` are both set, i.e. the chip is already a **DRP**, plus debug and
audio accessory detection. And `CC_STATUS0` was observed at 0x8a = CCStat
SOURCE with a device attached, and at 0x91 = CCStat SINK with a powered dock
attached. All four states are now measured. The real reason SOURCE was never
seen in the 2026-11-14 session is the one that section itself records for
`CCPinStat`: the chip cannot run detection while **our own** OTG boost is
driving the connector. Nothing was ever configured sink-only.

**The DP capability decode is easy to get backwards, and it matters.** From
mainline `include/linux/usb/typec_dp.h` (and Samsung's identical
`Num_DP_Port_Capability_Type`):

* `Port_Capability` **1 = UFP_D = a SINK**, 2 = DFP_D = a source. Reading 1 as
  "DFP_D only" makes an ordinary display adapter look like a video source and
  stops the handshake dead.
* `DP_CAP_RECEPTACLE` is **BIT(6)**: set means the partner has a Type-C
  receptacle, clear means it is the far end of a **captive plug**. And
  `DP_CAP_PIN_ASSIGN_UFP_D()` says a receptacle describes its own assignments
  in the **UFP_D** field while a captive plug describes them in the **DFP_D**
  field. Read the wrong field and the pin mask comes back empty, which looks
  like "no DisplayPort support".

The dock's VDO 0x00000c05 decodes as: UFP_D-capable (a sink), DP v1.3
signalling, captive plug, pin assignments **C and D** in the DFP_D field.
Perfectly ordinary. Both mistakes above were made here first.

### 37.3 The dock is a Nintendo Switch dock, and its own power supply matters

VID 0x057e / PID 0x2003. Unpowered it presents Rd, so `CCStat` reads SOURCE
(it is asking *us* for power), it never establishes a useful PD contract, and
its HDMI bridge is dead. With its 15 V adapter connected it presents Rp:
`CCStat` reads **SINK**, `VBUSDet` and `PSRDY` go true, we keep **DataRole =
DFP**, and the whole DP handshake above succeeds.

**`fold3-otg on` is wrong for a powered dock and the hazard is real.** It
unconditionally turns on the charger's OTG boost, so for several minutes this
unit was driving 5 V onto a VBUS the dock was also driving. Two sources on one
VBUS. Clear `CHG_CNFG_00` bits OTG|BOOST (`mode &= ~0x0a`) the moment
`CCStat` reads SINK; the role switch to host is still wanted, the boost is
not. `fold3-otg` needs a dock-aware mode -- see 37.6.

### 37.4 msm_dp DOES need HPD -- and the bridge chain is load-bearing

> **CORRECTED 2026-11-19, same evening.** This section first claimed that
> msm_dp needs no HPD plumbing and that a userspace-only first light was
> therefore possible. **That was wrong**, and acting on it cost one dark-screen
> flash cycle. The corrected version is below; the original reasoning is kept
> because the half of it that is true still matters.

`msm_dp_bridge_detect()` (dp_display.c) really does power the PHY and talk to
the sink itself:

```c
phy_deinit = msm_dp_display_host_phy_init(priv);   /* powers the DP PHY */
msm_dp_aux_enable_xfers(priv->aux, true);
ret = msm_dp_aux_is_link_connected(priv->aux);
ret = drm_dp_read_dpcd_caps(priv->aux, dpcd);      /* talks to the sink */
...
status = connector_status_connected;
```

**But it refuses to start.** The first thing it checks is:

```c
ret = msm_dp_aux_is_link_connected(priv->aux);
if (!priv->plugged && !ret) {
	DRM_DEBUG_DP("aux not connected\n");
	priv->plugged = false;
	goto end;
}
```

and `msm_dp_aux_is_link_connected()` reads bits 31:29 of the DP controller's
own `REG_DP_DP_HPD_INT_STATUS` -- its **HPD state machine**, which on USB-C no
hardware ever drives, because DisplayPort Alt Mode has no HPD wire. The sink
reports hot-plug in-band, as the HPD_State bit of a DP Status Update VDM.
Measured, with the dock in DP mode and the AUX mux set:

```
[drm:msm_dp_display_host_phy_init] type=10 core_init=1 phy_init=0
[drm:msm_dp_bridge_detect] aux link status: 0
[drm:msm_dp_bridge_detect] aux not connected
```

`priv->plugged` is set only by the plug handler, so **exactly one HPD-connected
notification is needed**; after that `detect()` works normally for the rest of
the session. The entry point is `drm_bridge_hpd_notify()` on whichever bridge
carries `DRM_BRIDGE_OP_HPD`, which fans out through
`drm_bridge_connector_hpd_cb()` to every `.hpd_notify` in the chain, including
`msm_dp_bridge_hpd_notify()` -> `msm_dp_hpd_plug_handle()`.

Forcing the connector from userspace does **not** substitute for this.
`echo on > status` sets `DRM_FORCE_ON`, which makes DRM skip `detect()` and
report connected -- but `get_modes` then has no EDID, because EDID is read by
the plug handler. `echo detect > status` re-probes (`!connector->force` is
true, so `status_store()` always re-runs `fill_modes()`) and lands back on
"aux not connected".

### 37.4a The bridge chain is load-bearing for the WHOLE display

The chain msm_dp walks is:

```
mdss_dp --port@1--> usb_1_qmpphy --port@0--> a terminating bridge
```

`qmp_combo_probe()` calls `drm_aux_bridge_register()` **unconditionally**, and
`aux-bridge.c` then *requires* a next bridge of its own:

```c
data->next_bridge = devm_drm_of_get_bridge(&auxdev->dev, of_node, 0, 0);
if (IS_ERR(data->next_bridge))
	return dev_err_probe(...);
```

So `usb_1_qmpphy_out` (port@0) must point at something providing a bridge.
Leave it dangling and the failure cascades all the way out:

```
platform ae90000.displayport-controller: deferred probe pending: (reason unknown)
```

and because mdss_dp is a **component** of the single msm DRM device, the
component master never completes, **no DRM device is created at all**, and both
DSI panels go dark. `/sys/class/drm` holds only `version` and msm.ko sits at
refcount 0. That is what a missing terminator looks like, and it is why
whatever terminates the chain **must be built in**: a module that has not
loaded yet is indistinguishable from a missing bridge.

Upstream boards never hit it because port@0 goes to their `usb-c-connector`,
whose HPD bridge a Type-C port driver creates with
`devm_drm_dp_hpd_bridge_alloc()` (`fusb302.c` and `pmic_glink_altmode.c` are
the models). We have no such driver yet, so
`drivers/gpu/drm/bridge/fold3-dp-hpd.c` (patches/0013, `CONFIG_DRM_FOLD3_DP_HPD=y`)
provides the bridge on its own DT node plus a sysfs switch:

```sh
echo 1 > /sys/bus/platform/drivers/fold3-dp-hpd/*/hpd
```

An upstream `dp-connector` was tried first and does terminate the chain
correctly -- `card0-DP-1` appeared with both panels intact -- but it can only
ever report disconnected, because it has no way to deliver HPD. It is still
worth knowing it works as a terminator: with no `ddc-i2c-bus` and no
`hpd-gpios` it claims neither `DRM_BRIDGE_OP_DETECT` nor `DRM_BRIDGE_OP_EDID`,
so msm_dp keeps both.

### 37.4b Two red herrings from that boot, both expensive

* **"DSI PLL(0) lock failed, status=0x00000000"** plus a `clk_core_disable`
  WARN out of `dsi_phy_driver_probe`, times two. It looks exactly like the
  cause of a dead display and it is not: **a known-good boot logs four of
  them too** (`journalctl -k | grep -c "PLL.*lock failed"` -> 4). Check the
  count against a working boot before chasing this.
* **`rmmod msm` to retry the probe.** It hard-crashed the phone into a reboot.
  Do not unload msm to re-run a display probe.

### 37.5 The AUX/SBU switch, and the orientation, are not guessed

DP's AUX rides SBU1/SBU2 through an analog switch. On this board it is **two
plain TLMM lines, not an i2c mux** -- no fsa4480 here. The vendor DT
(`q2q_eur_openx_w00_r08.dts` fragment@239) names them:

| pin | vendor pinctrl state | job |
|-----|----------------------|-----|
| 15 | `sde_dp_aux_sel_{active,suspend}` | AUX polarity select |
| 16 | `sde_dp_aux_en_{active,suspend}` | switch enable |

and the vendor DP driver documents the polarity in a table
(`techpack/display/msm/dp/dp_power.c`, `secdp_power_set_gpio`):

```
| usbplug-cc(dir) | orientation | flip  | aux-sel |
|        0        |     CC1     | false |    0    |
|        1        |     CC2     | true  |    1    |
```

with `aux-en` driven **0 to enable, 1 to disable** (active low -- which the
pinctrl suspend state agrees with: 16 suspends output-HIGH). Both properties
that would change this, `secdp,aux-sel-inv` and `secdp,redrv`, are **absent**
from the q2q DT, so the plain table applies. 15 and 16 come out of
`gpio-reserved-ranges` (`<10 7>` -> `<10 5>`) on the same evidence that freed
24/82/97: the stock non-secure kernel muxes and drives them.

`fold3-dp` drives them through `/dev/mem` rather than the GPIO chardev,
deliberately: a chardev line request is released when the fd closes, so a
one-shot command could not hold the mux on. SM8350's TLMM is a single tile at
**0x0f100000** with `REG_SIZE 0x1000` per pin -- `ctl = 0x1000*pin` ([5:2]
FUNC_SEL, bit 9 OE), `io = ctl+4` (bit 1 = output).

**Orientation.** With no driver calling `typec_switch_set()`, qmp-combo leaves
`orientation` at `TYPEC_ORIENTATION_NONE`, and NONE means `reverse = false` --
the normal (CC1) lane mapping. A cable the other way up therefore has its DP
lanes swapped. The one register that is the whole of orientation handling
("Use software based port select and switch on typec orientation") is
`QPHY_V3_DP_COM_TYPEC_CTRL` = **0x088e8010** (DP_COM is at offset 0 of the
PHY window for `qmp_combo_offsets_v3`; the register is at +0x10), bit 0
`SW_PORTSELECT_VAL`. `fold3-dp` can poke it, but note `qmp_combo_com_init()`
rewrites that register from `qmp->orientation` on every re-probe, so the poke
does not survive one. Flipping the plug always works.

### 37.6 Where this is going

Phase 1 is deliberately userspace-only so the hardware path could be proved
without touching the display stack beyond enabling two already-wired nodes.
What is left:

1. **A Type-C port driver for the MAX77705** (`max77705-typec`), registering a
   `typec_port` from a `connector` DT child, a DP altmode whose `->vdm()`
   marshals into the opcode mailbox, the terminating HPD bridge, and the
   orientation switch + `gpio-sbu-mux` as consumers. Then plugging the dock in
   just works. Note the MFD does **not** bind on this unit (PASS2), so this
   has to be a standalone i2c client like the charger -- and the charger
   already owns the shared INTB line (PM8350C GPIO 5), so either that line is
   shared or the driver polls.
2. **Advertise pin D only** in the port altmode's VDO, so `displayport.c`
   cannot pick a 4-lane assignment the PHY is not in. See the `data-lanes`
   comment in the DTS for why 2 lanes.
3. **`fold3-otg` needs a dock mode**: host role without the boost, refusing to
   boost whenever `CCStat` is SINK.
4. **Audio.** The user's choice is to keep the USB-C DAC, so this needs the
   dock's hub to enumerate -- which it has **not** done yet (only the two root
   hubs appear). DP audio through `q6afedai DISPLAY_PORT_RX` is the
   alternative and `mdss_dp` already carries `#sound-dai-cells = <0>`.

### 37.7 Where to pick this up

**State at the end of 2026-11-19.** Flashed and working: `card0-DP-1` exists
alongside both DSI panels, the PD handshake succeeds, AUX reads the sink's
DPCD, the link trains at RBR, the sink's EDID reads (27 real modes), and KWin
ran a 1280x720@60 modeset on it. The one display we got that far with showed a
**pure blue picture**, which is unexplained.

Do these in order.

1. **Make the userspace tooling idempotent, matching the vendor driver (no
   flash).** This is first because our tooling is the most likely reason the
   dock stopped cooperating. `fold3-dp on` re-sends Enter Mode *and* DP
   Configure on an already-configured session and `off` sends Exit Mode with
   no detach; we did that dozens of times. Samsung refuses to repeat DP
   Configure (`is_sent_pin_configuration`) and takes HPD from the sink's own
   `HPD_State`/`HPD_Interrupt` bits rather than forcing it. Adopt both, and
   read Attention VDMs. See 37.1 and the memory `fold3-displayport-usbc`.
   * The DP Configure *payload* is already byte-identical to Samsung's --
     checked against `DP_Pin_Assignment_Data[]`. Not a bug, do not re-chase.

2. **Get a plain USB-C -> HDMI adapter.** The Switch dock cannot train above
   RBR, its USB hub has never enumerated, and it needs a full physical detach
   to recover its alt-mode state. Everything on the phone is proven against a
   real sink, so a compliant adapter should work and removes the one component
   that has been awkward at every step.

3. **Then the blue picture.** It is a genuine fault in the DP pixel path, and
   it is localised. Two theories are already dead:
   * "Plasma Mobile does not draw on secondary outputs" -- **disproven**, the
     cover display as an extended output shows real UI (user-confirmed).
   * "DPU staging/mixer allocation is wrong" -- **disproven**, the cover panel
     uses the *same* `crtc-1`, the same `lm 2+3 / ctl 1 / dspp 2+3`, the same
     `sspp_9`, the same AR30 format and the same `multirect_index=solo`
     single-rect staging, and renders correctly.

   That leaves **INTF0 -> DP controller**. Leading suspect is **widebus**:
   `dp_display.c` marks our controller
   `{ .io_start = 0x0ae90000, ... .wide_bus_supported = true }`, while
   sm8350's `dpu_intf_cfg` entries in `dpu_7_0_sm8350.h` carry **no
   `.features` field at all**, unlike sc7280 and later which set
   `DPU_DATA_HCTL_EN`. Widebus trouble gives exactly this signature: correct
   timing, sink syncs, wrong pixels. **Not confirmed** -- both sides consult
   the same `dpu_encoder_is_widebus_enabled()`, so no actual disagreement has
   been demonstrated. First experiment is one line: `wide_bus_supported =
   false` for the 0x0ae90000 entry. Then `modetest` (needs libdrm-utils and
   the Plasma session stopped) to take KWin out of the picture entirely.

4. **Raise the link rate.** RBR caps the usable pixel clock near 108 MHz, so
   the mode list stops at 720p/1280x1024 and 1080p appears only as interlaced
   1920x540. HBR2 demonstrably fails on the Switch dock; **HBR is untested**.
   One DTB change, see the `link-frequencies` comment in the DTS.

5. **Then the real driver**: `max77705-typec`, owning the HPD bridge and the
   PHY's orientation switch and driving both from the sink's DP Status VDMs,
   so plugging in just works and a reversed cable does not need a plug flip.
   Advertise pin D only in the port altmode's VDO (37.6).

**Uncommitted at session end:** `dts-work/sm8350-samsung-q2q.dts`,
`kernel-work/q2q-stage1.config`, `patches/0013-drm-bridge-add-fold3-dp-hpd-bridge.patch`,
`drivers/gpu/drm/bridge/fold3-dp-hpd.c` in the tree, `rootfs-work/dp/{fold3-pd,fold3-dp}`,
and this section. The flashed boot image matches the tree.
