# Cameras

> **STATUS 2026-11-15: the rear ultrawide captures.** 4208x3120 10-bit raw
> Bayer off the IMX258 through mainline camss, with the sensor's own colour
> bars proving the path end to end -- see `samples/`. The full narrative is
> **HANDBOOK sections 33.9-33.11**; this file is the 2026-11-14 bring-up
> record and several of its conclusions below are superseded.
>
> What changed since this file was written:
>
> * **Three of five sensors have upstream drivers** (IMX258 ultrawide, IMX471
>   front, S5K3M5 tele) -- so "sensor init tables live in userspace HAL data"
>   is not the blocker it looked like. The cover module (IMX374) is one of the
>   two with none, which is why it is no longer the target.
> * **camss-sm8350 is ported** (`patches/0010`): Titan 580 is register-identical
>   to SM8250's 480, so `vfe_ops_480` + `csid_ops_gen2`, not `vfe_ops_170`.
> * **`imx258.c` never implemented `reset-gpios`** (`patches/0011`) -- that, not
>   the i2c address, is why the first probe NAKed.
> * **GDSC flags come from the vendor DT**, not from camcc-sm8250 by analogy.
> * **Open bug:** each IFE GDSC powers up once per boot (HANDBOOK 33.11).
>
> Tools added: `port-csiphy-sm8350.py` (self-validating), `sensor-rig/`,
> `capture-uw.sh`, `raw2png.py`, `gdscdump.py`, `check-camss.sh`.


Status: **not ported.** But the two reasons the repo used to give for not trying
were both wrong, and this directory holds the ground truth for anyone who
picks it up.

Everything here was measured on 2026-11-14 on this device, either from
mainline over SSH or from stock Android over adb. Nothing in it is inferred
from a .dts text parse -- see "How this was measured" for why that matters.

## 1. Unlocking does NOT disable the cameras

The old claim ("Cameras are disabled by the unlock itself") traced to an XDA
headline that `05-research-gaps.md` openly admitted was never read past the
title. It is **false** for SM-F926B on this firmware.

Tested with `verifiedbootstate=orange`, `flash.locked=0`, `warranty_bit=1`
(Knox blown), Android 15:

* `dumpsys media.camera` -> `Number of camera devices: 4`, twelve provider IDs
  registered (0,1,2,3,4,20,21,23,52,71,73,92).
* The camera app opened device 20 and **streamed**:
  `CAM_START_DEV Success, sensor_id:0x555` ->
  `cam_sensor_wait_stream_on: [CNT_DBG] 0x555 : Last frame_cnt 0xb` ->
  `CAM_STOP_DEV Success`.
* Sensor IDs read off the silicon: `read id: 0x555 expected id 0x555`,
  `read id: 0x258 expected id 0x258`.
* Every module's calibration EEPROM read and CRC-checked at boot.

Nothing in `SM-F926B/Kernel/techpack/camera/` gates on bootloader or Knox
state either: no warranty-bit, FRP or unlock check, and
`csiphy_info[].secure_mode` is per-request, defaulting to
`CAM_SECURE_MODE_NON_SECURE` -- the iris/face-unlock path, not a capture gate.

## 2. What this unit actually has

Module IDs and types are read from the modules' own EEPROMs at boot
(`module-ids.txt`), and `rear_camtype` agrees with the ID read off the
silicon. Note the **hardcoded fallback** strings in
`cam_sysfs_init.c` (`rear_type_show` -> `"SONY_IMX563"`) disagree and are not
what this unit reports -- do not use them.

| slot | part | module id | bus | csiphy | mclk |
|---|---|---|---|---|---|
| rear wide | **SONY IMX555** (`0x555`) | SVOHC17BE000112 | cci0 m0 | 0 | 19.2 MHz |
| rear ultrawide | SONY IMX258 (`0x258`) | CVOHR0604003003 | cci1 m0 | 4 | 19.2 MHz |
| rear tele | **HYNIX HI1337** (dual-sourced w/ S5K3M5) | — | i2c@a8c000, `reg = 0x5a` | 2 | 19.2 MHz |
| front | SONY IMX471 | PVOHG15520A0F05 | cci0 m1 | 5 | 19.2 MHz |
| front-top (cover) | SONY IMX374 | MVOHS1330000F01 | **i2c@998000** | 3 | **24 MHz** |

