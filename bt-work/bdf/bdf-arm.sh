#!/bin/bash
# bdf-arm.sh <label> <dir>  -- install every file in <dir> over the WiFi firmware set for exactly one boot, then reboot
F=/lib/firmware/ath11k/WCN6855/hw2.0; T=/root/bdf-test
ls $F/*.orig >/dev/null 2>&1 && { echo "already armed"; exit 1; }
for f in "$2"/*; do b=$(basename $f); cp $F/$b $F/$b.orig && cp $f $F/$b || exit 1; done
echo "$1" > $T/pending && sync && (sleep 1; reboot) &
