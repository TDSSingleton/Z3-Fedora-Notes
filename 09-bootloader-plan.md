> **HISTORICAL** — written during planning, before any code existed. Parts are now wrong.
> See [HANDBOOK.md](HANDBOOK.md) for the current state.

# The bootloader plan (Q2 — resolved into a scoped task)

Verified against the live repos on 2026-11-06. The headline: **uniLoader is the answer,
and the port is small** — roughly 60 lines across five files, plus three load addresses
that have to be determined on-device.

---

## 1. Options, checked and scored

### ❌ lk2nd — dead for us
`lk2nd`'s documented targets top out at **msm8996** (LG G5/V20, OnePlus 3/3T, Mi 5).
Its own docs say the newest supported class is SDM429/439/632. No SM8350, no Snapdragon
888 anywhere. Rule it out.

### ❌ U-Boot — not yet viable, and for an interesting reason
U-Boot's Qualcomm phone docs say the way to tell whether a SoC is supported is to look in
`drivers/clk/qcom/`. I listed it:

```
apq8016 apq8096 ipq4019 ipq5424 ipq9574 milos qcm2290 qcs404 qcs615 qcs8300
sa8775p sc7180 sc7280 sdm845 sm6115 sm6125 sm6350 sm7150 sm8150 sm8250 sm8550
sm8650 x1e80100
```

**No `sm8350`. Also no `sm8450`.** U-Boot jumps sm8250 → sm8550. (Note: the *Linux*
display clock controller does cover SM8350 — via the multi-SoC `dispcc-sm8250.c`. An
earlier revision of these docs drew a parallel between the two gaps; only U-Boot's is
real.)

Two further problems: U-Boot's documented test path is `fastboot boot u-boot.img`, and
**Samsung has no fastboot**; and its docs note "ABL is known to sometimes give bogus
entries in the memory node which can trip U-Boot up" — which matches the S22 port's
finding that *"the bootloader's DTB memory node had size 0"*.

Worth noting U-Boot *does* want exactly what we have: a `simple-framebuffer` with a
reserved-memory region labelled `cont_splash`. So if someone writes `clock-sm8350.c` for
U-Boot later, this reopens — and that would also satisfy Pocketblue's UEFI requirement.
**Park it, don't pursue it now.**

### ❌ A modified/patched ABL — not viable here, and not needed
Patched Qualcomm ABLs are real and well documented, but almost all of that work targets
devices where the **`Qualcomm Secure Boot` QFPROM fuse row is not blown** (notably some
Chinese OEM and OnePlus models). On those, XBL does not enforce ABL's signature and ABL
can be freely modified.

**This device is in the enforced case** — the download-mode screen reports
`Qualcomm Secure Boot: enabled`, which is that fuse. XBL verifies ABL against Samsung's
root-of-trust hash in fuses, so a modified ABL fails verification and will not run.
Unlocking does not change this: it relaxes *AVB* (ABL checking `boot`/`vbmeta`), not the
fuse-rooted chain above ABL. See [`03-boot-chain.md`](03-boot-chain.md) §1.

Two further reasons not to go near it:

1. **Recovery is probably impossible.** A bad ABL means EDL (9008), which needs a
   *signed* Firehose programmer for this SoC and OEM. Public reports for SM8350 Samsung
   are consistently negative — loaders that don't work, and programmers that need
   authorization nobody has. Unlike `boot`, ABL has no second chance.
2. **It would solve a problem we don't have.** Samsung's *unmodified* ABL already loads
   unsigned kernels after unlock — that is what the "unverified firmware" prompt is. Our
   problem is narrower: ABL merges its own DT overlay fragments into whatever DTB it
   loads. uniLoader sidesteps that by presenting itself *as a kernel* and carrying a DTB
   ABL never inspects. No signing required.

### ✅ uniLoader — viable, and cheaper than expected

The crucial discovery: uniLoader's Qualcomm **64-bit SoC support needs no SoC-specific
code at all.**

- `soc/qualcomm/` contains exactly one file: `msm8916.c`.
- `soc/Makefile` maps only `CONFIG_QC32_8916 → qualcomm/msm8916.o`. **There is no
  `SM8450` object.**
- Yet `soc/Kconfig` has a `config SM8450` stanza, and `board/samsung/` contains
  **`board-r0q.c`** (Galaxy S22, SM8450) and **`board-gts8wifi.c`** (Tab S8, SM8450),
  with `configs/r0q_defconfig` and `configs/gts8wifi_defconfig`.

So for a 64-bit Qualcomm target, `CONFIG_SM8450` is a pure Kconfig symbol that just
`select QUALCOMM`. All the device knowledge lives in the board file — and the board file
is tiny. Here is **the entire** r0q board file (517 bytes):

```c
static struct video_info r0q_fb = {
	.format  = FB_FORMAT_ARGB8888,
	.width   = 1080,
	.height  = 2340,
	.stride  = 4,
	.address = (void *)0xb8000000
};

static const struct device r0q_devices[] = {
	{ "simplefb", &r0q_fb, "fb" },
};

struct board_data board_ops = {
	.name = "samsung-r0q",
	.ops = { },
	.devices = r0q_devices,
	.num_devices = ARRAY_SIZE(r0q_devices),
	.quirks = 0
};
```

And the whole defconfig:

```
CONFIG_POSITION_INDEPENDENT=y
CONFIG_LINUX_KRNL_HEADER_IMG=y
CONFIG_SM8450=y
CONFIG_SAMSUNG_R0Q=y
CONFIG_TEXT_BASE=0x87000000
CONFIG_PAYLOAD_ENTRY=0x80b900000
CONFIG_RAMDISK_ENTRY=0xb6915000
```