**Slave addressing is not settled, and guessing it will cost you a session.**
The nodes carry two different conventions and I did not resolve which the
driver uses per device type:

* `qcom,eeprom*` have **both** `slave-addr = <0xa2>` (8-bit, so 7-bit `0x51`)
  **and** `reg = <0x03>`. `0x03` is in the i2c reserved range, so it cannot be
  a real bus address -- Qualcomm's eeprom driver must use `slave-addr`.
* `qcom,cam-sensor11/13` have **only** `reg = <0x11>` / `<0x13>`, and
  `qcom,cam-sensor3` only `reg = <0x5a>`, with no `slave-addr`. Whether those
  are 7-bit addresses or want the same `>>1` treatment is **unverified**.

Resolve this from `techpack/camera/.../cam_sensor_dev.c` and
`cam_eeprom_dev.c` (the i2c, non-CCI probe paths) before trusting an address.
It did not matter for the probe described in section 4, because that scan swept
`0x03`-`0x5b` and every address timed out identically.

Full resolved topology, rails, voltages and power sequences:
[`topology-from-live-dt.txt`](topology-from-live-dt.txt).

## 3. Rails (ground truth, phandles resolved exactly)

All camera rails come from the **main S2MPB02** on `i2c-0`, which mainline
already reaches bare (`i2cget -f -y 0 0x59`). LDO*n* CTRL = `0x1e + (n-1)`;
bit 7 enables; LDO1-5 are 600 mV + 12.5 mV*sel, LDO6-18 are 600 mV + 25 mV*sel.

They read back **off but pre-programmed to these exact voltages**, and are
writable. Nothing is fused or TZ-owned.

| slot | cam_vdig | cam_vio | cam_vana | extra |
|---|---|---|---|---|
| sensor0 (rear wide) | ldo3 1.100 V | ldo7 1.800 V | ldo14 2.825 V | custom1 ldo1 1.1 V, custom2 buck2 1.3 V |
| sensor1 (front) | ldo5 1.050 V | ldo9 1.800 V | ldo15 2.800 V | custom1 buck2 1.3 V |
| sensor2 (ultrawide) | ldo4 1.200 V | ldo6 1.800 V | ldo12 2.700 V | custom1 buck2 1.3 V |
| sensor3 (tele) | — | ldo6 1.800 V | ldo17 2.800 V | custom1 buck2 1.3 V |
| sensor11/13 (cover) | ldo3 1.050 V | ldo7 1.800 V | ldo13 2.800 V | — |
| eeprom11 (cover cal) | — | ldo7 1.800 V | — | only rail it needs |

## 4. Why the first mainline probe failed -- and the fix

`dts-work/sm8350-samsung-q2q.dts` enables `&i2c6` (`i2c@998000`) and frees
TLMM 28/29. That part **works**: the bus appears as a numbered i2c adapter
with no pinctrl complaint. Upstream's `qup_i2c6_default` already matches the
vendor's `qupv3_se6_i2c_active` byte-for-byte.

But every transfer on it times out at exactly ~1.01 s and fails, while the
same probe on a sibling GENI bus NAKs in 2 ms. `998000.i2c` interrupts *do*
advance (the abort path after the timeout, not a completion), so the
controller runs and the bus never reaches idle. Rails were not the problem --
LDO3/LDO7/LDO13 at the right voltages made no difference, and the rails and
the `0x51` address were later confirmed correct.

**What was missing, from `qcom,cam-sensor11`:**

```
gpio-req-tbl-label = "CAMIF_MCLK3", "VT10M2_RST_N"
gpios              = <&tlmm 103>, <&pca953x@22 21>
gpio-reset         = 1          # index 1 -> VT10M2_RST_N is the reset
```

1. **Module reset `VT10M2_RST_N` is expander gpio 21**, on the PCAL6524 at
   `0x22` -- the bitbanged expander bus mainline **already drives** (`i2c-3`).
   Held asserted, the whole module including its EEPROM stays mute.
