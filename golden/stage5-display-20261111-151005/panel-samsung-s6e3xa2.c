// SPDX-License-Identifier: GPL-2.0-only
/*
 * Samsung S6E3XA2 (AMF755ZE01) foldable AMOLED panel
 * Inner display of the Samsung Galaxy Z Fold 3 (SM-F926B, codename q2q).
 *
 * Command sequences, timings and DSC parameters transcribed from the Samsung
 * GPL kernel release for SM-F926B, board revision r08 (the revision fitted to
 * units reporting ro.revision = 9):
 *   arch/arm64/boot/dts/samsung/q2/q2q/q2q_eur_openx_w00_r08.dts
 *   techpack/display/msm/samsung/S6E3XA2_AMF755ZE01/
 * via tools/extract-panel-cmds.py + tools/gen-panel-init.py in this repo.
 *
 * Copyright (c) 2021 Samsung Electronics Co., Ltd.  (original sequences)
 *
 * ============================== STATUS ==============================
 * NOT COMPILED. NEVER RUN ON HARDWARE.
 *
 * It is, however, the only missing piece: the SM8350 display stack is already
 * upstream -- dispcc (via the multi-SoC dispcc-sm8250.c, CONFIG_SM_DISPCC_8250),
 * dpu_sm8350_cfg, DSI 6G v2.6.0 and dsi_phy_5nm_8350_cfgs -- and sm8350.dtsi is
 * already wired correctly. Nothing SoC-level is required.
 *
 * Structure follows upstream drivers/gpu/drm/panel/panel-samsung-s6e3ha8.c,
 * which is the closest in-tree relative: a Samsung command-mode DSC panel.
 * ====================================================================
 */

#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>

#include <drm/display/drm_dsc.h>
#include <drm/display/drm_dsc_helper.h>
#include <drm/drm_mipi_dsi.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <drm/drm_probe_helper.h>

/*
 * Panel supplies, from qcom,panel-supply-entries in the board DTS. All come
 * off the S2DOS05 display PMIC, whose driver (CONFIG_REGULATOR_S2DOS05) is
 * already upstream.
 *
 *   panel_vdd3  1.8 V   logic / VDDI
 *   panel_vddr  1.8 V   (the DTS drops this to 1.6 V in LPM)
 *   panel_vci   3.0 V   10 ms post-on settle
 */
static const struct regulator_bulk_data s6e3xa2_supplies[] = {
	{ .supply = "vdd3" },
	{ .supply = "vddr" },
	{ .supply = "vci"  },
};

struct s6e3xa2 {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct regulator_bulk_data *supplies;
	struct gpio_desc *reset_gpio;
	/*
	 * tlmm 97. Samsung calls it "mipisel"; dsi_panel.c drives it high in the
	 * panel power-on path and low on power-off. It looks like a lane-switch
	 * or redriver enable on the flex crossing the hinge. It is NOT a mux
	 * between the two displays -- those have independent DSI controllers,
	 * PHYs and TE lines.
	 */
	struct gpio_desc *mipisel_gpio;
	/*
	 * Must be mutable and per-instance: msm's DSI host reads computed fields
	 * out of this (slice_chunk_size and friends, filled by
	 * drm_dsc_compute_rc_parameters()). A shared const config would be wrong.
	 */
	struct drm_dsc_config dsc;
};

static inline struct s6e3xa2 *to_s6e3xa2(struct drm_panel *panel)
{
	return container_of(panel, struct s6e3xa2, panel);
}

/*
 * Samsung "test key" register locks. The panel rejects most manufacturer
 * commands unless the matching level is unlocked. Note the inverted payloads:
 * level 0 unlocks with a5 a5, levels 1 and 2 unlock with 5a 5a.
 */
#define s6e3xa2_key_lvl0_on(ctx)  mipi_dsi_dcs_write_seq_multi(ctx, 0x9f, 0xa5, 0xa5)
#define s6e3xa2_key_lvl0_off(ctx) mipi_dsi_dcs_write_seq_multi(ctx, 0x9f, 0x5a, 0x5a)
#define s6e3xa2_key_lvl1_on(ctx)  mipi_dsi_dcs_write_seq_multi(ctx, 0xf0, 0x5a, 0x5a)
#define s6e3xa2_key_lvl1_off(ctx) mipi_dsi_dcs_write_seq_multi(ctx, 0xf0, 0xa5, 0xa5)
#define s6e3xa2_key_lvl2_on(ctx)  mipi_dsi_dcs_write_seq_multi(ctx, 0xfc, 0x5a, 0x5a)
#define s6e3xa2_key_lvl2_off(ctx) mipi_dsi_dcs_write_seq_multi(ctx, 0xfc, 0xa5, 0xa5)

