# shellcheck shell=bash
# Shared helpers. Sourced by the numbered scripts; not run directly.
set -uo pipefail

A()  { timeout "${ADB_T:-25}" adb shell "$@" 2>/dev/null | tr -d '\r'; }
SU() { timeout "${ADB_T:-60}" adb shell "su -c '$*'" 2>/dev/null | tr -d '\r'; }

die() { printf '\n!! %s\n' "$*" >&2; exit 1; }
note(){ printf '   %s\n' "$*"; }
hdr() { printf '\n== %s\n' "$*"; }

require_device() {
  adb get-state >/dev/null 2>&1 || die "No device in adb. Check 'adb devices'."
  SERIAL="$(adb shell getprop ro.serialno 2>/dev/null | tr -d '\r')"
  MODEL="$(adb shell getprop ro.product.model 2>/dev/null | tr -d '\r')"
  DEVICE="$(adb shell getprop ro.product.device 2>/dev/null | tr -d '\r')"
  [ "$DEVICE" = "q2q" ] || printf '!! WARNING: ro.product.device=%s (expected q2q)\n' "$DEVICE" >&2
}

have_root() { [ "$(A 'su -c id -u')" = "0" ]; }
require_root() {
  have_root || die "This script needs root. Unlock + flash TWRP/Magisk first (see 11-extraction-plan.md section 0)."
}

manifest_init() {
  MANIFEST="$OUT/MANIFEST.txt"
  { echo "# Fold 3 extraction manifest"
    echo "date:    $(date -Is)"
    echo "script:  $(basename "${BASH_SOURCE[1]}")"
    echo "serial:  ${SERIAL:-?}"
    echo "model:   ${MODEL:-?}  device: ${DEVICE:-?}"
    echo "bootloader: $(A getprop ro.bootloader)"
    echo "revision:   $(A getprop ro.revision)"
    echo
    printf '%-18s %14s  %s\n' NAME BYTES SHA256
  } > "$MANIFEST"
}

# pull_partition <by-name> <destfile>
# Verifies the partition EXISTS, that the pulled size matches the block device,
# and that the device-side and host-side sha256 agree. Any failure is reported
# and returns non-zero -- it never records a skipped or short read as success.
pull_partition() {
  local name="$1" dest="$2" node sz got dhash hhash
  node="$(SU "readlink -f /dev/block/by-name/$name")"
  # readlink -f returns the input path unchanged for a missing entry, so test
  # for an actual block device rather than trusting a non-empty string.
  if [ -z "$node" ] || ! SU "test -b $node" >/dev/null 2>&1; then
    note "SKIP $name (not present on this device)"
    printf '%-18s %14s  %s\n' "$name" "-" "ABSENT (not on this device)" >> "$MANIFEST"
    return 1
  fi
  sz="$(SU "blockdev --getsize64 $node")"
  case "$sz" in ''|*[!0-9]*) sz="" ;; esac
  note "$name -> $node (${sz:-unknown} bytes)"
  adb exec-out "su -c 'dd if=$node bs=1M 2>/dev/null'" > "$dest"
  got="$(stat -c%s "$dest")"
  if [ "$got" = "0" ]; then
    note "   !! EMPTY read -- backup FAILED for $name"
    printf '%-18s %14s  %s\n' "$name" 0 "FAILED (empty read)" >> "$MANIFEST"
    rm -f "$dest"; return 1
  fi
  if [ -n "$sz" ] && [ "$got" != "$sz" ]; then
    note "   !! SHORT read: got $got of $sz bytes -- backup FAILED for $name"
    printf '%-18s %14s  %s\n' "$name" "$got" "FAILED (short: expected $sz)" >> "$MANIFEST"
    return 1
  fi
  dhash="$(SU "sha256sum $node" | awk '{print $1}')"
  hhash="$(sha256sum "$dest" | awk '{print $1}')"
  if [ -z "$dhash" ]; then
    note "   ?? could not hash on device; host sha256=${hhash:0:16}... (size verified)"
    printf '%-18s %14s  %s  (device hash unavailable)\n' "$name" "$got" "$hhash" >> "$MANIFEST"
    return 0
  fi
  if [ "$dhash" != "$hhash" ]; then
    note "   !! HASH MISMATCH -- dump is BAD for $name"
    printf '%-18s %14s  %s  MISMATCH(device=%s)\n' "$name" "$got" "$hhash" "$dhash" >> "$MANIFEST"
    return 1
  fi
  printf '%-18s %14s  %s\n' "$name" "$got" "$hhash" >> "$MANIFEST"
  note "   ok  sha256=${hhash:0:16}..."
}

# pull_dir <device-path> <destdir>
pull_dir() {
  local src="$1" dst="$2"
  SU "test -d $src" >/dev/null 2>&1 || { note "SKIP $src (absent)"; return 1; }
  mkdir -p "$dst"
  note "$src"
  SU "find $src -type f" > "$dst/.filelist.txt"
  adb exec-out "su -c 'tar -c -C $(dirname "$src") $(basename "$src") 2>/dev/null'" > "$dst/$(basename "$src").tar"
  printf '%-18s %14s  %s\n' "$(basename "$src").tar" \
     "$(stat -c%s "$dst/$(basename "$src").tar")" \
     "$(sha256sum "$dst/$(basename "$src").tar" | awk '{print $1}')" >> "$MANIFEST"
  note "   $(wc -l < "$dst/.filelist.txt") files"
}
