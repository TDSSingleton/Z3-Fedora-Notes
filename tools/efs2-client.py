#!/usr/bin/env python3
"""Read the modem's EFS by PATH, over DIAG/EFS2, on mainline Linux.

Why this exists: modemst1/2 are an encrypted IMGEFS1 blob, so a byte diff only
ever says THAT the store changed, never WHICH item. The modem itself will hand
over its EFS as a filesystem over DIAG. On this platform DIAG rides QRTR (no
diag kernel driver exists, and there is no mpss glink DIAG channel), so the
path is: diag-router publishes our side on QRTR -> the modem publishes
MODEM:CMD (service 4097, instance 1, node 0) -> we speak EFS2 through
diag-router's abstract unix socket "@diag", which carries raw un-HDLC'd DIAG.

READ-ONLY BY CONSTRUCTION. Only HELLO/OPEN/CLOSE/READ/OPENDIR/READDIR/
CLOSEDIR are implemented. WRITE, UNLINK, MKDIR, RMDIR, CHMOD, PUT, TRUNCATE
and friends are deliberately absent, so this tool cannot modify modem storage
even by mistake. (It could not persist anyway: rmtfs runs -r.)

Requires diag-router running (see HANDBOOK 35.2.1). Run on the phone as root.

    efs2-client.py hello
    efs2-client.py ls /
    efs2-client.py tree / 2
    efs2-client.py cat /path/to/item [--hex]

Packet layouts taken from QCSuper (src/qcsuper/protocol/efs2.py and
modules/efs_shell*.py), which is the reference implementation.
"""
import socket
import sys
from struct import pack, unpack, calcsize

DIAG_SUBSYS_CMD_F = 75
DIAG_SUBSYS_FS = 19             # EFS
DIAG_SUBSYS_FS_ALTERNATE = 62   # EFS2

EFS2_DIAG_HELLO = 0
EFS2_DIAG_OPEN = 2
EFS2_DIAG_CLOSE = 3
EFS2_DIAG_READ = 4
EFS2_DIAG_OPENDIR = 11
EFS2_DIAG_READDIR = 12
EFS2_DIAG_CLOSEDIR = 13

FILE_TYPES = {0: "file", 1: "dir", 2: "link", 3: "immovable", 4: "item"}

# diag-router binds with sizeof(struct sockaddr_un), so the abstract name is
# "diag" NUL-padded across the whole 108-byte sun_path -- not the 5-byte short
# form. Connecting with the short name gets ECONNREFUSED.
SOCK_NAME = b"\0diag".ljust(108, b"\0")