2. **`CAMIF_MCLK3` is TLMM 103 at 24 MHz**, which needs `camcc`. Many modules
   gate their i2c pads on MCLK, so this may be required even for the EEPROM.

The stock side proves the hardware is fine: `front2_moduleid =
MVOHS1330000F01` was read from `eeprom11` at `0x51` over this very bus.

### Result: the reset WAS the dead bus. MCLK is what is left.

Ran 2026-11-14 (`cover-cam-probe.py`), rails up, reset released through
`/dev/gpiochip3` line 21:

| probe | reset asserted | reset released |
|---|---|---|
| `i2c-6` 0x51 | **1.002 s** (geni timeout) | **0.002 s** |
| `i2c-6` 0x50 / 0x11 / 0x13 | — | 0.003 / 0.004 / 0.003 s |
| control (sibling GENI bus) | 0.003 s | 0.003 s |

**The bus went from a hard 1-second timeout to millisecond NAKs the moment the
module came out of reset.** Held in reset the module clamps SDA/SCL, so the
controller never saw the bus idle -- which is exactly the signature we saw, and
nothing to do with rails or pinctrl. That diagnosis is settled.

**But nothing answers yet.** 0x51, 0x50, 0x11 and 0x13 all NAK cleanly, so the
bus is electrically healthy and empty-looking. The remaining blocker is
**`CAMIF_MCLK3` -- TLMM 103 at 24 MHz** -- which this module needs before its
i2c slave will respond, and which requires **`camcc`**.

So `camcc-lahaina` -> mainline is now the critical path, and it is the
mechanical part: 3079 lines of vendor driver, a 3131-line mainline sibling
(`camcc-sm8450.c`) to pattern-match against, and `tools/port-dispcc.py` built
for exactly this substitution.

**Do NOT write the expander's registers by hand.** Closing a gpio line fd does
not return a pca953x line to input, so the first version of this probe
"restored" port2 bit 5 with `i2cset` on `0x22`. The `pca953x` driver bound to
that chip keeps a **regmap cache**, so those writes desynced it -- and
afterwards gpiolib's own direction write was skipped as redundant. Every later
reset release silently did nothing: the pin stayed an input, reset stayed
asserted, and three probe runs measured nothing while looking like camera
failures. Only a reboot resynced it.

Rule: on `0x22`, **read** freely (`i2cget` of `0x02`/`0x06`/`0x0e` is the right
way to verify a pin), and drive **only** through `/dev/gpiochip3`. The
S2MPB02 at `i2c-0` is the opposite case -- that bus is deliberately
driverless, so `i2cset` there is the normal method.

## 5. camcc: ported, and working on the device

`camcc-sm8350.c` is generated from Qualcomm's `camcc-lahaina.c` by
[`port-camcc.py`](port-camcc.py) and checked by
[`verify-camcc.py`](verify-camcc.py). Install into a tree with
[`install-camcc.sh`](install-camcc.sh) (driver + bindings header + Kconfig +
Makefile, idempotent).

**Status: built in (`CONFIG_SM_CAMCC_8350=y`) and verified on the device** --
see the result subsection below. Compiles clean at `W=1` with zero warnings;
the only undefined symbols are mainline exports (`clk_alpha_pll_lucid_5lpe_ops`,
`clk_alpha_pll_zonda_ops`, `clk_lucid_5lpe_pll_configure`,
`clk_zonda_pll_configure`, `qcom_cc_map`, `qcom_cc_really_probe`).

It is `=y`, not `=m`, on purpose: `build-kernel.sh` ships no modules, so a
loadable camcc would never reach the device from a boot-image flash. The symbol
lives in `kernel-work/q2q-stage1.config`, because that script re-runs
`make defconfig` and re-merges the fragment -- a `scripts/config` edit would be
silently discarded.

**Why generate from the vendor file rather than patch a sibling.**
`camcc-sm8250.c` is the closest mainline relative -- 102 of 119 clock names
shared, same 33 RCGs -- but SM8350 adds a third IFE (8 clocks), two PLLs
(pll5/pll6 + postdivs) and a split SBI (5 clocks), and drops the FD block,
mclk6, `cam_cc_gdsc_clk` and `cam_cc_pll2_out_main`. Every offset, frequency
table and parent map would still have to be substituted, and a mainline
leftover could survive silently. `camcc-sc8280xp.c` was also tried as a base
and is worse (88 shared). So the vendor file is the source of truth and the
script strips the downstream scaffolding instead.

