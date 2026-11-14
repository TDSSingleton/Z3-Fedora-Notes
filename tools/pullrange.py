#!/usr/bin/env python3
"""Pull a sector range off the device as base64 and write it locally."""
import os, re, sys, time, termios, base64, hashlib
DEV = "/dev/fold3"
dev_path, skip, count, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
BS = int(os.environ.get("PULL_BS", "512"))   # sda on this device is 4Kn!

fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
a = termios.tcgetattr(fd); a[0]=a[1]=a[3]=0
a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
termios.tcsetattr(fd, termios.TCSANOW, a)

def wr(b, t=15):
    end=time.time()+t
    while b and time.time()<end:
        try: n=os.write(fd,b); b=b[n:]
        except BlockingIOError:
            try: os.read(fd,65536)
            except Exception: pass
            time.sleep(0.005)

def drain(t):
    out=b''; end=time.time()+t
    while time.time()<end:
        try:
            c=os.read(fd,262144)
            if c: out+=c; end=time.time()+1.0   # extend while data flows
        except BlockingIOError: time.sleep(0.005)
        except OSError: break
    return out

drain(0.4)
# No sentinel markers: the shell ECHOES the command back, so any marker in it
# arrives BEFORE the data and splitting on it discards everything. Instead just
# keep lines that are pure base64 -- the echoed command has spaces and the
# prompt has '#', so neither can match.
cmd = (f"busybox dd if={dev_path} bs={BS} skip={skip} count={count} 2>/dev/null"
       f" | busybox base64\n")
wr(cmd.encode())
raw = drain(25).decode("utf-8","replace")
os.close(fd)

# The base64 payload is a CONTIGUOUS block of lines. Picking every
# base64-looking line anywhere in the stream grabs stray fragments (the
# echoed command, a leftover hash, the prompt). Take the longest consecutive
# run instead -- that is unambiguously the data.
lines = [l.strip() for l in raw.splitlines()]
isb64 = [bool(re.fullmatch(r"[A-Za-z0-9+/]+=*", l)) and len(l) >= 4 for l in lines]
# busybox base64 emits 76-char lines, with only the FINAL line shorter.
# The device tty also wraps the echoed command at 76 columns, which can leave
# a short fragment ("ase64") of valid base64 characters sitting right before
# the data -- that cost 4 bytes before this was handled. So: start the run at
# the first full 76-char line, and let exactly one short line end it.
best, cur, started = [], [], False
for l, ok in zip(lines, isb64):
    if not ok:
        if cur and len(cur) > len(best): best = cur
        cur, started = [], False
        continue
    if not started:
        if len(l) != 76:        # skip fragments before the real payload
            continue
        started = True
    cur.append(l)
    if len(l) != 76:            # a short line terminates the payload
        if len(cur) > len(best): best = cur
        cur, started = [], False
if cur and len(cur) > len(best): best = cur
b64 = "".join(best)
data = base64.b64decode(b64 + "=" * (-len(b64) % 4))
open(out,"wb").write(data)
local = hashlib.sha256(data).hexdigest()
ok = len(data) == count*BS
print(f"  {out}: {len(data)} bytes (wanted {count*BS}) {'OK' if ok else '** SHORT **'}")
print(f"  local  sha256 {local}")

# ask the device for its own hash of the same range -- never trust the pipe
fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
a = termios.tcgetattr(fd); a[0]=a[1]=a[3]=0
a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
termios.tcsetattr(fd, termios.TCSANOW, a)
drain(0.4)
wr(f"busybox dd if={dev_path} bs={BS} skip={skip} count={count} 2>/dev/null | busybox sha256sum\n".encode())
resp = drain(20).decode("utf-8","replace")
os.close(fd)
m = re.search(r"\b([0-9a-f]{64})\b", resp)
if not m:
    print("  device sha256: (could not read)")
elif m.group(1) == local:
    print(f"  device sha256 {m.group(1)}  MATCH")
else:
    print(f"  device sha256 {m.group(1)}  ** MISMATCH **"); sys.exit(1)
