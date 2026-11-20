#!/system/bin/sh
# android-modemst-watch.sh -- record WHEN Android rewrites the modem NV store.
#
# Run from ROOTED Android, early in the session:
#     adb push android-modemst-watch.sh /data/local/tmp/
#     adb shell su -c 'sh /data/local/tmp/android-modemst-watch.sh &'
# Then pull the log before leaving Android:
#     adb pull /data/local/tmp/modemst-watch.log
#
# READ-ONLY with respect to the modem: it only hashes the partitions and reads
# properties. It never writes modemst, and it never touches the radio.
#
# Purpose: modemst1/2 are encrypted, so a changed hash says only THAT a flush
# happened. Pairing each change with a timestamp and the radio properties of
# the moment is what tells us WHICH event triggers it -- boot, SIM detection,
# data attach, or shutdown.

OUT=/data/local/tmp/modemst-watch.log
INTERVAL=${1:-15}

M1=/dev/block/by-name/modemst1
M2=/dev/block/by-name/modemst2
[ -e "$M1" ] || M1=/dev/block/sda1
[ -e "$M2" ] || M2=/dev/block/sda2

h() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }

props() {
	for p in gsm.sim.state gsm.operator.numeric gsm.operator.alpha \
	         gsm.network.type ril.subscription.types sys.boot_completed \
	         gsm.sim.operator.numeric persist.radio.multisim.config; do
		printf '%s=%s ' "$p" "$(getprop $p)"
	done
}

echo "# modemst watch started $(date) interval=${INTERVAL}s" >> $OUT
echo "# m1=$M1 m2=$M2" >> $OUT

P1=""; P2=""; N=0
while true; do
	A=$(h $M1); B=$(h $M2)
	if [ "$A" != "$P1" ] || [ "$B" != "$P2" ]; then
		if [ -z "$P1" ]; then TAG="INITIAL"; else TAG="*** CHANGED ***"; fi
		echo "[$(date '+%Y-%m-%d %H:%M:%S')] $TAG" >> $OUT
		echo "    modemst1 $A" >> $OUT
		echo "    modemst2 $B" >> $OUT
		echo "    uptime:$(cut -d' ' -f1 /proc/uptime) $(props)" >> $OUT
		# header tail byte = the container's flush counter, plaintext
		echo "    hdr1 $(dd if=$M1 bs=48 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')" >> $OUT
		echo "    hdr2 $(dd if=$M2 bs=48 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')" >> $OUT
		P1=$A; P2=$B
	fi
	N=$((N+1))
	sleep $INTERVAL
done
