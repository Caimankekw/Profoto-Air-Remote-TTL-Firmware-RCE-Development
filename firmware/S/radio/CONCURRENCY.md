# Sony A6 native queue, camera state and short-commit audit

[中文](CONCURRENCY.zh-CN.md)

Input: `../shared_codec_candidate.base4000.bin`, SHA256
`b5d7c9b199cc1a705514c028d609e31bb8b6fb55813cdc2ab1fcba898be7cee5`.
No native HSS patch, updater execution, USB access or hardware test is involved.

## State meanings

RAM0D8 is the original exclusive-radio gate: A5A4 sets it, discards the E6 queue through A906 and queues RSUU1; 93BC clears it and queues RSUU0. It does not cover every camera phase.

RAM0DD is the factory diagnostic UI state. 6D54/6DB4 maps states1/2/3/5/6/7 to HELLO/A6/rAdio/G I t/bb178/all segments. DD=0 permits normal UI editing but does not prove HSS idle. RAM0DC is a temporary mode lock: 9D5E writes it, 78B4 forces camera[0]=1 when nonzero, and9708 expires it. The identified Sony calls6C0E/A028 both pass0; an active DC=1 path remains unproven.

Main binds D2/D3 to object0193 via5068. Object[0] is the mode read by9690; object[1], RAM0194, is the camera synchronization phase. States1..4 are recognized active phases; the ISR sets state5 at41BE/41F0 after completion. 6BB0 explicitly retains5 on timeout. Restricting the helper to state0 would reject normal post-shot operation. RAM56 is the handshake state, normally1;2/4 participate in interrupt-driven receive. RAM48 marks completion awaiting foreground93BC processing.

AB0C, called from80F2, only tests signed D1:D0>=3. It is not an HSS-busy test. 87CC invokes the CA/CB/CC adjustment callback without a queue transaction lock.

## Confirmed interrupt producer

The ISR starts at4108 and exits through4250 RETFIE1. Address41B8 is the second word of41B6 CALL8C00, not a separate ISR.

The chain414E→7842→78B0→5B34→5BE8→5858→589A→7D9E→90BA→AC84→7002 produces an RSUTP record. Conditions include0194=0/56=1 at414E, the361..449 timer-unit range in5B34, pointer3E/3F=025F, packet[7].7=1 and packet[10].7=0. Other5858 paths callA814→A5A4→A906 to discard the same queue and enqueueRSUU1. D8 alone therefore cannot provide exclusion.

`static_isr_audit.py` conservatively keeps all conditional outcomes. Its4108 direct-flow closure covers1711 addresses, with no unknown decode or identified indirect-control site. Producers90BA/AC84/A906/7002 are reachable; consumers5C08/5DA4/7296 are not. 5DA4 has one direct caller5C6C;5C08 is reached only throughA586;A586 has only main-loop calls4EA0/4EBC. Integration must remain foreground-only, outside those services and every native queue helper/callback.

`audit_concurrency.py` executes the actual native marker producer, then native90BA, then native86EA. With count0, the ASCII record splits the frame. With count83, the queue fills and drops the remaining frame bytes while the caller still returns1. Across400 cases, originalA158 takes2065–2105 instruction cycles; the high-RAM wrapper takes2259–2299. Masking interrupts around that entire operation is unsuitable for a short commit.

## Callable candidate

`fast_empty_queue.construct(base, frame_ram, irq_ram)` emits324 bytes (the original242-byte transaction plus an appended82-byte `sony_air2_quiet` read-only snapshot) and requires16 caller-owned frame bytes plus one private control byte. It does not install hooks or write a complete firmware image.

1. Check foreground context, D8=0, countE8=0,56=1,48=0,194 in{0,5}, and zero pending camera bitsFF0.0/.1,F98.4,FA4.7. Confirm native capacity100/data0400.
2. Save GIEH/GIEL and clear only those enable bits. Recheck the runtime predicates while masked.
3. Write the zero marker at400 and16 frame bytes at401..410, set read=0/write=17, and publish count=17 last. Previous empty-ring indices may be nonzero. The foreground consumer must not run or reenter during this transaction.
4. Restore the original enable bits individually. Preserve live IF and every other INTCON bit; leave IPEN untouched.

W=1 means local admission, not an RF acknowledgement. W=0 means no submission and no queue change. W/STATUS/BSR and the caller-owned control byte may change. An originalA5A4 abort after publication may legitimately discard the admitted frame; do not blindly resend a stale domain snapshot.

The gates identify observed software states, not measured physical HSS completion. An interrupt arriving after the last pending check can still be deferred. The maximum critical region is74 instruction cycles, or74/F_instruction seconds. Oscillator/PLL settings, hardware timing and air-interface latency are outside this result.

## Verification

Run `python -B analysis/air_remote_ttl_multi_air2/S/radio/test_fast_empty_queue.py`.

2555 shared-PIC18-VM cases pass:1600 empty-ring-position/stage/GIE/IPEN combinations;23 rejection conditions;192 read-only quiet checks;740 instruction-boundary schedules using native90BA append orA5A4 abort. Cases cover old indices93, new live IF bits during the operation, post-commit abort and subsequent native5DA4 serialization. Independent44-case review is recorded inshared/HSS_PRESERVATION_REVIEW.json.

Producer functions execute their original instructions without queue/clear stubs. Hardware interrupt priority, sampling and the complete4108 ISR are not simulated. This is bounded transaction evidence, not a hardware HSS-equivalence claim.
