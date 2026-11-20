// SPDX-License-Identifier: GPL-2.0
/*
 * Samsung S2MPB02 sub-PMIC -- the subset of rails this board describes.
 *
 * Minimal mainline-style port of the vendor driver
 * (SM-F926B drivers/regulator/s2mpb02/s2mpb02-regulator.c), written for the
 * Galaxy Z Fold 3 (q2q), where the "sub" instance at i2c 0x59 feeds the
 * QCA6490:
 *
 *   BUCK1  1.0125 V  vdd-wlan-aon + vdd-wlan-dig
 *   BUCK2  1.35 V    vdd-wlan-rfa2
 *
 * Without these two the chip is electrically absent and the PCIe link never
 * trains. Both were verified by hand with i2cset before this was written:
 * enabling them took LnkSta from 0x1011 to 0xb013.
 *
 * Register layout (vendor include/linux/mfd/samsung/s2mpb02-regulator.h):
 *   BxCTRL1  [7:6] enable (0b11 = on, 0b01 = off as left by the bootloader),
 *            [3:2] mode
 *   BxCTRL2  [7:0] vsel, 400 mV + 6.25 mV * sel
 *
 * The 18 LDOs, the buck-boost and the flash LED are deliberately NOT
 * exposed: the bootloader leaves several LDOs on for the panel, and an
 * unclaimed regulator the core does not know about cannot be turned off by
 * regulator_late_cleanup.
 */
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regmap.h>
#include <linux/regulator/driver.h>
#include <linux/regulator/of_regulator.h>

#define S2MPB02_REG_ID		0x00
#define S2MPB02_REG_B1CTRL1	0x0b
#define S2MPB02_REG_B1CTRL2	0x0c
#define S2MPB02_REG_B2CTRL1	0x0d
#define S2MPB02_REG_B2CTRL2	0x0e
#define S2MPB02_REG_MAX		0x32

#define S2MPB02_BUCK_ENABLE_MASK	0xc0
/*
 * The field idles at 0b01 with the buck OFF (bootloader state, CTRL1 = 0x58),
 * so "any bit set" is not "enabled": without an explicit enable_val the core's
 * regmap helpers read 0b01 as already-on and never write 0b11. Only 0b11 is
 * on, which is also what the vendor driver compares against. Disable restores
 * the 0b01 the bootloader leaves.
 */
#define S2MPB02_BUCK_OFF		0x40
#define S2MPB02_BUCK_VSEL_MASK		0xff
#define S2MPB02_BUCK_MIN_UV		400000
#define S2MPB02_BUCK_STEP_UV		6250
#define S2MPB02_BUCK_ENABLE_TIME_US	100
#define S2MPB02_RAMP_DELAY_UV_PER_US	12000

static const struct regulator_ops s2mpb02_buck_ops = {
	.list_voltage		= regulator_list_voltage_linear,
	.map_voltage		= regulator_map_voltage_linear,
	.is_enabled		= regulator_is_enabled_regmap,
	.enable			= regulator_enable_regmap,
	.disable		= regulator_disable_regmap,
	.get_voltage_sel	= regulator_get_voltage_sel_regmap,
	.set_voltage_sel	= regulator_set_voltage_sel_regmap,
	.set_voltage_time_sel	= regulator_set_voltage_time_sel,
};

#define S2MPB02_BUCK(_n, _ctrl1, _ctrl2) {				\
	.name		= "buck" #_n,					\
	.of_match	= of_match_ptr("buck" #_n),			\
	.regulators_node = of_match_ptr("regulators"),			\
	.id		= (_n) - 1,					\
	.ops		= &s2mpb02_buck_ops,				\
	.type		= REGULATOR_VOLTAGE,				\
	.owner		= THIS_MODULE,					\
	.min_uV		= S2MPB02_BUCK_MIN_UV,				\
	.uV_step	= S2MPB02_BUCK_STEP_UV,				\
	.n_voltages	= S2MPB02_BUCK_VSEL_MASK + 1,			\
	.vsel_reg	= _ctrl2,					\
	.vsel_mask	= S2MPB02_BUCK_VSEL_MASK,			\
	.enable_reg	= _ctrl1,					\
	.enable_mask	= S2MPB02_BUCK_ENABLE_MASK,			\
	.enable_val	= S2MPB02_BUCK_ENABLE_MASK,			\
	.disable_val	= S2MPB02_BUCK_OFF,				\
	.enable_time	= S2MPB02_BUCK_ENABLE_TIME_US,			\
	.ramp_delay	= S2MPB02_RAMP_DELAY_UV_PER_US,			\
}

