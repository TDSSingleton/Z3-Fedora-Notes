#!/usr/bin/env python3
"""Passively drain /dev/fold3 into a log file, forever, surviving replugs.

Why: an attached-but-unread CDC-ACM console applies backpressure and stalls
the phone (HANDBOOK section 12) -- shutdown hangs before "Rebooting", and a
boot that re-enumerates USB sits for minutes at ~20 s uptime. Run this across
every reboot. It never writes to the tty (a write to a console nobody reads on
the far side blocks close() for 30 s).

STOP IT before using dev.py/sergrab.py: two readers split the byte stream.

    tools/serdrain.py [logfile]     # default capture/boot-logs/serial-<ts>.log
"""
import os, sys, time

DEV = os.environ.get("FOLD3_DEV", "/dev/fold3")
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    root, "capture", "boot-logs", time.strftime("serial-%Y%m%d-%H%M%S.log"))
os.makedirs(os.path.dirname(out), exist_ok=True)
log = open(out, "ab", buffering=0)
print("draining", DEV, "->", out, flush=True)
fd = None
while True:
    if fd is None:
        try:
            fd = os.open(DEV, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
            log.write(b"\n=== %s opened %s ===\n" % (time.strftime("%H:%M:%S").encode(), DEV.encode()))
        except OSError:
            time.sleep(0.2)
            continue
    try:
        b = os.read(fd, 262144)
        if b:
            log.write(b)
        else:
            raise OSError("EOF")
    except BlockingIOError:
        time.sleep(0.02)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        fd = None
        log.write(b"\n=== %s lost ===\n" % time.strftime("%H:%M:%S").encode())
        time.sleep(0.2)
