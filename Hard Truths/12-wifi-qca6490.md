# QCA6490 under `ath11k` — answering "couldn't we just port it?"

**Short answer: yes, and it's probably not a port at all — it's likely a small patch to
an existing driver, possibly zero code.** The real dependency is firmware, not code.

But the chip you spotted upstream is probably not the one you think, so the mechanism is
worth laying out.

---

## 1. The "similarly named driver" is a red herring (in a useful way)

Upstream `ath11k` has a hardware entry literally named **`qca6390 hw2.0`**, which is
almost certainly what you noticed. QCA6490 is the next chip in that product line, so the
natural guess is "clone the QCA6390 support."

That's not how it's wired. From the actual PCI ID tables:

| Chip | PCI device ID | Source |
|---|---|---|
| QCA6390 | `0x1101` | `ath11k/pci.c` **and** downstream `cnss2/bus.h` — they agree |
| QCN7605 | `0x1102` | `cnss2/bus.h` |
| **QCA6490** | **`0x1103`** | `cnss2/bus.h:21` (vendor `0x17CB`) |
| **WCN6855** | **`0x1103`** | `ath11k/pci.c:32` |

**QCA6490 and WCN6855 share one PCI device ID.** So a QCA6490 does not enumerate as a
QCA6390 at all — it comes up on `ath11k`'s **WCN6855** code path. Cloning QCA6390 would be
the wrong starting point; WCN6855 is the right one.

## 2. `ath11k` already demultiplexes that ID — and that's the whole trick

`ath11k_pci.c` handles `0x1103` by reading the chip's own version registers:

```c
case WCN6855_DEVICE_ID:
    ath11k_pci_read_hw_version(ab, &soc_hw_version_major, &soc_hw_version_minor);
    switch (soc_hw_version_major) {
    case 2:
        switch (soc_hw_version_minor) {
        case 0x00: case 0x01:
            ab->hw_rev = ATH11K_HW_WCN6855_HW20;  break;
        case 0x10: case 0x11:
            sub_version = ath11k_pcic_read32(ab, TCSR_SOC_HW_SUB_VER);
            switch (sub_version) {
            case 0x1019A0E1 ... 0x1019D0E1: ATH11K_HW_QCA2066_HW21;   break;
            case 0x001e60e1:                ATH11K_HW_QCA6698AQ_HW21; break;
            default:                        ATH11K_HW_WCN6855_HW21;
            }
            break;
        default: goto unsupported_wcn6855_soc;
        }
    ...
```

So `0x1103` is not one chip — it's a **family**, and `ath11k` already carries four
distinct members: `wcn6855 hw2.0`, `wcn6855 hw2.1`, `qca2066 hw2.1`, `qca6698aq hw2.1`.

**That's the precedent you're looking for.** QCA2066 and QCA6698AQ were each added as a
sub-version case plus a `hw_params` entry cloned from WCN6855. Adding QCA6490 the same way
is a well-trodden, small patch — not a new driver.

## 3. Resolved on this device: outcome A (the free one)

**Verified 2026-11-07.** Three independent signals all say hardware revision **2.0**:

| Evidence | Reading |
|---|---|
| `/vendor/firmware/qca6490/` contains **`amss20.bin`, no `amss.bin`** | downstream `cnss2/pci.c` picks `amss20.bin` **only** when `device_version.major_version == FW_V2_NUMBER` (== 2) |
| Bluetooth firmware is **`hpbtfw20.tlv` + `hpnv20.bin`** | upstream `btqca.c` builds `qca/hpbtfw%02x.tlv` with the `hp` stem for `QCA_WCN6855`/`QCA_QCA2066` → rom_ver `0x20` |
| PCI config space | `17CB:1103`, revision byte **`0x01`** |

Major version 2 is the branch `ath11k` supports, and minor `0x00`/`0x01` maps to
`ATH11K_HW_WCN6855_HW20` — **no driver changes at all.**

