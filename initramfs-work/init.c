/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Stage-1a init for sm8350-samsung-q2q. Freestanding: no libc, no dynamic
 * linker, no dependencies at all beyond the kernel's syscall ABI. It exists to
 * answer exactly one question -- did the kernel boot far enough to execute
 * userspace? -- with the smallest possible surface for anything else to go
 * wrong.
 *
 * Writes a banner to fd 1 (the kernel console, which on this device is the
 * framebuffer), then sleeps forever so the message stays on screen.
 *
 * aarch64-linux-gnu-gcc -nostdlib -static -ffreestanding -Os
 */

static long sys(long n, long a, long b, long c)
{
	register long x8 __asm__("x8") = n;
	register long x0 __asm__("x0") = a;
	register long x1 __asm__("x1") = b;
	register long x2 __asm__("x2") = c;
	__asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2) : "memory");
	return x0;
}

#define SYS_openat         56
#define SYS_close          57
#define SYS_write          64
#define SYS_nanosleep      101
#define SYS_reboot         142

#define AT_FDCWD           -100
#define O_WRONLY           1
#define O_NOCTTY           256

/*
 * Where our output goes.
 *
 * The kernel's console_on_rootfs() opens /dev/console as fd 0 and dups it to
 * 1 and 2 -- but ONLY if that device node exists in the initramfs. The first
 * version of this initramfs had an empty /dev, so init started with no stdio
 * and every write() silently returned EBADF. The kernel log looked perfect and
 * ended at the last late_initcall, with no banner and no panic.
 *
 * The node is created now (see tools/build-initramfs.sh), but we also open it
 * ourselves rather than trusting inherited descriptors.
 */
static int confd = 1;

static unsigned long slen(const char *s)
{
	const char *p = s;
	while (*p)
		p++;
	return (unsigned long)(p - s);
}

static void say(const char *s)
{
	unsigned long n = slen(s);

	/*
	 * Single write. An earlier version also wrote to fd 1 whenever confd
	 * differed, as insurance while we still did not know if /dev/console
	 * worked. It does, and the serial capture showed every line twice.
	 */
	sys(SYS_write, confd, (long)s, (long)n);
}

/* Open /dev/console directly; fall back to the inherited fd 1. */
static void open_console(void)
{
	long fd = sys(SYS_openat, AT_FDCWD, (long)"/dev/console",
		      O_WRONLY | O_NOCTTY);
	if (fd >= 0)
		confd = (int)fd;
}

void _start(void)
{
	/* timespec { tv_sec, tv_nsec } */
	long ts[2] = { 5, 0 };

	open_console();

	say("\n");
	say("================================================\n");
	say("  Galaxy Z Fold 3 (SM-F926B / q2q)\n");
	say("  mainline kernel reached USERSPACE\n");
	say("================================================\n");
	say("\n");
	say("  If you are reading this on the inner screen then:\n");
	say("    - ABL accepted the uniLoader image\n");
	say("    - uniLoader relocated and jumped to the kernel\n");
	say("    - the DT /memory ranges are usable\n");
	say("    - simpledrm bound the bootloader framebuffer\n");
	say("    - the initramfs unpacked and /init ran\n");
	say("\n");
	say("  Nothing else is being attempted. Holding here.\n");
	say("  Power-cycle to return to Android (boot is untouched).\n");
	say("\n");

	for (;;) {
		say(".");
		ts[0] = 5;
		ts[1] = 0;
		sys(SYS_nanosleep, (long)ts, 0, 0);
	}
}