/*
 * LDOs. LnCTRL is ONE register per LDO: bit 7 enables, bits 6:0 select.
 * LDO1 is at 0x1e -- NOT 0x1f. The vendor enum starts at REG_ID = 0, and an
 * off-by-one here cost a day of "enabling" the wrong rails (checked against
 * all eighteen vendor voltages: only 0x1e + (n - 1) fits).
 * LDO1-5 step 12.5 mV, LDO6-18 step 25 mV, both from 600 mV.
 *
 * The descriptor table below is shared by BOTH instances of the chip; which
 * rails actually appear is decided per-instance by what that node's
 * "regulators" subnode describes, so a rail listed here but left out of the
 * DT is never registered and never touched. That is deliberate: the
 * bootloader leaves several LDOs on for the panel, and an unclaimed regulator
 * the core does not know about cannot be turned off by regulator_late_cleanup.
 *
 * Hence the same LDO number means different things on the two chips:
 *   LDO4   main: cam_vdig, rear ultrawide IMX258        1.2 V
 *   LDO6   main: cam_vio, rear ultrawide                1.8 V
 *          sub:  panel_vddr_sub, cover panel            1.7 V
 *   LDO8   main: sensor_dvdd, fold hall AK09970         1.8 V
 *   LDO9   sub:  subsensor_vdd, LSM6DSO IMUs            1.8 V
 *          (XBL leaves it off and Android's PIL node holds it; without it the
 *           IMU never enumerates on the SLPI)
 *   LDO10  sub:  panel_vdd3_sub, cover panel            1.8 V
 *   LDO12  main: cam_vana, rear ultrawide               2.7 V
 *   LDO15  sub:  panel_vci_sub, cover panel             3.0 V
 */
#define S2MPB02_REG_L1CTRL		0x1e
#define S2MPB02_LDO_ENABLE_MASK		0x80
#define S2MPB02_LDO_VSEL_MASK		0x7f
#define S2MPB02_LDO_MIN_UV		600000
#define S2MPB02_LDO_STEP1_UV		12500
#define S2MPB02_LDO_STEP2_UV		25000
#define S2MPB02_LDO_ENABLE_TIME_US	180

static const struct regulator_ops s2mpb02_ldo_ops = {
	.list_voltage		= regulator_list_voltage_linear,
	.map_voltage		= regulator_map_voltage_linear,
	.is_enabled		= regulator_is_enabled_regmap,
	.enable			= regulator_enable_regmap,
	.disable		= regulator_disable_regmap,
	.get_voltage_sel	= regulator_get_voltage_sel_regmap,
	.set_voltage_sel	= regulator_set_voltage_sel_regmap,
};

#define S2MPB02_LDO(_n, _step) {					\
	.name		= "ldo" #_n,					\
	.of_match	= of_match_ptr("ldo" #_n),			\
	.regulators_node = of_match_ptr("regulators"),			\
	.id		= 16 + (_n),					\
	.ops		= &s2mpb02_ldo_ops,				\
	.type		= REGULATOR_VOLTAGE,				\
	.owner		= THIS_MODULE,					\
	.min_uV		= S2MPB02_LDO_MIN_UV,				\
	.uV_step	= (_step),					\
	.n_voltages	= S2MPB02_LDO_VSEL_MASK + 1,			\
	.vsel_reg	= S2MPB02_REG_L1CTRL + (_n) - 1,		\
	.vsel_mask	= S2MPB02_LDO_VSEL_MASK,			\
	.enable_reg	= S2MPB02_REG_L1CTRL + (_n) - 1,		\
	.enable_mask	= S2MPB02_LDO_ENABLE_MASK,			\
	.enable_time	= S2MPB02_LDO_ENABLE_TIME_US,			\
}

/* LDO1-5 step 12.5 mV; LDO6-18 step 25 mV. Mixing them up sets a wrong
 * voltage silently -- the selector is accepted either way.
 */
