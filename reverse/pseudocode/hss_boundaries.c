/* Fujifilm A5 camera/HSS boundary map ONLY. 原厂相机/HSS 调用边界。
 * This is NOT a recovered full HSS algorithm, timing model or camera driver.
 * Native routines below are intentionally opaque. Not compilable firmware.
 */

void original_irq_boundary_4108(void) {        /* [4108,41C4) */
    native_save_FSR_context_to_01B_01E();
    native_irq_flag_dispatch();
    /* Camera path reaches [5D42,5E6A); foreground uses [614C,62F4).
     * 4150 -> 83B4 -> 8410 -> AE22 publishes RAM03B to RAM0FE.
     * 41AC -> AFB2 -> 75C8 produces RX ring01A5, not TX ring0092.
     */
    native_restore_FSR_context();
    native_retfie();
}

void original_camera_irq_5D42(void) {
    /* VERIFIED boundary [5D42,5E6A); initial command acceptance requires
     * native camera state1. Exact electrical protocol/timing remains opaque.
     */
    opaque_original_camera_irq_body();
}

void original_camera_foreground_614C(void) {
    /* VERIFIED boundary [614C,62F4), not a complete HSS reconstruction. */
    opaque_original_camera_foreground_body();
}

/* Evidence: F_A5_clock_irq_evidence.json: IRQ closure1238 instructions,
 * camera subgraph761; no reach to TX producers AF7C/7540/A60A/84D6 or
 * clock update7050. Reachability depends on pinned code and decoder.
 * UNKNOWN: complete HSS state machine, oscillator timing, RF airtime,
 * lamp output and operation on a physical Fujifilm camera.
 * 没有借用 Canon HSS 或 AIR2 的实现填补未知算法。 */
