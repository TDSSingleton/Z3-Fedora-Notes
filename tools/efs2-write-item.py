#!/usr/bin/env python3
"""Write ONE EFS item in the modem's RAM, over DIAG/EFS2. Deliberately separate
from efs2-client.py so that tool stays strictly read-only.

Scope and safety, stated precisely:
  * This writes the modem's in-RAM EFS. It CANNOT reach modem storage: our
    rmtfs runs read-only (-r), so when the modem flushes its EFS the write is
    dropped. A reboot therefore undoes anything done here.
  * That is the point -- it is how a repair can be re-asserted every boot
    (like fold3-sim-primary does for the subscription flip) without ever
    writing modemst1/2.
  * It writes exactly the path you name, with the bytes you give as hex, and
    reads the value back to prove what landed. No recursion, no globbing.

    efs2-write-item.py <path> <hex-bytes>
    efs2-write-item.py <path> --show

Requires diag-router (fold3-diag-router.service). See HANDBOOK 35.2.1.
"""
import sys
import importlib.util
from struct import pack, unpack, calcsize

REAL_ARGV = sys.argv[1:]

spec = importlib.util.spec_from_file_location(
    "efs2_client", "/usr/local/sbin/efs2-client.py")
C = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]
spec.loader.exec_module(C)

EFS2_DIAG_WRITE = 5
O_WRONLY_TRUNC_CREAT = 0o1101


def write_item(efs, path, data, mode=0o100666):
    body = efs.send_recv(
        pack("<BHii", efs.subsys, C.EFS2_DIAG_OPEN, O_WRONLY_TRUNC_CREAT, mode)
        + path.encode() + b"\0",
        C.EFS2_DIAG_OPEN)
    _, _, fd, errno = unpack("<BHIi", body[:calcsize("<BHIi")])
    if errno:
        raise OSError(errno, f"OPEN(write) {path} failed (errno {errno})")
    try:
        written = 0
        while written < len(data):
            chunk = data[written:written + 1024]
            body = efs.send_recv(
                pack("<BHiI", efs.subsys, EFS2_DIAG_WRITE, fd, written) + chunk,
                EFS2_DIAG_WRITE)
            f = "<BHiIii"
            v = unpack(f, body[:calcsize(f)])
            n, errno = v[4], v[5]
            if errno:
                raise OSError(errno, f"WRITE failed (errno {errno})")
            if n <= 0:
                raise OSError(0, "WRITE returned 0 bytes")
            written += n
        return written
    finally:
        try:
            efs.send_recv(pack("<BHi", efs.subsys, C.EFS2_DIAG_CLOSE, fd),
                          C.EFS2_DIAG_CLOSE)
        except Exception:
            pass


def show(efs, path):
    data = efs.read_file(path)
    print(f"  {path}")
    print(f"    hex   : {data.hex()}")
    try:
        print(f"    ascii : {data.decode()!r}")
    except Exception:
        pass
    return data


def main():
    if len(REAL_ARGV) < 2:
        print(__doc__)
        return 1
    path, arg = REAL_ARGV[0], REAL_ARGV[1]
    efs = C.Efs2()
    efs.hello()
    print("before:")
    before = show(efs, path)
    if arg == "--show":
        return 0
    data = bytes.fromhex(arg)
    n = write_item(efs, path, data)
    print(f"wrote {n} bytes (modem RAM only; rmtfs -r means it cannot persist)")
    print("after:")
    after = show(efs, path)
    if after == data:
        print("VERIFIED: readback matches what was written")
        return 0
    print(f"MISMATCH: wanted {data.hex()}, read {after.hex()}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
