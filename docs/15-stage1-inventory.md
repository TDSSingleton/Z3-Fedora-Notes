# Stage 1 runtime inventory (read over the serial console, 2026-11-08)

Taken from a live busybox shell on `/dev/fold3`.

## Bound platform devices

    100000.clock-controller        gcc
    1500000 1580000 1680000        interconnect (10 x qnoc-sm8350)
    16e0000 1700000 1740000
    3c40000 90c0000 9100000 a0c0000
    15000000.iommu                 arm-smmu (APPS)
    17c20000.timer                 arch-timer-mmio, 19.20 MHz
    18200000.rsc                   rpmh + bcm-voter, clock-controller,
                                   power-controller, regulators-0/-1
    1f40000.hwlock                 qcom_hwspinlock
    408000.mailbox                 qcom_apcs_ipc
    80860000.memory  80900000.smem qcom-smem
    88e3000.phy                    qcom-snps-hs-femto-v2 (USB HS)
    a600000.usb  a6f8800.usb       dwc3 core + dwc3-qcom glue
    b220000.interrupt-controller   qcom_pdc
    c300000.power-management       aoss qmp
    c440000.spmi                   spmi_pmic_arb v5 + 2 pmic gpio blocks
    e4000000.framebuffer           simplefb, 2208x1768x32, stride 8832
    f0b00000.ramoops
    f100000.pinctrl                sm8350-tlmm
    firmware:scm, psci, pmu-a55/a78/x1, regulator-vph-pwr, serial8250

## Numbers

    cpus       8
    MemTotal   11181004 kB  (10.66 GiB usable of 11.89 GiB physical)
    MemFree    11117032 kB  -- essentially nothing is using it

## Empty, and why

    /sys/class/power_supply/   EMPTY. No charger, no battery, no fuel gauge.
                               max77705 was never enabled. This is why the
                               device drains while running our kernel and
                               cannot charge from it. See
                               fold3-no-charging-on-mainline memory.
    /sys/class/thermal/        EMPTY. QCOM_TSENS off in the minimal cut.
                               Nothing is monitoring SoC temperature.

## Only real error in dmesg

    arm-smmu 3da0000.iommu: deferred probe timeout, ignoring dependency
    arm-smmu 3da0000.iommu: probe with driver arm-smmu failed with error -110

Self-inflicted: `deferred_probe_timeout=1` on our cmdline is too aggressive for
that SMMU's dependency chain. Harmless for Stage 1 (it is the LPASS/ADSP SMMU,
and we run neither), but raise the timeout before trusting any probe-order
conclusions.