**Honest caveat:** this is strong *indirect* evidence, not a direct read. `ath11k` reads
`soc_hw_version` from a TCSR register, which we have not read. The clean confirmation is a
reboot plus an immediate `dmesg | grep -i cnss` — both the live ring buffer and
`/proc/last_kmsg` had already wrapped (`log_buf_len=256K`), so the boot-time probe
messages were gone by the time we looked.

### The original analysis, for reference

Everything hinges on what the chip reports.

**Outcome A — it reports major 2, minor 0x00/0x01.**
It already lands on `ATH11K_HW_WCN6855_HW20` with **zero code changes**. Give it the right
firmware and it may simply work.

**Outcome B — it reports something else** (a minor outside `0x00/0x01/0x10/0x11`).
It hits `unsupported_wcn6855_soc` → `-EOPNOTSUPP`. Then the patch is:
1. add the `soc_hw_version_minor` case (or `TCSR_SOC_HW_SUB_VER` sub-case),
2. add an `ATH11K_HW_QCA6490_HW*` enum value,
3. add a `hw_params` entry — realistically a copy of `wcn6855 hw2.x` with the firmware
   directory name and any differing register offsets / ring config adjusted.

There is a hint in your own source that QCA6490 has at least two silicon revisions, which
maps neatly onto that `minor` switch — `cnss2/reg.h` defines separate SBL data regions:

```c
#define QCA6490_V1_SBL_DATA_START 0x143b000
#define QCA6490_V2_SBL_DATA_START 0x1435000
```

Either way this is a **tens-of-lines patch**, not a driver.

## 4. Evidence it already works on a Samsung device

**[3P, needs confirming]** The Galaxy S22 mainline port reports Wi-Fi working under
`ath11k` *"with Samsung firmware/board file"*, and a sibling S22-Linux project has an open
issue titled *"Bluetooth: QCA6490 HCI transport, pairing..."* — which indicates the S22's
combo chip is a QCA6490. If so, **QCA6490 + `ath11k` is already demonstrated on Samsung
hardware**, which is about as good a signal as this project gets.

Caveat from that same port: **5 GHz works, 2.4 GHz association times out.** Budget for
that being a real, unsolved bug rather than a configuration mistake.

## 5. What the Samsung source does and doesn't give you

You said "you should have the source anyway" — partly true, and the gap is informative.

### ❌ What's missing: the WLAN host driver
I searched the whole drop for `qcacld-3.0`, `qca_cld`, `wlan_hdd` — **nothing.** Samsung
did not ship the Wi-Fi host driver in this GPL release (it's delivered as a prebuilt
module). So there is **no downstream datapath driver to port from.**

That turns out not to matter, because `ath11k` *is* that driver, written independently
against the same firmware API.

### ✅ What's present and genuinely useful: `cnss2`, the platform driver
`drivers/net/wireless/cnss2/` is the power/PCIe/MHI bring-up layer, and it's full of
exactly the board-level facts mainline needs:

| Finding | Where | Why it matters |
|---|---|---|
| QCA6490 needs an **`xo_clk_gpio`** that WCN6855 doesn't — *"to minimize XO CLK selection leakage"* | `main.h:100`, `power.c:789` | A real QCA6490-vs-WCN6855 difference. **Good news: `q2q` doesn't use it** — absent from both `lahaina.dtsi` and the `q2q` overlay. |
| PMU needs **≥100 ms between `BT_EN` off and `WLAN_EN`** | `power.c:968` | Power-sequencing constraint for the DT / driver |
| V1/V2 SBL + PBL log regions, `TCSR_PBL_LOGGING_REG`, `PBL_BOOTSTRAP_STATUS` | `reg.h:304-315` | Debugging a chip that won't boot |
| Firmware filenames | `cnss2/*.c` | See §6 |

### The complete power/GPIO description, ready for a device tree
From `lahaina.dtsi:5381` plus the `q2q` overlay — this is what an `ath11k` node needs:

