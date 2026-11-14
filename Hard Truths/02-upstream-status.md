# Mainline SM8350 status, and the exact gaps

> **VALIDATED ON HARDWARE, 2026-11-11.** Every conclusion in this file about the
> display stack held up: `dispcc-sm8250.c` really does cover `qcom,sm8350-dispcc`,
> `CONFIG_SM_DISPCC_8250` is the right symbol, and the GPU nodes in `sm8350.dtsi`
> needed only `status = "okay"` plus a zap-shader `firmware-name`. The inner
> panel now runs under DPU + DSI and the Adreno 660 renders. The one claim to
> read with care is "no display at all" in the paragraph below: that was about
> *our board DTS*, not upstream, and is no longer true. See
> [../docs/17-gpu-display-bringup.md](../docs/17-gpu-display-bringup.md).


Verified against `torvalds/linux` on git.kernel.org, **2026-11-06**. Every ✅/❌ below was
confirmed by fetching the file or `Makefile` in question, not recalled.

> **Scope:** this file records *what exists upstream*, nothing more. The judgement calls
> that used to live here — per-goal feasibility ratings and which kernel to base on — moved
> to [`../04-roadmap.md`](../04-roadmap.md), because they are opinions that will change.

---

## 1. SM8350 devices that exist upstream

From `arch/arm64/boot/dts/qcom/Makefile`:

```
sm8350-hdk.dtb
sm8350-microsoft-surface-duo2.dtb
sm8350-mtp.dtb
sm8350-sony-xperia-sagami-pdx214.dtb
sm8350-sony-xperia-sagami-pdx215.dtb
```

Two things to take from this list:

- **No Samsung SM8350 device is upstream.** The Fold 3 would be the first.
- **The OnePlus 9/9 Pro (`lemonade`/`lemonadep`) never landed**, despite a patch series
  reaching v4 in late 2023. Don't plan around it existing.

On the next SoC up, **`sm8450-samsung-r0q.dtb` (Galaxy S22) *is* upstream** — that is
your single most valuable reference for Samsung-specific mainline conventions.

### Why the Surface Duo 2 DT is a disappointment

The Surface Duo 2 is a dual-screen SM8350 device, so it looks like the perfect reference
for Goal 3. It isn't: its upstream DTS (380 lines) describes regulators, UFS, USB, IPA,
remoteprocs and QUP buses — and **no display at all**. No panel, no DSI, nothing. The
reason is in §3 below.

**There is no existing mainline dual-DSI SM8350 display setup to copy.** You would be
first.

---

## 2. What SM8350 gives you for free

`sm8350.dtsi` is 4,634 lines and genuinely mature. Confirmed present:

| Subsystem | Nodes | Status |
|---|---|---|
| CPU / cluster / cpufreq | `cpu0..7`, `cpufreq_hw`, full thermal zones | ✅ |
| Interconnects | `gem_noc`, `mc_virt`, `config_noc`, `aggre1/2_noc`, … | ✅ |
| Regulators | `apps_rsc` + `rpmhpd` + `rpmhcc` | ✅ |
| Storage | `ufs_mem_hc`, `ufs_mem_phy`, `sdhc_2` | ✅ |
| USB | `usb_1` (+SS/DP), `usb_2`, `usb_1_hsphy`, `usb_1_qmpphy` | ✅ |
| PCIe | `pcie0`/`pcie1` + PHYs — Wi-Fi hangs off `pcie0` | ✅ |
| GPU | `gpu`, `gmu`, `gpucc`, `adreno_smmu`, `gpu_zap_shader` | ✅ |
| Display fabric | `mdss`, `mdss_mdp`, `mdss_dsi0`, `mdss_dsi1`, both PHYs, `mdss_dp` | ✅ |
| Display clocks | `dispcc` node + `qcom,sm8350-dispcc` | ✅ **`dispcc-sm8250.c` — see §3** |
| Remoteprocs | `mpss`, `adsp`, `cdsp`, `slpi` | ✅ `qcom,sm8350-*-pas` |
| Modem data path | `ipa`, `ipa_modem_tables`, `ipa_smp2p_*` | ✅ **`qcom,sm8350-ipa`** |
| Audio | `q6afe`, `q6asm`, `q6routing`, `lpass_tlmm` | ✅ |
| Video codec | `iris` | ✅ |
| Buses | `qupv3_id_0/1/2`, `i2c0..19`, `spi0..19`, `uart2/6/18` | ✅ |
| Crypto, RNG, SMMU, PDC, IPCC, tsens | | ✅ |
| Camera (`camss`) | — | ❌ absent (out of scope) |

`dpu_7_0_sm8350.h` confirms the display hardware the DPU driver knows about:
**4 DSC blocks and 4 INTFs** (`intf_0` DP, `intf_1` DSI0, `intf_2` DSI1, `intf_3` DP MST).
That is enough for two DSC-compressed DSI panels at once — the hardware description is
not the problem.

---

## 3. SM8350 display is **fully supported upstream** (corrected 2026-11-06)

> **This section previously claimed the opposite, and was wrong.** It said SM8350 had no
> display clock controller and called that the project's critical path. That conclusion
> came from checking for a *file* (`dispcc-sm8350.c` → 404), a *Kconfig symbol*
> (`SM_DISPCC_8350` → absent) and a *binding doc* (→ 404), and never checking whether
> another driver already claimed the `qcom,sm8350-dispcc` compatible. It does.

The entire SM8350 display chain is in mainline today:

| Piece | DT compatible | Driver | Evidence |
|---|---|---|---|
| Display clock controller | `qcom,sm8350-dispcc` | **`dispcc-sm8250.c`** (multi-SoC) | in its `of_device_id` table |
| DPU | `qcom,sm8350-dpu` | `dpu_kms.c` → `dpu_sm8350_cfg` | `dpu_7_0_sm8350.h` catalog |
| DSI controller | `qcom,sm8350-dsi-ctrl` | `dsi_cfg.c` → 6G v2.6.0 | |
| DSI PHY | `qcom,sm8350-dsi-phy-5nm` | `dsi_phy.c` → `dsi_phy_5nm_8350_cfgs` | |
| MDSS | `qcom,sm8350-mdss` | `msm_mdss.c` | |

### How dispcc covers SM8350
`drivers/clk/qcom/dispcc-sm8250.c` is a four-SoC driver. Its match table:

```c
{ .compatible = "qcom,sc8180x-dispcc" },
{ .compatible = "qcom,sm8150-dispcc" },
{ .compatible = "qcom,sm8250-dispcc" },
{ .compatible = "qcom,sm8350-dispcc" },
```

and its Kconfig is titled, in so many words, **"SM8150/SM8250/SM8350 Display Clock
Controller"** (`CONFIG_SM_DISPCC_8250`, which `depends on SM_GCC_8150 || SM_GCC_8250 ||
SM_GCC_8350`).

SM8350's register deltas are applied at runtime in `disp_cc_sm8250_probe()`:

```c
} else if (of_device_is_compatible(pdev->dev.of_node, "qcom,sm8350-dispcc")) {
        ...
                rcgs[i]->cmd_rcgr -= 4;            /* every RCG shifts by -4   */
        disp_cc_mdss_ahb_clk.halt_reg -= 4;
        disp_cc_mdss_ahb_clk.clkr.enable_reg -= 4;
        disp_cc_mdss_ahb_clk_src.cmd_rcgr = 0x22a0;
        disp_cc_pll0_config.config_ctl_hi1_val = 0x2a9a699c;
        disp_cc_pll0_config.test_ctl_hi1_val = 0x01800000;
        disp_cc_pll0_init.ops = &clk_alpha_pll_lucid_5lpe_ops;
        disp_cc_pll0.vco_table = lucid_5lpe_vco;
        ... same for pll1 ...
        disp_cc_sm8250_clocks[DISP_CC_MDSS_EDP_GTC_CLK] = NULL;
        disp_cc_sm8250_clocks[DISP_CC_MDSS_EDP_GTC_CLK_SRC] = NULL;
}
```

### Independent corroboration
Before finding the above, we ported the register map from Samsung's downstream
`dispcc-lahaina.c` onto `dispcc-sm8250.c` with `tools/port-dispcc.py`. It computed **27
register substitutions** — and they are exactly the deltas upstream applies at runtime
(the uniform −4 RCG shift, the `ahb_clk` −4, `ahb_clk_src = 0x22a0`, the lucid_5lpe PLL
values). Two independent derivations agreeing is good evidence the upstream fixups are
correct, and that the work is genuinely already done.

### Why the clock IDs are shared
`include/dt-bindings/clock/qcom,dispcc-sm8350.h` is a **symlink** whose content is the
single line `qcom,dispcc-sm8250.h`. Upstream deliberately shares one clock-ID enum across
the family, and `sm8350.dtsi` is written against it. The enum has no SLEEP or XO clock
IDs, so the `disp_cc_sleep_clk`/`disp_cc_xo_clk_src` that exist in the downstream driver
are deliberately not modelled upstream.

### The DT is already correct
`sm8350.dtsi`'s dispcc node supplies exactly the 7 parent clocks the driver asks for —
`bi_tcxo`, `dsi0/1_phy_pll_out_byteclk`, `dsi0/1_phy_pll_out_dsiclk`,
`dp_phy_pll_link_clk`, `dp_phy_pll_vco_div_clk` — byte-for-byte the same list
`sm8250.dtsi` uses, plus `power-domains = <&rpmhpd RPMHPD_MMCX>`. **No device-tree change
is needed.**

### Confirmed at Fedora's kernel version too
Re-checked at **v7.2.15** — the base of both Fedora 44 (`7.2.15-200.fc44`) and Fedora 45
(`7.2.15-300.fc45`). At that tag `dispcc-sm8250.c` still carries
`{ .compatible = "qcom,sm8350-dispcc" }`, and `CONFIG_SM_DISPCC_8250` is still titled
"SM8150/SM8250/SM8350 Display Clock Controller". And **Fedora's own aarch64 config already
sets `CONFIG_SM_DISPCC_8250=m`, `CONFIG_DRM_MSM=m`, `CONFIG_DRM_MSM_DSI=y`** — see
[`../06-fedora-strategy.md`](../06-fedora-strategy.md).

### What this means
Display on the Fold 3 needs **no new SoC-level work at all**. Enable
`CONFIG_SM_DISPCC_8250` and the clocks come up. The only genuinely missing pieces are the
two **panel** drivers, which is ordinary per-device work rather than SoC enablement.

It also means the upstream Surface Duo 2 DT having no display is *not* explained by a
missing clock driver, as previously claimed here — the stack was available; nobody wrote
panel drivers for that device.

### Two facts worth keeping from the (wrong) earlier analysis

- **U-Boot really does lack SM8350.** Its `drivers/clk/qcom/` has `clock-sm8250.c` and
  `clock-sm8550.c` and nothing for sm8350 or sm8450. That gap is real; only the Linux
  one was imaginary. Relevant to the U-Boot/Pocketblue option in
  [`../06-fedora-strategy.md`](../06-fedora-strategy.md).
- **The `sm8350-mainline` community project is stale.** `gitlab.com/sm8350-mainline/linux`
  branch `dev` is pinned at **6.7.0-rc3** (≈ December 2023). Mine it for patches; don't
  base on it.

---
