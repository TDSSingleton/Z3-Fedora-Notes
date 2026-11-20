// SPDX-License-Identifier: GPL-2.0-only
/*
 * ST FTS9CU80F touchscreen over SPI.
 *
 * The inner folding display of the Samsung Galaxy Z Fold 3 (SM-F926B, q2q).
 * Mainline has no driver for this part: its only ST touch driver, stmfts, is
 * I2C-only and targets the older FTS3BD60/FTM4 generation.
 *
 * The protocol here was read out of Samsung's GPL stm_spi driver
 * (drivers/input/sec_input/stm_spi in the SM-F926B kernel drop). Only the
 * parts needed to report touches are implemented: no firmware upload (the
 * controller runs resident firmware), no factory self-test command surface,
 * no gesture/sponge/secure-touch paths.
 *
 * Wire format, which is the non-obvious bit:
 *   write  commands A0/A2/A4/A7/FA/FB/D0 go out verbatim as [cmd][payload],
 *          everything else is prefixed with 0xC0
 *   read   a 3-byte header [0xD1][addr_hi][addr_lo] clocked out full-duplex;
 *          the reply begins 4 bytes into the rx buffer (1 dummy + 3 header)
 *   events 16 bytes each, fetched with 0x87; byte0 & 3 is the event class and
 *          byte7 & 0x1F says how many more are queued
 *
 * Chip select is a plain GPIO rather than qup4's native CS, because CS must
 * stay low across a whole message including the inter-transfer settle. The
 * SPI core does that for us via cs-gpios in the DT.
 */

#include <linux/delay.h>
#include <linux/input.h>
#include <linux/input/mt.h>
#include <linux/input/touchscreen.h>
#include <linux/interrupt.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/regulator/consumer.h>
#include <linux/slab.h>
#include <linux/spi/spi.h>

#define FTS_EVENT_SIZE			16
#define FTS_MAX_EVENTS			31
#define FTS_MAX_RESOLUTION		4096
#define FTS_MAX_SLOTS			10

/* commands that are sent without the 0xC0 prefix */
#define FTS_CMD_SCAN_MODE		0xa0
#define FTS_CMD_FEATURE			0xa2
#define FTS_CMD_SYSTEM			0xa4
#define FTS_CMD_FRM_BUFF_R		0xa7
#define FTS_CMD_REG_W			0xfa
#define FTS_CMD_REG_R			0xfb
#define FTS_CMD_SPONGE_W		0xd0

#define FTS_CMD_READ_EVENT		0x87

/* status-event decoding, from struct stm_ts_event_status: eid:2 stype:4 sf:2 */
#define FTS_EV_STYPE(b)			(((b) >> 2) & 0x0f)
#define FTS_STATUSTYPE_INFO		2
#define FTS_INFO_READY_STATUS		0x00
#define FTS_EVENT_ERROR_REPORT		0xf3
#define FTS_CMD_CLEAR_ALL_EVENT		0x62
#define FTS_CMD_READ_DEVICE_ID		0x22
#define FTS_CMD_READ_PANEL_INFO		0x23

#define FTS_WRITE_PREFIX		0xc0
#define FTS_READ_PREFIX			0xd1
/*
 * A read has two shapes, and they are NOT interchangeable -- getting this
 * wrong is what made the device-ID read return noise:
 *
 *   bare command (87/A7/A4/FA/FB): the command bytes ARE the read header.
 *       wire: [cmd ..]            total len = payload + 1 + clen
 *       payload starts at 1 + clen
 *
 *   any other command: it is first issued on its own as [0xC0][cmd], then a
 *       second transfer clocks the answer out with a 3-byte header. With a
 *       1-byte command the header carries NO command byte -- it is D1 00 00.
 *       wire: [0xD1][off_hi][off_lo]   total len = payload + 1 + 3
 *       payload starts at 4
 *
 * In both cases the extra +1 is the dummy byte the controller emits before
 * the payload (vendor: rbuf[1 + buf_len]).
 */
#define FTS_READ_HDR_MAX		3

#define FTS_SCAN_MODE_MS_SS		0x01

#define FTS_ID0				0x48
#define FTS_ID1				0x36