```
PCIe root complex:  pcie0  (qcom,wlan-rc-num = <0>)
wlan-en-gpio:       tlmm 64
bt-en-gpio:         tlmm 65
sw-ctrl-gpio:       tlmm 153

vdd-wlan-aon   S2E    1.0125 V   (q2q override; lahaina says 1.012 V)
vdd-wlan-dig   S11B   1.0125 V
vdd-wlan-io    S10B   1.8 V
vdd-wlan-rfa1  S1C    1.984 V
vdd-wlan-rfa2  S12B   1.35 V
wlan-ant-switch L7E   2.8 V
```

That's most of a working DT node, already determined.

---

## 6. The actual bottleneck: firmware

This is where the work really is, and no amount of driver porting avoids it.

`linux-firmware` ships `IPQ5018 IPQ6018 IPQ8074 QCA2066 QCA6390 QCA6698AQ QCN9074
WCN6750 WCN6855` — **no `QCA6490`.** So firmware must come off your phone.

`cnss2` tells us what the files are called downstream, and they map onto what `ath11k`
wants:

| Downstream (Android `/vendor/firmware/`) | `ath11k` expects | Role |
|---|---|---|
| **`qca6490/amss20.bin`** | `amss.bin` | main Wi-Fi firmware — **rename on install** |
| `qca6490/m3.bin` | `m3.bin` | M3 coprocessor image |
| `qca6490/regdb.bin` | `regdb.bin` | regulatory database |
| `qca6490/bdwlan.elf{,1,2,10}` (4 × 59,900 B) | **inside `board-2.bin`** | per-device board data (BDF) |

The last row is the fiddly one. Samsung ships a **bare BDF**; `ath11k` wants a
**`board-2.bin` container** that can hold many BDFs, indexed by bus/chip/board ID
(`ATH11K_BDF_SEARCH_BUS_AND_BOARD`). You wrap a bare BDF using upstream's
**`ath11k-bdencoder`** tool, or match it via `qcom,ath11k-calibration-variant` in the DT.

Firmware goes in **`/lib/firmware/ath11k/WCN6855/hw2.0/`** (hw2.0 confirmed above).
**It is not redistributable**, so a Fedora image can't ship it — hence `droid-juicer`.

All of it is captured in `capture/firmware-*/vendor_firmware/firmware.tar`.

## 7. Bluetooth is a separate, easier story

Same silicon, different driver path: **`hci_qca`** over the high-speed UART
(`qcom,msm-geni-serial-hs`), with `BT_EN` on tlmm 65. Needs:
- BT firmware/NVM from `/vendor/firmware/` (`crbtfw*.tlv`, `crnv*.bin` family),
- **the BT MAC address, which lives in the `EFS` partition** — back it up,
- **[3P]** the **PMR735A L7** rail enabled; the S22 port says Bluetooth doesn't come up
  without it.

---

## 8. Revised verdict on Goal 2

| Component | Assessment |
|---|---|
| `ath11k` driver support | ✅ **Zero code** — hw 2.0 confirmed, lands on `WCN6855_HW20` |
| Device tree | **Largely already determined** (§5) |
| Firmware | ✅ **Extracted.** Remaining: rename `amss20.bin`→`amss.bin`, wrap the 4 BDFs into `board-2.bin`. Not redistributable. |
| Precedent | **[3P]** QCA6490 + `ath11k` reportedly working on Galaxy S22 |
| Known risk | 2.4 GHz association failures reported on S22 |

So your instinct was right, and better than right: this probably isn't a port at all. It's
a firmware-extraction problem with a possible small patch attached — which is why
**Goal 2 remains the cheapest of your three main goals**, and why the extraction work in
[11-extraction-plan.md](../11-extraction-plan.md) is the thing that actually unblocks it.

---

## 9. First bringup attempt, 2026-11-11: everything but the link

