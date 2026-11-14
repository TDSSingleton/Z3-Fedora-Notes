#!/bin/bash
# upstream amss + the given board-2.bin (tmpfs firmware path), with a COLD reset of the WLAN
# half before each load: the firmware keeps state across a plain driver rebind and then
# rejects any board file that differs from the first one it saw.
exec >/root/wl-bdf-test.log 2>&1
cd /root
P=/run/fwtest/ath11k/WCN6855/hw2.0; mkdir -p $P; cp $1 $P/board-2.bin
cold() {
  [ -e /sys/bus/pci/devices/0000:01:00.0 ] && echo 1 > /sys/bus/pci/devices/0000:01:00.0/remove; sleep 1
  python3 tlmm.py out 94 0 >/dev/null; python3 tlmm.py out 64 0 >/dev/null; sleep 0.5
  python3 tlmm.py out 64 1 >/dev/null; sleep 0.2; python3 tlmm.py out 94 1 >/dev/null; sleep 1
  echo "LnkSta=$(setpci -s 00:00.0 CAP_EXP+0x12.w)"
  echo 1 > /sys/bus/pci/devices/0000:00:00.0/remove; sleep 1; echo 1 > /sys/bus/pci/rescan
}
waitfw() { n=0; until ip -br link | grep -q wlp1s0 || dmesg | grep -q "failed to load board data file" || [ $n -ge 40 ]; do sleep 1; n=$((n+1)); done; }
nmcli device disconnect wlp1s0 >/dev/null 2>&1
echo -n /run/fwtest > /sys/module/firmware_class/parameters/path
dmesg -C; cold; waitfw
if dmesg | grep -q "firmware crashed"; then echo "RESULT crash"; sleep 3
elif ip -br link | grep -q wlp1s0; then nmcli device connect wlp1s0 >/dev/null 2>&1; sleep 8; echo "RESULT ok"
  for i in 1 2 3; do ping -c3 -i0.2 -q 192.168.11.1 >/dev/null 2>&1; iw dev wlp1s0 station dump | grep "signal: "; sleep 1; done
  [ "$2" = keep ] && { echo KEEPING; exit 0; }
else echo "RESULT no-iface"; dmesg | grep -E "ath11k|mhi|pci" | tail -6; fi
echo -n "" > /sys/module/firmware_class/parameters/path; rm -f $P/board-2.bin
dmesg -C; cold; waitfw; sleep 2
if ip -br link | grep -q wlp1s0; then nmcli device connect wlp1s0 >/dev/null 2>&1; else echo "wifi did not return, rebooting"; reboot; fi
echo done