/* event classes: byte0 & 3 */
#define FTS_EV_COORDINATE		0
#define FTS_EV_STATUS			1
#define FTS_EV_GESTURE			2
#define FTS_EV_VENDOR			3

/* touch state: byte0 >> 6 */
#define FTS_ACT_NONE			0
#define FTS_ACT_PRESS			1
#define FTS_ACT_MOVE			2
#define FTS_ACT_RELEASE			3

/* touch type, split across bytes 6 and 7 */
#define FTS_TTYPE_NORMAL		0
#define FTS_TTYPE_PALM			5

struct fts_data {
	struct spi_device	*spi;
	struct input_dev	*input;
	struct mutex		io_lock;	/* serialises SPI messages */
	u32			max_x;
	u32			max_y;
	u32			chip_id;
	u8			*rxbuf;
	size_t			rxbuf_len;
	struct touchscreen_properties prop;
	struct regulator	*vdd;	/* 1.8V digital/IO, s2dos05 ldo2 */
	struct regulator	*avdd;	/* 3.0V analog,     s2dos05 ldo3 */
};

/*
 * Which commands skip the framing prefix. The write and read sides have
 * DIFFERENT sets in the vendor driver, which is easy to miss and expensive to
 * get wrong -- 0x87 (read event) is bare for reads but is not in the write
 * set, and 0xA0/0xA2/0xD0 are bare for writes but not for reads.
 *
 *   stm_ts_spi_write(): A0 A2 A4 A7 FA FB D0   else prefix 0xC0
 *   stm_ts_spi_read():  87 A7 A4 FA FB         else prefix 0xD1 + a preceding
 *                                              0xC0-framed command write
 */
/*
 * Orientation overrides.
 *
 * The proper home for these is the device tree -- touchscreen-swapped-x-y,
 * touchscreen-inverted-x and touchscreen-inverted-y, which
 * touchscreen_parse_properties() reads below. These module parameters exist
 * only so the orientation can be settled by experiment without rebuilding and
 * reflashing a boot image for each guess; -1 means "leave the DT value
 * alone". Once the right combination is known it belongs in the DTS.
 */
static int swap_xy = -1;
static int invert_x = -1;
static int invert_y = -1;
module_param(swap_xy, int, 0444);
MODULE_PARM_DESC(swap_xy, "override touchscreen-swapped-x-y (-1 = use DT)");
module_param(invert_x, int, 0444);
MODULE_PARM_DESC(invert_x, "override touchscreen-inverted-x (-1 = use DT)");
module_param(invert_y, int, 0444);
MODULE_PARM_DESC(invert_y, "override touchscreen-inverted-y (-1 = use DT)");

static bool fts_write_is_bare(u8 cmd)
{
	switch (cmd) {
	case FTS_CMD_SCAN_MODE:
	case FTS_CMD_FEATURE:
	case FTS_CMD_SYSTEM:
	case FTS_CMD_FRM_BUFF_R:
	case FTS_CMD_REG_W:
	case FTS_CMD_REG_R:
	case FTS_CMD_SPONGE_W:
		return true;
	default:
		return false;
	}
}

static bool fts_read_is_bare(u8 cmd)
{
	switch (cmd) {
	case FTS_CMD_READ_EVENT:
	case FTS_CMD_FRM_BUFF_R:
	case FTS_CMD_SYSTEM:
	case FTS_CMD_REG_W:
	case FTS_CMD_REG_R:
		return true;
	default:
		return false;
	}
}

static int fts_write(struct fts_data *ts, const u8 *cmd, size_t cmd_len,
		     const u8 *data, size_t data_len)
{
	u8 *buf;
	size_t len = cmd_len + data_len;
	bool bare = fts_write_is_bare(cmd[0]);
	int ret;

	if (!bare)
		len++;

	buf = kzalloc(len, GFP_KERNEL);
	if (!buf)
		return -ENOMEM;

	if (bare) {
		memcpy(buf, cmd, cmd_len);
		if (data_len)
			memcpy(buf + cmd_len, data, data_len);
	} else {
		buf[0] = FTS_WRITE_PREFIX;
		memcpy(buf + 1, cmd, cmd_len);
		if (data_len)
			memcpy(buf + 1 + cmd_len, data, data_len);
	}

	mutex_lock(&ts->io_lock);
	ret = spi_write(ts->spi, buf, len);
	mutex_unlock(&ts->io_lock);

	kfree(buf);
	return ret;
}

