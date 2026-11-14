#!/bin/sh
# Stage 1b init: bring up the basics, then hand over an interactive shell on
# the framebuffer console. Deliberately defensive -- every mount is optional,
# because a failure here must still leave us with a usable prompt.

/bin/busybox mkdir -p /proc /sys /dev /tmp /run
/bin/busybox mount -t proc     proc     /proc 2>/dev/null
/bin/busybox mount -t sysfs    sysfs    /sys  2>/dev/null
/bin/busybox mount -t devtmpfs devtmpfs /dev  2>/dev/null
/bin/busybox mount -t tmpfs    tmpfs    /tmp  2>/dev/null

echo
echo "==============================================================="
echo "  Galaxy Z Fold 3 (SM-F926B / q2q)  --  mainline Linux"
echo "  $( /bin/busybox uname -srm )"
echo "==============================================================="
echo
echo "  cpus     : $( /bin/busybox grep -c ^processor /proc/cpuinfo )"
echo "  memory   : $( /bin/busybox awk '/MemTotal/{printf "%.2f GiB", $2/1048576}' /proc/meminfo )"
echo "  fb       : $( /bin/busybox cat /sys/class/graphics/fb0/name 2>/dev/null ) \
$( /bin/busybox cat /sys/class/graphics/fb0/virtual_size 2>/dev/null )"
echo "  uptime   : $( /bin/busybox cut -d' ' -f1 /proc/uptime )s"
echo
echo "  type 'help' for busybox applets.  reboot with: reboot -f"
echo

exec /bin/busybox sh
