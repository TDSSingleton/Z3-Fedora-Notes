# uniLoader `q2q` port — working directory

Our sources live here and are installed into a (git-ignored) `uniloader/` clone by
`install.sh`. Same pattern as `panel-work/`.

```bash
git clone --depth 1 https://github.com/ivoszbg/uniLoader.git uniloader
./uniloader-work/install.sh "$PWD/uniloader" --build
```

| File | What |
|---|---|
| `board-q2q.c` | board definition — framebuffer descriptor + `board_data` |
| `q2q_defconfig` | SoC/board selection + the three load addresses |
| `install.sh` | idempotently patches `soc/Kconfig`, `board/Kconfig`, `board/Makefile`; installs both files; optionally builds |

## Status — ✅ BUILDS (2026-11-07)

```
uniLoader: Linux kernel ARM64 boot executable Image, little-endian, 4K pages
63568 bytes (with placeholder payloads)
```

Verified:
- **Image magic** `41 52 4d 64` at offset 56 — a valid arm64 Image, which is the whole
  point: ABL must accept it *as a kernel*.
- `text_offset = 0`, `flags = 0xa` → 4K pages, placement "anywhere" (correct for PIE).
- `_head` lands at exactly `0xa0200000` = `CONFIG_TEXT_BASE`; `board_ops` and the
  `samsung-q2q` string are linked in.
- The upstream `r0q_defconfig` still builds after our changes, so the Kconfig/Makefile
  edits are non-breaking.

## How the addresses were derived

`PAYLOAD_ENTRY` is where the kernel Image is `memcpy`'d and jumped to; `RAMDISK_ENTRY`
likewise for the initramfs (and it is written into `chosen/linux,initrd-start`);
`TEXT_BASE` is uniLoader's own link address, nominal under
`CONFIG_POSITION_INDEPENDENT=y`.

The vendor boot image is **header v3, which has no load-address fields** — the bootloader
fixes them — so these could not be read from the stock `boot.img`. They were derived from
the device instead:

```
/proc/iomem       Kernel code  a00a0000-a28cffff   <- where ABL actually loads a kernel
                  Kernel data  a2da0000-a3d48fff
live System RAM   0xc0000000-0xd7ef6fff  (383 MiB, the largest usable low block)
reserved carve-outs  35 parsed from the captured merged post-ABL DT
```

| Symbol | Value | Reasoning |
|---|---|---|
| `TEXT_BASE` | `0xa0200000` | 2 MiB-aligned, inside `a0002000-b00fffff` where ABL demonstrably loads kernels. Nominal under PIE. |
| `PAYLOAD_ENTRY` | `0xc0000000` | 2 MiB-aligned; start of a **256 MiB clear window**; far from both the ~`0xa0000000` region ABL loads *us* into (so the `memcpy` can't eat its own source) and the `0xe4000000` splash framebuffer |
| `RAMDISK_ENTRY` | `0xcc000000` | 2 MiB-aligned; 192 MiB above the payload; 64 MiB of room before the `linux,cma` carve-out at `0xd0000000` |

All three were checked against every reserved region and against live System RAM:
2 MiB-aligned ✓, in RAM ✓, zero collisions ✓.

> **A note on that check.** The first version of the carve-out parser didn't handle
> `label: node {` syntax, so it mislabelled nodes — it reported `uh_guest_region` at
> `0xd0800000` when it is actually at `0xb0400000`, and it missed `splash_region`
> entirely. Fixing it changed the parsed count from 33 to 35 and moved the conclusion.
> If you re-derive these, use the corrected parse.

**We deliberately did not copy r0q's values.** Its `TEXT_BASE = 0x87000000` falls in a
carve-out gap on q2q (between `0x851fffff` and `0x88200000`), and its
`CONFIG_PAYLOAD_ENTRY = 0x80b900000` has nine hex digits — ~34 GB, which cannot be a real
address on this class of device. Treat that upstream value as a typo, not a template.

## ⚠️ TEXT_BASE: the trap that cost us attempt 2

`CONFIG_POSITION_INDEPENDENT=y` does **not** mean "runs anywhere". Read
`arch/aarch64/reloc.S`:

```
adr x4, _start            ; where we actually are (wherever ABL loaded us)
ldr x5, _rel_stack_base   ; where we are LINKED  (= TEXT_BASE)
cmp x4, x5; beq _entry    ; same address? just run
_copy: ldp [x4],#16 / stp [x5],#16   ; else COPY SELF to TEXT_BASE, forward
       br x5                         ; then jump there
```

uniLoader **relocates itself to a fixed `TEXT_BASE`**, and `_reloc_size` is the
*whole image* — loader + kernel + DTB + ramdisk. Ours is **42.2 MiB**
(`_reloc_size = 0x2a2a000`).

Attempt 2 used `TEXT_BASE = 0xa0200000`, chosen *because* that is where ABL loads
kernels. That is precisely the one region it must avoid: ABL put the 42 MiB image
at ~`0xa0000000`, so the copy wrote `0xa0200000..0xa2c29fff` over its own source,
forward, destination above source — shredding what it had not yet read, then
branching into rubble. Symptom: Samsung logo stays up, no USB, no pstore.

**Rules for `TEXT_BASE`:**
1. A clear window of at least `_reloc_size` (check it after every payload change —
   it grows with the kernel).
2. 2 MiB aligned.
3. **Must not overlap ABL's load region** (~`0xa0000000` + image size here).
4. Prefer *below* that region: a forward copy with destination < source is safe
   even if they do overlap.

`0x81200000` satisfies all four — start of a 64 MiB free block, 2 MiB aligned, no
carve-out collisions, entirely below `0xa0000000`.

And a concrete reason not to copy r0q's value: its `TEXT_BASE = 0x87000000` lands
inside `pil_adsp_region` **and** `pil_cdsp_region` on this device.

## NOT verified — the honest list

1. **These addresses have never been used.** They are derived and collision-checked, not
   observed. First boot is the test. If they're wrong the symptom is a device that does
   nothing — no output, no progress.
2. **ABL's actual load address for the boot-image kernel is inferred**, from where the
   stock kernel's text ended up (`0xa00a0000`). PIE should make this not matter; that is
   an argument, not a measurement.
3. **The build used placeholder blobs.** A real image needs `blob/Image`, `blob/dtb` and
   `blob/ramdisk` — none of which exist yet.
4. **No `sm8350-samsung-q2q.dtb` exists yet.** This is the next blocker.

## Recovery

uniLoader goes in the **`boot`** partition only. A bad attempt is recoverable: re-flash
the stock `boot.img` (captured at `capture/backup-*/tier2-recovery/boot.img`,
hash-verified) via Odin or `dd`. **Never** touch `xbl`/`abl`/`tz`/`aop` — see
[`../09-bootloader-plan.md`](../09-bootloader-plan.md).

## Next

1. **Write `sm8350-samsung-q2q.dts`** — the real blocker now. Critically it needs
   *explicit* `/memory` ranges and the Samsung `no-map` carve-outs: both the Galaxy S22
   port and U-Boot's own docs report Samsung bootloaders emitting bogus or zero-sized
   memory nodes. We have exactly the data to write this: 16 live System RAM ranges from
   `/proc/iomem` and 35 reserved regions from the captured merged DT.
2. Build a minimal initramfs (busybox + sshd is enough).
3. Assemble: real `blob/{Image,dtb,ramdisk}` → `uniLoader` → `mkbootimg --header_version 4`
   preserving `os_version 11.0.0` / `os_patch_level 2026-08` from the stock header.
4. Flash `boot` only, and watch for the simplefb console at `0xe4000000`.
