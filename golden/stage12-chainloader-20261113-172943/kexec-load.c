// kexec-load <Image> <initramfs|-> <cmdline>   |   kexec-load exec
// Minimal kexec for the Fold 3 loader initramfs: kexec_file_load(2), which on
// arm64 reuses the running kernel's device tree (the one uniLoader passed in),
// then reboot(LINUX_REBOOT_CMD_KEXEC). Built freestanding against the kernel's
// nolibc (no static libc needed):
//   aarch64-linux-gnu-gcc -nostdlib -static -Os -include <tree>/tools/include/nolibc/nolibc.h
#include <linux/kexec.h>
#include <linux/reboot.h>

int main(int argc, char **argv)
{
	if (argc == 2 && !strcmp(argv[1], "exec")) {
		__nolibc_syscall0(__NR_sync);
		__nolibc_syscall4(__NR_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2, LINUX_REBOOT_CMD_KEXEC, 0);
		printf("kexec exec failed\n");
		return 1;
	}
	if (argc < 4) {
		printf("usage: %s <Image> <initramfs|-> <cmdline>   |   %s exec\n", argv[0], argv[0]);
		return 2;
	}
	int kfd = open(argv[1], O_RDONLY);
	if (kfd < 0) { printf("open %s failed: errno %d\n", argv[1], errno); return 1; }
	long ifd = -1;
	unsigned long flags = KEXEC_FILE_NO_INITRAMFS;
	if (strcmp(argv[2], "-")) {
		ifd = open(argv[2], O_RDONLY);
		if (ifd < 0) { printf("open %s failed: errno %d\n", argv[2], errno); return 1; }
		flags = 0;
	}
	/* Plain locals only below: the syscall macro pins its arguments to
	 * registers one by one, and a function call among them (strlen) would
	 * clobber the ones already loaded -- that gave -EFAULT. */
	long klen = strlen(argv[3]) + 1;
	long kfd_l = kfd;
	const char *cmd = argv[3];
	long r = __nolibc_syscall5(__NR_kexec_file_load, kfd_l, ifd, klen, cmd, flags);
	if (r) { printf("kexec_file_load failed: %d\n", (int)r); return 1; }
	printf("kexec: loaded %s\n", argv[1]);
	return 0;
}