The verdict in §8 held up. Zero driver code was needed and the firmware was
already extracted. What it did not anticipate is that **the PCIe link never
trains**, and that is now the single open problem.

### What is proven working

| thing | evidence |
|---|---|
| GPIO 64/65/153 (wlan-en, bt-en, sw-ctrl) not TZ-owned | boots with them carved out |
| GPIO 94/95/96 (perst, clkreq, wake) not TZ-owned | boots with them carved out |
| pmr735a RPMh block (pmic-id "e") | `pmr735a_s2`, `pmr735a_l7` register and enable |
| `wcn6855-pmu` | binds `pwrseq-qcom_wcn`; all 10 input rails enabled with consumers |
| `pci-pwrctrl-pwrseq` | binds `1c00000.pcie:pcie@0:wifi@0`, powers the chip |
| PCIe host + PHY | `qcom-qmp-pcie-phy` bound; `iATU: unroll T, 8 ob, 8 ib` |
| PCIe root port | enumerates as `0000:00:00.0 [17cb:010c]`, AER + PME up |
| WLAN_EN / PERST# driven | `gpio64 out high`, `gpio94 out high` (active-low = released) |
| firmware staged | `/lib/firmware/ath11k/WCN6855/hw2.0/{amss,m3,regdb,board}.bin` |

### What fails

    qcom-pcie 1c00000.pcie: Device not found
    LnkSta = 0x1011   ->   DLActive = 0, LinkTraining = 0

Bus 01 scans empty. A forced retrain (Link Control bit 5) changes nothing, and
`echo 1 > /sys/bus/pci/rescan` finds nothing. The endpoint is not on the link.

### Hypotheses ruled OUT

* **Driver support.** ath11k's WCN6855 path is correct; it never gets that far.
* **Modules missing.** Installing `ath11k`, `ath11k_pci`,
  `pci-pwrctrl-pwrseq`, `mhi` + deps took it from "host will not init" to
  "root port up". Note `build-kernel.sh` does NOT build modules --
  `build-kernel-modules.sh` does, and this was missed once.
* **Ordering / deferred_probe_timeout.** Suspected, and `deferred_probe_timeout`
  was raised 1 -> 60 because 1s genuinely did make the host stop waiting for
  the pwrctrl. Worth keeping, but it did not fix the link: with the timeout at
  60 the pwrctrl loads at ~1.4s, binds, and the host still reports
  `Device not found` at 14s.
* **Power.** All input rails enabled; the chip's own PMU drives sw-ctrl; the
  PMU's `regulators` subnode is NOT backed by a regulator driver by design --
  `pwrseq_qcom_wcn_match_regulator()` only uses those phandles to identify the
  consumer, so ath11k getting dummy regulators for `vreg_pmu_*` is expected.
* **Missing perst.** It was missing at first (that is what produced the very
  first `Device not found`), and adding it did not change the outcome.

### Hypotheses still open, in rough order of likelihood

1. **PERST# timing relative to power.** Spec wants PERST# held asserted until
   the rails are stable and released >=100ms later. The pwrseq powers the chip
   and qcom-pcie pulses PERST independently; nothing enforces the gap. The
   vendor's `cnss2/power.c:968` documents a related >=100ms constraint.
2. **Rail voltages, not identity.** Mapping followed sm8450-hdk, which wires
   the same chip, but the vendor's q2q values differ slightly: vdd-wlan-aon
   S2E is 1.0125V where our `pmr735a_s2` is constrained 0.95-0.976V, and
   vdd-wlan-rfa1 S1C is 1.984V. Worth reconciling against the q2q overlay.
3. **clkreq.** `gpio95` muxed to `pcie0_clkreqn` reads low, which would mean
   the endpoint is requesting the refclk -- but a pin muxed away from GPIO does
   not report a trustworthy level through gpiolib, so this is not evidence
   either way. `GCC_PCIE_0_CLKREF_EN` is wired as the PHY's "ref" clock
   upstream, so the refclk path itself looks correct.
