// SPDX-License-Identifier: GPL-2.0
/*
 * TEST ONLY: vote PMR735A S3 ("smpe3", the QCA6490 internal-PA rail) on at
 * 2.2 V through ordinary RPMh requests, to test the hypothesis that the
 * firmware crashes because nothing powers the PA. The vendor arms a PDC TCS
 * for this (cnss_enable_int_pow_amp_vreg); that MMIO region resets the phone
 * when touched from the non-secure world, so this goes through the RSC.
 * rmmod drops the enable vote.
 */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <soc/qcom/cmd-db.h>
#include <soc/qcom/rpmh.h>
#include <soc/qcom/tcs.h>

static unsigned int mv = 2200;
module_param(mv, uint, 0444);

static struct device *rdev;
static u32 addr;

static int __init s3e_init(void)
{
	struct tcs_cmd v = { }, e = { };
	int ret;

	rdev = bus_find_device_by_name(&platform_bus_type, NULL,
				       "18200000.rsc:regulators-2");
	if (!rdev)
		return -ENODEV;
	addr = cmd_db_read_addr("smpe3");
	if (!addr) {
		put_device(rdev);
		return -ENOENT;
	}
	v.addr = addr;       v.data = mv;	/* VRM voltage, mV */
	e.addr = addr + 4;   e.data = 1;	/* VRM enable */
	ret = rpmh_write(rdev, RPMH_ACTIVE_ONLY_STATE, &v, 1);
	if (!ret)
		ret = rpmh_write(rdev, RPMH_ACTIVE_ONLY_STATE, &e, 1);
	pr_info("s3e_test: smpe3 @0x%x -> %u mV enable, ret=%d\n", addr, mv, ret);
	if (ret)
		put_device(rdev);
	return ret;
}

static void __exit s3e_exit(void)
{
	struct tcs_cmd e = { .addr = addr + 4, .data = 0 };

	pr_info("s3e_test: disable ret=%d\n",
		rpmh_write(rdev, RPMH_ACTIVE_ONLY_STATE, &e, 1));
	put_device(rdev);
}
module_init(s3e_init);
module_exit(s3e_exit);
MODULE_LICENSE("GPL");
