/* Olympus A4 stock explanatory C-like pseudocode; not compilable firmware.
 * 原厂逆向说明，不是厂家完整 C 源码。地址为程序字节地址。
 * VERIFIED = decoded original instructions; physical time unit unknown.
 */

void sample_history(KeyObject *key, unsigned input) { /* 92FC..932A */
    key->history = (key->history & 0x80)
        | (((key->history << 1) | (input == 1)) & 0x7f);
}
void sample_keys_5036(void) {
    if (native_timer_732C(RAM + 0x00AF) == 0) return;
    native_sample_all_12_slots_5036(); /* 0100+4*i; 92FC appends each sample */
    native_rearm_scan_timer_8846();
}
void poll_one_9DF4(void) {
    KeyObject *key = RAM + 0x0100 + 4 * RAM[0x080];
    event_596E(key);
    RAM[0x080] = (RAM[0x080] + 1) % 12;
}

/* VERIFIED 596E..5A8E, summarized flag behavior, not instruction-for-
 * instruction ordering. +0 history, +1 flags, +2/+3 saved timestamp.
 */
void event_596E(KeyObject *key) {
    if (key->history == 0xff) {
        unsigned dt = native_elapsed_98AA(&key->timestamp);
        if (dt >= 250 && !key->flag5 && !key->flag1) {
            key->flag1 = 1; native_return_stub_ABC2();
        }
        if (dt >= 650 && !key->flag5 && !key->flag6 && !key->flag2) {
            key->flag2 = 1; native_hold_dispatch_9ED6(key);
        }
    }
    if (!(key->history & 0x80) && (key->history & 7) == 7) {
        key->flag3 = 0;
        if (!key->flag0) {
            key->timestamp = native_timestamp_A4DA();
            key->flag0 = 1; native_press_dispatch_80F4(key);
        }
        key->history |= 0x80;
    }
    if ((key->history & 0x80) && (key->history & 7) == 0) {
        if (!key->flag3 && !key->flag4) {
            key->flag3 = 1; native_release_dispatch_83B0(key);
        }
        key->flags = 0x08; key->timestamp = 0; key->history = 0;
    }
}
/* 9934 rearm: flags=(flags&0xBB)|0x80, rewrite timestamp.
 * 9ED6 invokes this rearm before normal hold dispatch6DD0.
 * Short +/-87BA ->86D6 uses +/-1; held6DD0 uses +/-10 and suppresses
 * the release's extra step. 250/650 are native COUNTS, not milliseconds.
 */

uint16 normalized_now(void) { /* A4DA -> AB2E; 8E00 -> AA52 */
    uint16 t = RAM16[0x075] & 0x7fff;
    return t ? t : 1;
}
uint16 elapsed_outline(uint16 *saved) {       /* 98AA -> 669C */
    if (*saved == 0) return 0;
    if (*saved & 0x8000) return 0xffff;
    uint16 delta = (normalized_now() - *saved) & 0x7fff;
    if (delta >= 24001)
        native_possible_coarse_sentinel_6708(saved); /* may set bit15 */
    return delta; /* current call returns delta; later marked call FFFF */
}

/* INFERRED: key labels from handler semantics. UNKNOWN: physical clock,
 * all flag5/flag6 writers, non-normal UI and analog multi-key aliasing.
 * 本模块不补入 AIR2 组合键延迟或新事件消费逻辑。 */
