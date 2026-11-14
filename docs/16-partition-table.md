# Fold 3 partition table (pulled over serial, 2026-11-08, device-verified)

```
  disk GUID     <redacted>
  this header   LBA 1      backup LBA 62340095
  usable        LBA 6 .. 62340090
  entries       40 x 128 B at LBA 2
  disk size     237.81 GiB usable, 4096 B sectors

    # name                    start LBA      end LBA         size
  --- -------------------- ------------ ------------ ------------
    1 modemst1                      265         1032           3M
    2 modemst2                     1033         1800           3M
    3 fsc                          1801         1832           0M
    4 ssd                          1833         1834           0M
    5 persist                      1835        10026          32M
    6 efs                         10027        15146          20M
    7 param                       15147        17706          10M
    8 debug                       17707        20266          10M
    9 sec_efs                     20267        25386          20M
   10 misc                        25387        25642           1M
   11 keystore                    25643        25770           0M
   12 frp                         25771        25898           0M
   13 rawdump                     25899        29994          16M
   14 bota                        29995        40334          40M
   15 persistent                  40335        40462           0M
   16 steady                      40463        41486           4M
   17 dsp                         41487        57870          64M
   18 modem                       57871        99823         164M
   19 boot                        99824       124399          96M
   20 recovery                   124400       148975          96M
   21 vendor_boot                148976       173551          96M
   22 dtbo                       173552       179695          24M
   23 apnhlos                    179696       228335         190M
   24 vbmeta_system              228336       228351           0M
   25 metadata                   228352       232447          16M
   26 super                      232448      3434495       12.21G
   27 prism                     3434496      3767295        1.27G
   28 optics                    3767296      3774975          30M
   29 cache                     3774976      3928575         600M
   30 omr                       3928576      3941375          50M
   31 spu                       3941376      3954175          50M
   32 testparti                 3954176      3955199           4M
   33 core_nhlos_a              3955200      3998719         170M
   34 catefv                    3998720      3998975           1M
   35 keyrefuge                 3998976      4012287          52M
   36 userdata                  4012288     62340090      222.50G

  36 partitions
  highest end LBA: userdata ends at 62340090 (usable last = 62340090)
  slack after it : 0.0 MiB

  largest:
    userdata               222.50 GiB
    super                   12.21 GiB
    prism                    1.27 GiB
    cache                    0.59 GiB
```