`verify-camcc.py` then re-reads both files and asserts that **every clock,
register value, frequency table and parent map is byte-identical to the
vendor's**, with only the two intentional deltas whitelisted. It reports
119 clocks, 18 freq tables, 8 parent maps, all matching.

**The non-obvious bits, each of which was a bug first:**

| issue | what was wrong | fix |
|---|---|---|
| PLL revision | The vendor probe calls a `fixup()` that reconfigures pll2 with `cam_cc_pll2_config_lahaina_v2` when the compatible is `qcom,lahaina-camcc-v2` -- **which is exactly what the Fold 3's DT says**. Generating naively used the v1 config, differing in `config_ctl_val`, `config_ctl_hi_val` and `config_ctl_hi1_val`. | use v2, delete v1 |
| always-on clock | The vendor probe does `regmap_update_bits(regmap, 0xc148, BIT(0), BIT(0))` -- "keep `cam_cc_gdsc_clk` enabled". That is why SM8350 has no `CAM_CC_GDSC_CLK` even though sm8250 does. Dropping the vendor probe lost it. | write added to probe |
| test clock | Mainline omits `core_bi_pll_test_se` entirely (sm8250: zero references) and no DT provides it, so keeping it gave all 33 RCGs an unresolvable `fw_name` parent. It is the **last** entry of every map/array, so removal leaves other indices untouched. | strip + `num_parents - 1` |
| suffixed array | `cam_cc_parent_data_7_ao` (for `bi_tcxo_ao`) also carries the test entry. A `\d+`-only regex matched **32 of 33** clocks and silently left that one's `num_parents` too high. | allow a `_ao` suffix |
| `max_register` | guessed `0x1400c`; the vendor says `0xf008` | use the vendor's |
| 5LPE idiom | mainline has no `LUCID_5LPE`/`ZONDA_5LPE` *type* enum and no `zonda_5lpe` ops -- it expresses 5LPE via vco table + ops, as `gpucc-sm8350.c` does. The two Zonda enable sequences are equivalent and mainline's is stricter (explicit 1 us between de-bypass and reset de-assert); the FSM-vote fast path only applies to voted PLLs, which camcc's are not. | plain types + `lucid_5lpe` / `zonda` ops |

**GDSCs** are not in the vendor *driver* at all -- downstream declares them as
separate `qcom,gdsc@ad0.....` DT nodes. Offsets taken from the vendor DT, and
they turn out identical to camcc-sm8250's except `titan_top` (`0xc144` ->
`0xc120`) and the added `ife_2` (`0xb070`).

**Before testing, note the module trap:** `build-kernel.sh` does not ship
modules, so a `=m` camcc will not reach the device from a boot-image flash
alone -- build it in, or install the `.ko` (see
[[fold3-build-kernel-skips-modules]] / `tools/build-kernel-modules.sh`).

### camcc result: works. MCLK runs. The EEPROM still does not answer.

Measured 2026-11-14 with `camcc-sm8350` built in:

* driver bound at `ad00000`, **119 clocks**, **7 GDSCs** with the right
  topology (`titan_top` parenting bps/ipe_0/sbi/ife_0/ife_1/ife_2)
* PLLs all correct: pll0 1200, pll1 600, **pll2 960** (= 50 x 19.2, i.e. the
  **v2** config is the one being applied), pll3/4/5 676, pll6 960 MHz
* `clk_set_rate(cam_cc_mclk3_clk, 24000000)` -> exactly 24000000 Hz
* TLMM 103 verified by register read: `FUNC_SEL=1` (cam_mclk), drive-strength
  4 mA, no pull -- matching the vendor's `cam_sensor_mclk3_active`

