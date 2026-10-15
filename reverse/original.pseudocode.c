/* Air Remote TTL-N C5: bounded ORIGINAL firmware reconstruction.
 * Human-written C-like notes, not manufacturer's complete C source.
 * NOT COMPILABLE, NOT FLASHABLE. RAM/ROM and native_* are notation only.
 * PIC18 byte addresses; source_map.json pins stock ranges and evidence.
 * Exact kernels are labelled; opaque calls deliberately retain unknown work.
 * 原厂有限范围伪代码；非厂家完整源码，不能编译或刷写。
 */

// [N-boot] Observed control flow; omitted initialization stays opaque.
void original_boot_and_loop(void) {
    // 0x4102 -> 0x417E -> 0x56DE; initializer ends with GOTO 0x4BAA.
    native_runtime_init_56DE(); // ROM copies, zero fill, flag initialization
    native_board_objects_4BAA();
    for (;;) {                 // 0x4CF6..0x4D44
        CLRWDT();
        native_clock_service_7124();
        clear_bit(SFR[0xFF0], 3);
        native_camera_5D74(/* RAM 0x0500, model 0x01B1 */);
        set_bit(SFR[0xFF0], 3);
        if (RAM[0x85] != 0) { native_9E42(); RAM[0x85] = 0; }
        native_A352(); native_8208(); native_ui_5018(); native_A352();
        native_8ED2(/* model 0x01B1 */);
    }
}

// [N-clock] Exact arithmetic kernel, 0x7124..0x7176; later bookkeeping omitted.
void original_tick_kernel(void) {
    u16 sampled = native_timer_read_A00E();
    u16 delta = sampled - RAM16[0x115];
    u16 elapsed = 0, divisor = RAM16[0x11D];
    while (delta > divisor) { ++elapsed; delta -= divisor; }
    if (elapsed == 0) return;
    RAM16[0x115] = sampled; // drops remainder, not previous += elapsed*divisor
    RAM16[0x11B] += elapsed; // full 16-bit wrap; no 0x7FFF mask here
    // Encoded deadline path A2D0 -> 8B8C -> A8DA is a separate interface.
    // Nominal 1 kHz design is inferred; counts are not calibrated milliseconds.
}

// [N-keys] Exact history kernel at 0x8E62; event machine stays explicit boundary.
u8 original_history_push(u8 old, u8 sample) {
    return (old & 0x80) | (((old << 1) | (sample == 1)) & 0x7F);
}
void original_key_boundaries(void) {
    native_raw_sample_4D44(); // eleven 4-byte objects 0x0272 + 4*i
    // 0x4EB6 -> 0x846A schedules next sample after 5 native counts.
    Key *key = RAM + 0x0272 + 4 * RAM[0x78]; // round-robin 0x9BA6
    native_event_machine_4ECC(key);
    RAM[0x78] = (RAM[0x78] + 1) % 11;
    // Observed FSM: last 3 samples gate press/release; hold thresholds 250/650.
    // Press: 7DB0 -> 55EC when RAM4D == 0 (ordinary application).
    // Release: 7F18 -> 8630; PLUS/MINUS sends +1/-1 to 7E0A.
    // Held: 9BCA -> 6786; PLUS/MINUS sends +10/-10 to 7E0A.
    // MODE, CHANNEL, A, B, C, MODEL, HEAD, +, -, TEST, extra PORTE.1 input.
    // Last input's physical user-facing role is not established.
}

// [N-ui] Original three-group semantics; helper internals intentionally opaque.
void original_select_group(u8 requested) { // 0x946E -> 0x5986
    // requested is A=1/B=2/C=3. Pressing selected group selects ALL=7.
    if (native_mode_9010() == 1) native_deadline_9EEC_to_56D4();
    u8 selected = (requested == RAM[0x60]) ? 7 : requested;
    native_group_apply_5986(selected); // stores 60, rebinds callbacks, sets LCD
}
void original_numeric_refresh(void) { // 0x6928
    Model *model = RAM16[0x49]; // normally 0x01B1; mode[0]: TTL=0, MAN=1
    u8 rows[3] = {0x89, 0x8B, 0x8D};
    for (u8 group = 0; group < 3; ++group) {
        s8 value = model[0] == 0 ? model[4 + group] : RAM[0x99 + group];
        native_signed_tenths_6F44(/* LCD=0x88, row=rows[group], value */);
    }
    // Compact value-selection sketch: native visibility/selection side effects
    // and HEAD-off branches are omitted; this is not a replacement renderer.
    // Original HEAD RAM4C / MODEL RAM50 use low three group bits.
    // Original 7B88 mode toggle includes radio effects; not just a mode write.
    // 9BEE serializes native LCD shadow 88..92 through 8BCA/9F0E.
}

// [N-radio] Original queue abstraction; normal foreground record, not an ACK.
bool original_enqueue16(u8 bank0_source) { // 0x9D54
    // Descriptor 93..98: write, read, count, capacity, pointer low/high.
    // Original backing 0400..0463, capacity 100; RAM18 holds source low byte.
    if (!native_space_8DB2(16)) return false; // count <=83 admits marker+16
    native_queue_byte_A80C(0);
    native_append_7BE4(bank0_source, 16);
    return true; // local admission only; no receiver/lamp acknowledgement
}
void original_relative_command(u8 group, s8 step) { // 0x6ECC
    if (RAM[0x4B] != 0) return; // observed radio gate, not the mode byte
    u8 command;
    switch (step) {
    case +1: command = 0x06; break; case -1: command = 0x07; break;
    case +10: command = 0x0D; break; case -10: command = 0x0E; break;
    default: command = 0; break; // original unmatched-step fallthrough
    }
    native_relative_frame_and_submit(group, command); // 8FB0 -> 9D54
    native_A68C(); // original tail6F1E -> A68C ->8A14; extra queue side effect
    // 5BE6 services the native transport; normal 5E34 path emits RSGT1+frame16.
    // Separate 7A12 path sends original ABC FEC command 0x25.
}

// [N-nvm] Recovered descriptor and flash primitives; journal policy is opaque.
void original_nvm_boundaries(void) {
    // 6088..609E -> 7FC4 constructs descriptor at RAM01C3:
    // end=0x01FBFF; width=4; constructor rounds odd widths up to even.
    native_journal_policy_unknown(); // slot scan/commit/recovery not reconstructed
    // Word helper 91C2: address RAM1F:20:21, two bytes RAM23:24,
    // TBLWT*+/TBLWT*, WPROG/WREN, 9B2E, 55/AA unlock, WR.
    // Erase helper 9B0E: address RAM0D:0E:0F, FREE/WREN, same unlock.
    // 9B2E clears FD0.7 and FF2.7; both helpers unconditionally set these
    // bits on return. This is NOT restoration of the prior interrupt state.
    // Original logical journal [1F800,1FC00); no new persistence format here.
}

// [N-hss] Observed timing/camera boundaries, NOT a complete HSS algorithm.
void original_camera_and_timing_boundaries(void) {
    native_irq_4108(); // marker53.bit1, FSR1/2 save/restore, RETFIE FAST at end
    // Other observed boundaries: 5D74 camera state, 65C2 camera transmitter,
    // 6CD0 camera helper, A77A RX queue dispatch; see source_map.json.
    // 9A02 pulls PORTB.3 low; A0AE samples timer until unsigned delta >= E1;
    // then PORTB.3 is high. E1's physical unit/calibration is not established.
    // These are address/call and instruction observations. Full HSS protocol,
    // transitive semantics, exposure correctness and hardware timing are unknown.
}