Note `r0q`'s framebuffer address `0xb8000000` is exactly the `splash_region` address in
upstream `sm8450-samsung-r0q.dts`. **Ours is `0xE4000000`** — we already have it from
`cont_splash_region` in the `q2q` DTS.

---

## 2. The q2q port, concretely

Five files. Everything except the three addresses is already known.

### `soc/Kconfig` — add, copying the SM8450 stanza
```
	config SM8350
		bool "Support for QUALCOMM SM8350"
		select QUALCOMM
		help
		  Say Y if your device uses this Qualcomm SoC
```

### `board/Kconfig` — add
```
	config SAMSUNG_Q2Q
		bool "Support for Samsung Galaxy Z Fold 3"
		default n
		depends on SM8350
		help
		  Say Y if you want to include support for Samsung Galaxy Z Fold 3
```

### `board/samsung/board-q2q.c` — new, ~25 lines
```c
static struct video_info q2q_fb = {
	.format  = FB_FORMAT_ARGB8888,
	.width   = 2208,          /* main panel is natively LANDSCAPE */
	.height  = 1768,
	.stride  = 4,
	.address = (void *)0xe4000000   /* cont_splash_region, 35 MiB */
};
```
…plus the `device[]` / `board_data` boilerplate, `.name = "samsung-q2q"`.

### `board/samsung/Makefile` — one line
```
lib-$(CONFIG_SAMSUNG_Q2Q) += board-q2q.o
```

### `configs/q2q_defconfig` — 7 lines
```
CONFIG_POSITION_INDEPENDENT=y
CONFIG_LINUX_KRNL_HEADER_IMG=y
CONFIG_SM8350=y
CONFIG_SAMSUNG_Q2Q=y
CONFIG_TEXT_BASE=???
CONFIG_PAYLOAD_ENTRY=???
CONFIG_RAMDISK_ENTRY=???
```

---

## 2b. ✅ PORT WRITTEN AND BUILDING (2026-11-07)

Done — see [`uniloader-work/`](uniloader-work/README.md). Output:

```
uniLoader: Linux kernel ARM64 boot executable Image, little-endian, 4K pages
```

Image magic `41 52 4d 64` verified at offset 56, `_head` at `TEXT_BASE`, board linked in,
and upstream's `r0q_defconfig` still builds after our Kconfig/Makefile edits.

The three addresses were derived from the device, not guessed, and checked against all 35
reserved carve-outs plus live System RAM:

| Symbol | Value |
|---|---|
| `CONFIG_TEXT_BASE` | `0xa0200000` |
| `CONFIG_PAYLOAD_ENTRY` | `0xc0000000` (start of a 256 MiB clear window) |
| `CONFIG_RAMDISK_ENTRY` | `0xcc000000` |

They remain **unvalidated on hardware** — first boot is the test.

## 3. The one real unknown: three load addresses

`TEXT_BASE`, `PAYLOAD_ENTRY` and `RAMDISK_ENTRY` describe where ABL places things and
where uniLoader should put the kernel and ramdisk. These are **the only genuinely
unknown values in the whole port.**

Ways to determine them, cheapest first:

1. **`/proc/iomem` and `/proc/cmdline`** on the running stock device (needs root) — shows
   the real memory map and where the stock kernel landed.
2. **The stock boot image header.** Note boot image **v3/v4 dropped the load-address
   fields** (the bootloader fixes them), so this may not help directly — but the header
   version, page size and `os_version`/`os_patch_level` all need reading anyway for
   `mkbootimg`.
3. **Reserved-memory layout from the `q2q` DTS** — gives the carve-outs you must avoid.
   We already know `cont_splash` is at `0xE4000000`–`0xE6300000`.
4. **Compare against r0q's values.** SM8450 used `TEXT_BASE=0x87000000`. SM8350's DRAM
   base is also `0x80000000`, so something in the same neighbourhood is a reasonable
   first guess — but guessing here produces a silent hang, so measure rather than guess.
5. **Ask upstream.** Opening an issue on `ivoszbg/uniLoader` describing an SM8350 Samsung
   target is cheap and the maintainers have done this twice already.

`tools/00-collect-facts.sh` captures items 1 and 2 in its rooted section.

> **Note the r0q defconfig's `CONFIG_PAYLOAD_ENTRY=0x80b900000` has nine hex digits**
> (≈ 34 GB), which cannot be a real 4 GB-device address. It is probably a typo in the
> upstream repo for `0x80b90000` or `0x8b900000`. Don't copy it blindly — and it's a
> useful reminder to verify these values rather than trust them.

---

## 4. Fallback: the stock boot chain

The **Galaxy M52 5G** port (SM7325) boots mainline through the **stock** chain with **no
shim at all**, injecting a mainline DT into `vendor_boot` with its own `tools/vb_dtb.py`.
If that generalises to SM8350, it skips the uniLoader work entirely.

It is worth one experiment early in Phase 1, because the payoff is large and the cost is
one flash cycle. But treat uniLoader as the plan of record — two SM8450 Samsung devices
prove that path works, and only one SM7325 device suggests the other might.

---

## 5. Revised risk

Q2 was one of the two project-killing unknowns. It is now:

| | Before | After |
|---|---|---|
| Shim loader exists for SM8350 | unknown, possibly fatal | **no, but the port is ~60 lines + 3 addresses** |
| SoC-specific code needed | unknown | **none** (Qualcomm 64-bit needs no SoC file) |
| Framebuffer address | unknown | **known: `0xE4000000`, 2208×1768 ARGB8888** |
| Precedent on Samsung + Qualcomm | one tablet | **two SM8450 Samsung devices in-tree** |

**Neither remaining blocker is fatal.** The project's risk is now concentrated where it
belongs: the two panel drivers, touch, and Wi-Fi firmware extraction.