4. **A board detail still missing from the DT** -- compare the q2q overlay's
   `qcom,pcie@1c00000` against ours property by property.

### Tooling gap that cost time

No tracefs: `FTRACE`/`KPROBE_EVENTS` are off in `q2q-stage1.config`, so the
exact `-EPROBE_DEFER` origin could not be probed and had to be inferred.
`DYNAMIC_DEBUG=y` is on but the `file ... +p` writes produced nothing useful on
this path. Enable kprobes before the next attempt; it is one rebuild and turns
guesswork into measurement.

## 10. Second attempt, 2026-11-11 (afternoon): the host is innocent

No link yet. But this round **closed three of the four hypotheses from §9**
and moved the problem decisively from the host to the chip. Net: the search
space is much smaller and the next attempt should not re-tread any of this.

### The host side is provably healthy

| evidence | reading |
|---|---|
| `pcie_0_pipe_clk` | **125 MHz, enabled, prepared** -- the QMP PHY locked and is producing a valid Gen1 pipe clock |
| `gcc_pcie_0_aux_clk` | 19.2 MHz, enabled |
| `wcn6855-pmu` | bound to `pwrseq-qcom_wcn` |
| `pci-pwrctrl-pwrseq` | bound to `1c00000.pcie:pcie@0:wifi@0` |
| `devices_deferred` | only `33c0000.pinctrl` and `1dfa000.crypto` -- nothing in the WLAN path |
| gpio64 WLAN_EN | `out high` |
| gpio94 PERST# | `out high` = **deasserted** (active low) |

`LnkSta` is still `0x1011` (DLActive 0, LinkTraining 0) and bus 01 is empty.
A host whose PHY has locked and whose pipe clock is running, with PERST
released, is not the problem.

### Closed: rail voltages

`pwrseq-qcom-wcn` only calls `regulator_bulk_enable()` -- it never requests a
voltage -- and the regulator core applies a DT voltage **only when
`min == max`**. Every WLAN rail in our DT was a range, so they came up enabled
at whatever RPMh had aggregated. That looked like a smoking gun.

