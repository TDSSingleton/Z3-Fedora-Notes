#!/bin/bash
# One-shot, self-reverting boot-time board-file test. Armed by /root/bdf-test/pending.
# The test file is already installed as board-2.bin; the original is board-2.bin.orig.
F=/lib/firmware/ath11k/WCN6855/hw2.0; T=/root/bdf-test
[ -e $T/pending ] || exit 0
label=$(cat $T/pending); rm -f $T/pending; sync
sleep 35
{ echo "=== $label  $(date +%T) up $(cut -d" " -f1 /proc/uptime)"; sha256sum $F/amss.bin $F/board-2.bin | cut -c1-12 | tr "\n" " "; echo
  dmesg | grep -E "ath11k" | grep -vE "^\[[ 0-9.]+\] ( |Workqueue)" | cut -c1-170 | head -14
  if ip -br link | grep -q wlp1s0 && ping -c3 -W2 -q 192.168.11.1 >/dev/null 2>&1; then echo "RESULT ok"
    for i in 1 2 3; do ping -c3 -i0.2 -q 192.168.11.1 >/dev/null 2>&1; iw dev wlp1s0 station dump | grep "signal: "; sleep 1; done
    btmgmt power on >/dev/null; echo "bt: $(timeout 12 btmgmt find 2>/dev/null | grep -oE "dev_found: [0-9A-F:]+ .*rssi -?[0-9]+" | sort -u -k2,2 | awk "{print \$NF}" | sort -n | tr "\n" " ")"
    ok=1
  elif dmesg | grep -q "firmware crashed"; then echo "RESULT crash"; else echo "RESULT no-wifi"; fi
} >> $T/results.log 2>&1
# always put the original back on disk; the running chip keeps what it loaded
for o in $F/*.orig; do mv -f $o ${o%.orig}; done; sync
[ -n "$ok" ] || { echo "rebooting to restore wifi" >> $T/results.log; sync; reboot; }
