#!/usr/bin/env python3
"""
Talk to the Fold 3 over the USB serial console, reliably.

    tools/dev.py run  '<shell command>'        run it, print stdout+stderr
    tools/dev.py put  <local> <remote>         copy a file onto the device
    tools/dev.py putdir <localdir> <remotedir> copy a directory (tar over b64)

Why this exists alongside ser.py: ser.py waits a fixed number of seconds and
prints whatever arrived, so any command slower than SER_WAIT silently returns
truncated output -- which has produced wrong answers before. Here every command
is bracketed by a unique marker and we read until the closing marker appears,
so output is either complete or an explicit timeout.

Transport notes (learned the hard way, see HANDBOOK sections 4 and 12):
  * The tty is canonical: never send control characters. Files go as base64.
  * The gadget applies real backpressure -- writes must honour EAGAIN and the
    return path must be drained while writing or the device stalls.
  * Use simple commands; '&&' and redirections are fine inside a single
    here-doc-free line, but keep them short.
"""
import os, re, sys, time, termios, hashlib, uuid, base64, subprocess, tempfile

DEV = os.environ.get("FOLD3_DEV", "/dev/fold3")
USER = os.environ.get("FOLD3_USER", "root")
# Set by tools/prep-rootfs.sh (ROOTPW, default "fold3") -- a development
# device with no network, deliberately not a secret.
PASS = os.environ.get("FOLD3_PW", "fold3")


def open_tty():
    fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = a[1] = a[3] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def drain(fd, t):
    end = time.time() + t
    out = b""
    while time.time() < end:
        try:
            out += os.read(fd, 262144)
        except BlockingIOError:
            time.sleep(0.002)
        except OSError:
            break
    return out


def write_all(fd, data, timeout=900, progress=False):
    end = time.time() + timeout
    n = len(data)
    sent = 0
    t0 = time.time()
    last = t0
    got = b""
    while data and time.time() < end:
        try:
            k = os.write(fd, data[:16384])
            data = data[k:]
            sent += k
        except BlockingIOError:
            try:
                got += os.read(fd, 262144)
            except Exception:
                pass
            time.sleep(0.002)
        if progress and time.time() - last > 5:
            el = time.time() - t0
            print(f"    {sent/1048576:6.2f} / {n/1048576:.2f} MiB "
                  f"({sent/el/1048576:.2f} MiB/s)", flush=True)
            last = time.time()
    return (not data), got


def run(fd, cmd, timeout=60):
    """Run cmd, return (output, exit status). TimeoutError if no marker comes."""
    tag = "X" + uuid.uuid4().hex[:12]
    line = f"{cmd} 2>&1; printf '{tag}:%s:' $?\n"
    ok, pre = write_all(fd, line.encode(), timeout=30)
    if not ok:
        raise TimeoutError("device not accepting input")
    buf = pre
    end = time.time() + timeout
    # Match the marker only where it carries a real numeric status, so this
    # works whether or not the tty is echoing our command back at us.
    pat = re.compile(re.escape(tag) + r":(\d+):")
    while time.time() < end:
        try:
            buf += os.read(fd, 262144)
        except BlockingIOError:
            time.sleep(0.005)
        except OSError:
            break
        txt = buf.decode("utf-8", "replace")
        m = pat.search(txt)
        if m:
            return clean(txt[:m.start()], cmd, tag), m.group(1)
    raise TimeoutError(f"no marker after {timeout}s; got {len(buf)} bytes")


def clean(txt, cmd, tag=None):
    """Strip the shell's echo of our command and the OSC 3008 markers."""
    out = []
    for ln in txt.replace("\r", "").split("\n"):
        if tag and tag in ln:
            continue
        if "\x1b]3008;" in ln or ln.startswith("]3008;"):
            # the marker runs to a BEL/ST; keep whatever follows the last one
            ln = ln.split("\\")[-1]
        if ln.strip() == cmd.strip():
            continue
        out.append(ln)
    return "\n".join(out).strip("\n")


