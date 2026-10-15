/* Fujifilm A5 STOCK; explanatory pseudocode, not a flashing implementation.
 * No updater, hardware or flash write was executed for this publication.
 */

void startup_outline(void) {
    native_data_init_5F6E();                  /* through RAM 0x067F */
    native_main_init_4C3A();                  /* camera/radio/UI setup */
    /* Original loop 4D84..4DC6 calls clock, camera/radio and 596E UI.
     * RAM[085] is a latched camera/external-IRQ wake request, not TX count.
     * 4DA4..4DAC consumes it via 9524, then clears it.
     */
    native_main_loop_4D84();
}

/* VERIFIED 9BAC..9BDE. Original explicitly clears then unconditionally
 * sets FD0.7 and FF2.7. It DOES NOT save/restore their previous values.
 * Addresses are retained instead of assuming an unverified MCU SFR map.
 */
void original_flash_word_write(void) {
    TBLPTR = bytes(C2, C3, C4);
    TABLAT = C6; table_write_postincrement();
    TABLAT = C7; table_write_current();
    set_bit(0xFA6, 5); set_bit(0xFA6, 2);
    clear_bit(0xFD0, 7); clear_bit(0xFF2, 7); /* helper A3FE */
    SFR[0xFA7] = 0x55; SFR[0xFA7] = 0xaa;
    set_bit(0xFA6, 1);
    set_bit(0xFD0, 7); set_bit(0xFF2, 7);    /* 9BD4 / 9BD6 */
    clear_bit(0xFA6, 5); clear_bit(0xFA6, 2);
}

/* VERIFIED A3DE..A404: native erase uses the same clear/unlock/start/
 * unconditional-enable pattern. Keep data/control setup opaque here.
 */
void original_erase_outline(void) {
    native_erase_pointer_and_control_setup_A3DE();
    clear_bit(0xFD0, 7); clear_bit(0xFF2, 7);
    SFR[0xFA7] = 0x55; SFR[0xFA7] = 0xaa;
    set_bit(0xFA6, 1);
    set_bit(0xFD0, 7); set_bit(0xFF2, 7);
}

/* VERIFIED descriptor construction 6AAC..6AC2 -> 8868 has end1FBFF,
 * record width4. This observation alone does not establish erase geometry
 * or safe ownership of apparently blank flash. RAM600..67F is initialized
 * but its complete purpose is not established here.
 * IRQ4108..41C4 has no TBLPTR/TABLAT or NVM-control touch within its
 * audited closure and initialized-pointer assumptions; bootloader unknown.
 * 开发版保存中断位、独立新日志等方案不属于这里的原厂结论。 */
