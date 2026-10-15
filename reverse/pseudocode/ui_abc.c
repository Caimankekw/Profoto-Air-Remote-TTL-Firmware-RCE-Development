/* Fujifilm A5 STOCK: explanatory C-like pseudocode, not compilable firmware.
 * 原厂只有 A/B/C 三组和 ALL；这里没有 AIR2 的 D/E/F 或绝对功率 UI。
 */

/* VERIFIED 0x9EBE -> 0x6492. Selection 1=A, 2=B, 3=C, 7=ALL. */
void select_key(unsigned requested) {
    unsigned next = (RAM[0x060] == requested) ? 7 : requested;
    native_select_6492(next);
    /* 6492 stores 060 and rebinds MODEL 063..065, HEAD 066..068,
     * power 069..06B and mode-dependent power-setup 06C..06E. */
}

/* VERIFIED 0x7ED4..0x7F40; synopsis, not complete bookkeeping. */
void mode_toggle_synopsis(uint8 request) {
    uint8 *config = pointer_at_RAM_22_23();     /* startup target 0x018C */
    RAM[0x0E3] = request;                     /* original W argument */
    config[0] = config[0] == 1 ? 0 : 1;
    /* Established encoding: 0 = TTL, 1 = MAN. */
    RAM[0x061] = 0;
    native_transient_timer_updates_B024_A786_5F64();
    native_indirect_mode_callback_at_06C();
    if (request == 0) RAM[0x07B] = 1;         /* 7F38..7F3C */
    else if (config[0] == 0) native_ttl_followup_7F40();
    native_refresh_9C74();
}

/* VERIFIED 0x8D7E..0x8DC8. Input W is a signed byte; stored at 0x0E2.
 * This is callback dispatch, not a six-group or absolute-power command. */
void power_step(int8 step) {
    RAM[0x0E2] = step;
    uint8 initial_mode = native_mode_569A(); /* mode tested before callback */
    native_indirect_power_callback_at_069();
    if (initial_mode != 0)                   /* legal MAN value is 1 */
        RAM[0x061] += step;                  /* pending manual aggregate */
    else if (RAM[0x060] != 7)
        native_ttl_followup_7F40();
}
/* Original state: FEC at config+4/+5/+6 (0190..0192),
 * manual relative at 002F..0031, Head mask 0029, Model mask 0038.
 * 96D0 is the signed clamp helper; retain signed-byte add/clamp ordering.
 */

/* VERIFIED 0xA6BA..0xA6D2. Preserve the existing destination bit 7. */
void glyph_write(uint8 destination, uint8 glyph_index) {
    RAM[destination] = (RAM[destination] & 0x80)
        | native_glyph_table(glyph_index);   /* original has no extra &7F */
}

/* VERIFIED interfaces, with formatter internals deliberately opaque. */
void render_native_row(uint8 row, int8 value) {
    /* 7AD2: B4=0x87 flag byte, B5=row (88/8A/8C), B6=signed tenths.
     * Negative conversion mutates B6. 6E7E writes sign markers.
     * 8F7E gates visibility, including the native MAN expiry path.
     * AFE4 blank and AFD4 Head OFF remain distinct native helpers.
     */
    native_row_gate_8F7E(row, value);
}

/* INFERRED: UI names follow callback/display semantics.
 * UNKNOWN: all display segment-to-physical-LCD labels and hardware behavior.
 * 本文件不把开发版六组、绝对值显示或新超时规则当作原厂功能。 */