class Efs2:
    def __init__(self, subsys=DIAG_SUBSYS_FS, timeout=10.0):
        self.subsys = subsys
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.sock.settimeout(timeout)
        self.sock.connect(SOCK_NAME)

    def send_recv(self, payload, want_cmd):
        """Send one EFS2 request; return the matching response payload."""
        self.sock.send(bytes([DIAG_SUBSYS_CMD_F]) + payload)
        for _ in range(64):  # skip async log/event traffic
            resp = self.sock.recv(65536)
            if not resp or resp[0] != DIAG_SUBSYS_CMD_F:
                continue
            body = resp[1:]
            if len(body) < 3:
                continue
            subsys, cmd = unpack("<BH", body[:3])
            if subsys == self.subsys and cmd == want_cmd:
                return body
        raise RuntimeError(f"no response to EFS2 cmd {want_cmd}")

    # --- read-only operations -------------------------------------------
    def hello(self):
        body = self.send_recv(
            pack("<BH6I3II", self.subsys, EFS2_DIAG_HELLO,
                 0x100000, 0x100000, 0x100000, 0x100000, 0x100000, 0x100000,
                 1, 1, 1, 0xFFFFFFFF),
            EFS2_DIAG_HELLO)
        f = "<BH6I3II"
        v = unpack(f, body[:calcsize(f)])
        return {"targ_pkt_window": v[2], "targ_byte_window": v[3],
                "host_pkt_window": v[4], "host_byte_window": v[5],
                "version": v[8], "min_version": v[9], "max_version": v[10],
                "feature_bits": hex(v[11])}

    def opendir(self, path):
        body = self.send_recv(
            pack("<BH", self.subsys, EFS2_DIAG_OPENDIR) + path.encode() + b"\0",
            EFS2_DIAG_OPENDIR)
        _, _, dir_fd, errno = unpack("<BHIi", body[:calcsize("<BHIi")])
        if errno:
            raise OSError(errno, f"OPENDIR {path} failed (errno {errno})")
        return dir_fd

    def readdir(self, dir_fd):
        """Yield (name, type, mode, size, mtime) for one directory."""
        seq = 1
        fmt = "<BHI8i"
        while True:
            body = self.send_recv(
                pack("<BHIi", self.subsys, EFS2_DIAG_READDIR, dir_fd, seq),
                EFS2_DIAG_READDIR)
            v = unpack(fmt, body[:calcsize(fmt)])
            errno, entry_type, mode, size = v[4], v[5], v[6], v[7]
            mtime = v[9]
            name = body[calcsize(fmt):].split(b"\0")[0].decode("latin1")
            if errno:
                raise OSError(errno, f"READDIR failed (errno {errno})")
            if not name:
                return
            yield name, entry_type, mode, size, mtime
            seq += 1

    def closedir(self, dir_fd):
        try:
            self.send_recv(pack("<BHI", self.subsys, EFS2_DIAG_CLOSEDIR, dir_fd),
                           EFS2_DIAG_CLOSEDIR)
        except Exception:
            pass

    def read_file(self, path, limit=1 << 20):
        body = self.send_recv(
            pack("<BHii", self.subsys, EFS2_DIAG_OPEN, 0, 0) + path.encode() + b"\0",
            EFS2_DIAG_OPEN)
        _, _, fd, errno = unpack("<BHIi", body[:calcsize("<BHIi")])
        if errno:
            raise OSError(errno, f"OPEN {path} failed (errno {errno})")
        out = b""
        fmt = "<BHiIii"
        try:
            while len(out) < limit:
                body = self.send_recv(
                    pack("<BHiII", self.subsys, EFS2_DIAG_READ, fd, 1024, len(out)),
                    EFS2_DIAG_READ)
                v = unpack(fmt, body[:calcsize(fmt)])
                nread, errno = v[4], v[5]
                if errno:
                    raise OSError(errno, f"READ failed (errno {errno})")
                if nread <= 0:
                    break
                out += body[calcsize(fmt):calcsize(fmt) + nread]
        finally:
            try:
                self.send_recv(pack("<BHi", self.subsys, EFS2_DIAG_CLOSE, fd),
                               EFS2_DIAG_CLOSE)
            except Exception:
                pass
        return out


def ls(efs, path):
    fd = efs.opendir(path)
    try:
        rows = list(efs.readdir(fd))
    finally:
        efs.closedir(fd)
    print(f"{path}  ({len(rows)} entries)")
    for name, etype, mode, size, mtime in sorted(rows):
        kind = FILE_TYPES.get(etype) or f"type{etype}"
        print(f"  {kind:9s} {mode:06o} {size:10d}  {name}")
    return rows


def tree(efs, path, depth, _level=0):
    try:
        fd = efs.opendir(path)
    except OSError as e:
        print("  " * _level + f"{path}  <{e.strerror or e}>")
        return
    try:
        rows = list(efs.readdir(fd))
    finally:
        efs.closedir(fd)
    for name, etype, mode, size, mtime in sorted(rows):
        full = (path.rstrip("/") + "/" + name) or "/"
        kind = FILE_TYPES.get(etype) or f"type{etype}"
        print("  " * _level + f"{kind:9s} {size:9d}  {full}")
        if etype == 1 and _level < depth:
            tree(efs, full, depth, _level + 1)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    subsys = DIAG_SUBSYS_FS_ALTERNATE if "--efs2" in args else DIAG_SUBSYS_FS
    args = [a for a in args if a != "--efs2"]
    efs = Efs2(subsys=subsys)
    info = efs.hello()
    cmd = args[0]
    if cmd == "hello":
        for k, v in info.items():
            print(f"  {k}: {v}")
    elif cmd == "ls":
        ls(efs, args[1] if len(args) > 1 else "/")
    elif cmd == "tree":
        tree(efs, args[1] if len(args) > 1 else "/",
             int(args[2]) if len(args) > 2 else 1)
    elif cmd == "cat":
        data = efs.read_file(args[1])
        if "--hex" in args or not all(32 <= b < 127 or b in (9, 10, 13) for b in data):
            print(data.hex())
        else:
            sys.stdout.write(data.decode("latin1"))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
