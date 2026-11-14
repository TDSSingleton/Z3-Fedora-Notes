#!/bin/bash
# READ-ONLY charging census for the Fold 3 under mainline. Writes nothing to
# any chip. Run on the device, ideally at mid SoC with USB attached:
#   python3 -I tools/dev.py put tools/charge-census.sh /root/charge-census.sh
#   python3 -I tools/dev.py run 'bash /root/charge-census.sh'
BUS=$(basename "$(readlink -f /sys/bus/i2c/devices/*-0066/..)" | sed s/i2c-//)
echo "== i2c7 is bus $BUS"
echo "== max77705 charger @0x69, regs 0xb0-0xc3 (INT, MASK, INT_OK, DTLS0-2, CNFG00-12)"
i2cdump -y -f -r 0xb0-0xc3 "$BUS" 0x69 b
echo "== fuel gauge"
for p in status capacity voltage_now current_now current_avg temp charge_now charge_full; do
	f=$(ls /sys/class/power_supply/*/$p 2>/dev/null | head -1)
	[ -n "$f" ] && echo "$p=$(cat "$f")"
done
echo "== TLMM pins (cfg, io): 86/74 main enb/enb2, 167 sub enb, 131/132 det, 8/9 i2c1, 40/41 i2c9"
python3 - <<'PY'
import mmap, os, struct
fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
for n in (86, 74, 167, 131, 132, 8, 9, 40, 41):
    m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ, offset=0xf100000 + 0x1000 * n)
    cfg, io = struct.unpack("<II", m[:8])
    print(f"gpio{n:<3} cfg=0x{cfg:08x} func={(cfg>>2)&0xf} pull={cfg&3} oe={(cfg>>9)&1} in={io&1} out={(io>>1)&1}")
    m.close()
PY
echo "== thermal zones"
for z in /sys/class/thermal/thermal_zone*; do echo "$(cat $z/type) $(cat $z/temp 2>/dev/null)"; done
