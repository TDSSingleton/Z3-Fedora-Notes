#!/bin/bash
# bdtest.sh <label> <bdf.elf> [keep]  -- load a board file under upstream amss on the phone
# (via a tmpfs firmware path: nothing on the rootfs changes, a reboot undoes everything).
D=$(dirname "$0"); K="-i $HOME/.ssh/fold3_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=8 -o BatchMode=yes"; H=root@192.168.11.131
T=$(mktemp); python3 -I "$D/mkboard2.py" $T "$2" || exit 1
scp -q $K $T $H:/run/test-board-2.bin || { echo "[$1] scp failed"; exit 1; }; rm -f $T
ssh $K $H "rm -f /root/wl-bdf-test.log; setsid nohup /root/wl-bdf-test.sh /run/test-board-2.bin $3 >/dev/null 2>&1 </dev/null &"
o=""; n=0
until echo "$o" | grep -qE '^(done|KEEPING)' || [ $n -ge 30 ]; do sleep 4; n=$((n+1)); o=$(ssh $K $H 'cat /root/wl-bdf-test.log' 2>/dev/null); done
echo "[$1] $(echo "$o" | grep -E '^RESULT|signal:|rebooting|^done' | tr -s '\t ' ' ' | tr '\n' ';')"
