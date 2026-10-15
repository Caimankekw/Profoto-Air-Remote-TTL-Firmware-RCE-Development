/* Olympus A4 STOCK three-group UI. Explanatory pseudocode, not firmware.
 * 三组 A/B/C + ALL 原厂界面；未引入 AIR2 六组或绝对功率显示。
 */

void group_key(unsigned requested) {          /* 98D8 -> 609A */
    unsigned selection = RAM[0x060] == requested ? 7 : requested;
    native_select_609A(selection);
    /* 060 stores1/2/3/7; pointers063..065 MODEL,066..068 HEAD,
     * 069..06B power,06C..06E mode-dependent power-setup.
     */
}

/* VERIFIED native 6A62..6AF2. No temporary radio-inhibit manipulation
 * is added here: that is an AIR2 adapter strategy, not stock behavior. */
void native_mode_synopsis(void) {
    uint8 *config = pointer_at_RAM_07E_07F();  /* startup0199 */
    if (RAM[0x081] != 0) config[0] = 1;
    else config[0] = config[0] == 1 ? 0 : 1; /* 0 TTL, 1 MAN */
    RAM[0x061] = 0;
    native_mode_timer_and_callback_updates_6A62();
    native_mode_redraw_9A48();
}
/* Normal MODE press5C12 with081!=0 instead goes to A4F4.
 * Selection mode callbacks: A9B54/B9B28/C9AFC/ALL9B80.
 * Mode0 power: 8A4C/814E/8BAA/ABC0(return stub).
 * Mode1 power: 90AE/9072/9036/6930(all three).
 */

void native_step_86D6(int8 delta) {
    RAM[0x0EA] = delta;
    native_indirect_power_callback_at_069();
    /* Mode0: enabled group adds delta then clamps config+4/+5/+6
     * (019D..019F) to -20..20 with90EA. Mode1: enabled group adds then
     * clamps relative036..038 to -99..99 via69BC ->90EA.
     * Head enable mask02C and Model bits03F are distinct fields. */
    if (native_mode_5666() == 1) RAM[0x061] += delta;
    else if (RAM[0x060] != 7) native_ttl_followup_7B14();
}

void glyph_write(uint8 destination, uint8 glyph_index) { /* A10E..A130 */
    RAM[destination] = (RAM[destination] & 0x80)
        | (native_glyph_table(glyph_index) & 0x7f);
}
void native_row_outline(uint8 row, int8 value) {
    /* 742E: B7=8A flags; B8=row8B/8D/8F; B9=signed value.
     * 688E sign:1E=8A,1F=row,20=0minus/1plus/2none.
     * 94E6 clears row bit7 (decimal); A91E blank; A90E dashes.
     * 876E row gate includes native MAN visibility rules.
     */
    native_row_gate_876E(row, value);
}

/* VERIFIED native7F7E expiry is MAN-only:87B2 ->732C checks AD:AE;
 * expiry clears manual-relative state, 7FBE calls6C24 redraw, then AA38
 * disarms. Extending this expiry to TTL belongs to AIR2, not stock.
 * INFERRED: physical UI labels and delta unit (do not assert0.1EV here).
 * UNKNOWN: every physical LCD segment/label and non-normal UI state. */
