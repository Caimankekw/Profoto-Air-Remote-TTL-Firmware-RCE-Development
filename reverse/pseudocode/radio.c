/* Fujifilm A5 stock C-like pseudocode. Read-only reverse engineering.
 * 原厂队列行为；不是 AIR2 新命令实现，也不代表 RF/灯具确认。
 */

unsigned radio_type_B2CE(void) { return 2; }   /* VERIFIED RETLW 2 */
unsigned body_length_A6DC(void) { return 16; } /* selected by native type 2 */

/* VERIFIED 0x9562..0x95A0 native admission rule. TX descriptor 0x0092,
 * offsets: write0/read1/count2/capacity3/bufferLE16=4; capacity100,
 * buffer0x0500. Use ordinary arithmetic to express the decoded comparison.
 */
bool native_space(unsigned requested) {
    return requested <= 31 && RAM[0x094] + requested < 100;
}

/* VERIFIED 0xA60A..0xA62E actually requests BODY length 16, then writes
 * marker 0 plus 16 body bytes. Do not replace 16 with an AIR2 17-byte
 * preflight here: count83 passes this original test (83+16<100).
 */
bool enqueue_native_packet(uint8 *body) {
    unsigned n = body_length_A6DC();
    if (!native_space(n)) return false;       /* exact native n=16 */
    native_append_AF7C(0);                    /* marker byte */
    native_copy_packet_84D6(body);            /* 16 bytes for type2 */
    return true;
}

/* VERIFIED 99FE..9A36 builds {dest,FF,FF,FF,payload[12]}.
 * 8594..85EA chooses RSGT1/RSGT5; fixed type2 chooses RSGT1.
 * 84D6 contains a legacy-type0 XOR branch; do not apply it to type2.
 */
void wrap_destination(uint8 dest, uint8 payload[12]) {
    uint8 body[16] = {dest, 0xff, 0xff, 0xff, payload[0..11]};
    enqueue_native_packet(body);
}

/* VERIFIED two different original command families. */
void group_relative_7174(uint8 group, int8 step) {
    if (RAM[0x028] != 0) return;
    opcode = lookup(step, {+1:0x06, -1:0x07, +10:0x0d, -10:0x0e}, default=0);
    native_command_build_and_send_7174(group, opcode);
}
void alternate_step_864C(uint8 group, int8 step) {
    if (RAM[0x028] != 0) return;
    opcode = lookup(step, {+1:0x04, -1:0x05, +10:0x0b, -10:0x0c}, default=0);
    native_command_build_and_send_864C(group, opcode);
}

/* VERIFIED AA10 enters command inhibition; 9524 clears it.
 * Inference: sleep/suspend lifecycle is suggested by wake handling.
 * UNKNOWN: electrical radio power state and RF execution acknowledgement.
 * IRQ RX producer 41AC -> AFB2 -> 75C8 targets 01A5/0480/capacity50;
 * the audited IRQ callgraph has no TX producer. Assumes valid objects.
 */
