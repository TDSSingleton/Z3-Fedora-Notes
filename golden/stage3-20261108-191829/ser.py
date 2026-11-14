#!/usr/bin/env python3
"""Send a command to the device shell over /dev/ttyACM0 and print the reply."""
import os, sys, time, termios

DEV = "/dev/fold3"
cmd = " ".join(sys.argv[1:])
wait = float(os.environ.get("SER_WAIT", "2.5"))

fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
try:
    a = termios.tcgetattr(fd)
    a[0] = a[1] = a[3] = 0                      # iflag oflag lflag: raw
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[6][termios.VMIN] = 0; a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
except Exception as e:
    print("(tcsetattr skipped: %s)" % e, file=sys.stderr)

def drain(t=0.4):
    out=b''; end=time.time()+t
    while time.time()<end:
        try: out += os.read(fd, 65536)
        except BlockingIOError: time.sleep(0.02)
        except OSError: break
    return out

def wr(b, timeout=5.0):
    """Write, retrying on EAGAIN -- the gadget's buffer is not always ready
    the moment the device node appears."""
    end = time.time() + timeout
    while b and time.time() < end:
        try:
            n = os.write(fd, b); b = b[n:]
        except BlockingIOError:
            time.sleep(0.05)
    return not b

drain(0.3)                                      # clear anything pending
if cmd:
    if not wr((cmd + "\n").encode()):
        print("(write timed out -- device not accepting input)", file=sys.stderr)
data = drain(wait)
os.close(fd)
sys.stdout.write(data.decode("utf-8", "replace"))