`pmr735a_s2` (S2E, the vendor's `vdd-wlan-aon`) was pinned to the vendor's
exact `1012000`, confirmed applied (`pmr735a_s2: Setting 1012000-1012000uV`).
**No change to the link.**

And the theory is wrong anyway: **sm8450-hdk drives the same WCN6855 at
*lower* voltages and works** -- `vreg_s11b_0p95`, `vreg_s2e_0p85`,
`vreg_s1c_1p86`, `vreg_s12b_1p25`. If the chip trains at 0.85 V on S2E there,
q2q's 1.012 V is not a precondition. The pin is **kept** because it is the
correct value for this board, not because it helps.

S11B/S12B/S1C remain unpinned on purpose: they are shared with the UFS LDO
parents and the display `vddio`, so a wrong value there costs the root
filesystem or the screen.

### Closed: PERST# timing

§9 ranked this first. The boot log settles it: `pci-pwrctrl-pwrseq` powers the
chip at ~1.4 s and `qcom-pcie` reports `Device not found` at **10.28 s**. The
gap is ~9 seconds, not the <100 ms the hypothesis needed. Nothing to fix.

(There is no runtime re-test available: `qcom-pcie` sets `suppress_bind_attrs`,
so `unbind`/`bind` return `Permission denied` even as root.)

### Closed: a missing DT property

The vendor's `qcom,pcie@1c00000` (`lahaina-pcie.dtsi`) matches ours
property-for-property: `perst-gpio = <&tlmm 94 0>`, `wake-gpio = <&tlmm 96 0>`,
`vreg-1p8` = L6B at 1.2 V, `vreg-0p9` = L5B at 0.88 V.

`xo-clk-gpios` is the *only* difference from sm8450-hdk, and it does not apply:
the binding describes it as selecting the XO *configuration*, hdk drives
gpio204 for it, and q2q's vendor pinctrl has only
`cnss_wlan_en_active`/`_sleep` -- no XO pin exists on this board, so the strap
is in hardware.

**Dead end, recorded so it is not chased again:** `RPMH_RF_CLK5` with
`clock-names = "rf_clk"` *does* appear in `lahaina.dtsi`, and it is tempting.
It belongs to the **wil6210 60 GHz WiGig** node (`qcom,wigig-en`,
`qcom,pcie-parent = <&pcie1>`, `status = "disabled"`), not to the QCA6490. The
`qcom,cnss-qca6490` node has no `clocks` property at all. sm8350's upstream
rpmhcc exposes RF_CLK1/3/4, not RF_CLK5.

### The new lead: the chip's own PMU never reports ready

```
gpio64  : out high   WLAN_EN asserted
gpio94  : out high   PERST# released
gpio153 : in  low    sw-ctrl -- driven BY the QCA6490's internal PMU
```

**sw-ctrl is low.** On the vendor side this is `qcom,sw-ctrl-gpio`, an input
from the chip's PMU that indicates its internal regulators have come up. If it
is genuinely low, the chip is not powering up internally -- which explains
every observation above at once, including why the host looks perfect.

**Confidence: strong but not proven.** Two caveats, both to resolve first:

1. **Our own pinctrl pulls it down.** `gpio153` is configured
   `bias-pull-down` (deliberately, as an input with no drive). If the chip's
   output is open-drain or high-Z while off, our pull-down holds it low no
   matter what the chip does. Re-test with `bias-disable` before concluding.
2. **Nothing in the kernel reads it.** `swctrl-gpios` is consumed only by
   `hci_qca.c` for Bluetooth; `pwrseq-qcom-wcn` ignores it entirely. So it is
   a passive hardware observation, not a driver-visible failure.

### Suggested next steps, in order

1. Re-read gpio153 with `bias-disable` to establish whether sw-ctrl is really
   low or just pulled down. Cheap, one DTS line, and it decides between "the
   chip is dead" and "we have been reading our own pull-down".
2. If genuinely low: the chip has rails and WLAN_EN but will not start, so look
   for what else its PMU needs on *this* board -- compare the vendor's
   `cnss2` power-on path (`cnss_power_on_device`) against what pwrseq does,
   especially `qcom,tcs_offset_int_pow_amp_vreg = <0x4D0>`, which is a direct
   RPMh TCS write that upstream has no equivalent for.
3. Enable `CONFIG_PCIE_DW_DEBUGFS` (currently `n`) for LTSSM state. Knowing
   whether the host sits in `Detect.Quiet` (no receiver detected at all)
   versus `Polling` would separate "chip electrically absent" from "chip
   present but not negotiating". One build, and it changes nothing else.

## 11. Third attempt, 2026-11-11 (evening): it works

`wlp1s0` exists and scans. Two independent things were wrong, and neither was
any hypothesis from §9 or §10.

### Root cause 1: the rails were copied from the wrong DT

Every earlier attempt took the supplies from `lahaina.dtsi`
(`qcom,cnss-qca6490`: S2E, S11B, S12B, S1C, L7E). On q2q that node is
**overridden by the board overlay** (`q2q_eur_openx_w00_r08.dts`, fragment@189):

| vendor supply | generic lahaina | **q2q overlay** |
|---|---|---|
| vdd-wlan-aon | S2E 1.012 V | **S2MPB02 sub BUCK1, 1.0125 V** |
| vdd-wlan-dig | S11B | **S2MPB02 sub BUCK1, 1.0125 V** |
| vdd-wlan-rfa2 | S12B 1.35 V | **S2MPB02 sub BUCK2, 1.35 V** |
| vdd-wlan-rfa1 | S1C 1.9-1.952 V | S1C, node replaced: fixed **1.984 V** |
| wlan-ant-switch | L7E 2.8 V | *deleted* |
| qcom,sw-ctrl-gpio | gpio153 | *deleted* |

S2MPB02 "sub" is a Samsung PMIC at 0x59 on the same bitbanged i2c
(gpio76/77) as the s2dos05. BUCKn: enable = CTRL1 bits 7:6 (0x0b / 0x0d),
vsel = CTRL2 (0x0c / 0x0e), 400 mV + 6.25 mV/step. The bootloader leaves both
bucks off. There is no mainline driver; `wifi-work/s2mpb02-regulator.c` is a
minimal one (bucks only, on purpose -- the LDOs feed the cover panel).

Proof, at runtime with no flash: `i2cset` BUCK1 on -> nothing; BUCK2 on as
well, with PERST#/WLAN_EN re-sequenced through `/dev/mem` -> `LnkSta`
`0x1011` -> `0xb013`, and `17cb:1103` enumerates.

So §10's "live lead" was wrong: gpio153 reads low under a pull-up even with
the chip running, because it is not sw-ctrl on this board at all.

**Lesson: for any q2q peripheral read the overlay, not `lahaina*.dtsi`.**

### Root cause 2: Samsung's firmware does not run under ath11k

With the link up, Samsung's `amss20.bin` (`WLAN.HSP.1.1.c4-00645`, the Android
build) boots over MHI, takes BDF/M3, answers WMI service-ready, and then
asserts ~1.7 s after `wmi init` (`cmnos_thread.c:4713`, PC `0x1590ec4`, LR
`0x188b508`, line 478 -- from the RDDM dump; no symbols). Identical with all
four `bdwlan.elf*`. Upstream `amss.bin` with Samsung's BDF dies earlier, on the
last BDF segment.