`clk_prepare_enable` first returned **-EBUSY**, and a 5-clock experiment
localised it exactly: `cam_cc_core_ahb_clk` and `cam_cc_sleep_clk` enable
fine; `cam_cc_cpas_ahb_clk`, `cam_cc_camnoc_axi_clk`, `cam_cc_cci_0_clk` and
`cam_cc_mclk3_clk` all fail -- i.e. precisely the `titan_top_gdsc` set, which
sat `off-0` with no consumer. A GDSC is a genpd and only powers up for an
attached device, so the fix was a DT consumer (`camcc-mclk-test`), not a
driver change. With it: domain `on`, MCLK enabled.

**With all four preconditions provably satisfied -- rails up, MCLK3 at 24 MHz,
reset released (verified `dir=OUT level=1` by reading `0x22`), bus alive
(1.022 s -> 0.001 s) -- a full 0x03-0x77 scan finds NOTHING**, in 8-bit or
16-bit addressing. That is a clean negative, unlike the three runs before it.

**Strongest unexplored lead:** the vendor pinctrl has
`cam_sensor_active_ext_regs0` / `..._ext_regs1` states. "ext_regs" reads as
**GPIO-driven external regulator enables** -- a load switch gating module
power that the DT's three rails do not describe. That was flagged in section 4
and never followed up, and it would explain a module that is powered "per the
DT" yet electrically absent. Also still unverified: that MCLK is physically
oscillating on the pin (framework state and mux are confirmed; the waveform is
not), and whether Samsung's `front2_moduleid` really corresponds to
`eeprom11`.

**Previously the first thing to check:** that the 7 GDSCs and 119 clocks
register, then set `cam_cc_mclk3_clk` to 24 MHz and re-run
`cover-cam-probe.py`. That is the exact gap section 4 identified.

## 6. The ceiling, so nobody is surprised later

Mainline `camss` is a **CSI receiver, not an ISP**. It emits raw Bayer
(`SBGGR10P`/`SRGGB12P`) to memory. There is no IPE/BPS/ICP driver (`icp_ahb`
is only a clock it ungates), so Titan 580's image-processing hardware stays
dark and demosaic + 3A are software. The realistic outcome is a camera that
takes recognisable pictures, not One UI output. Stock's quality comes from the
hardware ISP, per-module tuning, and multi-frame stacking -- none of which
mainline has.

Upstream also has no `qcom,sm8350-camss` and no `camcc-sm8350`. But SC8280XP
is the same CAMSS generation (q2q `csiphy-v1.2.3` @`0xac6a000`, `csid580`
@`0xacb5200`; sc8280xp @`0xac65000`/`0xacb3000`) and mainline drives it with
**existing** `csid_ops_gen2` + `vfe_ops_170`. So the port is a resource table,
a `camcc` port and DT -- not new hardware ops. `camcc-lahaina.c` (3079 lines)
is in the Samsung drop; mainline's `camcc-sm8450.c` is 3131; and
`tools/port-dispcc.py` exists for exactly this register-map substitution.

## How this was measured

`dt-camera-map.py` walks `/sys/firmware/devicetree/base` pulled off the
running stock kernel as a **filesystem** -- one file per property -- so
phandle -> node resolution is exact.

This matters because the first attempt at this table parsed the decompiled
merged `.dts` with naive brace tracking, silently mapped two distinct
phandles onto the same regulator, and produced a wrong rail map that was then
acted on. If you need a DT fact here, get it from the filesystem form.

**The Fedora rootfs is NOT readable from Android**, despite what an earlier
version of `/root/fold3-restore/back-to-linux.sh` claimed. `ext4` is in the
Android kernel's `/proc/filesystems`, but mounting sda37 fails with
`Invalid argument` -- almost certainly incompat features that Fedora's modern
`mkfs.ext4` sets and a 5.4 kernel rejects. Restore from the PC instead:
`adb push` + `dd` ran at 96 MB/s. The staged image is still usable from TWRP,
which has current e2fsprogs.

```sh
adb shell 'su -c "cd /sys/firmware/devicetree && tar cf - base"' > dt.tar
tar xf dt.tar -C somewhere
python3 camera-work/dt-camera-map.py somewhere/base
```

`tools/cam-eeprom-probe.sh` runs the EEPROM probe from mainline. It finds
buses by `of_node` (they renumber between builds), enables `cam_vio`, probes,
and restores the rail on exit.