/* Generated init sequence -- see the file header for provenance. */
static void s6e3xa2_on(struct s6e3xa2 *priv,
		       struct mipi_dsi_multi_context *ctx,
		       struct drm_dsc_picture_parameter_set *pps)
{
	s6e3xa2_key_lvl0_on(ctx);
	s6e3xa2_key_lvl1_on(ctx);
	s6e3xa2_key_lvl2_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf1, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xd0, 0x08);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x0d, 0xc1);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xc1, 0xdb);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x2a, 0xc1);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xc1, 0xc0);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x03, 0x7e, 0x68);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x68, 0x01, 0x30);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x38, 0x68);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x68, 0x01, 0x30, 0x01, 0x00, 0x50);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x11);
	mipi_dsi_msleep(ctx, 120);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x2a, 0xc1);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xc1, 0x00);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf1, 0xf1, 0xa2);
	/*
	 * DSC. The vendor stream sends compression-mode enable followed by a raw
	 * 89-byte PPS blob at exactly this point. Upstream generates the PPS from
	 * priv->dsc instead, so the two can never drift apart. Verified: the
	 * vendor blob decodes to precisely the values set in _probe().
	 */
	mipi_dsi_compression_mode_multi(ctx, true);
	drm_dsc_pps_payload_pack(pps, &priv->dsc);
	mipi_dsi_picture_parameter_set_multi(ctx, pps);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x35, 0x00);
	/*
	 * The ONLY byte differing between the four vendor init streams: 0x00 for
	 * the 120/96 Hz modes, 0x01 for 60/48 Hz. All 602 bytes are otherwise
	 * byte-identical across all four. This driver advertises only 120/96 Hz,
	 * so 0x00 is correct unconditionally -- see the mode table.
	 */
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb9, 0x01, 0x00, 0x06, 0xfe, 0x07, 0x09);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x2d, 0xf4);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf4, 0x18);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x01, 0xed);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xed, 0x40, 0x20);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x1e, 0xc5);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xc5, 0x11, 0x10, 0x50, 0x05, 0x4d, 0x7c, 0x4b, 0xef);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb9, 0x00);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x0e, 0xb9);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb9, 0xb1, 0x21);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x19, 0xb9);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb9, 0x08, 0xcc, 0xcc, 0xcc);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0xae, 0x68);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x68, 0x01, 0x30, 0x01, 0x30, 0x01, 0x30);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x60, 0x08, 0x00);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x0e, 0x66);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x66, 0x01);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0xd6, 0x63);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x63, 0x02);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x0d, 0x66);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x66, 0x60);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x53, 0x28);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x00, 0x12, 0x66);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x66, 0x16);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x51, 0x00, 0x55);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf7, 0x0f);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf1, 0xa5, 0xa5);
	s6e3xa2_key_lvl2_off(ctx);
	s6e3xa2_key_lvl1_off(ctx);
	s6e3xa2_key_lvl0_off(ctx);
}

static void s6e3xa2_off(struct mipi_dsi_multi_context *ctx)
{
	s6e3xa2_key_lvl0_on(ctx);
	s6e3xa2_key_lvl1_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x28);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x10);
	s6e3xa2_key_lvl1_off(ctx);
	mipi_dsi_msleep(ctx, 120);
	s6e3xa2_key_lvl0_off(ctx);
}

static void s6e3xa2_reset(struct s6e3xa2 *priv)
{
	/* qcom,mdss-dsi-reset-sequence = <1 10> in the board DTS */
	gpiod_set_value_cansleep(priv->reset_gpio, 1);
	usleep_range(5000, 6000);
	gpiod_set_value_cansleep(priv->reset_gpio, 0);
	usleep_range(5000, 6000);
	gpiod_set_value_cansleep(priv->reset_gpio, 1);
	usleep_range(10000, 11000);
}

static int s6e3xa2_prepare(struct drm_panel *panel)
{
	struct s6e3xa2 *priv = to_s6e3xa2(panel);
	struct mipi_dsi_multi_context ctx = { .dsi = priv->dsi };
	struct drm_dsc_picture_parameter_set pps;
	int ret;

	ret = regulator_bulk_enable(ARRAY_SIZE(s6e3xa2_supplies), priv->supplies);
	if (ret < 0)
		return ret;
	usleep_range(10000, 11000);	/* panel_vci post-on-sleep = 10 ms */

	gpiod_set_value_cansleep(priv->mipisel_gpio, 1);
	s6e3xa2_reset(priv);

	/* qcom,mdss-dsi-on-command-state = "dsi_lp_mode" */
	priv->dsi->mode_flags |= MIPI_DSI_MODE_LPM;

	s6e3xa2_on(priv, &ctx, &pps);

	if (ctx.accum_err) {
		gpiod_set_value_cansleep(priv->reset_gpio, 0);
		gpiod_set_value_cansleep(priv->mipisel_gpio, 0);
		regulator_bulk_disable(ARRAY_SIZE(s6e3xa2_supplies),
				       priv->supplies);
	}

	return ctx.accum_err;
}

