/* SPDX-License-Identifier: GPL-2.0 */
/*
 * uniLoader board support for the Samsung Galaxy Z Fold 3
 * (SM-F926B, codename q2q, SoC SM8350 / lahaina).
 *
 * Why this exists: Samsung's ABL merges its own device-tree overlay fragments
 * into whatever DTB it loads, which corrupts a mainline DT. uniLoader presents
 * itself to ABL *as a kernel* and carries a DTB that ABL never inspects, so the
 * mainline DT reaches Linux untouched. We cannot patch ABL itself -- it is
 * verified against Samsung's root-of-trust hash in QFPROM fuses.
 *
 * Framebuffer values are the bootloader's continuous-splash surface, taken from
 * the vendor DTS (cont_splash_region) and the panel timings, both confirmed
 * against the device:
 *   base    0xE4000000, 35 MiB reserved (splash_region, no-map)
 *   panel   S6E3XA2_AMF755ZE01, 2208x1768 -- NATIVELY LANDSCAPE
 *   a 2208 x 1768 x 4 B surface is 14.89 MiB, so it fits the 35 MiB region
 *
 * Confirmed fitted panel, from ABL's own command line:
 *   msm_drm.dsi_display0=ss_dsi_panel_S6E3XA2_AMF755ZE01_QXGA  lcd_id=811044
 */

#include <board.h>
#include <util.h>
#include <drivers/framework.h>
#include <lib/simplefb.h>

static struct video_info q2q_fb = {
	.format = FB_FORMAT_ARGB8888,
	.width = 2208,
	.height = 1768,
	.stride = 4,
	.address = (void *)0xe4000000
};

/*
 * NO late_init here, deliberately.
 *
 * Attempts 7 and 8 added one that disabled the APSS watchdog by writing
 * WDT_EN at 0x17c10008. Both produced a total blackscreen after uniLoader's
 * banner, then a reboot -- the kernel never ran at all. late_init executes
 * between the banner and the jump to the kernel, so a fault on that MMIO
 * access (uniLoader need not map the watchdog's device memory) kills the
 * shim exactly there. Reverted: the armed watchdog is a far smaller problem
 * than never reaching Linux.
 */

static const struct device q2q_devices[] = {
	{ "simplefb", &q2q_fb, "fb" },
};

struct board_data board_ops = {
	.name = "samsung-q2q",
	.ops = {
	},
	.devices = q2q_devices,
	.num_devices = ARRAY_SIZE(q2q_devices),
	.quirks = 0
};
