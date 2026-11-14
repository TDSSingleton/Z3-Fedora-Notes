# Verified findings — the load-bearing facts

Everything in this folder was confirmed from a **primary source** on 2026-11-06:
the Samsung GPL drop in `SM-F926B/`, the live `torvalds/linux` tree on git.kernel.org,
the uniLoader/U-Boot repositories, or **the device itself over `adb`**.

Nothing here is a plan, an estimate, or a third-party report. Those live one directory up.

| File | What it establishes |
|---|---|
| [01-hardware-inventory.md](01-hardware-inventory.md) | Every chip on the board, from the `r08` DTS, each cross-checked against upstream |
| [02-upstream-status.md](02-upstream-status.md) | What SM8350 support exists in mainline, with HTTP-verified presence/absence |
| [08-device-facts.md](08-device-facts.md) | Values read off **your** unit, unrooted |
| [12-wifi-qca6490.md](12-wifi-qca6490.md) | The QCA6490/WCN6855 PCI-ID collision and how `ath11k` demultiplexes it |

---

## The six facts the whole project rests on

### 1. The device is unlockable, and Knox is intact
`sys.oem_unlock_allowed = 1`, `ro.boot.warranty_bit = 0`, `ro.boot.flash.locked = 1`.
Read from the device. → [08-device-facts.md](08-device-facts.md)

### 2. `r08` is the correct device tree for this unit
`ro.revision = 9`, and only `q2q_eur_openx_w00_r08.dts` covers revision 9 (its
`dtbo-hw_rev` range is 0x8–0x20). All hardware analysis used that file.

### 3. SM8350 display is fully supported upstream
*(This finding previously said the opposite. It was wrong — see
[02-upstream-status.md](02-upstream-status.md) §3 for the correction and the evidence.)*

| Piece | Compatible | Driver |
|---|---|---|
| Display clock controller | `qcom,sm8350-dispcc` | `dispcc-sm8250.c` (a 4-SoC driver) |
| DPU | `qcom,sm8350-dpu` | `dpu_sm8350_cfg` |
| DSI controller | `qcom,sm8350-dsi-ctrl` | DSI 6G v2.6.0 |
| DSI PHY | `qcom,sm8350-dsi-phy-5nm` | `dsi_phy_5nm_8350_cfgs` |

`CONFIG_SM_DISPCC_8250` is titled "SM8150/SM8250/SM8350 Display Clock Controller". The
SM8350 register deltas are applied at runtime in its probe. The clock-ID header
`qcom,dispcc-sm8350.h` is a symlink to `qcom,dispcc-sm8250.h`, and `sm8350.dtsi` already
supplies exactly the parent clocks the driver wants — **no DT change needed**.

The lesson for the rest of this folder: *absence of a file is not absence of support.*
A compatible string can be claimed by a differently-named, multi-SoC driver. Check the
`of_device_id` tables, not the filenames.

### 4. Samsung's ABL merges device-tree overlays — verified from our own source
The claim originates with the Galaxy Tab S8+ port, which states ABL *"merges its own
device-tree overlay fragments onto whatever DTB it selects, which corrupts a mainline
device tree."* That is third-party — **but our own source drop corroborates the
mechanism directly**, which is why it sits in this folder.

`q2q_eur_openx_w00_r08.dts` is not a conventional board DTS. It is 17,889 lines of
~266 blocks of the form:

```dts
fragment@118 {
    target = <0xffffffff>;
    __overlay__ {
        ss_dsi_panel_S6E3FAB_AMB623ZF01_HD { ... };
    };
};
```

…closed by a `__symbols__`/fixups table mapping fragment paths onto targets (`tlmm`,
`cnss_pci`, `wlan`, `bluetooth`, …). That overlay-plus-fixups structure *is* what ABL
applies. A mainline DTB contains none of the nodes those fixups reference.

### 5. QCA6490 and WCN6855 share one PCI device ID
`cnss2/bus.h:21` → `QCA6490_DEVICE_ID 0x1103` (vendor `0x17CB`).
`ath11k/pci.c:32` → `WCN6855_DEVICE_ID 0x1103`.

So a QCA6490 enumerates on `ath11k`'s **WCN6855** path, not the QCA6390 one, and
`ath11k` already splits `0x1103` four ways by silicon version. → [12-wifi-qca6490.md](12-wifi-qca6490.md)

### 6. Required firmware is not redistributable
Upstream `linux-firmware` ships `ath11k/` for IPQ5018, IPQ6018, IPQ8074, QCA2066,
QCA6390, QCA6698AQ, QCN9074, WCN6750, WCN6855 — and **no QCA6490**. Wi-Fi firmware and
board data must come off this device and cannot be shipped in an image.

---

## Key numbers, for reference without re-deriving

```
SoC           SM8350 "lahaina", soc_id 415, revision 2.1, hw_platform MTP
Board         q2q, ro.revision 9  ->  r08 DTS
Splash FB     cont_splash_region @ 0xE4000000, 0x2300000 (35 MiB)

Main panel    S6E3XA2_AMF755ZE01 (or XA1 — r08 offers both; needs root to confirm)
              2208 x 1768  (natively LANDSCAPE), 149 x 119 mm
              cmd mode, 4 lanes, DSC 2 x (1104 x 34), 24 bpp
              1,362,000,000 Hz bit clock, 120/96/60/48 Hz
              H 76/76/76   V 68/68/61 @120Hz
Cover panel   S6E3FAB_AMB623ZF01
              832 x 2268, 54 x 148 mm
              cmd mode, 4 lanes, DSC 2 x (416 x 42), 24 bpp
              766,000,000 Hz bit clock, 120/96/60/48 Hz
              H 40/40/63   V 60/60/146 @120Hz

Wi-Fi/BT      QCA6490 on pcie0, PCI 17CB:1103
              wlan-en tlmm 64, bt-en tlmm 65, sw-ctrl tlmm 153
              aon S2E 1.0125V  dig S11B 1.0125V  io S10B 1.8V
              rfa1 S1C 1.984V  rfa2 S12B 1.35V   ant-switch L7E 2.8V

Battery       2 cells in parallel, S2ASL01 limiters at I2C 0x38 / 0x39
              each with bat_enb + bat_det GPIOs, powermeter, thermal shutdown
```
