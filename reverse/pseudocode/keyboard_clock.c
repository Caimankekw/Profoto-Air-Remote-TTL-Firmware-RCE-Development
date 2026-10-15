/* Fujifilm A5 stock reverse engineering; C-like explanatory pseudocode.
 * 原厂行为的说明性伪代码；不是厂家完整 C 源码，不可编译为固件。
 * Byte addresses; half-open evidence windows are in ../provenance.json.
 * VERIFIED = decoded original instructions. Opaque calls retain unknown work.
 */

/* VERIFIED 0x97C0: object pointer B0:B1, boolean input B2. */
void history_append(KeyObject *key, unsigned input) {
    key->history = (key->history & 0x80)
        | (((key->history << 1) | (input == 1)) & 0x7f);
}

/* VERIFIED 0x48EA samples all 12 four-byte objects at 0x010A..0x0139.
 * Physical key names below are semantic labels, not a hardware key test.
 * MODE 010A, SYNC 010E, CHANNEL 0112, A/B/C 0116/011A/011E,
 * MODEL 0122, HEAD 0126, PLUS 012A, MINUS 012E, TEST 0132, AUX 0136.
 */
void key_poll_one(void) {                     /* 0xA50E..0xA532 */
    KeyObject *key = RAM + 0x010A + 4 * RAM[0x078];
    native_key_state_machine_581A(key);       /* 0x581A..0x596E */
    RAM[0x078] = (RAM[0x078] + 1) % 12;
}

/* VERIFIED normal callbacks, not a new keyboard implementation. */
void normal_release(KeyObject *key) {         /* 0x8D34..0x8D7E */
    if (key == RAM + 0x012A) native_power_8D7E(+1);
    if (key == RAM + 0x012E) native_power_8D7E(-1);
}
void normal_hold(KeyObject *key) {            /* 0x70E6..0x716A */
    if (key == RAM + 0x012A) native_power_8D7E(+10);
    if (key == RAM + 0x012E) native_power_8D7E(-10);
    /* Other native hold work is omitted; this is not the full handler. */
}

/* VERIFIED 0x7050..0x70E6. Native counts, NOT established milliseconds.
 * Unsigned 16-bit arithmetic; strictly > divider, not >=.
 * The original drops the residual fraction when it advances prev_sample.
 */
void update_native_clock(void) {
    uint16 sample = read_counter_F23_F24();
    uint16 elapsed = sample - RAM16[0x100];
    uint16 n = 0;
    while (elapsed > RAM16[0x108]) {
        elapsed -= RAM16[0x108];
        ++n;
    }
    if (n == 0) return;
    RAM16[0x100] = sample;
    RAM16[0x106] += n;
    if ((uint16)(RAM16[0x106] - RAM16[0x102]) >= 1001) {
        RAM16[0x102] = RAM16[0x106];
        ++RAM16[0x104];
    }
}
/* 4D16 -> AF34 -> 99C6: W=0x30 chooses divider 1500;
 * 99C6 with W=0x10 chooses 4000. These do not prove oscillator frequency. */
uint16 raw_tick_B202(void) { return RAM16[0x106]; }
uint16 timestamp_AB22(void) {
    uint16 t = raw_tick_B202() & 0x7fff;
    return t == 0 ? 1 : t;
}

/* UNKNOWN here: complete 581A flags/timer paths, analog multi-key aliasing,
 * physical clock frequency and full non-normal UI event behavior.
 * 未在此重建完整按键状态机、模拟多键组合或实际时间单位。 */
