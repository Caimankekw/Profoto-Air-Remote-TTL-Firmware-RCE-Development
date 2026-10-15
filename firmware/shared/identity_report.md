# Stock N/S/F/O MCU capability audit

2026-10-15. Offline read-only analysis; no updater execution or USB access.

The stock images independently support the same PIC18F/LF46/47J13/J53 peripheral-map family. The intended 128 KB config layout narrows this to **F/LF47J13 or F/LF47J53**. Exact silicon identification remains unproven. This ambiguity does not change the required memory capability.

- **RAM `[0x680,0x800)` (384 bytes) is physical GPR on every matched candidate.** `[0x800,0xC00)` is also GPR. This report does not prove these locations are unused by stock code or a bootloader.
- **FREE erases 1024 bytes, aligned to `0x400`.** Thus `F800..FBFF` and `FC00..FFFF` are distinct erase blocks. On the intended 128 KB variants, neither touches config `1FFF8..1FFFF`. The 64 KB 46 variants would place config at `FFF8..FFFF`; they are incompatible with the stock container config layout.
- All eight matched local headers agree on `EECON1=FA6`, `EECON2=FA7`; bits `WR=1`, `WREN=2`, `WRERR=3`, `FREE=4`, `WPROG=5`.

All N/S/F/O raw HEX files contain config `98 F7 3D F8 63 FA 04 F9` at `1FFF8`, and FF at `1FFF0..1FFF7`. These are container bytes, not device readback. J13 accepts the key config1H/config2L values, so they cannot establish J53 uniquely.

| Stock | Init start | CCP8CON F06 operation | CCPTMRS2 F50 operation | RPOR13 ECD write | RPINR2 EE2 write |
|---|---:|---:|---:|---:|---:|
| N | 0x4baa | 0x4bcc | 0x4bd8 | 0x4bf0 | 0x4c4e |
| S | 0x4d42 | 0x4d7c | 0x4d88 | 0x4da2 | 0x4dfa |
| F | 0x4c4a | 0x4c6e | 0x4c7a | 0x4c94 | 0x4cec |
| O | 0x569c | 0x56c0 | 0x56cc | 0x56e6 | 0x5742 |

Each listed instruction was checked against known-mask bytes with its preceding BSR selection. The same init blocks also access ANCON0/1 F48/F49 and PORTD/TRISD/TRISE F83/F95/F96. This joint signature matches exactly F/LF46J13,47J13,46J53,47J53 among installed gputils `p18*.inc` files. It excludes the J50 register layouts; no assumption from the C11 part name is needed.

Primary references (printed page numbers):

- [Microchip DS30009974C, J13](https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ProductDocuments/DataSheets/30009974C.pdf): Table1 p2 has 64 KB/128 KB flash and 3760-byte SRAM; Fig6-6 p83 shows banks6/7 as GPR; section7.4 p106 gives 1024-byte erase with low10 TBLPTR bits ignored.
- [Microchip DS30009964C, J53](https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ProductDocuments/DataSheets/30009964C.pdf): Table1 p2 has 64 KB/128 KB flash and nominal3.8 KB SRAM; Table6-1 p77 config addresses; Fig6-6 p85 shows banks6/7 as GPR; section7.4 p109 gives the same erase geometry.

The JSON companion records exact bytes, addresses, verified source hashes, every matched header/linker definition, and the evidence boundary. Use a capability flag such as `common_family_memory_capabilities_verified`, not `exact_physical_chip_identity_verified`.

Further 128 KB corroboration: each stock application builds the same high-flash journal address `0x0001FBFF` with record width4: N `6088..609D -> CALL7FC4`, S `6468..647D -> CALL835E`, F `6AAC..6AC1 -> CALL8868`, O `5E42..5E57 -> CALL825A`. Exact known bytes are recorded in JSON. This intended high-flash access independently conflicts with a64 KB target.

Word programming is common across both families: `WPROG=1` writes2 bytes; `WPROG=0` writes64. J13 Register7-1p103 and section7.5.2p109; J53 Register7-1p106 and section7.5.2p112. Word mode requires an even, erased address, two loaded bytes, no post-increment on the second TBLWT, then55/AA/WR with interrupts disabled.
