# AIR2 multi-mount core / native backend ABI v1

Status: implementation interface; target addresses and storage capacity still require each model's evidence. This ABI does not authorize a firmware package while profile proofs are missing. No Canon HSS-P3 baseline or policy code is linked.

## Construction and ownership

`runtime_generator.construct(original, *, app_base, code_base, profile, backend)` returns a dictionary:

```python
{
    'sections': [{'address': int, 'data': bytes, 'role': 'air2_core'}],
    'hooks': [],                 # Native model adapter owns hooks.
    'exports': {name: address},
    'reserved_ram': [{'start': int, 'end': int, 'owner': str}],
    'required_imports': [name], 'unresolved_imports': [],
    'metadata': {...}
}
```

Model adapters use the same section representation and hooks of the form
`{address, expected_hex, new_hex, role, continuation, evidence}`. Addresses are MCU absolute byte addresses; ranges are end-exclusive. Every preimage and continuation must be verified against that model's original firmware. The common core emits no native hooks. Fixed-width native CALLs allow two-pass layout; zero/placeholder imports must never reach a package.

`profile` supplies `model_tag` (`F/N/O/S`), `state_base`, `state_span`, `window_counts`, `stable_counts`, `clock_mask`, `code_limit`, and proof identifiers for RAM/hardware/clock/native interfaces. State span is **0x180 bytes maximum**, partitioned below. `0x680..0x800` is only an allocation candidate, not a default or proven physical RAM. Model ports must prove both real SRAM capacity and complete original-program/ISR non-overlap before setting `ram_proven=True`. No automatic C11-address fallback exists.

The six mandatory backend imports are `read_inputs`, `apply_native_state`, `redraw`, `tx_frame`, `nv_load`, `nv_commit`. A port without proved storage supplies `nv_load/nv_commit` stubs returning W=0 and sets `nv_enabled=False`. It must disclose that power-cycle persistence is not available, rather than marking a partial feature complete.

## State block, all offsets relative to proven `state_base`

| Offset | Meaning |
| --- | --- |
| 00 | Runtime magic; initialized only after validated native snapshot |
| 01 | Global mode: 0 TTL / 1 MAN |
| 02 | Remembered manual subtype: 1 AIR1 / 2 AIR2 |
| 03 / 04 | Page 0 ABC / 1 DEF; selected local row1..3 or ALL7 |
| 05 / 06 / 07 | Head/model six-bit masks; relative-value visible six-bit mask |
| 08..0D | Absolute targets A..F, panel tenths1..100 |
| 0E..13 | Relative values A..F, signed−99..99 |
| 14..16 | ABC FEC signed−20..20 |
| 17 | NVM bit0 dirty; bit1 startup projection pending; bit7 write-fault latch until reboot |
| 18..27 | Deferred secondary-key state, first key, times, candidate, captured domain and stall tracking |
| 28..2D | Nonblocking transmit transaction kind/group/mask/step/subphase/mode snapshot |
| 2E..2F | Last committed NVM sequence LE16 |
| 30..3F | **16-byte native queue body**; `tx_frame` reads this exact block |
| 40..5F | 32-byte optional NVM record transfer buffer |
| 60..63 | ABI argument/result bytes; 61 holds `display_row` value |
| 64..6F | Core operation scratch; not native context storage |
| 70 | Snapshot native global mode 0 TTL / 1 MAN |
| 71 | Snapshot native selected row1..3 or7 |
| 72 / 73 | Snapshot native ABC Head/model ON masks, low three bits |
| 74..76 | Snapshot native ABC FEC |
| 77 | Snapshot readiness flags: bit0 edit, bit1 radio, bit2 NVM, bit7 snapshot valid; unknown =0 |
| 78..79 | Snapshot native monotonic tick LE16; use profile clock mask/counts, never assume milliseconds |
| 7A | Snapshot raw secondary keys: C1 / MODEL2 / HEAD4 |
| 7B | Snapshot any other relevant pressed key (0/1); backend must sample actual native input objects |
| 7C..7F | Reserved input extension; zero until specified |
| 80..AF | Core scratch/record validation; exclusively loaned to nv_load/nv_commit during those calls |
| B0..17F | Provider-owned save area, bridge scratch and outer native-hook context (208 bytes) |

The **core-owned range is 00..AF**. The full reserved range is 00..17F (384 bytes). Earlier suggestions of only B0..FF provider scratch are superseded to allow preservation of compiled native bank-local scratch. A backend requiring more space must provide a separately proved allocation, not borrow another live core range.

## Calling conventions

All exports use PIC18 CALL/RETURN, with WREG scalar input/result where stated. Backend routines may clobber W, STATUS, BSR, FSR0/1/2, PRODL/H and target-native scratch, provided they preserve core-owned state except their documented outputs. Core keeps intermediate values in its own block, so it does not rely on native scratch surviving calls.

**The outer native hook wrapper must preserve the original caller's live scratch actually clobbered by the injected path, registers and stack expectations**, replay displaced instructions when necessary, and enter the correct continuation. It must not blindly restore RAM updated by an ISR: for example F RAM0FE publishes a camera event and cannot be snapshotted/restored as ordinary scratch. A core RETURN is not a substitute for validating a native tail-entry. Original IRQ priorities, native RF scheduler and HSS/TTL helpers are not rewritten. If native enqueue has another interrupt producer, the target adapter must establish safe entry or bounded atomicity; queue capacity alone is not a concurrency proof. Tick snapshots must be coherent: prove foreground-only update, use an atomic native accessor, or a bounded high/low/high retry.

