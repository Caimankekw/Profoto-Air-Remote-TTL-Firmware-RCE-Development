"""Sony A6 native ABI facts for an AIR2 port, offline analysis only.

Addresses are PIC18 byte addresses.  This module validates the Sony baseline;
it does not modify a firmware or claim that the complete AIR2 port is ready.
RAM for new state is deliberately an input to future adapters, not Canon's
hard-coded bank2 allocation (which overlaps Sony's original objects).
"""
from pathlib import Path
import hashlib
import json

BASE = 0x4000
END = 0x1FC00
EXE_SHA256 = '707b65d9cb6ea6c320976e5a6244de05b1f0856ab9c7ddc5008fe739337b9737'
CODE_END = 0xAF80
CODE_CAVE_CANDIDATE = (CODE_END, 0xF800)

NATIVE = {
    'reset_vector': 0x4102,
    'reset_trampoline': 0x4252,
    'runtime_initialization': 0x6174,
    'board_and_object_initialization': 0x4D42,
    'main_loop': 0x4E94,
    'ui_service': 0x51DE,
    'key_sample_service': 0x4EE2,
    'key_history_push': 0x930E,
    'key_round_robin_service': 0xA0C8,
    'key_debounce_and_event_service': 0x5348,
    'key_press_callback': 0x80F2,
    'key_release_callback': 0x85FE,
    'key_short_dispatch': 0x595A,
    'key_hold_dispatch': 0x6A96,
    'group_select': 0x973C,
    'set_group_and_handlers': 0x5CD8,
    'power_step_dispatch': 0x87CC,
    'mode_read': 0x9690,
    'native_numeric_refresh': 0x6DDE,
    'native_tenths_renderer': 0x7584,
    'native_radio_relative': 0x7490,
    'native_radio_enqueue16': 0xA158,
    'native_radio_prefix': 0x7FDC,
    'native_radio_frame_wrapper': 0x5DA4,
    'native_memcpy': 0x83B4,
    'flash_word_write': 0x9840,
    'flash_erase': 0x9FE4,
}

# Each key has a history byte, flag byte and 16-bit timestamp.  930E shifts
# only history bits 0..6 and preserves bit7 (the native active latch).
KEY_OBJECTS = {
    'mode': 0x115,
    'aux_adc0_low': 0x119,
    'A': 0x11D,
    'B': 0x121,
    'C': 0x125,
    'model': 0x129,
    'head': 0x12D,
    'plus': 0x131,
    'minus': 0x135,
    'aux_portb6': 0x139,
    'aux_porte1': 0x13D,
}

RAM = {
    'key_round_robin_index': 0xD9,
    'key_current_pointer': [0x2A4, 0x2A5],
    'press_callback_pointer': [0xAD, 0xAE],
    'short_dispatch_pointer': [0xAB, 0xAC],
    'hold_dispatch_pointer': [0xBF, 0xC0],
    'native_mode_object_pointer': [0xD2, 0xD3],
    'native_mode_value': 0x193,
    'ttl_abc_fec': [0x197, 0x198, 0x199],
    'manual_relative_abc': [0xEC, 0xED, 0xEE],
    'visible_group_selector': 0xC1,
    'head_mask_abc': 0xDB,
    'model_mask_abc': 0xF3,
    'model_handler': [0xC4, 0xC5, 0xC6],
    'head_handler': [0xC7, 0xC8, 0xC9],
    'power_handler': [0xCA, 0xCB, 0xCC],
    'power_signed_step': 0xA3,
    'ui_snapshot': [0x2A7, 0x2B2],
    'radio_queue_descriptor': 0xE6,
    'lcd_shadow': 0x49,
    'lcd_numeric_rows': [0x4A, 0x4C, 0x4E],
}