#define S2MPB02_LDO_STEP1(_n)	S2MPB02_LDO(_n, S2MPB02_LDO_STEP1_UV)
#define S2MPB02_LDO_STEP2(_n)	S2MPB02_LDO(_n, S2MPB02_LDO_STEP2_UV)

static const struct regulator_desc s2mpb02_regulators[] = {
	S2MPB02_BUCK(1, S2MPB02_REG_B1CTRL1, S2MPB02_REG_B1CTRL2),
	S2MPB02_BUCK(2, S2MPB02_REG_B2CTRL1, S2MPB02_REG_B2CTRL2),
	S2MPB02_LDO_STEP1(4),	/* main: cam_vdig, rear ultrawide 1.2 V */
	S2MPB02_LDO_STEP2(6),	/* sub: panel_vddr_sub, cover panel 1.7 V;
				 * main: cam_vio, rear ultrawide 1.8 V
				 */
	S2MPB02_LDO_STEP2(8),	/* main: sensor dvdd, fold hall AK09970 1.8 V */
	S2MPB02_LDO_STEP2(9),	/* sub: subsensor_vdd, IMUs 1.8 V */
	S2MPB02_LDO_STEP2(10),	/* sub: panel_vdd3_sub, cover panel 1.8 V */
	S2MPB02_LDO_STEP2(12),	/* main: cam_vana, rear ultrawide 2.7 V */
	S2MPB02_LDO_STEP2(15),	/* sub: panel_vci_sub, cover panel 3.0 V */
};

static const struct regmap_config s2mpb02_regmap_config = {
	.reg_bits	= 8,
	.val_bits	= 8,
	.max_register	= S2MPB02_REG_MAX,
};

static int s2mpb02_probe(struct i2c_client *i2c)
{
	struct regulator_config config = { };
	struct regmap *regmap;
	struct device_node *regs;
	unsigned int id;
	int i, ret;

	regmap = devm_regmap_init_i2c(i2c, &s2mpb02_regmap_config);
	if (IS_ERR(regmap))
		return dev_err_probe(&i2c->dev, PTR_ERR(regmap), "regmap init failed\n");

	ret = regmap_read(regmap, S2MPB02_REG_ID, &id);
	if (ret)
		return dev_err_probe(&i2c->dev, ret, "cannot read chip id\n");

	config.dev = &i2c->dev;
	config.regmap = regmap;

	regs = of_get_child_by_name(i2c->dev.of_node, "regulators");

	for (i = 0; i < ARRAY_SIZE(s2mpb02_regulators); i++) {
		struct regulator_dev *rdev;
		struct device_node *np;

		/*
		 * Register ONLY what the DT describes. An undescribed rail
		 * must stay exactly as the bootloader left it -- several of
		 * this chip's LDOs feed the cover panel.
		 */
		np = regs ? of_get_child_by_name(regs, s2mpb02_regulators[i].name) : NULL;
		if (!np)
			continue;
		of_node_put(np);

		rdev = devm_regulator_register(&i2c->dev, &s2mpb02_regulators[i], &config);
		if (IS_ERR(rdev))
			return dev_err_probe(&i2c->dev, PTR_ERR(rdev),
					     "failed to register %s\n",
					     s2mpb02_regulators[i].name);
	}

	of_node_put(regs);
	dev_info(&i2c->dev, "S2MPB02 rev 0x%02x registered\n", id);
	return 0;
}

static const struct of_device_id s2mpb02_of_match[] = {
	{ .compatible = "samsung,s2mpb02" },
	{ }
};
MODULE_DEVICE_TABLE(of, s2mpb02_of_match);

static const struct i2c_device_id s2mpb02_i2c_id[] = {
	{ "s2mpb02" },
	{ }
};
MODULE_DEVICE_TABLE(i2c, s2mpb02_i2c_id);

static struct i2c_driver s2mpb02_driver = {
	.driver = {
		.name = "s2mpb02-regulator",
		.of_match_table = s2mpb02_of_match,
	},
	.probe = s2mpb02_probe,
	.id_table = s2mpb02_i2c_id,
};
module_i2c_driver(s2mpb02_driver);

MODULE_DESCRIPTION("Samsung S2MPB02 sub-PMIC regulators");
MODULE_LICENSE("GPL");