def put(fd, local, remote, timeout=1800):
    """Stream a file onto the device as base64, sha256-verified.

    Same transport as selfflash.py: a receiver process reads base64 from the
    tty and 0x04 (EOT) terminates it. base64.encodebytes wraps at 76 columns,
    which keeps every line well inside the tty's canonical 4096-byte buffer.
    Echo is turned off for the transfer: otherwise the device has to write
    every byte back to us, and that return traffic is what applies the
    backpressure that stalls this device (HANDBOOK section 12).
    """
    raw = open(local, "rb").read()
    want = hashlib.sha256(raw).hexdigest()
    enc = base64.encodebytes(raw)
    print(f"  {local} -> {remote}  ({len(raw)} bytes)")
    out, st = run(fd, f"mkdir -p $(dirname {remote})")
    if st != "0":
        sys.exit(f"!! cannot create target directory: {out}")
    run(fd, "stty -echo")
    try:
        write_all(fd, f"base64 -d > {remote}; echo __WROTE__\n".encode(),
                  timeout=15)
        time.sleep(0.3)
        drain(fd, 0.2)
        t0 = time.time()
        if not write_all(fd, enc, timeout=timeout, progress=len(enc) > 4 << 20):
            sys.exit("!! stream stalled")
        write_all(fd, b"\x04", timeout=15)
        got = drain(fd, 3).decode("utf-8", "replace")
        el = time.time() - t0
        if "__WROTE__" not in got:
            got += drain(fd, 30).decode("utf-8", "replace")
    finally:
        run(fd, "stty echo")
    out, st = run(fd, f"sha256sum {remote}", timeout=120)
    if want not in out:
        sys.exit(f"!! sha256 mismatch\n   want {want}\n   got  {out}")
    print(f"  ok, sha256 verified ({len(raw)/max(el,0.01)/1024:.0f} KiB/s)")


def ensure_shell(fd, timeout=40):
    """Get to a usable shell, logging in if agetty is prompting.

    Needed because every reboot ends the session: earlier work talked to a
    shell a previous session had left logged in, so the login prompt only
    showed up the first time the device was rebooted cleanly.
    """
    end = time.time() + timeout
    sent_user = sent_pass = False
    write_all(fd, b"\n", timeout=10)
    buf = b""
    while time.time() < end:
        buf += drain(fd, 0.5)
        txt = buf.decode("utf-8", "replace").lower()
        if "login:" in txt and not sent_user:
            write_all(fd, (USER + "\n").encode(), timeout=10)
            sent_user = True
            buf = b""
            continue
        if "password:" in txt and not sent_pass:
            write_all(fd, (PASS + "\n").encode(), timeout=10)
            sent_pass = True
            buf = b""
            time.sleep(1.5)
            continue
        if "login incorrect" in txt:
            sys.exit("!! login rejected -- set FOLD3_PW")
        try:
            out, st = run(fd, "echo __SHELL_OK__", timeout=8)
        except TimeoutError:
            write_all(fd, b"\n", timeout=10)
            continue
        if "__SHELL_OK__" in out:
            return
    sys.exit("!! could not get a shell; last bytes: "
             + repr(buf.decode('utf-8', 'replace')[-200:]))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    mode = sys.argv[1]
    fd = open_tty()
    drain(fd, 0.3)
    try:
        ensure_shell(fd)
        if mode == "run":
            out, st = run(fd, " ".join(sys.argv[2:]),
                          timeout=float(os.environ.get("DEV_TIMEOUT", "60")))
            print(out)
            sys.exit(0 if st == "0" else 1)
        elif mode == "put":
            put(fd, sys.argv[2], sys.argv[3])
        elif mode == "putdir":
            src, dst = sys.argv[2], sys.argv[3]
            with tempfile.TemporaryDirectory() as td:
                tgz = os.path.join(td, "payload.tar.gz")
                subprocess.run(["tar", "czf", tgz, "-C", src, "."], check=True)
                put(fd, tgz, "/tmp/payload.tar.gz")
            out, st = run(fd, f"mkdir -p {dst}; tar xzf /tmp/payload.tar.gz -C {dst}; rm -f /tmp/payload.tar.gz", timeout=300)
            print(out or f"  unpacked into {dst}")
        else:
            sys.exit(__doc__)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
