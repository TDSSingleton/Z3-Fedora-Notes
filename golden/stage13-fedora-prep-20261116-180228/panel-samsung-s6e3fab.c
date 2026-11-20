// SPDX-License-Identifier: GPL-2.0-only
/*
 * Samsung S6E3FAB (AMB623ZF01) -- the Galaxy Z Fold 3 COVER display.
 * 832x2268 command-mode AMOLED, DSC 1.1 (two 416x42 slices), 4 lanes, on the
 * second DSI controller (mdss_dsi1).
 *
 * Sibling of panel-work/panel-samsung-s6e3xa2.c (the inner panel) and built
 * the same way: every register write is a transcription of the vendor DT
 * (ss_dsi_panel_S6E3FAB_AMB623ZF01_HD in the merged post-ABL DT, decoded in
 * panel-work/decode-cover-s6e3fab.txt). Differences that matter:
 *
 *   * This panel is NOT lit by the bootloader when the phone boots unfolded,
 *     so unlike the inner panel it gets a true cold init from us, including a
 *     real reset pulse. Reset is TLMM 17 (qcom,platform-reset-gpio = 0x11 in
 *     the Samsung node -- NOT 24/25, which are the amps' i2c bus).
 *   * TE is TLMM 83, the SECONDARY vsync input: the DSI endpoint needs
 *     qcom,te-source = "mdp_vsync_s" or the DPU waits on the inner panel's TE.
 *   * Display-on (0x29) is a separate vendor command set and is sent from
 *     .enable -- the lesson from the inner panel, where its absence made the
 *     first blank permanent.
 *
 * Only the 120 Hz mode is advertised. The six vendor init streams differ in
 * one byte (0x60: 0x20 for 120/96/60p/48p, 0x00 for 60/48).
 *
 * Supplies (S2MPB02 "sub"): vdd3 = LDO10 1.8 V, vddr = LDO6 1.7 V,
 * vci = LDO15 3.0 V. The bootloader leaves all three on.
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
#include <drm/drm_connector.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <drm/drm_probe_helper.h>

static const struct regulator_bulk_data s6e3fab_supplies[] = {
	{ .supply = "vdd3" },
	{ .supply = "vddr" },
	{ .supply = "vci"  },
};

struct s6e3fab {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct regulator_bulk_data *supplies;
	struct gpio_desc *reset_gpio;
	struct drm_dsc_config dsc;
};

static inline struct s6e3fab *to_s6e3fab(struct drm_panel *panel)
{
	return container_of(panel, struct s6e3fab, panel);
}

#define key_f0_on(ctx)   mipi_dsi_dcs_write_seq_multi(ctx, 0xf0, 0x5a, 0x5a)
#define key_f0_off(ctx)  mipi_dsi_dcs_write_seq_multi(ctx, 0xf0, 0xa5, 0xa5)
/* the vendor stream closes three blocks with a5 5a, not a5 a5; kept verbatim */
#define key_f0_off2(ctx) mipi_dsi_dcs_write_seq_multi(ctx, 0xf0, 0xa5, 0x5a)

/* qcom,mdss-dsi-on-command of the hd120hs timing, 47 commands */
static void s6e3fab_on(struct s6e3fab *priv, struct mipi_dsi_multi_context *ctx,
		       struct drm_dsc_picture_parameter_set *pps)
{
	mipi_dsi_dcs_write_seq_multi(ctx, 0x2c, 0x00, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x11);
	mipi_dsi_msleep(ctx, 5);
	key_f0_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x1d, 0xf6);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf6, 0x00);
	key_f0_off(ctx);
	mipi_dsi_msleep(ctx, 120);
	key_f0_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x1d, 0xf6);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf6, 0x03);
	key_f0_off(ctx);
	key_f0_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x35, 0x00);
	key_f0_off(ctx);
	key_f0_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x23, 0xf4);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf4, 0x31);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xed, 0x04, 0x40, 0x20);
	key_f0_off(ctx);
	key_f0_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x3b, 0x91);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x91, 0x02);
	key_f0_off2(ctx);
	key_f0_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb9, 0x00, 0x00, 0x00, 0x00, 0x00,
				     0x00, 0x00, 0x11, 0x03);
	key_f0_off(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xfc, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xc5, 0x11, 0x10, 0x50, 0x50, 0xa0,
				     0x50, 0xa0);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xfc, 0xa5, 0xa5);
	key_f0_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x04, 0xf2);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf2, 0x40);
	key_f0_off2(ctx);
	/* PPS generated from priv->dsc; the vendor blob decodes to the same */
	mipi_dsi_compression_mode_multi(ctx, true);
	drm_dsc_pps_payload_pack(pps, &priv->dsc);
	mipi_dsi_picture_parameter_set_multi(ctx, pps);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x2c, 0x00, 0x00, 0x00);
	key_f0_on(ctx);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x60, 0x20);	/* 0x00 for 60/48 Hz */
	mipi_dsi_dcs_write_seq_multi(ctx, 0x53, 0x28);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x05, 0xc6);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xc6, 0x16, 0x01);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x0b, 0x92);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x92, 0x6f);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xb0, 0x2d, 0xc6);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xc6, 0x19);
	mipi_dsi_dcs_write_seq_multi(ctx, 0x51, 0x07, 0xff);
	mipi_dsi_dcs_write_seq_multi(ctx, 0xf7, 0x0f);
	key_f0_off(ctx);
}

