# Sony A6 native radio interface review

This is offline porting evidence, not flashable firmware. PIC18 addresses are byte addresses; the candidate image starts at `0x4000`. No updater, USB operation or original-file modification was performed.

The recovered path is `7490 relative manual adjustment -> 9516 frame builder -> A158 queue -> 5C08 scheduler -> 5DA4 RSGT1 serializer -> native object/state machine at RAM 028D`.

- `7490`: W is the numeric group; RAM `09B` is signed step `+1/-1/+10/-10`, selecting commands `06/07/0D/0E`. Native busy flag `0D8 != 0` returns immediately; caller at `6066..606C`.
- `9516`: W becomes the first byte, `078/079` points to 12 payload bytes. It builds `W FF FF FF payload12` at `07B..08A` and calls `A158` through pointer `076=7B`. It does not add `20` to the first byte.
- `A158`: `076` is the start **low address in bank 0** of a 16-byte frame. W returns queue accepted `1` or refused `0`, not a receiver ACK. It queues a zero record marker and then the frame.
- `00E6..00EB`: write index, read index, used count, capacity, data-pointer low/high. Original initialization at `668A..669C` establishes capacity100, data `0400..0463`. Admission for a 16-byte frame succeeds only with count `<=83` because the record also needs its marker.
- `6F7A/7296`: byte enqueue/dequeue, descriptor pointer at `06B/06C`. Empty dequeue returns0; zero is also valid data.
- `5DA4`: `07A/07B` points to the native transmit buffer, normally `0143`. A zero record produces exactly `RSGT1 + frame16`, length21 in `0144`, data from `014A`.
- `AF70` is literally `RETLW 02`, not an object getter. Consequently `7FDC` chooses RSGT1 and `A2DE` returns16. Leave them unchanged.

The native queue call clobbers `06B..077`, FSR and W/STATUS/BSR as well as queue state; the frame builder additionally uses `07A..08A`. Integration must use the independently audited Sony RAM map, never Canon scratch/global addresses.

AIR2 preserves the native HSS/camera/UART/state-machine code and constructs the existing P8 receiver-contract frame below. The original queue calls establish its ABI, but a subsequent ISR concurrency audit found an actual race. Use the short-commit candidate described below for integration:

```
27 FF FF FF 01 11 A B C D E F HEAD6 MODEL6 00 00
```

Targets are complete values1..100 in 0.1-power units. Do not guess zero or FF as a no-change sentinel. This command is imported from P8/receiver evidence, not claimed as an original Sony feature. Native transport passes it unchanged in the replay; actual receiver acceptance needs product testing.

Native relative/switch frames are `group FF FF FF 01 command group` followed by nine zeros. The packet layer accepts groups1..6/ALL7; that does not imply the original UI supports D–F.

Retain current-domain dirty state on refusal. An original camera abort after admission remains authoritative; do not blindly resend stale domain snapshots. Never put new state in queue RAM `0400..0463`. `A158` does not mask interrupts, and ISR-reachable `AC84` is another producer for the same queue. `audit_concurrency.py` reproduces both record interleaving and frame truncation, so state preflight alone is insufficient. This review does not establish full RF acknowledgement semantics or physical timing.

Run `python -B analysis/air_remote_ttl_multi_air2/S/radio/verify_native_queue.py`: **308 instruction replay cases pass**. Of these,272 execute original code for groups1..7, eight basic commands, an AIR2 snapshot, ring starts0/92/99 and used counts0..100. Another36 execute the new high-RAM wrapper plus original queue instructions. No queue or serializer hook replaces native code. The test adds POSTDEC alias handling and PIC18 DECF/INCF Carry semantics to the existing bounded VM without editing that old VM.

`native_queue_adapter.py` builds a callable PIC18 wrapper without installing hooks. The integrator explicitly allocates frame RAM and code placement. It checks native `0D8`, calls `8F84` and `AB66`, then uses native `86EA` (`071/072` 16-bit source pointer, `073=16`) to avoid the bank-0 frame restriction. Tests cover source0500/06F8/0EE0, D8=0/1/255 and count0/83/84/100, retaining source bytes and D8. It allocates no permanent RAM, patches no native HSS, and masks no interrupts; the caller still needs concurrency/context verification.

Native D8 evidence: `A5A4` sets D8=1, clears the queue through `A906`, and queues `RSUU1\r` through `90BA`; `93BC` clears D8 and queues `RSUU0\r`. `A814` enters that mode and sets deadline `1C2/1C3`; `A586` exits on timeout before `5C08` service. This is the native exclusive-radio gate, not a completed proof of every camera-busy phase.

`protocol_adapter.py` is a host-only packet contract. `native_queue_verification.json` records the replay. `abi_preimages.json` pins the candidate image and native entry bytes. None is a flashable deliverable or proof of RF timing/HSS correctness.

## Short commit and concurrency verification

`fast_empty_queue.py` provides `construct(base, frame_ram, irq_ram)`, a324-byte callable candidate (242-byte commit plus an82-byte read-only quiet export). It admits a frame only when the original queue is empty, D8 is clear and observed camera software states permit it. It masks GIEH/GIEL briefly, rechecks, copies17 fixed bytes and publishes count last. It restores enable bits individually, leaves IPEN/live interrupt flags intact, and must be called from foreground outside every native queue service. The older `native_queue_adapter.py` remains ABI research, not the recommended submission path.

The shared PIC18 VM passes2555 cases, including740 instruction-boundary schedules using original producer/abort code. The maximum critical region is74 instruction cycles. `static_isr_audit.py` confirms producer reachability and absence of consumer/identified indirect-control sites in the original ISR direct-flow closure. See [the concurrency audit](CONCURRENCY.md) for predicates, callsites and limits. Software quiet does not guarantee physical HSS completion; an event arriving after the last pending check can incur finite added latency.