HOOKS = {
    'key_service_call': {
        'address': 0xA0DA, 'before_hex': 'a4ec29f0',
        'resume': 0xA0DE, 'native_call': 0x5348,
        'contract': 'CALL replacement. 2A4/2A5=key-object pointer, entry bank2; '
                    'all keys except 125/129/12D must call original5348. '
                    'Caller explicitly restores bank0 at A0DE.'},
    'power_step_entry': {
        'address': 0x87CC, 'before_hex': 'a36f48ec4bf0',
        'resume': 0x87D2, 'native_call': 0x9690,
        'contract': 'GOTO replacement covering TWO complete instructions. '
                    'W=int8 step. Fallback must replay MOVWF A3/BANKED and '
                    'CALL9690, then preserve native Z into branch87D2.'},
    'numeric_refresh_entry': {
        'address': 0x6DDE, 'before_hex': '48ec4bf0',
        'resume': 0x6DE2, 'native_call': 0x9690,
        'contract': 'GOTO replacement. A2 custom renderer can return to caller; '
                    'fallback must CALL9690 and preserve native Z into6DE2.'},
    'short_dispatch_tail': {
        'address': 0x8116, 'before_hex': 'adef2cf0',
        'resume': 0x595A, 'native_call': None,
        'contract': 'Tail GOTO. AB/AC is key-object pointer. Not a complete '
                    'gesture hook: native hold/release callbacks remain separate.'},
}

# Ranges proved used by original startup or runtime, end-exclusive.
OCCUPIED_RAM_EVIDENCE = [
    {'range': [0x300, 0x3BB], 'at': 0x6180, 'kind': 'ROM initialization copy'},
    {'range': [0x1F3, 0x1FC], 'at': 0x61A0, 'kind': 'ROM initialization copy'},
    {'range': [0x400, 0x464], 'at': 0x61D8, 'kind': 'startup zero fill'},
    {'range': [0x3BB, 0x3ED], 'at': 0x61E4, 'kind': 'startup zero fill'},
    {'range': [0x200, 0x2A4], 'at': 0x61F0, 'kind': 'startup zero fill'},
    {'range': [0x100, 0x1E0], 'at': 0x61FC, 'kind': 'startup zero fill'},
    {'range': [0xC1, 0xF4], 'at': 0x6208, 'kind': 'startup zero fill'},
    {'range': [0x3E, 0x57], 'at': 0x6214, 'kind': 'startup zero fill'},
    {'range': [0x2A4, 0x2A6], 'at': 0xA0D0, 'kind': 'round-robin key pointer'},
    {'range': [0x2A6, 0x2A7], 'at': 0x51F0, 'kind': 'UI transaction flag'},
    {'range': [0x2A7, 0x2B2], 'at': 0x51F6, 'kind': 'LCD comparison snapshot'},
]


def history_push(old, pressed):
    """Exact 930E semantics, including pressed values other than 0 and 1."""
    return ((old * 2) & 0x7F) | (old & 0x80) | int(pressed == 1)


def validate_stock(image, known):
    if len(image) != END - BASE or len(known) != len(image):
        raise ValueError('Expected shared stock dense application and mask')
    if known[:2] != b'\0\0' or not all(known[2:]):
        raise ValueError('Unexpected recovered mask')
    if image[0x52:0x56] != bytes.fromhex('030cbba6'):
        raise ValueError('Not Sony model0C03/A6BB')
    for name, hook in HOOKS.items():
        p = hook['address'] - BASE
        raw = bytes.fromhex(hook['before_hex'])
        if image[p:p+len(raw)] != raw:
            raise ValueError('Native hook preimage mismatch: ' + name)
    if image[CODE_END-BASE:0x10000-BASE] != b'\xff' * (0x10000-CODE_END):
        raise ValueError('Sony candidate tail is not entirely erased')
    return {
        'status': 'NATIVE_ABI_REVERSE_ENGINEERING_NOT_FLASHABLE',
        'image_sha256': hashlib.sha256(image).hexdigest(),
        'hooks': HOOKS, 'native': NATIVE, 'ram': RAM,
        'key_objects': KEY_OBJECTS,
        'original_ram_used': OCCUPIED_RAM_EVIDENCE,
        'new_ram_allocation': None,
        'hardware_ram_extent_not_proved': True,
        'full_hss_transitive_closure_not_yet_declared': True,
    }


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    stock = root.parent / 'shared/stock/S'
    report = validate_stock((stock/'original.base4000.partial.bin').read_bytes(),
                            (stock/'original.known_mask.bin').read_bytes())
    (root/'sony_native_mapping.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('PASS Sony A6 native hook preimages; no firmware modified')
