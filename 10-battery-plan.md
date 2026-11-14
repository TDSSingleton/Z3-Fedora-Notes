> **HISTORICAL** — written during planning, before any code existed. Parts are now wrong.
> See [HANDBOOK.md](HANDBOOK.md) for the current state.

# Dual-cell battery: topology, safety, and what to do (Q4)

You said: *"We likely will need to discuss the ability to safely and understandably
reverse engineer the driver. Until then, I don't mind either leaving things to the
hardware (if possible) or disabling the smaller battery."*

Two answers up front:

1. **It isn't reverse engineering.** The full driver source and register map are GPL-2.0
   in your own source drop (`SM-F926B/Kernel/drivers/battery/limiter/s2asl01_limiter/`,
   `.c` + `.h` + `.dtsi`). This is a *port*, not an RE effort. No decapping, no tracing,
   no clean-room — just reading GPL code you already have and rewriting it to upstream
   conventions.
2. **Of your two interim options, "leave it to the hardware" is the safer one.
   "Disable the smaller battery" is the more dangerous one** — I'd advise against it.
   Reasoning below.

---

## 1. The actual topology

From `q2q_eur_openx_w00_r08.dts` and the driver sources:

```
                        ┌─────────────────┐
  USB-C ──► MAX77705 ──►│                 │
            (charger,   │  common charge  │
             fuel gauge,│      node       │
             OTG, PD)   └────┬───────┬────┘
                             │       │
                   ┌─────────▼─┐   ┌─▼─────────┐
                   │ S2ASL01   │   │ S2ASL01   │   each: I²C + powermeter
                   │ main @0x38│   │ sub  @0x39│   (VBAT/VCHG/ICHG/IDISCHG)
                   │  bat_enb  │   │  bat_enb  │   + per-cell enable GPIO
                   │  bat_enb2 │   │  bat_det  │   + thermal shutdown (tsd_en)
                   └─────┬─────┘   └─────┬─────┘
                         │               │
                      CELL 1          CELL 2
                      (main)           (sub)
```

Confirmed details:

| Fact | Evidence |
|---|---|
| Two cells, **in parallel**, each behind its own limiter | `sec-dual-battery` with `main_current_limiter` + `sub_current_limiter` |
| Limiter I²C addresses 0x38 / 0x39 | `I2C_ADDR_LIMITER_MAIN (0x70>>1)`, `_SUB (0x72>>1)` in `s2asl01_limiter.h` |
| Each cell has an **enable GPIO** | `limiter,main_bat_enb_gpio`, `main_bat_enb2_gpio`, `sub_bat_enb_gpio` |
| Each cell has **detect** | `main_bat_det_gpio`, `sub_bat_det_gpio` |
| Limiters include a **powermeter** | registers `VAL1/2_VCHG`, `_VBAT`, `_ICHG`, `_IDISCHG` (0x07–0x0E) |
| Limiters include **thermal shutdown** | `limiter,tsd-en` property, `pdata->tsd_en` |
| There is a **"supplement mode"** | `s2asl01_set_supplement_mode()`, `POWER_SUPPLY_EXT_PROP_*` |
| Per-cell charge current *rates* per temperature zone | `main_zone1_current_rate = 0x41` (65), `sub_zone1_current_rate = 0x46` (70), etc. |
| Same full-charge targets for both | `main_full_condition_vcell` == `sub_full_condition_vcell` = `{0x1130,0x111c,...}` (4400 mV …) |

The cells are the Fold 3's well-documented 2280 mAh + 2120 mAh pair — similar capacity,
same chemistry, same nominal voltage. Electrically that's a parallel pack with
per-branch current control and metering.

---

## 2. Why "disable the smaller battery" is the riskier choice

It sounds conservative — fewer cells, less to go wrong — but it inverts the risk:

- **The charger still targets a ~4400 mAh pack.** `max77705_charger` will be configured
  for a full-size pack's charge current. Push that into one ~2100 mAh cell and you are
  charging it at roughly **2× its design C-rate**. That is the classic path to heat,
  lithium plating and swelling — in a device whose battery sits behind a glued folding
  display.
- **You lose that cell's thermal shutdown.** `tsd_en` lives in the limiter. Disabling a
  cell via the limiter means that branch's protection is in an unconfigured state.
- **`enb` is almost certainly active-low ("enable bar").** Driving it "off" from a
  half-initialised driver, or leaving it floating, is not a defined safe state. Getting
  the polarity backwards is a one-line mistake with a physical consequence.