/*
 * Reads are full duplex: the header is clocked out while the reply is clocked
 * in, so the reply sits at an offset in the rx buffer rather than starting at
 * zero. Commands outside the "bare" set additionally need the register
 * selected by a preceding single-byte write.
 */
static int fts_read(struct fts_data *ts, const u8 *cmd, size_t clen,
		    u8 *out, size_t out_len)
{
	struct spi_transfer xfer = {};
	struct spi_message msg;
	u8 hdr[FTS_READ_HDR_MAX];
	size_t hdr_len, len;
	u8 *tx;
	int ret;

	if (clen < 1 || clen > FTS_READ_HDR_MAX)
		return -EINVAL;

	if (fts_read_is_bare(cmd[0])) {
		memcpy(hdr, cmd, clen);
		hdr_len = clen;
	} else {
		/* issue the command on its own first */
		ret = fts_write(ts, cmd, 1, NULL, 0);
		if (ret)
			return ret;

		hdr[0] = FTS_READ_PREFIX;
		hdr[1] = (clen == 3) ? cmd[1] : 0x00;
		hdr[2] = (clen >= 2) ? cmd[0] : 0x00;
		hdr_len = 3;
	}

	len = out_len + 1 + hdr_len;
	if (len > ts->rxbuf_len)
		return -EINVAL;

	tx = kzalloc(len, GFP_KERNEL);
	if (!tx)
		return -ENOMEM;

	memcpy(tx, hdr, hdr_len);

	xfer.tx_buf = tx;
	xfer.rx_buf = ts->rxbuf;
	xfer.len = len;
	xfer.delay.value = 10;
	xfer.delay.unit = SPI_DELAY_UNIT_USECS;

	spi_message_init(&msg);
	spi_message_add_tail(&xfer, &msg);

	mutex_lock(&ts->io_lock);
	ret = spi_sync(ts->spi, &msg);
	mutex_unlock(&ts->io_lock);

	if (!ret)
		memcpy(out, ts->rxbuf + 1 + hdr_len, out_len);

	kfree(tx);
	return ret;
}

/* read one of the single-byte commands */
static int fts_read_cmd(struct fts_data *ts, u8 cmd, u8 *out, size_t out_len)
{
	return fts_read(ts, &cmd, 1, out, out_len);
}

static void fts_report_coord(struct fts_data *ts, const u8 *ev)
{
	u8 slot = (ev[0] >> 2) & 0x0f;
	u8 action = (ev[0] >> 6) & 0x03;
	u8 ttype = ((ev[6] & 0xc0) >> 4) | ((ev[7] & 0xc0) >> 6);
	unsigned int x, y, major, minor;

	if (slot >= FTS_MAX_SLOTS)
		return;

	/* Palm rejection is the controller's job to flag, ours to honour. */
	if (ttype == FTS_TTYPE_PALM)
		return;

	input_mt_slot(ts->input, slot);

	if (action == FTS_ACT_RELEASE || action == FTS_ACT_NONE) {
		input_mt_report_slot_inactive(ts->input);
		return;
	}

	x = ((unsigned int)ev[1] << 4) | (ev[3] & 0x0f);
	y = ((unsigned int)ev[2] << 4) | ((ev[3] >> 4) & 0x0f);
	major = ev[4];
	minor = ev[5];

	input_mt_report_slot_state(ts->input, MT_TOOL_FINGER, true);
	touchscreen_report_pos(ts->input, &ts->prop, x, y, true);
	input_report_abs(ts->input, ABS_MT_TOUCH_MAJOR, major);
	input_report_abs(ts->input, ABS_MT_TOUCH_MINOR, minor);
}