static int s6e3xa2_unprepare(struct drm_panel *panel)
{
	struct s6e3xa2 *priv = to_s6e3xa2(panel);
	struct mipi_dsi_multi_context ctx = { .dsi = priv->dsi };

	s6e3xa2_off(&ctx);

	gpiod_set_value_cansleep(priv->reset_gpio, 0);
	gpiod_set_value_cansleep(priv->mipisel_gpio, 0);
	regulator_bulk_disable(ARRAY_SIZE(s6e3xa2_supplies), priv->supplies);

	return ctx.accum_err;
}

/*
 * Mode table, from qcom,mdss-dsi-display-timings in the board DTS.
 *
 * The panel is natively LANDSCAPE: 2208x1768, physical 149 x 119 mm. The two
 * aspect ratios agree to three decimal places, so this is not a DTS typo --
 * the glass really does scan along the hinge, and the compositor must rotate.
 *
 * The DSI bit clock (1'362'000'000 Hz) and the PHY timings
 * [00 2c 0c 0c 29 26 0c 0c 0b 02 04 00 25 1b] are identical in all four vendor
 * modes, and vtotal is a constant 1965; only the vertical porch split shifts.
 * That is expected for a command-mode panel, where the refresh rate is set by
 * how often the host pushes a frame rather than by the blanking.
 */
static const struct drm_display_mode s6e3xa2_modes[] = {
	{
		/* qxga120hs -- preferred. 2436 htotal * 1965 vtotal * 120 Hz */
		.clock	     = 574408,
		.hdisplay    = 2208,
		.hsync_start = 2208 + 76,			/* + hfp */
		.hsync_end   = 2208 + 76 + 76,			/* + hpw */
		.htotal	     = 2208 + 76 + 76 + 76,		/* + hbp */
		.vdisplay    = 1768,
		.vsync_start = 1768 + 61,			/* + vfp */
		.vsync_end   = 1768 + 61 + 68,			/* + vpw */
		.vtotal	     = 1768 + 61 + 68 + 68,		/* + vbp */
		.type	     = DRM_MODE_TYPE_DRIVER,
	}, {
		/* qxga96hs. Same vtotal (1965); only the porch split moves. */
		.clock	     = 459527,
		.hdisplay    = 2208,
		.hsync_start = 2208 + 76,
		.hsync_end   = 2208 + 76 + 76,
		.htotal	     = 2208 + 76 + 76 + 76,
		.vdisplay    = 1768,
		.vsync_start = 1768 + 62,
		.vsync_end   = 1768 + 62 + 68,
		.vtotal	     = 1768 + 62 + 68 + 67,
		.type	     = DRM_MODE_TYPE_DRIVER,
	},
	/*
	 * 60 Hz (vfp 63, vbp 66) and 48 Hz (vfp 64, vbp 65) are deliberately
	 * omitted: they need the 0xb9 byte set to 0x01, and drm_panel has no
	 * mode_set callback to select per-mode init from. Advertising them would
	 * mean advertising modes this driver initialises incorrectly.
	 */
};

static int s6e3xa2_get_modes(struct drm_panel *panel,
			     struct drm_connector *connector)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(s6e3xa2_modes); i++) {
		struct drm_display_mode *mode;

		mode = drm_mode_duplicate(connector->dev, &s6e3xa2_modes[i]);
		if (!mode)
			return -ENOMEM;

		if (i == 0)
			mode->type |= DRM_MODE_TYPE_PREFERRED;
		drm_mode_set_name(mode);
		drm_mode_probed_add(connector, mode);
	}

	connector->display_info.width_mm  = 149;
	connector->display_info.height_mm = 119;
	connector->display_info.bpc = 8;

	return ARRAY_SIZE(s6e3xa2_modes);
}

static const struct drm_panel_funcs s6e3xa2_panel_funcs = {
	.prepare   = s6e3xa2_prepare,
	.unprepare = s6e3xa2_unprepare,
	.get_modes = s6e3xa2_get_modes,
};

/*
 * Backlight. qcom,mdss-dsi-bl-pmic-control-type = "bl_ctrl_dcs",
 * bl-max-level = 0x1fe (510), brightness-default-level = 0xff.
 * DCS 0x51 carries a 16-bit value; the vendor init writes 0x51 0x00 0x55.
 *
 * Ordering trap, reported independently by the Galaxy S22 mainline port and
 * confirmed in this panel's own init stream: 0x53 must be written BEFORE 0x51.
 * The init sequence above already does so.
 */