- **Parallel cells don't like being separated and rejoined.** If one cell sits at a
  different state of charge and is later reconnected, the inrush between cells is
  limited only by internal resistance.

The one case where disabling a cell is right is if it is **already faulty** — but that is
a repair decision, not a bring-up strategy.

---

## 3. Recommended approach, in order

### Step 1 — ✅ DONE, and it validates the safe option
The question turned on the default state of the `bat_enb` GPIOs. **Answered on device
2026-11-07:** the limiter driver logs, repeatedly (92 samples) on a booted, working phone:

```
s2asl01_check_status [MAIN LIMITER]: enb = 0,  det = 0
s2asl01_check_status [SUB LIMITER]:  enb = 0,  det = 0
```

`enb` is active-low and the device runs normally in this state, so **both cells rest in
the ENABLED state**. A mainline kernel has no `s2asl01` driver and so won't touch those
GPIOs — the cells stay connected in parallel and the MAX77705 sees one pack. "Leave it to
the hardware" is now evidence-backed, not assumed.

One caveat to carry forward: make sure the mainline device tree doesn't claim or drive
TLMM pins for those GPIOs, and don't configure a pinctrl default that pulls them high.

Capture, with root, before you wipe anything:
```
/sys/kernel/debug/gpio                      # default states of the enb/det GPIOs
dmesg | grep -iE 's2asl01|dual_battery|limiter|max77705'
/sys/class/power_supply/*/uevent            # what Samsung's stack reports
```
`tools/00-collect-facts.sh` does this (it dumps `/sys/kernel/debug/gpio`). Also read `s2asl01_limiter.c`'s `probe()` to see
what it drives the GPIOs to and in which order — that tells you what state the hardware
was in before the driver touched it.

### Step 2 (Phase 3) — bring up charging deliberately conservatively
- Both cells **connected**, limiters left alone.
- **Cap charge current low** in the device tree — start at **500 mA**, and don't exceed
  ~1 A until you have temperature telemetry. A low current is inherently safe for a
  mildly unbalanced parallel pack and needs no limiter driver at all. It also sidesteps
  the whole fast-charge question, since `sm5451` isn't upstream anyway.
- Get **temperature** working early. The DTS has `samsung,sec-thermistor` and the PMIC
  has `qcom,spmi-adc7`/`adc-tm7`; `pm8350b`'s ADC can read battery temperature. A charge
  path without a temperature limit is the thing to avoid, far more than an unbalanced one.
- **Charge attended only**, on a non-flammable surface, until you have thermal cutoff.

### Step 3 (later, optional) — port the limiter driver properly
You have the GPL source. A clean upstream `s2asl01` driver would be:
- a `power_supply` / `regulator`-style driver on I²C 0x38 and 0x39,
- exposing the powermeter via `POWER_SUPPLY_PROP_VOLTAGE_NOW` / `CURRENT_NOW`,
- managing `bat_enb` through `gpiod`,
- enabling `tsd` (thermal shutdown) at probe.

Upstreaming it is plausible but not easy: the Samsung dual-battery framework it was built
for doesn't exist upstream, so the driver would need rethinking around standard
`power_supply` semantics rather than ported one-to-one. Treat it as a stretch goal, well
after display works.

---

## 4. What you lose, and whether it matters

| Capability | Status under mainline | Matters? |
|---|---|---|
| Basic USB-C charging | ✅ `max77705_charger` upstream | **This is Goal 1 — yes** |
| Charge current / voltage control | ✅ via `max77705_charger` | yes — this is your safety lever |
| Battery percentage | ⚠️ `max77705` fuel gauge not upstream; `max17042_battery` is close family | nice to have |
| Per-cell balancing | ❌ no `s2asl01` | tolerable at low charge current |
| Per-cell thermal shutdown | ❌ no `s2asl01` | **mitigate with a pack-level temperature limit** |
| Fast charging (25 W) | ❌ no `sm5451` | no |
| Wireless charging | ❌ no `s2miw04` | no |
| Battery profile data | ✅ `BATTERY_SAMSUNG_SDI` upstream | helpful for calibration |

---

## 5. The honest summary

Charging this device under mainline at a **low, temperature-limited current with both
cells connected** is a reasonable thing to do, and it's what I'd plan for. It is close to
what the hardware does unaided, it needs no new driver, and the MAX77705 support you need
is already upstream.

What I would **not** do is disable a cell, or run fast charge, or leave it charging
unattended before temperature limiting works. And the one fact that must be established
before any of this is **the default state of the `bat_enb` GPIOs** — everything above
assumes they come up enabled, and that assumption needs checking on the device rather
than trusting my reading of the DTS.
