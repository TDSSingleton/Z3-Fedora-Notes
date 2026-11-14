// SPDX-License-Identifier: GPL-2.0
/*
 * Experiment only: write one RPMh VRM register for a named resource, behind
 * the regulator framework's back. insmod rpmh_poke.ko res=ldoe7 off=4 val=0
 * off: 0 = voltage (mV), 4 = enable, 8 = mode.
 */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <soc/qcom/cmd-db.h>
#include <soc/qcom/rpmh.h>
#include <soc/qcom/tcs.h>

static char *res = "";
module_param(res, charp, 0444);
static char *dev = "18200000.rsc:regulators-2";
module_param(dev, charp, 0444);
static uint off = 4, val;
module_param(off, uint, 0444);
module_param(val, uint, 0444);

static int __init rpmh_poke_init(void)
{
	struct device *d = bus_find_device_by_name(&platform_bus_type, NULL, dev);
	struct tcs_cmd cmd = { .data = val };
	u32 addr = cmd_db_read_addr(res);
	int ret;

	if (!d || !addr) {
		pr_err("rpmh_poke: dev %p addr %#x\n", d, addr);
		return -ENODEV;
	}
	cmd.addr = addr + off;
	ret = rpmh_write(d, RPMH_ACTIVE_ONLY_STATE, &cmd, 1);
	pr_info("rpmh_poke: %s addr %#x <- %u: %d\n", res, cmd.addr, val, ret);
	put_device(d);
	return ret ? ret : -EAGAIN;	/* never stay loaded */
}
module_init(rpmh_poke_init);
MODULE_LICENSE("GPL");
