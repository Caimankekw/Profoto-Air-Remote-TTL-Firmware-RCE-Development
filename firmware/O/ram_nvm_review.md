# Olympus A4 RAM / NVM offline review

All program addresses are byte addresses. RAM/Flash ranges below are inclusive. Exact MCU package/config and unrecovered bootloader are not certified. No USB, EXE or network actions were performed. Exact image hash and preimages are in `ram_nvm_contract.json`.

## RAM boundaries

Startup clears: `024..040` (`6A4C`), `060..0B6` (`6A40`), `100..1CD` (`6A34`), `200..26E` (`6A28`), `300..363` (`6A1C`). Startup copies ROM `835C[0x54=84]` to `26F..2C2` (`69CA`), ROM `AB56[9]` to `1F1..1F9` (`69EA`), and ROM `ABE0[1]` to `041` (`6A0A`).

Startup end is not the complete runtime footprint: `5430..5450` and `598A/598E` evidence scratch variables in `1CE..1F0`; `581A MOVLB 2 / 581C MOVWF C3` uses `2C3`; `581E..5832` copies 11 bytes from `008A` to `2C4..2CE` through `8306`.

The highest confirmed fixed object is the 100-byte ring `300..363`: `6774..6786` passes descriptor `0095`, buffer `0300`, length `64` to `8FBA`. That initializer stores buffer at descriptor+4/+5, length at +3, clears the three indices. The second ring is initialized by `678A..679E`: descriptor `01B2`, buffer `0215`, length `32`, hence `215..246`. IRQ `A8EC -> 719A` writes it. IRQ `67E8` also writes packet buffer `247..26E`, using `089` as index and `28` as termination limit.

A new bank-aligned candidate is `400..5FF`, conditional on the existing PIC18F47J53-family GPR interpretation and normal pointer invariants. `2CF..2FF` and `364..3FF` are only candidate gaps. All generic pointer caller bounds were not formally proven. C P8 allocations at `220..248`, `263..27F`, `2C0..2CE`, `330..35F` conflict with original O objects.

## FSR and stack

FSR0 explicit references occur only in startup copy/clear. FSR1/FSR2 are object/field/copy cursors: for example `719C..71A6` computes object+2 and `7200..7214` computes object+3 or field offsets. No RAM software-stack initialization or growth mechanism was identified. `6148..6164`, `6AA0..6ABA`, and `A6B4..A6CA` use PUSH plus three writes to hardware TOS followed by RETURN for indirect function calls; they are not RAM stacks. Whole-listing MOVLB values are only 0, 1, 2, E, F; no other direct BSR writes were found. This does not substitute for a whole-program indirect-pointer proof.

## IRQ closure

Static traversal from `4108`, including direct callees, branches and both skip edges, contains 392 instructions with no missing target or TOS dispatch. `410A..4116` saves FSR1/FSR2 into `1A..1D`, and `4164..4170` restores them. `4176 RETFIE 1` restores fast W/STATUS/BSR under PIC18 semantics. Scratch is `001..019`; saved slots are `01A..01D`; shared state includes `040`, `042.1`, `089`, `0B1..0B2`, `0B5..0B6`, `19A`, ring descriptor `1B2..1B7`, buffers `215..26E`. `073..076` are read. This closure does not write FSR0, PRODL/PRODH, TBLPTR/TABLAT. Other bootloader/exception paths and nesting configuration remain unproven.

## Original Flash journal

`5796 -> 5E1C`; `5E38..5E54` passes descriptor=01AB, Flash endpoint=0001FBFF, count byte=00, stride=04 to `825A`. The descriptor becomes `FF FB 01 00 00 00 04` at `1AB..1B1`. `97D6..97E8` passes descriptor=01AB and buffer=01D6 to `5396`. Commit callers are `8A0E` and `922E`.

`81A8..8200` computes `record_end = 1FBFF - 4*index`. `5428..5474` computes each word address as `record_end - remaining + 1`, remaining 4 then 2. Index 0 writes `1FBFC..1FBFF`; index 255 writes `1F800..1F803`; the 256 records cover `1F800..1FBFF`. `54B2 -> 962C` is the unique direct word-write call. `53DA -> 9E1A` is the unique direct erase call; it uses endpoint 1FBFF when index=0. A 1024-byte physical erase page matches this layout, but erase geometry is hardware-dependent and is not independently proven by these instructions.

`962C` loads TBLPTR from C3..C5 and two data bytes from C7/C8, executes TBLWT twice, sets FA6.5/WPROG and FA6.2/WREN, unlocks 55/AA and sets FA6.1/WR. `9E1A` uses FA6.4/FREE. Both call `9E3A`, which clears FD0.7 and FF2.7; completion **unconditionally sets both bits**, rather than restoring prior state. Patch callers must account for this side effect.

F800..FFFF has image-FF evidence and does not overlap this normal original journal. That alone is not a standalone allocation proof: new linked code, bootloader and configuration constraints must also be checked.