static irqreturn_t fts_irq(int irq, void *dev_id)
{
	struct fts_data *ts = dev_id;
	u8 ev[FTS_MAX_EVENTS * FTS_EVENT_SIZE];
	int remaining, i, ret;

	ret = fts_read_cmd(ts, FTS_CMD_READ_EVENT, ev, FTS_EVENT_SIZE);
	if (ret) {
		dev_err_ratelimited(&ts->spi->dev, "event read failed: %d\n", ret);
		return IRQ_NONE;
	}

	/* A zero first byte means the controller had nothing queued. */
	if (!ev[0])
		return IRQ_HANDLED;

	remaining = ev[7] & 0x1f;
	if (remaining > FTS_MAX_EVENTS - 1) {
		u8 cmd = FTS_CMD_CLEAR_ALL_EVENT;

		dev_warn(&ts->spi->dev, "event overflow (%d), clearing\n", remaining);
		fts_write(ts, &cmd, 1, NULL, 0);
		return IRQ_HANDLED;
	}

	if (remaining) {
		ret = fts_read_cmd(ts, FTS_CMD_READ_EVENT, ev + FTS_EVENT_SIZE,
			       remaining * FTS_EVENT_SIZE);
		if (ret) {
			dev_err_ratelimited(&ts->spi->dev,
					    "batch read failed: %d\n", ret);
			remaining = 0;
		}
	}

	for (i = 0; i <= remaining; i++) {
		const u8 *e = ev + i * FTS_EVENT_SIZE;

		switch (e[0] & 0x03) {
		case FTS_EV_COORDINATE:
			fts_report_coord(ts, e);
			break;
		case FTS_EV_STATUS:
		case FTS_EV_GESTURE:
		case FTS_EV_VENDOR:
		default:
			dev_dbg(&ts->spi->dev, "event %*ph\n", 8, e);
			break;
		}
	}

	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
	return IRQ_HANDLED;
}

/*
 * Rail sequencing, from the vendor's sec_input_power(): IO first, 1ms, then
 * analog; on the way down analog first, 4ms, then IO. The 20ms settle after
 * power-up is the vendor's TOUCH_POWER_ON_DWORK_TIME.
 */
static int fts_power_on(struct fts_data *ts)
{
	int ret;

	ret = regulator_enable(ts->vdd);
	if (ret)
		return ret;

	usleep_range(1000, 1500);

	ret = regulator_enable(ts->avdd);
	if (ret) {
		regulator_disable(ts->vdd);
		return ret;
	}

	msleep(20);
	return 0;
}

static void fts_power_off(struct fts_data *ts)
{
	regulator_disable(ts->avdd);
	usleep_range(4000, 4500);
	regulator_disable(ts->vdd);
}

static void fts_power_off_action(void *data)
{
	fts_power_off(data);
}

/*
 * The part has no reset pin -- the vendor's stm_ts_reset() is a rail power
 * cycle and nothing else. This matters on a warm boot: XBL leaves both touch
 * LDOs up, so the controller is never power-on-reset and answers the device
 * ID read with noise (observed: c5 9d f8 ad 85 instead of .. .. 48 36 ..).
 * Cycling the rails ourselves is the only way to get a known state.
 */
static int fts_power_cycle(struct fts_data *ts)
{
	int ret;

	/* Take our references first; the rails may already be live. */
	ret = fts_power_on(ts);
	if (ret)
		return ret;

	fts_power_off(ts);
	msleep(20);			/* discharge, vendor stm_ts_reset(ts, 20) */

	return fts_power_on(ts);
}

/*
 * Poll the one-event FIFO for the controller-ready status event, as the
 * vendor's stm_ts_wait_for_ready() does. Without this the firmware is still
 * booting and every read returns stale or zero bytes.
 */
static int fts_wait_for_ready(struct fts_data *ts)
{
	u8 ev[FTS_EVENT_SIZE];
	int i, ret;

	for (i = 0; i < 150; i++) {
		ret = fts_read_cmd(ts, FTS_CMD_READ_EVENT, ev, sizeof(ev));
		if (ret)
			return ret;

		if (FTS_EV_STYPE(ev[0]) == FTS_STATUSTYPE_INFO &&
		    ev[1] == FTS_INFO_READY_STATUS)
			return 0;

		if (ev[0] == 0xff && ev[1] == 0xff && ev[2] == 0xff) {
			dev_err(&ts->spi->dev, "firmware looks absent/broken\n");
			return -ENODEV;
		}

		if (ev[0] == FTS_EVENT_ERROR_REPORT)
			dev_warn(&ts->spi->dev, "error event %*ph\n", 8, ev);

		msleep(20);
	}

	dev_err(&ts->spi->dev, "timed out waiting for ready, last event %*ph\n",
		8, ev);
	return -ETIMEDOUT;
}

