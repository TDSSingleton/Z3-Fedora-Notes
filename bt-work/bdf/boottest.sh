#!/bin/bash
# boottest.sh <label> <bdf.elf>  -- one-boot test of a board file on the phone (cold chip), prints the result
D=$(dirname "$0"); K="-i $HOME/.ssh/fold3_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=10 -o BatchMode=yes"; H=root@192.168.11.131
T=$(mktemp); python3 -I "$D/mkboard2.py" $T "$2" || exit 1
scp -q $K $T $H:/root/bdf-test/next-board-2.bin || { echo "scp failed"; exit 1; }; rm -f $T
ssh $K $H "/root/bdf-arm.sh '$1' /root/bdf-test/next-board-2.bin" || exit 1
sleep 50
until ssh $K $H "grep -q '=== $1 ' /root/bdf-test/results.log && ! [ -e /lib/firmware/ath11k/WCN6855/hw2.0/board-2.bin.orig ] && sed -n '/=== $1 /,\$p' /root/bdf-test/results.log" 2>/dev/null; do sleep 5; done
