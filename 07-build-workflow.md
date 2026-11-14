> **HISTORICAL** — written during planning, before any code existed. Parts are now wrong.
> See [HANDBOOK.md](HANDBOOK.md) for the current state.

# Build and debug workflow

Practical mechanics: what to install, how to lay the tree out, and how to keep the
edit→flash→observe loop short. A slow loop is the main thing that kills ports like this.

Host here is **Fedora 44, kernel 7.2.4, x86_64**. `git`, `adb`, `fastboot` and `mkbootimg`
are already present; `heimdall` and `abootimg` are not.

---

## 1. Host setup

```bash
# Cross toolchain + kernel build deps
sudo dnf install -y gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu \
    clang llvm lld bc bison flex openssl-devel elfutils-libelf-devel \
    ncurses-devel dtc rpm-build

# Android / Samsung flashing + image tools
sudo dnf install -y android-tools   # adb, fastboot
pip install --user avbtool          # or build from AOSP external/avb

# Odin for Linux: the official v4 CLI (`odin4`) is distributed via XDA, not packaged.
# Heimdall is the open-source alternative:
sudo dnf install -y heimdall        # verify availability; may need COPR or source build
```

**Target kernel: v7.2.15** — that is Fedora 44's *and* Fedora 45's base
(`7.2.15-200.fc44` / `7.2.15-300.fc45`). Don't develop against a mainline `-rc`; it's
useful as a secondary check for upstreamability, not as the thing you ship.

Two trees are set up in this repo (both git-ignored, both re-clonable):

```
linux-fedora/   v7.2.15     <- primary target, Fedora 44/45 base
linux/          v7.4.0-rc1  <- mainline, for upstreamability checks only
```

`tools/build-panel-test.sh` defaults to the Fedora tree. It is a *single translation
unit* build, which is the fast way to check code against real headers:

```bash
./tools/build-panel-test.sh                 # against v7.2.15
./tools/build-panel-test.sh "$PWD/linux"    # against mainline
```

Caveat worth stating: `linux-fedora` is upstream stable v7.2.15, not Fedora's *patched*
tree. For driver-API purposes that's an extremely close proxy, and Fedora's patches don't
touch the DRM panel APIs. If you ever need full fidelity, `dnf download --source kernel`
gets the real SRPM.

**On toolchains:** build with **LLVM**, not GCC. Both Samsung precedents do
(`make ARCH=arm64 LLVM=1`), Qualcomm's downstream kernels are clang-built, and you will
hit fewer surprises. Ignore the Samsung README's advice to use the ancient
`aarch64-linux-android-4.9` GCC — that's only for building their 5.4 tree.

**USB access without root** — add udev rules for Samsung's vendor ID (`04e8`), covering
both normal and download mode:
```
SUBSYSTEM=="usb", ATTR{idVendor}=="04e8", MODE="0666", GROUP="plugdev"
```

---

## 2. Suggested tree layout

```
Fold3Playground/
├── README.md, 0*-*.md          # these docs
├── SM-F926B/                   # Samsung GPL drop (reference only — never build for the device)
│   ├── Kernel/                 # 5.4.274 lahaina. The source of truth for registers & init seqs.
│   ├── Platform/
│   └── Baseband/
├── linux/                      # your mainline fork + patches  (git)
├── uniloader/                  # shim bootloader, if Q2 says yes  (git)
├── firmware-q2q/               # EXTRACTED vendor firmware — never commit, never publish
├── backups/                    # EFS, persist, modemst*, stock boot/vbmeta — never commit
├── images/                     # built boot.img, rootfs
└── tools/                      # repack/flash/extract scripts you write
```

Two rules worth enforcing from day one:

- **`SM-F926B/` is read-only reference.** You are not building that kernel for the device.
  You read it to learn register layouts, clock tables and DCS init sequences.
- **`backups/` and `firmware-q2q/` never go into git.** `EFS` contains identifiers unique
  to your device, and the firmware is Qualcomm's. Add a `.gitignore` before the first
  `git init`.

---

## 3. Mining the Samsung source

This is where most of the real information lives. The highest-value paths:

| Path | What you need from it |
|---|---|
| `Kernel/drivers/clk/qcom/dispcc-lahaina.c` | Register reference only — upstream dispcc already covers SM8350 |
| `Kernel/drivers/clk/qcom/gcc-lahaina.c` | Cross-check upstream `gcc-sm8350` |
| `Kernel/techpack/display/msm/samsung/S6E3XA2_AMF755ZE01/` | Main panel DCS init sequences |
| `Kernel/techpack/display/msm/samsung/S6E3FAB_AMB623ZF01/` | Cover panel DCS init sequences |
| `Kernel/arch/arm64/boot/dts/samsung/q2/q2q/*.dts` | Board topology, GPIOs, I²C/SPI addresses, revisions r01–r08 |
| `Kernel/arch/arm64/boot/dts/vendor/qcom/lahaina*.dtsi` | SoC-level reference (e.g. `wlan` node at `lahaina.dtsi:5381`) |
| `Kernel/drivers/battery/` | `sec-battery`, `s2asl01` dual-cell topology (research Q4) |
| `Kernel/drivers/net/wireless/cnss2/` | QCA6490 PCI IDs, firmware paths, init |

