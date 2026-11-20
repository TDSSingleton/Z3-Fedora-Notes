import mmap, os, struct, sys
BASE = 0xad00000
REGS = {"bps":0x7004,"ipe_0":0x8004,"sbi":0x9004,"ife_0":0xa004,
        "ife_1":0xb004,"ife_2":0xb070,"titan_top":0xc120}
f = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
m = mmap.mmap(f, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ, offset=BASE)
def r(o): return struct.unpack("<I", m[o:o+4])[0]
print(f"{'gdsc':<11} {'GDSCR':>10} {'CFG_GDSCR':>10}  PWR_ON SW_COLL HW_CTRL | UP_DONE DOWN_DONE RETAIN_FF")
for n, off in REGS.items():
    g, c = r(off), r(off + 4)
    print(f"{n:<11} {g:#010x} {c:#010x}  "
          f"{bool(g & (1<<31)):>6} {bool(g & 1):>7} {bool(g & (1<<1)):>7} | "
          f"{bool(c & (1<<16)):>7} {bool(c & (1<<15)):>9} {bool(c & (1<<11))}")
