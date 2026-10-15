/* Olympus A4 stock radio C-like pseudocode. Not a transmit utility.
 * 原厂字节队列与帧边界；不表示 RF 或灯具执行确认。 */

unsigned radio_type_ABD8(void) { return 2; }   /* VERIFIED RETLW2 */
unsigned body_length_9F8A(void) { return 16; }

/* VERIFIED 919E..91DA. TX descriptor0095, buffer0300, capacity100.
 * Descriptor layout write/read/count/capacity/bufferLE16.
 */
bool native_admission(unsigned requested) {
    return requested <= 31 && RAM[0x097] + requested < 100;
}

/* VERIFIED9F1E..9F42; BC is packet pointer low byte (packetC1..D0).
 * Original asks for16, then inserts marker0 +16 body bytes. A separate
 * requested17 preflight is an AIR2 change, not this original code.
 */
bool enqueue_packet(uint8 *packet) {
    if (!native_admission(body_length_9F8A())) return false;
    native_ring_append_marker_zero();
    native_copy_original_body(packet, 16);
    return true;
}
void wrap_destination(uint8 dest, uint8 payload[12]) { /* 936C..93A4 */
    uint8 packet[16] = {dest, 0xff, 0xff, 0xff, payload[0..11]};
    enqueue_packet(packet);
}

/* VERIFIED82B0..8306: BC:BD output pointer receives native RSGT1 or
 * RSGT5 prefix, then advances5; fixed type2 selects RSGT1.
 * Native8FBA constructor arguments:1E:1F descriptor,20:21 buffer,
 * 22 capacity. TX0095/buf0300/cap100; RX01B2/buf0215/cap50.
 * IRQ A8EC ->719A produces RX bytes0215..0246.
 * Separate camera packet buffer0247..026E uses cursor0089.
 * UNKNOWN: complete radio air protocol, reply/ack semantics and RF timing.
 * No new command11, six-group admission or scheduler is reconstructed here.
 */
