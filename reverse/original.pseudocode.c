/* Air Remote TTL-S A6: bounded ORIGINAL firmware reconstruction.
 * Human-written C-like notes, not manufacturer's complete C source.
 * NOT COMPILABLE, NOT FLASHABLE. RAM/ROM and native_* are notation only.
 * PIC18 byte addresses; source_map.json pins stock ranges and evidence.
 * Exact kernels are labelled; opaque calls deliberately retain unknown work.
 * 原厂有限范围伪代码；非厂家完整源码，不能编译或刷写。
 */

// [S-boot] Observed control flow; initialization internals stay opaque.
void original_boot_and_loop(void) {
    // 4102 -> 4252 -> 6174; then original board/object initialization 4D42.
    native_runtime_init_6174(); // ROM copy and zero fill; source_map RAM evidence
    native_board_objects_4D42();
    for (;;) {                 // 0x4E94..0x4ED2
        CLRWDT();
        native_clock_6972(); native_arguments_4ED2(); native_camera_6BB0();
        native_radio_service_A586(); native_85AC();
        native_clock_6972(); native_arguments_4ED2(); native_camera_6BB0();
        if (RAM[0x48] != 0) { native_exclusive_exit_93BC(); RAM[0x48] = 0; }
        native_radio_service_A586(); native_ui_51DE();
        native_954E(/* config 0x0193 */);
    }
}

// [S-clock] Exact arithmetic kernel 6972..69DA; later bookkeeping omitted.
void original_tick_kernel(void) {
    u16 sampled = native_timer_read_A20C();
    u16 delta = sampled - RAM16[0x100];
    u16 elapsed = 0, divisor = RAM16[0x108];
    while (delta > divisor) { ++elapsed; delta -= divisor; }
    if (elapsed == 0) return;
    RAM16[0x100] = sampled; // residual delta is discarded
    RAM16[0x106] += elapsed; // full 16-bit addition, 69CC..69D8
    // A710 is a separate getter/deadline boundary; no physical ms calibration.
}

// [S-keys] Exact history kernel 930E; full event machine remains a boundary.
u8 original_history_push(u8 old, u8 sample) {
    return ((old << 1) & 0x7F) | (old & 0x80) | (sample == 1);
}
void original_key_boundaries(void) {
    native_raw_sample_4EE2();
    // Eleven 4-byte objects:115,119,11D,121,125,129,12D,131,135,139,13D.
    // A0C8 chooses the next object; 2A4:2A5 points to it before 5348.
    native_round_robin_A0C8();
    // 5348 requires three matching samples for press/release.
    // 250-count callback AF5A is RETURN; 650-count path A134 -> 6A96.
    // Press 80F2 -> 8116 -> 595A enters ordinary application only if DD==0.
    // Release 85FE -> 8782 and long handler 6A96 have no C/MODEL/HEAD action.
    // + / - give signed +1/-1 or +10/-10 to 87CC, then selected callbacks.
    // DC changes MODE paths; its user-facing meaning is not fully identified.
    // Threshold evidence does not reconstruct the repeating long-hold schedule.
}

// [S-ui] Original A/B/C and ALL selection, not six independent groups.
void original_group_boundary(u8 selector) { // 5CD8
    // selector A=1/B=2/C=3/ALL=7 stored at C1; callbacks C4..CF rebound.
    native_set_group_and_handlers_5CD8(selector);
    // Original ALL helper 814C clears selection boxes.
}
void original_numeric_refresh(void) { // 6DDE
    Model *model = RAM16[0xD2]; // bound to 0193 by 5068; TTL=0, MAN=1
    u8 rows[3] = {0x4A, 0x4C, 0x4E};
    for (u8 group = 0; group < 3; ++group) {
        s8 value = model[0] == 0 ? RAM[0x197 + group] : RAM[0xEC + group];
        native_signed_tenths_7584(/* buffer=49, row=rows[group], value */);
    }
    // Value-selection sketch; native HEAD-off/visibility paths are omitted.
    // Original ranges in tenths: FEC[-20,20], MAN-relative[-99,99].
    // HEAD DB and MODEL F3 use low three bits; 97D8 renders repeated glyphs.
    // UI51DE snapshots LCD49..53 into2A7..2B1; compare52F0, dirty52FE->AEB2,
    // and 5318->9E80 serial transfer. Snapshot also includes nonnumeric fields.
}

// [S-radio] Original frame builder/queue, excluding additional development code.
bool original_enqueue16(u8 bank0_source) { // A158, source low byte in RAM076
    // E6..EB=(write,read,count,capacity,pointer-low,pointer-high).
    // 668A initialization: capacity100, backing0400..0463.
    if (!native_space_8F84(16)) return false; // marker+16: count<=83
    native_queue_marker_AB66(0);
    native_append_7E02(bank0_source, 16);
    return true; // local queue acceptance, not a receiver acknowledgement
}
void original_relative_command(u8 group, s8 step) { // 7490
    if (RAM[0xD8] != 0) return; // original exclusive-radio gate only
    u8 command;
    switch (step) {
    case +1: command = 0x06; break; case -1: command = 0x07; break;
    case +10: command = 0x0D; break; case -10: command = 0x0E; break;
    default: command = 0; break; // original unmatched-step fallthrough
    }
    u8 payload12[] = {1, command, group, 0,0,0,0,0,0,0,0,0};
    // 9516 builds [group,FF,FF,FF,payload12] at7B..8A, calls A158.
    native_frame_builder_9516(group, payload12);
    native_A960(); // original tail74E4 -> A960 ->8E8A; extra queue side effect
    // 5C08 consumer -> 5DA4: normal marker0 emits RSGT1 + frame16 (21 bytes).
    // AF70 literally returns2; 7FDC chooses RSGT1 and A2DE returns16.
    // A158 has no interrupt lock. ISR also reaches producer AC84 and abort A906;
    // this pseudocode does not assert that a multi-byte queue record is atomic.
}

// [S-nvm] Exact logical address arithmetic; complete journal policy not recovered.
u24 original_slot_last_byte(u8 index) { // 81A6, descriptor initialized by 835E
    // Original descriptor RAM1A5..1AB: end1FBFF, 0 slot-count byte=256, width4.
    return 0x01FBFF - (u24)index * 4;
    // Derived first byte = returned last byte - 3 for the original width4.
    // index0 first=1FBFC; index255 first=1F800; 81A6 returns the LAST byte.
}
void original_nvm_boundaries(void) {
    native_journal_scan_commit_recovery_unknown();
    // Logical journal[1F800,1FC00), not proof of physical erase geometry.
    // 9840 writes a flash word; 9FE4 erases; both unconditionally set
    // FD0.7 and FF2.7 on return, rather than restoring their prior states.
}

// [S-hss] Observed camera/ISR paths, not complete HSS algorithm semantics.
void original_camera_boundaries(void) {
    native_irq_4108(); // restoration4226..424A; RETFIE FAST4250
    // Direct-flow producer chain:
    // 414E ->7842 ->78B0 ->5B34 ->5BE8 ->5858 ->589A ->7D9E ->90BA ->AC84.
    // Observed guards include RAM194=0,RAM56=1, timer interval361..449,
    // pointer3E:3F=025F, packet0215[7].bit7=1 and packet[10].bit7=0.
    // ISR direct-flow audit reaches producers90BA/AC84 and abortA906/7002;
    // it does not reach queue consumers5C08/5DA4/7296 in that bounded closure.
    // Unknown: full protocol semantics, physical HSS pulse/exposure correctness,
    // and arbitrary indirect/runtime behavior. This is not a hardware proof.
}