static int fts_reset(struct fts_data *ts)
{
	static const u8 payload[] = { 0x20, 0x00, 0x00, 0x24, 0x81 };
	u8 cmd = FTS_CMD_REG_W;
	int ret;

	ret = fts_write(ts, &cmd, 1, payload, sizeof(payload));
	if (ret)
		return ret;

	/* The controller reboots its firmware; it is not addressable meanwhile. */
	msleep(10);

	return fts_wait_for_ready(ts);
}

/*
 * Ask the controller for its own coordinate space instead of trusting DT.
 *
 * This matters: the vendor DT says sec,max_coords = <4096 4096>, but
 * stm_ts_get_channel_info() then OVERRIDES it with the IC's value, so 4096 is
 * never what reaches userspace on stock. Declaring 4096 made every touch land
 * compressed toward the top-left -- a press at the bottom of the panel
 * reported y=2780 of a claimed 4096 and the pointer appeared two thirds down.
 *
 * Layout of the 11-byte reply, from stm_ts_get_channel_info():
 *   [0..1] X resolution, big endian      [2..3] Y resolution, big endian
 *   [8] TX (force) channels              [9] RX (sense) channels
 */
static int fts_read_panel_info(struct fts_data *ts)
{
	u8 d[11] = {};
	u32 rx, ry;
	int ret;

	ret = fts_read_cmd(ts, FTS_CMD_READ_PANEL_INFO, d, sizeof(d));
	if (ret)
		return ret;

	rx = (d[0] << 8) | d[1];
	ry = (d[2] << 8) | d[3];

	dev_info(&ts->spi->dev,
		 "panel info: resolution %ux%u, tx %u, rx %u\n", rx, ry, d[8], d[9]);

	if (!rx || !ry || rx > FTS_MAX_RESOLUTION || ry > FTS_MAX_RESOLUTION) {
		dev_warn(&ts->spi->dev,
			 "implausible resolution from IC, keeping %ux%u\n",
			 ts->max_x, ts->max_y);
		return 0;
	}

	ts->max_x = rx;
	ts->max_y = ry;
	return 0;
}

static int fts_check_id(struct fts_data *ts)
{
	u8 id[5] = {};
	int ret;

	ret = fts_read_cmd(ts, FTS_CMD_READ_DEVICE_ID, id, sizeof(id));
	if (ret)
		return ret;

	ts->chip_id = (id[2] << 16) | (id[3] << 8) | id[4];
	dev_info(&ts->spi->dev, "device id %*ph (chip_id %06x)\n",
		 5, id, ts->chip_id);

	/*
	 * The vendor's stm_ts_read_chip_id() rejects only when BOTH id bytes
	 * are wrong (&&, not ||). Mirror that rather than being stricter than
	 * the driver that is known to work on this panel.
	 */
	if (id[2] != FTS_ID0 && id[3] != FTS_ID1)
		return -ENODEV;

	return 0;
}

static int fts_start_scan(struct fts_data *ts)
{
	u8 cmd[3] = { FTS_CMD_SCAN_MODE, 0x00, FTS_SCAN_MODE_MS_SS };

	return fts_write(ts, cmd, sizeof(cmd), NULL, 0);
}