static int s6e3xa2_bl_update_status(struct backlight_device *bl)
{
	struct mipi_dsi_device *dsi = bl_get_data(bl);
	u16 brightness = backlight_get_brightness(bl);

	return mipi_dsi_dcs_set_display_brightness_large(dsi, brightness);
}

static const struct backlight_ops s6e3xa2_bl_ops = {
	.update_status = s6e3xa2_bl_update_status,
};

static struct backlight_device *s6e3xa2_create_backlight(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	const struct backlight_properties props = {
		.type		= BACKLIGHT_RAW,
		.brightness	= 255,
		.max_brightness	= 510,
	};

	return devm_backlight_device_register(dev, dev_name(dev), dev, dsi,
					      &s6e3xa2_bl_ops, &props);
}

static int s6e3xa2_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	struct s6e3xa2 *priv;
	int ret;

	priv = devm_drm_panel_alloc(dev, struct s6e3xa2, panel,
				    &s6e3xa2_panel_funcs,
				    DRM_MODE_CONNECTOR_DSI);
	if (IS_ERR(priv))
		return PTR_ERR(priv);

	ret = devm_regulator_bulk_get_const(dev, ARRAY_SIZE(s6e3xa2_supplies),
					    s6e3xa2_supplies, &priv->supplies);
	if (ret < 0)
		return dev_err_probe(dev, ret, "failed to get regulators\n");

	priv->reset_gpio = devm_gpiod_get(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(priv->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(priv->reset_gpio),
				     "failed to get reset-gpios\n");

	priv->mipisel_gpio = devm_gpiod_get_optional(dev, "mipi-sel",
						     GPIOD_OUT_LOW);
	if (IS_ERR(priv->mipisel_gpio))
		return dev_err_probe(dev, PTR_ERR(priv->mipisel_gpio),
				     "failed to get mipi-sel-gpios\n");

	priv->dsi = dsi;
	mipi_dsi_set_drvdata(dsi, priv);

	dsi->lanes = 4;
	dsi->format = MIPI_DSI_FMT_RGB888;
	/* samsung,mdss-dsi-sot-hs-mode; qcom,mdss-dsi-rx-eot-ignore/tx-eot-append */
	dsi->mode_flags = MIPI_DSI_CLOCK_NON_CONTINUOUS;

	priv->panel.prepare_prev_first = true;

	priv->panel.backlight = s6e3xa2_create_backlight(dsi);
	if (IS_ERR(priv->panel.backlight))
		return dev_err_probe(dev, PTR_ERR(priv->panel.backlight),
				     "failed to register backlight\n");

	ret = devm_drm_panel_add(dev, &priv->panel);
	if (ret)
		return ret;

	/*
	 * DSC is mandatory on this panel. Values cross-checked two independent
	 * ways that agree exactly: the qcom,mdss-dsc-* DTS properties, and a
	 * decode of the raw 89-byte PPS blob in the vendor init stream.
	 * See panel-work/decode-main-s6e3xa2.txt.
	 */
	dsi->dsc = &priv->dsc;

	priv->dsc.dsc_version_major = 1;
	priv->dsc.dsc_version_minor = 1;
	priv->dsc.slice_height = 34;
	priv->dsc.slice_width = 1104;
	WARN_ON(2208 % priv->dsc.slice_width);
	priv->dsc.slice_count = 2208 / priv->dsc.slice_width;
	priv->dsc.bits_per_component = 8;
	priv->dsc.bits_per_pixel = 8 << 4;	/* 8.0 bpp, 4 fractional bits */
	priv->dsc.block_pred_enable = true;

	ret = devm_mipi_dsi_attach(dev, dsi);
	if (ret < 0)
		return dev_err_probe(dev, ret, "failed to attach to DSI host\n");

	return 0;
}

static const struct of_device_id s6e3xa2_of_match[] = {
	{ .compatible = "samsung,s6e3xa2-amf755ze01" },
	{ }
};
MODULE_DEVICE_TABLE(of, s6e3xa2_of_match);

static struct mipi_dsi_driver s6e3xa2_driver = {
	.probe = s6e3xa2_probe,
	.driver = {
		.name = "panel-samsung-s6e3xa2",
		.of_match_table = s6e3xa2_of_match,
	},
};
module_mipi_dsi_driver(s6e3xa2_driver);

MODULE_DESCRIPTION("DRM driver for Samsung S6E3XA2 AMF755ZE01 foldable AMOLED panel");
MODULE_LICENSE("GPL");
