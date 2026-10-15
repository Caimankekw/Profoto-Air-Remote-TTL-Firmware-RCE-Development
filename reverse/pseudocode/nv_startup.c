/* Olympus A4 STOCK startup/journal outline. Not compilable or a flash API.
 * 原厂启动与持久化说明；没有运行更新器、USB 或擦写操作。 */

void startup_outline(void) {
    native_data_init_69CA();                  /* [69CA,6A62) */
    /* copies835C->026F..02C2, AB56->01F1..01F9;
     * clears0300..0363,0200..026E,0100..01CD,0060..00B6,0024..0040. */
    native_journal_restore_5E1C();             /* call5796 */
    native_config_init_5520();                /* call57AA, ptr07E:07F=0199 */
    native_main_loop_57C0();
}

/* VERIFIED original four-byte journal at1F800..1FBFF:
 * descriptor1AB..1B1 starts ff fb 01 00 00 00 04; 8-bit index0..255.
 * end(index)=1FBFF-4*index; words written at end-remaining+1 (4 then2).
 * The erase target1FBFF alone does NOT prove a1024-byte erase geometry.
 */
void unpack_original_record(uint32 packed) {  /* 5EB0 -> A66C */
    config[4] = extract_bits(packed, 0, 6) - 20;
    config[5] = extract_bits(packed, 6, 6) - 20;
    config[6] = extract_bits(packed, 12, 6) - 20;
    config[0] = extract_bits(packed, 18, 1);
    config[2] = extract_bits(packed, 19, 2);
    /* Restore precedes5520 and does not call mode-toggle6A62. */
}

/* VERIFIED962C..965E: C3:C4:C5 pointer, C7:C8 data.
 * 9E3A clears FD0.7/FF2.7; original write AND erase unconditionally
 * enable both afterwards. They do not restore previous enable states.
 */
void original_word_write_outline(void) {
    TBLPTR = bytes(C3, C4, C5);
    TABLAT = C7; table_write_postincrement();
    TABLAT = C8; table_write_current();
    native_write_control_setup_962C();
    clear_bit(0xFD0, 7); clear_bit(0xFF2, 7);
    native_unlock_55_AA_and_start_write();
    set_bit(0xFD0, 7); set_bit(0xFF2, 7);
    native_write_control_cleanup();
}
/* 9E1A erase uses pointer01E..020 and the same unconditional-enable
 * policy. 54B2 ->962C is the direct word-write call;53DA ->9E1A erase.
 * Original boot558C..559E arms085 according to native mode;5946..5962
 * tests readiness ABB0 then sends7B14 if085 is set and clears085.
 * AIR2 post-boot mode projection and new journal are separate development.
 * UNKNOWN: bootloader flash ownership and actual erase/stall geometry. */