Useful habit: `rg`/`grep` the techpack sources for a DCS command byte to find where and
why a sequence is sent. The panel drivers you write are mostly a translation exercise
from these files into `mipi_dsi_dcs_write_buffer()` calls.

Licensing note: the Samsung kernel is GPL-2.0, so lifting register tables and init
sequences into a GPL-2.0 upstream driver is fine. Translating, attributing and
reformatting into upstream style is normal practice and is how most of these drivers get
written.

---

## 4. Build loop

### Kernel
```bash
cd linux
export ARCH=arm64 LLVM=1
make q2q_defconfig           # your defconfig, once it exists
make -j"$(nproc)" Image.gz dtbs modules
```

Your DTB: `arch/arm64/boot/dts/qcom/sm8350-samsung-q2q.dtb`

### Boot image

If using uniLoader (expected — see [03-boot-chain.md](03-boot-chain.md)):
```bash
gunzip -c arch/arm64/boot/Image.gz > ../uniloader/blob/Image
cp arch/arm64/boot/dts/qcom/sm8350-samsung-q2q.dtb ../uniloader/blob/dtb
cp ../images/initramfs                              ../uniloader/blob/ramdisk
cd ../uniloader && make ARCH=aarch64 CROSS_COMPILE=aarch64-linux-gnu- q2q_defconfig && make
# -> ./uniLoader, an "ARM64 boot executable Image" that ABL accepts as a kernel

mkbootimg --header_version 4 \
  --os_version 13.0.0 --os_patch_level 2025-04 \
  --kernel ./uniLoader --ramdisk <stock-ramdisk> --cmdline '' \
  -o ../images/boot.img
```

**[3P]** Preserve the stock `os_version` / `os_patch_level` values — the Tab S8 port says
to, and anti-rollback cares. Read them off the stock boot image first.

### Flash
- **First time:** Odin, with a verification-disabled vbmeta in the same session:
  ```bash
  tar -H ustar -cf ap.tar boot.img vbmeta.img
  odin4 -a ap.tar -u vbmeta_disabled.tar
  ```
  (`vbmeta_disabled.tar` built with `avbtool ... --flags 3`.)
- **Every time after:** the `dd` loop in [03-boot-chain.md](03-boot-chain.md) §7, over
  `adb` or `ssh`. Hash before and after, resolve the partition by name. Never hardcode
  `/dev/block/sdaNN`.

---

## 5. Getting a console — in order of usefulness

1. **UART.** If a test point exists (research Q12), this is worth whatever it takes to
   find. It's the only thing that shows you failures *before* the kernel can run code,
   which is exactly where early porting fails. `qcom,msm-geni-serial-hs` is in the DTS.
2. **`simple-framebuffer`.** `cont_splash_region` @ `0xE4000000`, 35 MiB. Gives a visible
   console with no display driver, as `sm8450-samsung-r0q.dts` does. Add `clocks` and
   `power-domains` to the node or the bootloader's scanout gets torn down **[3P]**.
   Pair with `fbcon` + `earlycon`.
3. **USB gadget + SSH.** The workhorse once USB is up: `g_ether`/`usb_f_ncm`, static IP,
   `sshd` in the initramfs. Both Samsung precedents drive their devices over SSH at
   `172.16.42.1`.
4. **`ramoops` / pstore.** The Samsung DTS already declares a `ramoops` node — survives a
   reboot and will tell you about panics you never saw. Cheap to enable, repeatedly
   useful.
5. **`PSTORE_CONSOLE` + `CONFIG_PANIC_TIMEOUT`** so a crash reboots and leaves evidence
   rather than hanging on a black screen.

---

## 6. Debug hygiene

- `CONFIG_CMDLINE_FORCE=y` — ABL's command line cannot be trusted; the shim loader owns
  it anyway.
- `earlycon` from the first boot attempt, not after it fails.
- **Blocklist `qcrypto`** **[3P]** — reported to hang the phone through Samsung's
  TrustZone.
- **[3P]** Never unbind `msm-mdss` on a live system.
- Keep **TWRP permanently in the `recovery` slot** (a `q2q` build exists, credited to
  @Azkali). A rescue path that doesn't need Odin every time is worth a lot when you're
  flashing nightly.
- Keep a `git` branch per phase, and keep the panel drivers and board DTS as clean
  standalone commits from the start — you will want to post them upstream, and
  retrofitting cleanliness is much harder than maintaining it.

---

## 7. Known traps, collected

All from the three third-party Samsung ports; none verified on Fold 3 hardware, all cheap
to remember:

| Trap | Source |
|---|---|
| `qcrypto` hangs the device (Samsung TZ) — blocklist it | S22 |
| Bluetooth needs the **PMR735A L7** rail enabled | S22 |
| UFS needs `rootfs_image_sector_size=4096` | S22 |
| `dispcc` built-in garbled `simple-framebuffer`; build it as a **module** | S22 |
| Panel init: DCS `0x53` **before** `0x51`; DSC PPS sent once from `drm_dsc_config` | S22 |
| `simplefb` needs `clocks` + `power-domains` or scanout is torn down | Tab S8 |
| Bootloader's DTB `/memory` node had size 0 — supply explicit RAM ranges + `no-map` carve-outs | S22 |
| 2.4 GHz Wi-Fi association times out while 5 GHz works | S22 |
| `fastboot boot` does not exist on Samsung | all three |
