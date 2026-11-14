#!/bin/bash
# Is the weak Bluetooth a dead antenna shared with one WiFi chain?
#
# QCA6490 WiFi is 2x2; BT rides one of the 2.4 GHz chains. "WiFi is fine at
# -43 dBm" is the COMBINED figure and says nothing about each chain alone.
# If one chain sits ~40 dB under the other, that antenna/flex is broken and
# BT is on it -- hardware, nothing left to fix in software.
#
#   tools/bt-chain-test.sh            passive: per-chain RSSI, changes nothing
#   tools/bt-chain-test.sh --force    also runs each chain alone (WiFi drops
#                                     ~1 min, restores itself, log on phone)
#
# The phone must be associated on 2.4 GHz for the result to mean anything.
set -u
HOST=${FOLD3_HOST:-192.168.11.131}
SSH="ssh -i $HOME/.ssh/fold3_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=8 root@$HOST"

$SSH 'sh -s' <<'REMOTE'
echo "== link"; iw dev wlan0 link
echo "== station (look at: signal: -NN [-chain0, -chain1] dBm)"
for i in 1 2 3 4 5; do iw dev wlan0 station dump | grep -E "signal|bitrate"; sleep 1; done
echo "== antennas"; iw phy | grep -iE "Wiphy|antenna"
echo "== bt"; hciconfig hci0 2>/dev/null | head -3
REMOTE

[ "${1:-}" = "--force" ] || exit 0

# Detached on the phone: SSH dies when wlan0 goes down, the script must not.
$SSH 'cat > /root/chain-force.sh; chmod +x /root/chain-force.sh; setsid nohup /root/chain-force.sh >/root/chain-force.log 2>&1 </dev/null &' <<'REMOTE'
#!/bin/sh
PHY=$(iw dev wlan0 info | awk '/wiphy/{print "phy"$2}')
restore() { ip link set wlan0 down; iw phy $PHY set antenna 3 3; ip link set wlan0 up; nmcli device connect wlan0; }
trap restore EXIT
for m in 1 2; do
    echo "=== chainmask $m"
    nmcli device disconnect wlan0
    ip link set wlan0 down
    iw phy $PHY set antenna $m $m || { echo "set antenna $m failed"; continue; }
    ip link set wlan0 up
    nmcli device connect wlan0 || echo "no association on mask $m"
    sleep 8
    iw dev wlan0 link
    for i in 1 2 3 4 5; do iw dev wlan0 station dump | grep -E "signal"; sleep 1; done
    echo "--- bt scan with only chain $m on WiFi"
    timeout 15 btmgmt find 2>&1 | grep -c "dev_found"
done
REMOTE
echo "forced run started; in ~90 s:  $SSH cat /root/chain-force.log"