static int s6e3fab_prepare(struct drm_panel *panel)
{
	struct s6e3fab *priv = to_s6e3fab(panel);
	struct mipi_dsi_multi_context ctx = { .dsi = priv->dsi };
	struct drm_dsc_picture_parameter_set pps;
	int ret;

	ret = regulator_bulk_enable(ARRAY_SIZE(s6e3fab_supplies), priv->supplies);
	if (ret < 0)
		return ret;
	usleep_range(10000, 11000);

	/* qcom,mdss-dsi-reset-sequence = <1 10>; pulse it so a warm chip resets */
	gpiod_set_value_cansleep(priv->reset_gpio, 1);
	usleep_range(5000, 6000);
	gpiod_set_value_cansleep(priv->reset_gpio, 0);
	usleep_range(5000, 6000);
	gpiod_set_value_cansleep(priv->reset_gpio, 1);
	usleep_range(10000, 11000);

	/* qcom,mdss-dsi-on-command-state = "dsi_lp_mode" */
	priv->dsi->mode_flags |= MIPI_DSI_MODE_LPM;

	s6e3fab_on(priv, &ctx, &pps);

	if (ctx.accum_err) {
		gpiod_set_value_cansleep(priv->reset_gpio, 0);
		regulator_bulk_disable(ARRAY_SIZE(s6e3fab_supplies), priv->supplies);
	}

	return ctx.accum_err;
}

/* samsung,display_on_tx_cmds_revA */
static int s6e3fab_enable(struct drm_panel *panel)
{
	struct s6e3fab *priv = to_s6e3fab(panel);
	struct mipi_dsi_multi_context ctx = { .dsi = priv->dsi };

	key_f0_on(&ctx);
	mipi_dsi_dcs_write_seq_multi(&ctx, 0x9f, 0xa5, 0xa5);
	mipi_dsi_dcs_set_display_on_multi(&ctx);
	mipi_dsi_msleep(&ctx, 21);
	mipi_dsi_dcs_write_seq_multi(&ctx, 0x9f, 0x5a, 0x5a);
	key_f0_off(&ctx);

	return ctx.accum_err;
}

/* qcom,mdss-dsi-off-command */
static int s6e3fab_unprepare(struct drm_panel *panel)
{
	struct s6e3fab *priv = to_s6e3fab(panel);
	struct mipi_dsi_multi_context ctx = { .dsi = priv->dsi };

	mipi_dsi_dcs_write_seq_multi(&ctx, 0x9f, 0xa5, 0xa5);
	mipi_dsi_dcs_write_seq_multi(&ctx, 0x28);
	mipi_dsi_msleep(&ctx, 20);
	mipi_dsi_dcs_write_seq_multi(&ctx, 0x10);
	mipi_dsi_dcs_write_seq_multi(&ctx, 0x9f, 0x5a, 0x5a);
	mipi_dsi_msleep(&ctx, 120);

	gpiod_set_value_cansleep(priv->reset_gpio, 0);
	regulator_bulk_disable(ARRAY_SIZE(s6e3fab_supplies), priv->supplies);

	return ctx.accum_err;
}

/* hd120hs: 832x2268, h 40/40/63 (pw/bp/fp), v 60/60/146, 120 Hz */
static const struct drm_display_mode s6e3fab_mode = {
	.clock	     = 296478,			/* 975 * 2534 * 120 / 1000 */
	.hdisplay    = 832,
	.hsync_start = 832 + 63,
	.hsync_end   = 832 + 63 + 40,
	.htotal	     = 832 + 63 + 40 + 40,
	.vdisplay    = 2268,
	.vsync_start = 2268 + 146,
	.vsync_end   = 2268 + 146 + 60,
	.vtotal	     = 2268 + 146 + 60 + 60,
	.type	     = DRM_MODE_TYPE_DRIVER | DRM_MODE_TYPE_PREFERRED,
};

