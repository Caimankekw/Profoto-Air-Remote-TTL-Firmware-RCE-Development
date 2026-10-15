/* Olympus A4 original camera/IRQ boundaries ONLY.
 * 只陈述已核调用边界；不是完整 HSS 曝光算法、时间模型或可编译固件。
 */

void original_irq_4108(void) {                 /* [4108,4178) */
    native_save_FSR1_FSR2_to_01A_01D();
    native_phase_and_radio_dispatch();
    /* 4122 checks phase019A. Phase1: AB38 pulse path, clear019A,
     * set native B1 timer; alternate path stores3.
     * Camera IRQ call415E ->67E8; RX A8EC ->719A targets01B2.
     */
    native_restore_FSR1_FSR2_4164();
    native_retfie_fast_4176();
}

void camera_receive_outline_67E8(void) {       /* [67E8,688E) */
    /* State0040=1 waits for RX. First byte55 ->state2;
     * second byte ->state3. Cursor0089 addresses0247..026E.
     * Main4FEA dispatches native states3/4/5/8.
     */
    opaque_original_camera_receive_body();
}

void camera_mode_request_outline(void) {
    /* 466A..4688 inspects packet+8 low7bits==8 ->8A92(1), sets081
     * and armsA1. 75AC with native TTL sets02D, arms9F, calls6A62 to
     * force MAN. Later8A92(0), if02D!=0, calls6A62 to restore TTL.
     * 4E22..4E42 clears019A on native timeout.
     */
    opaque_original_camera_mode_lifecycle();
}

/* VERIFIED audited original IRQ closure392 instructions, no dynamic
 * dispatch. FSR1/2 saved, no FSR0/PROD/TBLPTR/TABLAT modification in
 * that closure under initialized descriptor/pointer assumptions.
 * UNKNOWN: bootloader, unproven interrupt nesting, exact camera electrical
 * timing, full HSS state machine and physical flash/camera performance.
 * No Canon HSS or AIR2 implementation is substituted for unknown behavior.
 */
