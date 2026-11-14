#!/bin/bash
# usage: btmeasure.sh <label>  -- phone discovery count + phone RSSI at the laptop
MAC=${FOLD3_BT_MAC:?set FOLD3_BT_MAC to the Bluetooth address of the phone}; S=$(dirname "$0")
bluetoothctl remove $MAC >/dev/null 2>&1
adb shell su -c "'logcat -c; input keyevent KEYCODE_WAKEUP; am force-stop com.android.settings; am start -a android.settings.BLUETOOTH_PAIRING_SETTINGS'" >/dev/null 2>&1
( bluetoothctl --timeout 24 scan on > $S/host-scan-$1.txt 2>&1 & )
r=""
for i in $(seq 1 10); do sleep 2; v=$(bluetoothctl info $MAC 2>/dev/null | grep -oE 'RSSI: .*\((-?[0-9]+)\)' | grep -oE '\-[0-9]+'); [ -n "$v" ] && r="$r $v"; done
adb shell su -c "'logcat -d'" 2>/dev/null | grep deviceFoundCallback | awk '{print $NF}' | sort -u | wc -l | sed "s/^/[$1] phone found unique devices: /"
echo "[$1] phone RSSI at laptop (dBm):${r:- none}"
echo "[$1] laptop saw $(sed 's/\x1b\[[0-9;]*m//g' $S/host-scan-$1.txt | grep -c 'NEW. Device') devices"
