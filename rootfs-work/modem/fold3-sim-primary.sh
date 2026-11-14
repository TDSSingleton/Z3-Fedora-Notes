#!/bin/bash
# Fold 3: the nano-SIM tray is the modem's physical slot 2, and with Samsung's
# dual-SIM config the modem provisions it as the SECONDARY subscription.
# ModemManager only drives the primary one and fails with "sim-missing".
# Move the card's USIM app to the primary session. Runtime-only: rmtfs is
# read-only, so the modem forgets this every boot. Runs before ModemManager.
Q="qmicli -d qrtr://0"
for i in $(seq 1 40); do
	st=$(timeout 8 $Q --uim-get-card-status 2>/dev/null) && echo "$st" | grep -q "Card state: 'present'" && break
	sleep 1.5
done
[ -n "$st" ] || { echo "modem UIM service never answered"; exit 0; }
echo "$st" | grep -q "Primary GW:   slot" && { echo "primary session already provisioned"; exit 0; }
slot=$(echo "$st" | sed -n "s/.*Secondary GW: slot '\([0-9]\)'.*/\1/p")
[ -n "$slot" ] || { echo "no card on a secondary session (no SIM?)"; exit 0; }
aid=$(echo "$st" | grep -A1 "Application ID:" | sed -n 2p | tr -d ' \t')
[ -n "$aid" ] || { echo "no application id found"; exit 0; }
timeout 15 $Q --uim-change-provisioning-session="session-type=secondary-gw-provisioning,activate=no" >/dev/null 2>&1
sleep 1
timeout 15 $Q --uim-change-provisioning-session="session-type=primary-gw-provisioning,activate=yes,slot=$slot,aid=$aid" >/dev/null 2>&1
sleep 2
timeout 8 $Q --uim-get-card-status 2>/dev/null | grep "Primary GW"
exit 0
