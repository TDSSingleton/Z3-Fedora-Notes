import fcntl, os, struct, sys
ALLOC = 0xC0184800  # _IOWR('H', 0, struct dma_heap_allocation_data)
size = int(sys.argv[1]) if len(sys.argv) > 1 else 4200*3120*4
for heap in ("system", "default_cma_region", "reserved"):
    p = "/dev/dma_heap/" + heap
    try:
        fd = os.open(p, os.O_RDWR)
    except OSError as e:
        print(f"  {heap:<20} open failed: {e}"); continue
    buf = bytearray(struct.pack("QIIQ", size, 0, os.O_RDWR | os.O_CLOEXEC, 0))
    try:
        fcntl.ioctl(fd, ALLOC, buf, True)
        newfd = struct.unpack("QIIQ", bytes(buf))[1]
        print(f"  {heap:<20} OK   allocated {size/1048576:.1f} MiB (fd {newfd})")
        os.close(newfd)
    except OSError as e:
        print(f"  {heap:<20} FAIL {e}")
    os.close(fd)
