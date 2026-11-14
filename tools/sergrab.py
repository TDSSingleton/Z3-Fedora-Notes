#!/usr/bin/env python3
"""Run a command on the device over /dev/fold3 and capture ALL of its output.

Unlike ser.py (which drains for a fixed time and is fine for one-liners), this
reads until a sentinel, so it can capture something as large as a full dmesg
without guessing a timeout.

Four pitfalls this handles, each of which has produced a wrong answer before:

  * EAGAIN on write -- the gadget's buffer is not always ready, so every write
    retries instead of assuming one os.write() is enough.
  * The sentinel matching the ECHOED command rather than the output. The marker
    is split in the command text ("QEND" "7731") so the line we type never
    contains the string we search for, even if echo is on.
  * The device tty WRAPPING the echoed command and injecting a stray fragment
    into the captured stream. We widen the device tty and turn its echo off.
  * A login prompt. Fedora's getty wants credentials; the initramfs fallback
    shell does not. We detect which and act accordingly.

Usage:  tools/sergrab.py 'dmesg' [-o outfile] [--user root] [--pass fold3]
"""
import os, sys, time, termios, argparse

DEV = "/dev/fold3"
MARK = "QEND7731"
MARK_CMD = '"QEND""7731"'      # typed form: never literally equal to MARK

ap = argparse.ArgumentParser()
ap.add_argument("command")
ap.add_argument("-o", "--out")
ap.add_argument("--user", default="root")
ap.add_argument("--password", default="fold3")
ap.add_argument("--timeout", type=float, default=90.0)
a_ = ap.parse_args()

fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
try:
    t = termios.tcgetattr(fd)
    t[0] = t[1] = t[3] = 0
    t[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    t[6][termios.VMIN] = 0; t[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, t)
except Exception as e:
    print("(tcsetattr skipped: %s)" % e, file=sys.stderr)

def wr(s, timeout=10.0):
    b = s.encode(); end = time.time() + timeout
    while b and time.time() < end:
        try:
            b = b[os.write(fd, b):]
        except BlockingIOError:
            time.sleep(0.03)
    return not b

def read_until(needle, timeout, quiet_ok=False):
    buf = b""; end = time.time() + timeout
    while time.time() < end:
        try:
            chunk = os.read(fd, 65536)
            if chunk:
                buf += chunk
                if needle and needle.encode() in buf:
                    return buf, True
        except BlockingIOError:
            time.sleep(0.02)
        except OSError:
            break
    return buf, False

def drain(t=0.5):
    return read_until(None, t)[0]

drain(0.4)
wr("\n")
probe = drain(2.0).decode("utf-8", "replace")
tail = probe[-400:]

state = "shell"
if "login:" in tail:
    state = "login"
elif "Password:" in tail:
    state = "password"
print("  console state: %s" % state, file=sys.stderr)

if state == "login":
    wr(a_.user + "\n"); r = drain(2.5).decode("utf-8", "replace")
    if "assword" in r:
        wr(a_.password + "\n"); r = drain(3.5).decode("utf-8", "replace")
    print("  logged in as %s" % a_.user, file=sys.stderr)
elif state == "password":
    wr(a_.password + "\n"); drain(3.0)

# quiet the tty: no echo, and wide enough that nothing wraps into our capture
wr("stty -echo; stty cols 4000 rows 200 2>/dev/null\n")
drain(1.0)

wr("%s; printf '%%s\\n' %s\n" % (a_.command, MARK_CMD))
data, hit = read_until(MARK, a_.timeout)
wr("stty echo 2>/dev/null\n")        # leave the console usable
drain(0.3)
os.close(fd)

text = data.decode("utf-8", "replace").replace("\r\n", "\n")
if hit:
    text = text.split(MARK)[0]
else:
    print("  !! sentinel never arrived -- output may be truncated", file=sys.stderr)

out = a_.out
if out:
    with open(out, "w") as f:
        f.write(text)
    print("  wrote %d bytes to %s" % (len(text), out), file=sys.stderr)
else:
    sys.stdout.write(text)
sys.exit(0 if hit else 2)