static int s6e3fab_get_modes(struct drm_panel *panel,
			     struct drm_connector *connector)
{
	struct drm_display_mode *mode;

	mode = drm_mode_duplicate(connector->dev, &s6e3fab_mode);
	if (!mode)
		return -ENOMEM;
	drm_mode_set_name(mode);
	drm_mode_probed_add(connector, mode);

	/* qcom,mdss-pan-physical-{width,height}-dimension */
	connector->display_info.width_mm  = 54;
	connector->display_info.height_mm = 148;
	connector->display_info.bpc = 8;

	return 1;
}

static const struct drm_panel_funcs s6e3fab_panel_funcs = {
	.prepare   = s6e3fab_prepare,
	.unprepare = s6e3fab_unprepare,
	.enable    = s6e3fab_enable,
	.get_modes = s6e3fab_get_modes,
};

static int s6e3fab_bl_update_status(struct backlight_device *bl)
{
	struct mipi_dsi_device *dsi = bl_get_data(bl);

	return mipi_dsi_dcs_set_display_brightness_large(dsi,
						backlight_get_brightness(bl));
}

static const struct backlight_ops s6e3fab_bl_ops = {
	.update_status = s6e3fab_bl_update_status,
};

static int s6e3fab_probe(struct mipi_dsi_device *dsi)
{
	const struct backlight_properties props = {
		.type		= BACKLIGHT_RAW,
		.brightness	= 255,
		.max_brightness	= 510,	/* qcom,mdss-dsi-bl-max-level */
	};
	struct device *dev = &dsi->dev;
	struct s6e3fab *priv;
	int ret;

	priv = devm_drm_panel_alloc(dev, struct s6e3fab, panel,
				    &s6e3fab_panel_funcs,
				    DRM_MODE_CONNECTOR_DSI);
	if (IS_ERR(priv))
		return PTR_ERR(priv);

	ret = devm_regulator_bulk_get_const(dev, ARRAY_SIZE(s6e3fab_supplies),
					    s6e3fab_supplies, &priv->supplies);
	if (ret < 0)
		return dev_err_probe(dev, ret, "failed to get regulators\n");

	priv->reset_gpio = devm_gpiod_get(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(priv->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(priv->reset_gpio),
				     "failed to get reset-gpios\n");

	priv->dsi = dsi;
	mipi_dsi_set_drvdata(dsi, priv);

	dsi->lanes = 4;
	dsi->format = MIPI_DSI_FMT_RGB888;
	dsi->mode_flags = MIPI_DSI_CLOCK_NON_CONTINUOUS;

	priv->panel.prepare_prev_first = true;

	priv->panel.backlight = devm_backlight_device_register(dev, dev_name(dev),
					dev, dsi, &s6e3fab_bl_ops, &props);
	if (IS_ERR(priv->panel.backlight))
		return dev_err_probe(dev, PTR_ERR(priv->panel.backlight),
				     "failed to register backlight\n");

	ret = devm_drm_panel_add(dev, &priv->panel);
	if (ret)
		return ret;

	dsi->dsc = &priv->dsc;
	priv->dsc.dsc_version_major = 1;
	priv->dsc.dsc_version_minor = 1;
	priv->dsc.slice_height = 42;
	priv->dsc.slice_width = 416;
	priv->dsc.slice_count = 832 / 416;
	priv->dsc.bits_per_component = 8;
	priv->dsc.bits_per_pixel = 8 << 4;
	priv->dsc.block_pred_enable = true;

	ret = devm_mipi_dsi_attach(dev, dsi);
	if (ret < 0)
		return dev_err_probe(dev, ret, "failed to attach to DSI host\n");

	return 0;
}

static const struct of_device_id s6e3fab_of_match[] = {
	{ .compatible = "samsung,s6e3fab-amb623zf01" },
	{ }
};
MODULE_DEVICE_TABLE(of, s6e3fab_of_match);

static struct mipi_dsi_driver s6e3fab_driver = {
	.probe = s6e3fab_probe,
	.driver = {
		.name = "panel-samsung-s6e3fab",
		.of_match_table = s6e3fab_of_match,
	},
};
module_mipi_dsi_driver(s6e3fab_driver);

MODULE_DESCRIPTION("DRM driver for the Samsung S6E3FAB AMB623ZF01 cover AMOLED panel");
MODULE_LICENSE("GPL");
