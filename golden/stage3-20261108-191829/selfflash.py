#!/usr/bin/env python3
"""
Flash a boot image to the Fold 3 over the USB serial console -- no Download
Mode, no buttons, no heimdall.

    PC:      base64 -> tty
    device:  busybox base64 -d | busybox dd of=/dev/sda19

base64 is deliberate: the device tty is in canonical mode, so the stream must
contain no control characters. base64's alphabet is safe, and 0x04 (EOT) then
gives the receiver a clean EOF.

Always verifies sha256 on the device afterwards and refuses to power-cycle if
it does not match.
"""
import os, sys, time, termios, hashlib, base64 as b64mod

DEV    = os.environ.get("FOLD3_DEV", "/dev/fold3")
TARGET = os.environ.get("FOLD3_BOOT", "/dev/sda19")

def open_tty():
    fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd); a[0]=a[1]=a[3]=0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd

def drain(fd, t):
    end=time.time()+t; out=b''
    while time.time()<end:
        try: out += os.read(fd, 262144)
        except BlockingIOError: time.sleep(0.002)
        except OSError: break
    return out

def write_all(fd, data, timeout=600):
    """Push bytes, honouring EAGAIN -- the gadget applies real backpressure."""
    end=time.time()+timeout; sent=0; n=len(data)
    t0=time.time(); last_report=t0
    while data and time.time()<end:
        try:
            k = os.write(fd, data[:16384]); data = data[k:]; sent += k
        except BlockingIOError:
            try: os.read(fd, 262144)      # keep the return path clear
            except Exception: pass
            time.sleep(0.002)
        if time.time()-last_report > 5:
            el=time.time()-t0
            print(f"    {sent/1048576:6.1f} / {n/1048576:.1f} MiB  "
                  f"({sent/el/1048576:.2f} MiB/s)", flush=True)
            last_report=time.time()
    return not data

def cmd(fd, c, wait=3.0):
    # must use the retrying writer: a bare os.write hits EAGAIN whenever the
    # gadget's buffer is not ready, which happens right after enumeration.
    write_all(fd, (c+"\n").encode(), timeout=15)
    return drain(fd, wait).decode("utf-8","replace")

def main():
    img = sys.argv[1] if len(sys.argv)>1 else "images/q2q-stage1-boot.img"
    raw = open(img,"rb").read()
    want = hashlib.sha256(raw).hexdigest()
    blocks, rem = divmod(len(raw), 4096)
    if rem: sys.exit(f"!! {img} is not a multiple of 4096 ({len(raw)} bytes)")
    print(f"  image  {img}")
    print(f"  size   {len(raw)} bytes ({len(raw)/1048576:.1f} MiB), {blocks} x 4096")
    print(f"  sha256 {want}")
    print(f"  target {TARGET}")

    fd = open_tty(); drain(fd, 0.5)
    if "ALIVE" not in cmd(fd, "echo ALIVE"):
        sys.exit("!! no shell on "+DEV)

    print("\n  starting receiver on device ...")
    write_all(fd, f"busybox base64 -d | busybox dd of={TARGET} bs=64k 2>/tmp/dd.log; echo __WROTE__\n".encode(), timeout=15)
    time.sleep(0.5); drain(fd, 0.3)

    print("  streaming ...")
    t0=time.time()
    enc = b64mod.encodebytes(raw)          # wrapped at 76 cols, newline-terminated
    if not write_all(fd, enc):
        sys.exit("!! stream stalled")
    write_all(fd, b"\x04", timeout=15)     # EOT -> EOF for base64 -d
    el=time.time()-t0
    print(f"  sent {len(enc)/1048576:.1f} MiB of base64 in {el:.0f}s "
          f"({len(enc)/el/1048576:.2f} MiB/s)")

    out = drain(fd, 30)
    if "__WROTE__" not in out.decode("utf-8","replace"):
        print("  (no __WROTE__ yet, waiting longer)"); out += drain(fd, 60)

    print("\n  verifying on device ...")
    got = cmd(fd, f"busybox dd if={TARGET} bs=4096 count={blocks} 2>/dev/null | busybox sha256sum", 90)
    os.close(fd)
    if want in got:
        print(f"  MATCH {want[:32]}...")
        print("\n  safe to power-cycle:  poweroff -f")
        return 0
    print("  !! MISMATCH -- device reported:"); print("   ", got.strip()[-200:])
    print("  !! do NOT power-cycle; reflash with heimdall from Download Mode")
    return 1

sys.exit(main())