static int fts_probe(struct spi_device *spi)
{
	struct device *dev = &spi->dev;
	struct fts_data *ts;
	int ret;

	ts = devm_kzalloc(dev, sizeof(*ts), GFP_KERNEL);
	if (!ts)
		return -ENOMEM;

	ts->spi = spi;
	mutex_init(&ts->io_lock);
	spi_set_drvdata(spi, ts);

	ts->rxbuf_len = FTS_MAX_EVENTS * FTS_EVENT_SIZE + 1 + FTS_READ_HDR_MAX;
	ts->rxbuf = devm_kzalloc(dev, ts->rxbuf_len, GFP_KERNEL);
	if (!ts->rxbuf)
		return -ENOMEM;

	ts->max_x = 4096;
	ts->max_y = 4096;
	device_property_read_u32(dev, "touchscreen-size-x", &ts->max_x);
	device_property_read_u32(dev, "touchscreen-size-y", &ts->max_y);

	/*
	 * Both rails are required. The first attempt made them optional,
	 * assuming the bootloader left the controller powered for its splash;
	 * it does not. The ID read came back 00 00 00 00 00 -- the SPI clocked
	 * cleanly, MISO just never answered, because the part was dark. They
	 * come from an s2dos05 on a bitbanged i2c bus, so a missing supply
	 * here means the DT or that bus is broken and should be loud.
	 *
	 * vdd = 1.8V digital/IO (s2dos05 ldo2, vendor tsp_io_ldo)
	 * avdd = 3.0V analog   (s2dos05 ldo3, vendor tsp_avdd_ldo)
	 * Order matters: IO before analog, as the vendor driver does.
	 */
	ts->vdd = devm_regulator_get(dev, "vdd");
	if (IS_ERR(ts->vdd))
		return dev_err_probe(dev, PTR_ERR(ts->vdd), "no vdd\n");

	ts->avdd = devm_regulator_get(dev, "avdd");
	if (IS_ERR(ts->avdd))
		return dev_err_probe(dev, PTR_ERR(ts->avdd), "no avdd\n");

	ret = fts_power_cycle(ts);
	if (ret)
		return dev_err_probe(dev, ret, "failed to power the controller\n");

	ret = devm_add_action_or_reset(dev, fts_power_off_action, ts);
	if (ret)
		return ret;

	ret = fts_reset(ts);
	if (ret)
		return dev_err_probe(dev, ret, "reset failed\n");

	ret = fts_check_id(ts);
	if (ret)
		return dev_err_probe(dev, ret, "no FTS9CU80F found\n");

	ret = fts_read_panel_info(ts);
	if (ret)
		return dev_err_probe(dev, ret, "failed to read panel info\n");

	ts->input = devm_input_allocate_device(dev);
	if (!ts->input)
		return -ENOMEM;

	ts->input->name = "ST FTS9CU80F Touchscreen";
	ts->input->phys = "fts9cu80f/input0";
	ts->input->id.bustype = BUS_SPI;

	input_set_abs_params(ts->input, ABS_MT_POSITION_X, 0, ts->max_x - 1, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_POSITION_Y, 0, ts->max_y - 1, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_TOUCH_MAJOR, 0, 255, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_TOUCH_MINOR, 0, 255, 0, 0);

	touchscreen_parse_properties(ts->input, true, &ts->prop);

	if (swap_xy >= 0)
		ts->prop.swap_x_y = !!swap_xy;
	if (invert_x >= 0)
		ts->prop.invert_x = !!invert_x;
	if (invert_y >= 0)
		ts->prop.invert_y = !!invert_y;

	dev_info(dev, "orientation: swap_x_y=%d invert_x=%d invert_y=%d\n",
		 ts->prop.swap_x_y, ts->prop.invert_x, ts->prop.invert_y);

	ret = input_mt_init_slots(ts->input, FTS_MAX_SLOTS,
				  INPUT_MT_DIRECT | INPUT_MT_DROP_UNUSED);
	if (ret)
		return dev_err_probe(dev, ret, "failed to init MT slots\n");

	ret = input_register_device(ts->input);
	if (ret)
		return dev_err_probe(dev, ret, "failed to register input\n");

	ret = devm_request_threaded_irq(dev, spi->irq, NULL, fts_irq,
					IRQF_ONESHOT, "fts9cu80f", ts);
	if (ret)
		return dev_err_probe(dev, ret, "failed to request irq %d\n",
				     spi->irq);

	ret = fts_start_scan(ts);
	if (ret)
		return dev_err_probe(dev, ret, "failed to start scanning\n");

	dev_info(dev, "FTS9CU80F ready, %ux%u, irq %d\n",
		 ts->max_x, ts->max_y, spi->irq);
	return 0;
}

static const struct of_device_id fts_of_match[] = {
	{ .compatible = "st,fts9cu80f" },
	{ }
};
MODULE_DEVICE_TABLE(of, fts_of_match);

static struct spi_driver fts_driver = {
	.driver = {
		.name = "fts9cu80f",
		.of_match_table = fts_of_match,
	},
	.probe = fts_probe,
};
module_spi_driver(fts_driver);

MODULE_DESCRIPTION("ST FTS9CU80F SPI touchscreen");
MODULE_LICENSE("GPL");