`apply_native_state` must recheck native permission before any write. A refused projection has no partial native writes; core restores its pre-edit canonical state and starts no dependent TX. Native external mode changes cancel only not-yet-admitted frames from the old domain. Native mode wins; already queued frames remain under the original scheduler. A service call that admits a frame skips persistence for that call. Before saving, inputs are sampled again, and nv_commit rechecks current native gate/queue conditions before each write/erase. Nv backends may borrow 80..AF and 60..63 only; they must preserve 64..7F except documented read_inputs outputs70..7F. Core sequences2E:F mean last durable sequence and advance only after successful commit.

Core exports:

| Entry | Contract |
| --- | --- |
| `init` | Read native defaults, initialize canonical state; optionally load and validate NVM. No transmit or NVM write. |
| `service` | Read current native inputs; reconcile external mode/context; poll secondary gesture; attempt at most one pending native queue frame; defer optional save. Returns promptly, no busy wait. |
| `power_edit` | W=int8 ±1/±10 from original short/long path. Atomic six-group preflight, then canonical edit/TX plan. W=1 accepted,0 rejected/unsafe. No extra chord window. |
| `select_row` | W=local row1..3. Toggle that row versus ALL7; preserve page mapping; no native relative command. |
| `secondary_press` | W=1 C / 2 MODEL / 4 HEAD, after original normal-application/input gate. Start deferred gesture; suppress corresponding original low-frequency press/release/hold effects until resolved. |
| `idle_expired` | Original native idle deadline explicitly calls this; hide/reset relative values without RF or NVM write. Do not invent a second idle timer. |
| `display_row` | W=row1..3; returns W kind:0 blank,1 signed FEC/relative,2 absolute,3 HeadOFF; base+61=value. Pure canonical query, no native input/queue effects. |

`redraw` should render all three rows through `display_row`, plus canonical page/selected/model markings. It must support TTL-DEF manual behavior and AIR1 temporary values; a MAN-only absolute predicate with legacy fallback is not a complete renderer. The backend may call `display_row` from its native display hook. Do not permit original relative callbacks to run after a handled AIR2 power edit.

Backend imports:

| Entry | Contract |
| --- | --- |
| `read_inputs` | Write only 70..7F, preserving core canonical state. Return W=1 iff valid snapshot, otherwise W=0 and readiness=0. Readiness bits are independent; native exclusive-radio/camera/foreground gates must be proved per model. |
| `apply_native_state` | W bitmask:1 global mode,2 ABC FEC,4 selector,8 **canonical ABC Head/model low-three-bit masks**. Native ABC fields retain ABC meaning even while DEF is displayed; DEF icons are rendered directly at the LCD layer, never substituted into native camera/TTL group masks. Reflect selected canonical fields into target native state **without enqueuing duplicate commands**. Return W=1 success,0 refused. Restore storage-native dirty tracking only through proved original semantics. |
| `redraw` | Render canonical state through existing native LCD primitives; no radio, mode mutation or persistent write. W result ignored. |
| `tx_frame` | Read 30..3F; W=1 iff the complete frame was admitted to the existing native queue; W=0 means not admitted, core retries the same frame later. Must preserve frame and core state; check native exclusive mode and queue capacity including marker. Never direct UART/drain/delay replacement. |
| `nv_load` | If enabled/proved, return one candidate record in40..5F, W=1 available /0 absent. Core verifies model tag, ranges, CRC/commit. No write. |
| `nv_commit` | If enabled/proved and ready bit2, consume40..5F. W=1 only after durable, read-back-verified atomic record completion; W=0 busy/no-write retry; W=2 actual erase/write/readback fault. Core latches bit7 of17 on a fault and makes no more write attempts until reboot. Backend owns target-native journal, sequencing/write/erase primitives and interrupt/context preservation. No writes to original calibration/config pages. |

## Transmit policy

Use the original 16-byte queue protocol and scheduler. Snapshot body is
`27 FF FF FF 01 11 A B C D E F HEAD MODEL 00 00`.
Relative and switch bodies are `g FF FF FF 01 cmd g 00 00 00 00 00 00 00 00 00`.
ABC FEC is `27 FF FF FF 01 25 FA FB FC 00 00 00 00 00 00 00`.

TTL ABC uses FEC; DEF uses remembered AIR1/AIR2. A DEF absolute update sends the complete snapshot and may refresh ABC manual cache, as in P8. Head ON reasserts Model intent after the Head frame. A six-group Head ON can require twelve frames; the transaction is advanced one admitted frame at a time and never assumes all fit at once. Queue-full does not clear state or advance the cursor. While a transaction is active, further edits are gated as in P8; normal power keys do not enter the secondary-key 200-count wait. Queue admission is not an RF or lamp-execution ACK.

## Optional NVM record core

New cross-mount records are V5 to prevent accidental interpretation of Canon historical V1–V4 or another mount's data: 32 bytes, magic41 32, version5, effective mode0TTL/1A1/2A2 at3, sequenceLE16 at4..5, targets6..11, Head/model12/13, page14, lastMAN15, model tag ASCII F/N/O/S at16, reserved17..27 zero, CCITT-FALSE(first28) LE16 at28..29, commit5A A5 at30..31. No historical cross-mount migration is assumed. Pure record encode/decode is separate from storage writes; unproved storage stays disabled.

After loading a valid startup record, a refused native RAM projection leaves bit1 of17 pending and stores the original native mode in2D. Service retries the projection before ordinary context reconciliation. TX and NV remain disabled until success. If the native mode changes while waiting, that external mode wins and the old saved mode is not reapplied. This pending state is only used at startup. The NV backend may choose the durable sequence based on its journal; W1 returns the actual committed record in40..5F and core adopts bytes44..45 as its last durable sequence.

The reference contract is in `p8_port_contract.json`; target profiles and actual-machine-code replay must close every new native adapter before packaging.
