#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""N C5 foreground-only hook wrappers for the shared AIR2 runtime.

No radio, hot-shoe, ISR, HSS, timer or original NVM instruction is patched.
Construction produces sections and exact preimages, not an updater package.
"""
import hashlib
from native_backend import Asm, STOCK_SHA256, absolute, words

CORE_IMPORTS = ('init', 'service', 'power_edit', 'select_row', 'secondary_press', 'idle_expired')
REGISTERS = (0xFE8, 0xFD8, 0xFE0, 0xFE9, 0xFEA, 0xFE1, 0xFE2,
             0xFD9, 0xFDA, 0xFF3, 0xFF4, 0xFF5, 0xFF6, 0xFF7, 0xFF8)
REGISTERS += (0xFFA,)  # Native indirect-call thunk temporarily uses PCLATH.
# Native ISR's low scratch is 01..0C, deliberately outside this save set.
# BSR/FSR architectural state is preserved by the original interrupt handler.
CONTEXT = REGISTERS + tuple(range(0x0D, 0x47)) + tuple(range(0xC0, 0xF2))
PREIMAGES = {
    0x4CF2: '0001856b',
    0x4D30: 'a9ec51f0',
    0x512A: 'f7ec4df0',
    0x55EC: '720e0001',
    0x7E0A: '3f6e08ec48f0',
    0x7B72: '94ec34f0',
    0x7B5C: '11e15bec43f0',
}


def construct(original, *, app_base=0x4000, code_base, state_base=0x680,
              imports, backend_exports, profile=None):
    if hashlib.sha256(original).hexdigest() != STOCK_SHA256 or app_base != 0x4000:
        raise ValueError('Nikon original hash mismatch')
    if len(CONTEXT) + 0xC0 > 0x180:
        raise ValueError('native context exceeds provider save area')
    for name in CORE_IMPORTS:
        if not imports.get(name) or imports[name] & 1:
            raise ValueError('missing core import: ' + name)
    if not backend_exports.get('redraw'):
        raise ValueError('missing native redraw import')
    for address, expected in PREIMAGES.items():
        if original[address-app_base:address-app_base+len(bytes.fromhex(expected))].hex() != expected:
            raise ValueError(f'preimage differs at {address:04X}')
    s = lambda offset: state_base + offset
    a = Asm(code_base)

    a.label('save_context')
    for index, address in enumerate(CONTEXT):
        a.movff(address, s(0xC0+index))
    a.ret()
    a.label('restore_context')
    for index, address in reversed(tuple(enumerate(CONTEXT))):
        a.movff(s(0xC0+index), address)
    a.ret()
    save, restore = a.labels['save_context'], a.labels['restore_context']

    def valid(label):
        a.load(s(0)); a.w(0x0AA8); a.jump(label, 'BNZ')
        a.load(0x4D); a.w(0x0900); a.jump(label, 'BNZ')

    a.label('startup_hook')
    a.emit(bytes.fromhex(PREIMAGES[0x4CF2]))
    a.call(save)
    for offset in range(0xB4,0xB8):
        a.put(s(offset),0)
    a.call(imports['init']); a.call(restore); a.goto(0x4CF6)

    a.label('service_hook')
    a.call(0xA352)  # displaced original scheduler, once and before new work
    a.call(save); valid('service_finished')
    a.call(imports['service'])
    a.label('service_finished'); a.call(restore); a.ret()

    a.label('lcd_hook')
    a.call(save); valid('lcd_finished')
    a.call(backend_exports['redraw'])
    a.label('lcd_finished'); a.call(restore)
    a.call(0x9BEE); a.ret()  # preserve all original LCD serialization effects

    a.label('press_hook')
    a.call(save); valid('press_original')
    a.load(0xC1); a.w(0x0A02); a.jump('press_original', 'BNZ')
    keys = ((0x7A, 'select_row', 1), (0x7E, 'select_row', 2),
            (0x82, 'secondary_press', 1), (0x86, 'secondary_press', 2),
            (0x8A, 'secondary_press', 4))
    for low, operation, value in keys:
        a.load(0xC0); a.w(0x0A00 | low); a.jump(f'press_{low:02X}', 'BZ')
    a.jump('press_original')
    for low, operation, value in keys:
        a.label(f'press_{low:02X}')
        a.lit(value); a.call(imports[operation]); a.call(restore); a.ret()
    a.label('press_original')
    a.call(restore); a.emit(bytes.fromhex(PREIMAGES[0x55EC])); a.goto(0x55F0)

    a.label('power_hook')
    a.call(save); valid('power_original')
    # The saved W is exactly the native short/long step. Rejected busy edits
    # are still consumed; never fall through to the original relative sender.
    a.load(s(0xC0)); a.call(imports['power_edit']); a.call(restore); a.ret()
    a.label('power_original')
    a.call(restore); a.emit(bytes.fromhex(PREIMAGES[0x7E0A])); a.goto(0x7E10)

    a.label('idle_hook')
    a.call(save); valid('idle_original')
    a.call(imports['idle_expired']); a.call(restore); a.ret()
    a.label('idle_original'); a.call(restore); a.call(0x6928); a.ret()

    a.label('idle_deadline_hook')
    # The native caller clears B4:B5 immediately after its old idle CALL.
    # A deferred AIR1 clear must keep the expired native timer armed, so a
    # GOTO wrapper selects the native continuation without an extra stack item.
    # A2, inactive visibility, and uninitialized native operation keep the
    # original consume path; they are not retryable AIR1 requests.
    a.call(save)
    a.load(s(0)); a.w(0x0AA8); a.jump('idle_deadline_consume', 'BNZ')
    a.load(s(2)); a.w(0x0A01); a.jump('idle_deadline_consume', 'BNZ')
    a.load(s(7)); a.w(0x0900); a.jump('idle_deadline_consume', 'BZ')
    a.call(imports['idle_expired']); a.w(0x0900)
    a.jump('idle_deadline_retry', 'BZ')
    a.call(restore); a.goto(0x7B76)
    a.label('idle_deadline_consume')
    a.call(restore); a.call(a.labels['idle_hook']); a.goto(0x7B76)
    a.label('idle_deadline_retry'); a.call(restore); a.goto(0x7B80)

    a.label('idle_mode_hook')
    # Original DECF mode,W has already set Z. Keep its MAN path, and permit
    # the same original deadline in TTL when DEF currently uses AIR1.
    a.call(save)
    a.bit(s(0xC1),2,'skip_set'); a.jump('idle_check_ttl_def')
    a.jump('idle_mode_continue')
    a.label('idle_check_ttl_def'); valid('idle_mode_skip')
    a.load(s(1)); a.w(0x0900); a.jump('idle_mode_skip','BNZ')
    a.load(s(2)); a.w(0x0A01); a.jump('idle_mode_skip','BNZ')
    a.load(s(3)); a.w(0x0A01); a.jump('idle_mode_skip','BNZ')
    a.label('idle_mode_continue'); a.call(restore); a.call(0x86B6); a.goto(0x7B62)
    a.label('idle_mode_skip'); a.call(restore); a.goto(0x7B80)

    data = a.finalize()
    limit = (profile or {}).get('code_limit', 0xF800)
    if code_base < 0xAA80 or code_base + len(data) > limit:
        raise ValueError('native hooks outside available code cave')
    cave = original[code_base-app_base:code_base-app_base+len(data)]
    if len(cave) != len(data) or cave != b'\xff' * len(data):
        raise ValueError('native hook cave is not original FF')
    hook_specs = (
        (0x4CF2, 'startup_hook', 0xEF00, 0x4CF6, 'after original model/camera initialization'),
        (0x4D30, 'service_hook', 0xEC00, 0x4D34, 'after normal UI service; original A352 preserved'),
        (0x512A, 'lcd_hook', 0xEC00, 0x512E, 'ordinary UI LCD composition, original serializer preserved'),
        (0x55EC, 'press_hook', 0xEF00, 0x55F0, 'after original application/input permission gates'),
        (0x7E0A, 'power_hook', 0xEF00, 0x7E10, 'native release/hold signed power step, no chord wait'),
        (0x7B72, 'idle_deadline_hook', 0xEF00, 0x7B76,
         'original deadline; deferred AIR1 clear skips timer disarm to 7B80'),
        (0x7B5C, 'idle_mode_hook', 0xEF00, 0x7B62, 'extend original relative deadline to TTL-DEF AIR1'),
    )
    hooks = []
    for address, label, opcode, continuation, evidence in hook_specs:
        replacement = absolute(opcode, a.labels[label])
        if len(bytes.fromhex(PREIMAGES[address])) == 6:
            replacement += words(0)
        hooks.append({'address': address, 'expected_hex': PREIMAGES[address],
                      'new_hex': replacement.hex(), 'role': 'N_foreground_ui_hook',
                      'continuation': continuation, 'evidence': evidence})
    return {
        'sections': [{'address': code_base, 'data': data, 'role': 'N_native_hooks'}],
        'hooks': hooks, 'exports': {key: value for key, value in a.labels.items() if key.endswith('_hook')},
        'labels': dict(a.labels), 'required_imports': list(CORE_IMPORTS)+['redraw'],
        'unresolved_imports': [],
        'reserved_ram': [{'start': s(0xC0), 'end': s(0xC0+len(CONTEXT)), 'owner': 'N_outer_native_context'}],
        'metadata': {
            'status': 'HOOKS_EMITTED_REPLAY_REQUIRED', 'native_hook_binding_complete': True,
            'context_addresses': list(CONTEXT), 'irq_masking_added': False,
            'release_hold_hook_not_needed': '8630 and 6786 contain no C/HEAD/MODEL effect to suppress',
            'no_hss_or_radio_original_instruction_modified': True,
            'warning': 'Qualification and linked replay are required; this is not a flashable package.',
        },
    }
