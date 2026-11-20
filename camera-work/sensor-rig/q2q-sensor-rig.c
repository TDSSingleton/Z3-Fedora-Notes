// SPDX-License-Identifier: GPL-2.0-only
/*
 * q2q-sensor-rig: hold a camera module in its powered-on state so the CCI bus
 * can be scanned.
 *
 * WHY THIS EXISTS
 * ---------------
 * The one fact the device tree cannot supply for a CCI-attached sensor is its
 * i2c address: Qualcomm's stack is told the address by userspace in the probe
 * packet, so the vendor's qcom,cam-sensor nodes carry no slave-addr and the
 * GPL drop never mentions one. The address has to be found by scanning.
 *
 * But a CMOS sensor only answers on i2c when it is powered, un-reset and has
 * its master clock running, and all three of those are owned by the sensor
 * driver -- which powers the module back down the moment its chip-ID read
 * fails. So a plain i2cdetect on the CCI bus always scans a dead module.
 *
 * This module reproduces exactly what imx258_power_on() does -- enable the
 * supplies, enable MCLK at the right rate, deassert reset, wait -- and then
 * just holds it, for as long as the module is loaded. With it loaded,
 * i2cdetect on the CCI master sees a live module.
 *
 * It is also the rig for the other four cameras on this phone, which have the
 * same unknown: point a DT node at their MCLK, rails and reset line.
 *
 * It deliberately claims the power domain through runtime PM rather than
 * grabbing clocks off the provider: camcc's MCLKs live inside titan_top_gdsc,
 * and a GDSC is a genpd that only powers up for an attached device. Without
 * that, clk_prepare_enable() returns -EBUSY (measured 2026-11-14).
 *
 *   insmod q2q-sensor-rig.ko          # powered, reset released
 *   i2cdetect -y -r <cci-bus>         # now meaningful
 *   rmmod q2q-sensor-rig              # back to rest state
 *
 * TEMPORARY. Delete once every sensor's address is known and recorded.
 */
#include <linux/clk.h>
#include <linux/clk-provider.h>	/* __clk_get_name */
#include <linux/delay.h>
#include <linux/err.h>
#include <linux/gpio/consumer.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>
#include <linux/regulator/consumer.h>

static unsigned long rate = 19200000;
module_param(rate, ulong, 0444);
MODULE_PARM_DESC(rate, "MCLK rate in Hz to request (default 19200000)");

static unsigned int settle_ms = 20;
module_param(settle_ms, uint, 0444);
MODULE_PARM_DESC(settle_ms, "delay after releasing reset, ms (default 20)");

/* Same three names the upstream imx258/imx471 drivers use. */
static const char * const rig_supply_name[] = { "vana", "vdig", "vif" };
#define RIG_NUM_SUPPLIES ARRAY_SIZE(rig_supply_name)

struct sensor_rig {
	struct clk *mclk;
	struct gpio_desc *reset;
	struct regulator_bulk_data supplies[RIG_NUM_SUPPLIES];
	bool clk_on;
};

static int rig_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct sensor_rig *r;
	unsigned int i;
	int ret;

	r = devm_kzalloc(dev, sizeof(*r), GFP_KERNEL);
	if (!r)
		return -ENOMEM;
	platform_set_drvdata(pdev, r);

	r->mclk = devm_clk_get(dev, "mclk");
	if (IS_ERR(r->mclk))
		return dev_err_probe(dev, PTR_ERR(r->mclk), "no mclk\n");

	for (i = 0; i < RIG_NUM_SUPPLIES; i++)
		r->supplies[i].supply = rig_supply_name[i];
	ret = devm_regulator_bulk_get(dev, RIG_NUM_SUPPLIES, r->supplies);
	if (ret)
		return dev_err_probe(dev, ret, "cannot get supplies\n");

	/*
	 * Active-low in DT (the module's XCLR), so "assert" here means the
	 * sensor is held in reset. Start asserted, then release below.
	 */
	r->reset = devm_gpiod_get_optional(dev, "reset", GPIOD_OUT_HIGH);
	if (IS_ERR(r->reset))
		return dev_err_probe(dev, PTR_ERR(r->reset), "cannot get reset\n");

	/* This is what powers titan_top_gdsc: attach + resume the genpd. */
	ret = devm_pm_runtime_enable(dev);
	if (ret)
		return dev_err_probe(dev, ret, "pm_runtime_enable\n");
	ret = pm_runtime_resume_and_get(dev);
	if (ret)
		return dev_err_probe(dev, ret, "resume (titan_top_gdsc?)\n");

	ret = regulator_bulk_enable(RIG_NUM_SUPPLIES, r->supplies);
	if (ret) {
		dev_err(dev, "regulator_bulk_enable = %d\n", ret);
		goto err_pm;
	}

	ret = clk_set_rate(r->mclk, rate);
	if (ret)
		dev_warn(dev, "clk_set_rate(%lu) = %d\n", rate, ret);

	ret = clk_prepare_enable(r->mclk);
	if (ret) {
		dev_err(dev, "clk_prepare_enable = %d (still gated)\n", ret);
		goto err_reg;
	}
	r->clk_on = true;

	/* Release reset only once rails and clock are up, like the sensor
	 * drivers do: XCLR low with no INCK leaves the module undefined.
	 */
	if (r->reset)
		gpiod_set_value_cansleep(r->reset, 0);
	msleep(settle_ms);

	dev_info(dev,
		 "POWERED: mclk '%s' = %lu Hz, %zu supplies on, reset %s\n",
		 __clk_get_name(r->mclk), clk_get_rate(r->mclk),
		 RIG_NUM_SUPPLIES,
		 r->reset ? "released" : "(none in DT)");
	for (i = 0; i < RIG_NUM_SUPPLIES; i++)
		dev_info(dev, "  %-5s %d uV\n", rig_supply_name[i],
			 regulator_get_voltage(r->supplies[i].consumer));
	dev_info(dev, "scan the CCI bus now; rmmod to return to rest\n");

	return 0;

err_reg:
	regulator_bulk_disable(RIG_NUM_SUPPLIES, r->supplies);
err_pm:
	pm_runtime_put(dev);
	return ret;
}

static void rig_remove(struct platform_device *pdev)
{
	struct sensor_rig *r = platform_get_drvdata(pdev);
	struct device *dev = &pdev->dev;

	if (r->reset)
		gpiod_set_value_cansleep(r->reset, 1);
	if (r->clk_on)
		clk_disable_unprepare(r->mclk);
	regulator_bulk_disable(RIG_NUM_SUPPLIES, r->supplies);
	pm_runtime_put(dev);
	dev_info(dev, "powered down\n");
}

static const struct of_device_id rig_match[] = {
	{ .compatible = "q2q,sensor-rig" },
	{ }
};
MODULE_DEVICE_TABLE(of, rig_match);

static struct platform_driver rig_driver = {
	.probe = rig_probe,
	.remove = rig_remove,
	.driver = {
		.name = "q2q-sensor-rig",
		.of_match_table = rig_match,
	},
};
module_platform_driver(rig_driver);

MODULE_DESCRIPTION("Hold a q2q camera module powered so CCI can be scanned");
MODULE_LICENSE("GPL");
