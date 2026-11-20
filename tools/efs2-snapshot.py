#!/usr/bin/env python3
"""Snapshot the modem's EFS by PATH, for diffing good vs broken states.

The point: modemst1/2 are encrypted, so a byte diff says only THAT the store
changed. This asks the modem for its own filesystem over DIAG/EFS2 and writes
a stable, sorted, line-per-path record, so two snapshots can be diffed and the
changed ITEMS named. See HANDBOOK 35.2.1.

READ-ONLY: walks with OPENDIR/READDIR and reads with OPEN/READ only. It
imports the client in tools/efs2-client.py, which implements no write opcode
at all.

    efs2-snapshot.py OUTFILE [root ...]      # default roots: see ROOTS

Output line:  <type> <mode> <size> <path>\t<value-or-hash>
Small files are recorded as literal hex (directly interpretable in a diff);
larger ones as sha256:<hex>. Unreadable paths are recorded as ERROR:<reason>
so a permission change is itself visible in the diff.
"""
import sys
import time
import hashlib
import importlib.util

HEX_INLINE_MAX = 64         # <= this many bytes: record literal hex
READ_MAX = 65536            # read at most this much per file, then hash
# NOT served by EFS2 on this modem: /nvm, /safe, /ss_prop, /sst -- the modem
# sends no response at all to OPENDIR on them (not an error, silence), so they
# are a permanent blind spot. Excluded because each costs a 10 s timeout; the
# omission is consistent across snapshots and so adds no diff noise.
ROOTS = ["/nv", "/ds", "/mmode", "/policyman", "/mcfg", "/data", "/sd",
         "/mmgsdi", "/pdp_profiles", "/nvruim", "/rfc", "/mdb"]

REAL_ARGV = sys.argv[1:]            # captured before we clear sys.argv below

spec = importlib.util.spec_from_file_location(
    "efs2_client", "/usr/local/sbin/efs2-client.py")
efs2_client = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]          # keep the client's main() out of the way
spec.loader.exec_module(efs2_client)


def snapshot(out_path, roots):
    efs = efs2_client.Efs2()
    efs.hello()
    lines = []
    stack = list(roots)
    seen = set()
    files = dirs = errors = 0
    t0 = time.time()

    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        try:
            fd = efs.opendir(path)
        except Exception as e:
            lines.append(f"dir       ------         0 {path}\tERROR:{e}")
            errors += 1
            continue
        try:
            entries = list(efs.readdir(fd))
        except Exception as e:
            lines.append(f"dir       ------         0 {path}\tERROR:readdir {e}")
            errors += 1
            continue
        finally:
            efs.closedir(fd)
        dirs += 1
        for name, etype, mode, size, mtime in entries:
            full = (path.rstrip("/") + "/" + name)
            kind = efs2_client.FILE_TYPES.get(etype) or f"type{etype}"
            if etype == 1:                      # directory
                stack.append(full)
                lines.append(f"{kind:9s} {mode:06o} {size:9d} {full}\t-")
                continue
            value = "-"
            try:
                data = efs.read_file(full, limit=READ_MAX)
                if len(data) <= HEX_INLINE_MAX:
                    value = data.hex() or "(empty)"
                else:
                    value = "sha256:" + hashlib.sha256(data).hexdigest()
                files += 1
            except Exception as e:
                value = f"ERROR:{e}"
                errors += 1
            lines.append(f"{kind:9s} {mode:06o} {size:9d} {full}\t{value}")

    lines.sort(key=lambda l: l.split("\t")[0].split(" ")[-1])
    with open(out_path, "w") as f:
        f.write(f"# EFS2 snapshot, {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        f.write(f"# roots: {' '.join(roots)}\n")
        f.write(f"# dirs={dirs} files_read={files} errors={errors} "
                f"elapsed={time.time()-t0:.1f}s\n")
        f.write("\n".join(lines) + "\n")
    print(f"dirs={dirs} files_read={files} errors={errors} "
          f"lines={len(lines)} elapsed={time.time()-t0:.1f}s -> {out_path}")


if __name__ == "__main__":
    if not REAL_ARGV:
        print(__doc__)
        sys.exit(1)
    snapshot(REAL_ARGV[0], REAL_ARGV[1:] or ROOTS)
