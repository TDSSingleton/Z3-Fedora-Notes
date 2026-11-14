# Forcing TWRP from Download Mode

Needed when the phone is stuck in Linux and cannot be powered off normally
(our kernel has no power-button handling), so Download Mode is the only exit.

`misc` (partition 10, PIT name `MISC`, 1 MiB) holds the AOSP **BCB**
(bootloader control block). Setting `command = "boot-recovery"` makes the
bootloader boot the recovery partition — TWRP — on the next start. This device
demonstrably honours it: an earlier session got stuck in a recovery-only boot
loop from exactly this field being set.

`misc` is a scratch partition. It is not secure-world and not on the Tier-1
never-write list, so writing it is safe.

## 1. Force recovery

Phone in Download Mode (power off / from Linux: Vol-Up + Vol-Down + plug USB):

```sh
heimdall flash --MISC rescue/misc-boot-recovery.img
```

Heimdall reboots the phone afterwards; it should come up in TWRP.

## 2. CLEAR IT IMMEDIATELY — this step is not optional

The BCB persists. Leave it set and the phone boots **only** recovery, forever,
which is the loop that cost a previous session. From TWRP:

```sh
adb shell 'dd if=/dev/zero of=/dev/block/sda10 bs=4096 count=256'
adb shell 'sync'
```

Or, if you are back in Download Mode instead:

```sh
heimdall flash --MISC rescue/misc-cleared.img
```

Verify it is clear (should print nothing but zeros):

```sh
adb exec-out 'dd if=/dev/block/sda10 bs=4096 count=1 2>/dev/null' | od -A d -c | head -3
```

## Alternative, no writes at all

From Download Mode, long-press **Vol-Down + Power** to leave it, then
immediately hold **Power + Vol-Up** to boot recovery. Costs nothing and leaves
the BCB untouched; worth trying first.
