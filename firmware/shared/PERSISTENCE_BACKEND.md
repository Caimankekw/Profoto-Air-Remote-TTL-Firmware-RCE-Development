# AIR2 V5 persistence backend

`persistence_backend.py` emits new, relocatable PIC18 journal code for the shared
multi-mount ABI. It does not run a device tool or modify any firmware file. It
contains a small generic assembler derived from the authored P8 `hss_patch.py`
encoding helpers. It has no runtime dependency on P8 source; no Canon construct,
state addresses, native fields or HSS policy are called or copied into the backend.

## Linking and proof gates

```python
result = persistence_backend.construct(
    original,                         # app-relative bytes, optional during sizing
    app_base=0x4000,
    code_origin=next_even_address,     # code_base is an accepted alias
    state_base=0x680,
    profile={"model_tag": "F", "code_limit": 0xF800},
    imports={"read_inputs": native_exports["read_inputs"]},
    backend={"persistence": {
        "hardware_proven": True,
        "ram_proven": True,
        "pages_proven": True,
        "isr_context_proven": True,
        "flash_bytes": 0x20000,
        "erase_bytes": 0x400,
        "write_bytes": 2,
        "eecon1": 0xFA6,
        "eecon2": 0xFA7,
        "wprog_bit": 5,
    }},
)
```

The descriptor's proof flags are assertions supplied by the target evidence
layer, not conclusions made by this generator. `identity_report.json` documents
the static common-family geometry/register evidence for the intended
PIC18F/LF47J13/J53 families. Exact physical chip identity remains unproved.
`ram_proven` must include native/ISR non-overlap; `pages_proven` must include the
known-byte mask and original all-FF contents. `isr_context_proven` must establish
that interrupt handlers preserve BSR, FSR2, TBLPTR and TABLAT, including any native
scratch they use: scanning and readback run with the caller's interrupt state.
Each target remains responsible for its actual input/radio/camera readiness
proof and for preventing another foreground Flash writer from entering this
nonreentrant backend.

Missing flags produce two explicit W=0 stubs and `metadata.nv_enabled=False`.
If all flags are true but the geometry/register descriptor disagrees, construction
fails. When original bytes are supplied, both complete pages must be FF. Every
code section must end at or before F800. No default native address is assumed.

The return schema is the shared `sections`, `hooks`, `exports`, `reserved_ram`,
`required_imports`, `unresolved_imports`, `metadata` dictionary. First-pass calls
can leave `read_inputs` unresolved; its CALL is fixed width, so second-pass labels
and sizes are unchanged. A packager must reject unresolved imports. The enabled
component is 2,234 bytes before future documented modifications; use its actual
section length when linking.

## Caller contract and state

`nv_load` returns the latest valid complete 32-byte V5 record in state+40..5F,
with W=1. W=0 means absent. It performs no Flash controller access or mutation.
The core owns restoring canonical mode, remembered manual kind, page, targets,
Head/model masks and committed sequence from this record.

`nv_commit` consumes a complete validated candidate at state+40..5F. It returns
W=1 only for an already identical durable payload, or after all 16 programmed
words have been read back. W=0 means refused or retryable busy. W=2 identifies an
actual erase/program/readback failure: the core retains dirty state and latches
further NVM attempts off until restart. The backend assigns the
next sequence and recomputes CRC in the transfer buffer. An unchanged payload
copies the old durable record back to the transfer buffer and performs no erase
or programming. The core clears its dirty flag only after W=1. Canonical
state+00..3F, the frame body and core operation scratch are not modified.

Only core scratch+80..AF is borrowed during either call; provider scratch+ B0..17F
is untouched. The record is never overwritten by the commit-time scanner.
W is the documented result; STATUS, BSR, FSR0/1/2, PRODL/H, TBLPTR and TABLAT are
preserved. `read_inputs` may update state+70..7F under its ordinary ABI contract;
it must preserve record and borrowed scratch. The backend preserves its FSR2
across that call and restores its own bank selection.

Before scanning a commit candidate, and immediately before **each** erase or word
program, it saves both interrupt-enable bits, masks them and calls the imported
real `read_inputs`. The sampler must return W=1 and snapshot+77 must contain both
valid bit7 and `IN_NV_READY` bit2. Failed refreshes restore the prior enables and
refuse the command. A successful refresh keeps interrupts masked through the
write-latch/unlock sequence. Restoring enables uses bit instructions, so pending
INTCON peripheral flags are not overwritten. Previously disabled enables remain
disabled. The original EECON1 value is restored on a normal return after a Flash
operation; an already asserted WR causes refusal.

## Format and atomicity

The V5 record is exactly the shared ABI: `41 32 05`, effective mode0/1/2,
sequenceLE16, six targets1..100, Head/model masks0..63, page0/1, lastMAN1/2,
ASCII model tag F/N/O/S, eleven reserved zero bytes, CCITT-FALSE of the first
28 bytes as LE16, then commit word `5A A5`. Nonzero effective mode must equal
lastMAN. Machine instructions validate the envelope, every range, model tag,
reserved bytes, CRC and both commit bytes. Historical V1–V4 records and other
model tags are rejected.

Only F800..FBFF and FC00..FFFF are storage. Both are 1,024-byte pages, each with
32 aligned records. The scanner visits all 64 slots. Sequence ordering uses a
nonzero unsigned difference less than 0x8000; exactly half-range differences are
not newer. Interrupted/invalid records cannot become the latest record.

The writer searches for a completely FF 32-byte slot in the current valid
record's page. It never reuses a partly written slot. When the page is full it
erases only the other page, checks all 1,024 erased bytes and writes there. The
old valid page remains until a new committed record is durable. Address guards
accept erase only at exact F800/FC00 page starts and word programs only at even
addresses F800..FFFE. The original stock journal 1F800..1FBFF and device
configuration/calibration pages are never targets.

Each two-byte word uses WPROG=1; the second TBLWT does not postincrement. It
executes the 55/AA unlock with interrupts masked, checks WRERR and reads both
bytes back. The final operation programs the commit word at offsets30..31.
Reset before that complete word leaves the preceding valid record selectable.
CPU reset after a complete commit may leave the RAM dirty flag set, but the
next load selects the durable new record.

## Validation and limits

Run `python -m unittest test_persistence_backend -v` from this directory. Tests
execute the emitted bytes through `pic18_vm.CPU`; no Python callback replaces
the validator, CRC, scan, compare, sequence, erase selector or writer. The only
device model is an explicit EECON1/EECON2 Flash controller that checks the actual
unlock keys, IRQ mask, latch addresses and WPROG mode, then applies Flash effects.
The isolated test sampler is disclosed machine code standing in for native
inputs; integrated target tests must instead execute each real adapter.

Tests cover all model tags; exact mode/page/targets/masks; invalid values even
with a repaired CRC; torn commit; stale/corrupted CRC; serial wrap and half-range;
rollover in both directions; unchanged compare-write; refreshed busy denial;
program and final-page-byte erase readback failures; register and canonical
preservation; all four prior interrupt-enable combinations; and simulated reset
before every word, with and without a partially programmed word, during ordinary
append and page rollover; reset immediately after destination-page erase also
retains the old valid page.

These are bounded instruction/device-model checks. They do not prove electrical
retention, endurance, brownout behavior, oscillator timing, camera traffic during
hardware write stalls, unknown bootloader integrity checks or safe installation
on a physical unidentified MCU. Native hooks/readiness and the complete linked
image require the separate target integration evidence.