Upstream `amss.bin` + `m3.bin` + `regdb.bin` + **upstream `board-2.bin`**
works. `board-2.bin` has an exact entry for
`subsystem 17cb:0108, qmi-chip-id=2, qmi-board-id=255`; it had never been used
because the kernel is built without `FW_LOADER_COMPRESS` and Fedora ships
`.xz`. The files are decompressed in place by hand for now.

Open: only 2.4 GHz APs observed; the generic board file is not this board's
calibration; regulatory/5 GHz/tx power are unverified.

### Ruled out along the way

* **S1C voltage.** 1.808 V -> 1.984 V (overlay value, kept): no effect.
* **Link speed.** Vendor sets `qcom,target-link-speed = <2>`; retraining to
  Gen2 changed nothing. Gen3 runs with occasional correctable RxErr.
* **S3E / internal PA** (`qcom,tcs_offset_int_pow_amp_vreg`, §10 step 2).
  Reading the PDC TCS window from Linux resets the phone; voting `smpe3` on
  through RPMh resets it too. Not needed, and not to be touched.

### Ordering matters

Powering the chip with PERST# already released does not train the link, and
afterwards the root port would not train again until reboot. The regulators
must therefore be real supplies of `wcn6855-pmu`, so that
pwrseq -> pci-pwrctrl -> qcom-pcie defer in the right order.

### Result: unattended boot, 2026-11-11

With the S2MPB02 node, the remapped `wcn6855-pmu` supplies and
`s2mpb02-regulator.ko` in `/lib/modules/<rel>/extra`, a cold boot brings
`wlp1s0` up by itself at ~8 s: `17cb:1103` enumerates, BAR0 assigned first
time, `LnkSta 0x3013` (Gen3 x1), no manual sequencing.

One driver bug cost a boot: the buck enable field idles at `0b01` when OFF
(CTRL1 = 0x58), and the regmap helpers treat any set bit as enabled unless
`enable_val` is given -- so the core believed the bucks were on and never
wrote `0b11`. The regulator summary showed them enabled while the register
still read 0x58. Fixed with explicit `enable_val`/`disable_val`.
