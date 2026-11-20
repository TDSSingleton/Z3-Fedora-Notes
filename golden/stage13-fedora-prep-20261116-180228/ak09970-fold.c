// SPDX-License-Identifier: GPL-2.0
/*
 * AKM AK09970 3-axis digital hall sensor used as the fold switch of the
 * Samsung Galaxy Z Fold 3 (SM-F926B, q2q).
 *
 * The chip measures the hinge magnet and drives its INT pin from a
 * programmable threshold pair on one axis, so once configured it behaves like
 * a plain hall switch: INT high = phone closed. It powers up idle with INT
 * floating high through the pull-up, which is why wiring the pin up as a bare
 * gpio-key reported nothing useful.
 *
 * Settings mirror the vendor DT node digital_hall@10 and the sequence in
 * Samsung's drivers/input/misc/akm.c (akm_setup_device_control):
 *   akm,pol = <0 1 0 0>, akm,sw_en = <0 1 0 0>, akm,err_en = <1>,
 *   akm,drdy_en = <0>, akm,measurement_number = <5>, akm,sdr = <1>,
 *   akm,threshold_y = <0x889 0x690>  (operate 2185, release 1680; open ~ 820)
 *
 * Reported as SW_MACHINE_COVER, not SW_LID: logind and Plasma act on SW_LID
 * (suspend, blank everything) and suspend cannot be resumed on this device.
 */
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/mod_devicetable.h>
#include <linux/regulator/consumer.h>

#define AK09970_REG_ID		0x00	/* 48 c1 */
#define AK09970_REG_ST_ZYX	0x17	/* status + z, y, x; reading clears DRDY/ERR */
#define AK09970_REG_CNTL1	0x20
#define AK09970_REG_CNTL2	0x21
#define AK09970_REG_THRESH_Y	0x23
#define AK09970_REG_SRST	0x30

#define AK09970_BOP_Y		0x0889
#define AK09970_BRP_Y		0x0690

struct ak09970 {
	struct i2c_client *client;
	struct input_dev *input;
	struct gpio_desc *int_gpio;
};

static int ak09970_configure(struct ak09970 *hall)
{
	struct i2c_client *client = hall->client;
	/* polarity: Y inverted | switch on Y + error pin enable */
	static const u8 cntl1[] = { 0x02, 0x24 };
	static const u8 thy[] = { AK09970_BOP_Y >> 8, AK09970_BOP_Y & 0xff,
				  AK09970_BRP_Y >> 8, AK09970_BRP_Y & 0xff };
	u8 id[2];
	int ret;

	ret = i2c_smbus_read_i2c_block_data(client, AK09970_REG_ID, sizeof(id), id);
	if (ret != sizeof(id))
		return ret < 0 ? ret : -EIO;
	if (id[0] != 0x48 || id[1] != 0xc1)
		return dev_err_probe(&client->dev, -ENODEV,
				     "unexpected id %02x %02x\n", id[0], id[1]);

	ret = i2c_smbus_write_byte_data(client, AK09970_REG_SRST, 0x01);
	if (ret)
		return ret;
	usleep_range(2000, 3000);

	ret = i2c_smbus_write_i2c_block_data(client, AK09970_REG_CNTL1, sizeof(cntl1), cntl1);
	if (ret)
		return ret;
	ret = i2c_smbus_write_i2c_block_data(client, AK09970_REG_THRESH_Y, sizeof(thy), thy);
	if (ret)
		return ret;
	/* continuous measurement mode 5 (0x0a), low-noise drive (sdr) */
	return i2c_smbus_write_byte_data(client, AK09970_REG_CNTL2, 0x0a | BIT(5));
}

static void ak09970_report(struct ak09970 *hall)
{
	u8 st[7];

	/* Clears a latched error/data-ready so INT follows the switch again. */
	i2c_smbus_read_i2c_block_data(hall->client, AK09970_REG_ST_ZYX, sizeof(st), st);

	input_report_switch(hall->input, SW_MACHINE_COVER,
			    gpiod_get_value_cansleep(hall->int_gpio));
	input_sync(hall->input);
}

static irqreturn_t ak09970_irq(int irq, void *data)
{
	ak09970_report(data);
	return IRQ_HANDLED;
}

static int ak09970_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct ak09970 *hall;
	int ret;

	hall = devm_kzalloc(dev, sizeof(*hall), GFP_KERNEL);
	if (!hall)
		return -ENOMEM;
	hall->client = client;

	ret = devm_regulator_get_enable(dev, "dvdd");
	if (ret)
		return dev_err_probe(dev, ret, "failed to enable dvdd\n");
	usleep_range(5000, 6000);

	hall->int_gpio = devm_gpiod_get(dev, "int", GPIOD_IN);
	if (IS_ERR(hall->int_gpio))
		return dev_err_probe(dev, PTR_ERR(hall->int_gpio), "failed to get int-gpios\n");

	ret = ak09970_configure(hall);
	if (ret)
		return dev_err_probe(dev, ret, "failed to configure the sensor\n");

	hall->input = devm_input_allocate_device(dev);
	if (!hall->input)
		return -ENOMEM;
	hall->input->name = "fold-hall";
	hall->input->id.bustype = BUS_I2C;
	input_set_capability(hall->input, EV_SW, SW_MACHINE_COVER);

	ret = input_register_device(hall->input);
	if (ret)
		return ret;

	ret = devm_request_threaded_irq(dev, gpiod_to_irq(hall->int_gpio), NULL, ak09970_irq,
					IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING | IRQF_ONESHOT,
					"fold-hall", hall);
	if (ret)
		return dev_err_probe(dev, ret, "failed to request irq\n");

	msleep(20);	/* first measurement, so the initial state is real */
	ak09970_report(hall);
	dev_info(dev, "AK09970 fold switch ready, phone is %s\n",
		 gpiod_get_value_cansleep(hall->int_gpio) ? "closed" : "open");
	return 0;
}

static const struct of_device_id ak09970_of_match[] = {
	{ .compatible = "asahi-kasei,ak09970" },
	{ }
};
MODULE_DEVICE_TABLE(of, ak09970_of_match);

static const struct i2c_device_id ak09970_id[] = {
	{ "ak09970" },
	{ }
};
MODULE_DEVICE_TABLE(i2c, ak09970_id);

static struct i2c_driver ak09970_driver = {
	.driver = {
		.name = "ak09970-fold",
		.of_match_table = ak09970_of_match,
	},
	.probe = ak09970_probe,
	.id_table = ak09970_id,
};
module_i2c_driver(ak09970_driver);

MODULE_DESCRIPTION("AK09970 digital hall as a fold switch (Galaxy Z Fold 3)");
MODULE_LICENSE("GPL");
