#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Behavioral contract checks; run with Python 3.9+ using this file directly.

No target execution, device access, persistent write, or HSS timing claim.
Golden radio vectors are checked independently of production packet builders.
"""
import unittest
import json
from pathlib import Path

from state_model import (A1, A2, ALL, MAN, TTL, Air2State, GestureClassifier,
                         NvRecord, TxPlan, crc_ccitt_false)


def drain(state):
    packets = []
    while state.tx.active:
        state.pump_tx(lambda body: packets.append(body) or True)
    return packets


def snapshot(state):
    return (state.mode, state.last_manual, state.page, state.selected,
            tuple(state.targets), tuple(state.relative), tuple(state.fec),
            state.head_mask, state.model_mask, state.visible_mask,
            state.nv_dirty, state.tx.pending)


def absolute_state(mode=MAN):
    state = all_on_state("F", native_mode=mode)
    state.last_manual = A2
    return state


def all_on_state(tag="F", **kwargs):
    """Explicit user-enabled DEF fixture; first-install DEF stays OFF."""
    state = Air2State(tag, **kwargs)
    state.head_mask = 63
    return state


class StateTests(unittest.TestCase):
    def test_gesture_defaults_match_formal_mount_profiles(self):
        for tag in 'NSFO':
            profile = json.loads((Path(__file__).resolve().parents[1] / tag /
                                  'port_profile.json').read_text(encoding='utf-8'))
            keys = Air2State(tag).gestures
            self.assertEqual((keys.clock_mask, keys.WINDOW, keys.STABLE),
                             (profile['clock_mask'], profile['window_counts'],
                              profile['stable_counts']))
            self.assertIsNone(keys.poll(1, 0, 'same-domain'))
            self.assertIsNone(keys.poll(5, 5, 'same-domain'))
            self.assertIsNone(keys.poll(5, 5 + keys.STABLE - 1, 'same-domain'))
            self.assertEqual(keys.poll(5, 5 + keys.STABLE, 'same-domain'), 'page')

    def test_native_startup_preserved_no_effect(self):
        for tag in "FNOS":
            state = Air2State(tag, native_mode=TTL, native_head_abc=5,
                              native_model_abc=2, native_fec=(-20, 0, 20), native_selected=2)
            self.assertEqual((state.mode, state.head_mask, state.model_mask), (TTL, 5, 2))
            self.assertEqual(state.selected, 2)
            self.assertEqual(state.fec, [-20, 0, 20])
            self.assertEqual(state.targets, [50] * 6)
            self.assertFalse(state.tx.active or state.nv_dirty or state.storage_backend_enabled)
            state.page = 1
            self.assertEqual([row.text for row in state.display()], ["--"] * 3)

    def test_atomic_absolute_bounds_both_steps(self):
        for step, edge in ((1, 100), (10, 91), (-1, 1), (-10, 10)):
            state = absolute_state()
            state.targets[4] = edge
            before = snapshot(state)
            self.assertFalse(state.edit_power(step))
            self.assertEqual(snapshot(state), before)

    def test_atomic_relative_bounds_both_steps(self):
        for step, edge in ((1, 99), (10, 90), (-1, -99), (-10, -90)):
            state = all_on_state("N")
            state.relative[4] = edge
            before = snapshot(state)
            self.assertFalse(state.edit_power(step))
            self.assertEqual(snapshot(state), before)

    def test_atomic_mixed_ttl_bounds(self):
        for manual in (A1, A2):
            for step, edge in ((1, 20), (10, 11), (-1, -20), (-10, -11)):
                state = all_on_state("O", native_mode=TTL)
                state.last_manual, state.fec[1] = manual, edge
                before = snapshot(state)
                self.assertFalse(state.edit_power(step))
                self.assertEqual(snapshot(state), before)

    def test_all_valid_boundaries_reached_exactly(self):
        for manual, domain, low, high in ((A2, "targets", 1, 100), (A1, "relative", -99, 99)):
            for step in (-10, -1, 1, 10):
                state = all_on_state("S")
                state.last_manual = manual
                expected = low if step < 0 else high
                getattr(state, domain)[:] = [expected - step] * 6
                self.assertTrue(state.edit_power(step))
                self.assertEqual(getattr(state, domain), [expected] * 6)

    def test_disabled_group_excluded_from_preflight(self):
        state = absolute_state()
        state.head_mask, state.targets[0] = 62, 100
        self.assertTrue(state.edit_power(1))
        self.assertEqual(state.targets, [100, 51, 51, 51, 51, 51])
        self.assertEqual(state.tx.pending[0][6:12], bytes(state.targets))

    def test_all_off_power_is_noop(self):
        state = absolute_state()
        state.head_mask = 0
        before = snapshot(state)
        self.assertFalse(state.edit_power(10))
        self.assertEqual(snapshot(state), before)

    def test_all_is_six_groups_on_either_page(self):
        for page in (0, 1):
            state = absolute_state()
            state.page = page
            self.assertTrue(state.edit_power(-10))
            self.assertEqual(state.targets, [40] * 6)
            self.assertEqual(len(state.tx.pending), 1)

    def test_local_row_mapping_and_selection_toggle(self):
        state = absolute_state()
        state.toggle_page()
        state.select(2)
        state.edit_power(1)
        self.assertEqual(state.targets, [50, 50, 50, 50, 51, 50])
        drain(state)
        state.select(2)
        self.assertEqual(state.selected, ALL)

    def test_ttl_a2_all_golden_wire(self):
        state = absolute_state(TTL)
        state.targets, state.fec = [21, 32, 43, 54, 65, 76], [-3, 0, 5]
        state.edit_power(1)
        self.assertEqual(state.targets, [21, 32, 43, 55, 66, 77])
        self.assertEqual(state.fec, [-2, 1, 6])
        self.assertEqual(state.tx.pending, (
            bytes.fromhex("27 ff ff ff 01 25 fe 01 06 00 00 00 00 00 00 00"),
            bytes.fromhex("27 ff ff ff 01 11 15 20 2b 37 42 4d 3f 00 00 00")))

    def test_ttl_a1_all_golden_wire(self):
        state = all_on_state("F", native_mode=TTL, native_fec=(-3, 0, 5))
        state.edit_power(1)
        self.assertEqual(state.relative, [0, 0, 0, 1, 1, 1])
        self.assertEqual(state.tx.pending, (
            bytes.fromhex("27 ff ff ff 01 25 fe 01 06 00 00 00 00 00 00 00"),
            bytes.fromhex("04 ff ff ff 01 06 04 00 00 00 00 00 00 00 00 00"),
            bytes.fromhex("05 ff ff ff 01 06 05 00 00 00 00 00 00 00 00 00"),
            bytes.fromhex("06 ff ff ff 01 06 06 00 00 00 00 00 00 00 00 00")))

    def test_ttl_def_a2_includes_abc_cache_side_effect(self):
        state = absolute_state(TTL)
        state.targets, state.fec = [21, 32, 43, 54, 65, 76], [-3, 0, 5]
        state.page, state.selected = 1, 1
        state.edit_power(1)
        self.assertEqual(state.fec, [-3, 0, 5])
        self.assertEqual(state.tx.pending, (bytes.fromhex(
            "27 ff ff ff 01 11 15 20 2b 37 41 4c 3f 00 00 00"),))

    def test_ttl_abc_fec_for_both_manual_kinds(self):
        for kind in (A1, A2):
            state = Air2State("F", native_mode=TTL)
            state.last_manual, state.selected = kind, 3
            state.edit_power(-10)
            self.assertEqual(state.fec, [0, 0, -10])
            self.assertEqual(state.targets, [50] * 6)
            self.assertEqual(state.relative, [0] * 6)
            self.assertEqual([body[5] for body in state.tx.pending], [0x25])

    def test_relative_command_mapping(self):
        for step, command in ((1, 6), (-1, 7), (10, 13), (-10, 14)):
            state = all_on_state("S")
            state.selected, state.page = 3, 1
            state.edit_power(step)
            self.assertEqual(state.tx.pending, (bytes((6, 255, 255, 255, 1, command, 6)) + bytes(9),))

    def test_head_on_reasserts_saved_model_both_values(self):
        for model, command in ((0, 3), (1, 2)):
            state = Air2State("F", native_head_abc=6, native_model_abc=model)
            state.selected = 1
            state.toggle_switch("head")
            self.assertEqual([packet[5] for packet in state.tx.pending], [0, command])
            self.assertTrue(all(packet[0] == packet[6] == 1 for packet in state.tx.pending))

    def test_head_off_does_not_clear_model_intent(self):
        state = Air2State("F", native_model_abc=1)
        state.selected = 1
        state.toggle_switch("head")
        self.assertEqual(state.model_mask, 1)
        self.assertEqual([packet[5] for packet in state.tx.pending], [1])

    def test_all_switch_mixed_means_all_on_then_all_off(self):
        for kind in ("head", "model"):
            state = Air2State("F")
            setattr(state, kind + "_mask", 0x15)
            state.toggle_switch(kind)
            self.assertEqual(getattr(state, kind + "_mask"), 63)
            packets = drain(state)
            self.assertEqual({packet[0] for packet in packets}, set(range(1, 7)))
            state.toggle_switch(kind)
            self.assertEqual(getattr(state, kind + "_mask"), 0)
            self.assertEqual(len(state.tx.pending), 6)

    def test_snapshot_plan_is_immutable_and_retries_without_reorder(self):
        state = all_on_state("F", native_mode=TTL)
        state.edit_power(1)
        original = state.tx.pending
        calls = []
        self.assertFalse(state.pump_tx(lambda body: calls.append(body) or False))
        self.assertEqual(state.tx.pending, original)
        self.assertTrue(state.pump_tx(lambda body: calls.append(body) or True))
        self.assertEqual(calls, [original[0], original[0]])
        self.assertEqual(state.tx.pending, original[1:])
        self.assertEqual(drain(state), list(original[1:]))

    def test_callback_exception_keeps_body_pending(self):
        state = absolute_state()
        state.edit_power(1)
        before = state.tx.pending
        def fail(body):
            raise RuntimeError("native queue failure")
        with self.assertRaises(RuntimeError):
            state.pump_tx(fail)
        self.assertEqual(state.tx.pending, before)

    def test_busy_rejects_all_edits_without_mutation(self):
        for busy in ("native_busy", "camera_busy", "plan"):
            state = absolute_state()
            if busy == "plan":
                state.edit_power(1)
            else:
                setattr(state, busy, True)
            before = snapshot(state)
            for edit in (lambda: state.edit_power(1), lambda: state.select(2),
                         state.toggle_page, state.toggle_mode, state.toggle_manual,
                         lambda: state.toggle_switch("head")):
                self.assertFalse(edit())
                self.assertEqual(snapshot(state), before)

    def test_native_busy_does_not_enqueue(self):
        state = absolute_state()
        state.edit_power(1)
        state.native_busy = True
        called = []
        self.assertFalse(state.pump_tx(lambda packet: called.append(packet) or True))
        self.assertEqual(called, [])
        self.assertTrue(state.tx.active)

    def test_five_quick_power_taps_never_enter_combo_window(self):
        state = absolute_state()
        state.selected = 1
        for _ in range(5):
            self.assertTrue(state.edit_power(1))
            drain(state)
        self.assertEqual(state.targets, [55, 50, 50, 50, 50, 50])
        self.assertEqual(state.gestures.phase, "idle")

    def test_a2_all_rows_persist_and_off_is_dash(self):
        state = absolute_state()
        state.selected, state.head_mask = 1, 62
        self.assertEqual([row.text for row in state.display()], ["--", "5.0", "5.0"])
        self.assertFalse(state.native_idle())
        state.select(2)
        self.assertEqual([row.text for row in state.display()], ["--", "5.0", "5.0"])

    def test_relative_visibility_idle_selection_and_man_entry(self):
        for action in ("idle", "selection", "man_entry"):
            state = Air2State("F")
            state.edit_power(1)
            drain(state)
            self.assertEqual([row.text for row in state.display()], ["+0.1"] * 3)
            record = state.capture_record()
            if action == "idle":
                state.native_idle()
            elif action == "selection":
                state.select(2)
            else:
                state.toggle_mode()
                state.toggle_mode()
            self.assertEqual(state.relative, [0] * 6)
            self.assertEqual(state.visible_mask, 0)
            self.assertEqual([row.text for row in state.display()], [""] * 3)
            self.assertEqual(state.capture_record(), record)
            self.assertFalse(state.tx.active)

    def test_mode_page_and_subtype_memory(self):
        state = Air2State("O")
        state.toggle_manual()
        state.toggle_page()
        state.toggle_mode()
        self.assertEqual((state.mode, state.last_manual, state.page), (TTL, A2, 1))
        self.assertFalse(state.toggle_manual())
        state.toggle_mode()
        self.assertEqual((state.mode, state.last_manual, state.page), (MAN, A2, 1))
        restored = Air2State("O", nv_record=state.capture_record(23))
        self.assertEqual((restored.mode, restored.last_manual, restored.page, restored.sequence), (MAN, A2, 1, 23))
        self.assertFalse(restored.tx.active or restored.nv_dirty)

    def test_fec_and_relative_not_saved(self):
        for mode in (MAN, TTL):
            state = Air2State("F", native_mode=mode)
            before = state.capture_record()
            state.edit_power(1)
            drain(state)
            self.assertEqual(state.capture_record(), before)


class RecordTests(unittest.TestCase):
    def test_crc_published_check_vector(self):
        self.assertEqual(crc_ccitt_false(b"123456789"), 0x29B1)

    def test_layout_and_roundtrip_all_models_modes(self):
        for tag in "FNOS":
            for mode, kind in ((TTL, A1), (TTL, A2), (MAN, A1), (MAN, A2)):
                record = NvRecord(tag, mode, kind, (1, 10, 20, 30, 99, 100), 0x35, 0x0A, 1, 0x1234)
                data = record.encode()
                self.assertEqual(len(data), 32)
                self.assertEqual(data[:3], b"A2\x05")
                self.assertEqual(data[3], kind if mode == MAN else 0)
                self.assertEqual(data[4:6], b"\x34\x12")
                self.assertEqual(data[6:17], bytes((1, 10, 20, 30, 99, 100, 0x35, 0x0A, 1, kind, ord(tag))))
                self.assertEqual(data[17:28], bytes(11))
                self.assertEqual(data[30:], b"\x5a\xa5")
                self.assertEqual(NvRecord.decode(data, tag), record)

    def test_every_bit_corruption_rejected(self):
        good = NvRecord("F", MAN, A2, (50,) * 6, 63, 0, 0).encode()
        for byte in range(32):
            for bit in range(8):
                bad = bytearray(good)
                bad[byte] ^= 1 << bit
                with self.assertRaises(ValueError, msg="byte%d bit%d" % (byte, bit)):
                    NvRecord.decode(bytes(bad), "F")

    def test_valid_crc_does_not_bypass_field_validation(self):
        good = NvRecord("F", MAN, A2, (50,) * 6, 63, 0, 0).encode()
        for offset, value in ((3, 3), (3, 1), (6, 0), (11, 101), (12, 64),
                              (13, 128), (14, 2), (15, 0), (17, 1)):
            bad = bytearray(good)
            bad[offset] = value
            bad[28:30] = crc_ccitt_false(bad[:28]).to_bytes(2, "little")
            with self.assertRaises(ValueError, msg="offset%d" % offset):
                NvRecord.decode(bytes(bad), "F")

    def test_wrong_tag_and_truncated_record_never_restore(self):
        record = NvRecord("F", MAN, A2, (75,) * 6, 0, 63, 1).encode()
        for bad in (record, record[:-1], record + b"\x00"):
            state = Air2State("N", native_mode=TTL, native_head_abc=3, nv_record=bad)
            self.assertFalse(state.nv_loaded)
            self.assertEqual((state.mode, state.head_mask, state.targets), (TTL, 3, [50] * 6))
            self.assertFalse(state.tx.active or state.nv_dirty)


class NativePriorityTests(unittest.TestCase):
    def test_nv_mode_restore_needs_explicit_native_projection_not_stale_snapshot(self):
        record = NvRecord("F", TTL, A2, (55,) * 6, 63, 0, 1).encode()
        projections, sent = [], []
        state = Air2State("F", native_mode=MAN, nv_record=record,
                          apply_native_state=lambda request: projections.append(request) or True)
        self.assertEqual((state.mode, state.native_domain), (TTL, (MAN, 0)))
        result = state.service_once(lambda body: sent.append(body) or True)
        self.assertEqual(result.nv_reason, "native_mode_unreconciled")
        self.assertEqual(state.mode, TTL)
        self.assertFalse(state.edit_power(1))
        self.assertTrue(state.project_native_startup())
        self.assertEqual(projections[0].fields, 13)
        self.assertEqual((state.mode, state.native_domain), (TTL, (TTL, 0)))
        self.assertEqual(sent, [])
        self.assertFalse(state.tx.active or state.nv_dirty)
        state.service_once(lambda body: sent.append(body) or True, native_mode=MAN)
        self.assertEqual(state.mode, MAN)  # An actual fresh native mode still wins.

    def test_refused_startup_projection_keeps_restore_pending_without_writes(self):
        record = NvRecord("F", TTL, A2, (55,) * 6, 63, 0, 1).encode()
        state = Air2State("F", native_mode=MAN, nv_record=record,
                          apply_native_state=lambda request: False)
        before = snapshot(state)
        self.assertFalse(state.project_native_startup())
        self.assertEqual(snapshot(state), before)
        self.assertEqual(state.native_domain, (MAN, 0))
        self.assertFalse(state.pump_tx(lambda body: True))

    def test_mode_change_before_first_admission_discards_all_tail(self):
        state = all_on_state("N")
        state.edit_power(1)
        pending = state.tx.pending
        self.assertEqual(len(pending), 6)
        enqueued = []
        result = state.service_once(lambda body: enqueued.append(body) or True, native_mode=TTL)
        self.assertEqual(result.cancelled, pending)
        self.assertEqual(state.mode, TTL)
        self.assertEqual(enqueued, [])
        self.assertEqual(state.tx.admitted, ())

    def test_partly_admitted_ttl_plan_preserves_prefix_and_native_mode(self):
        projected = []
        state = all_on_state("F", native_mode=TTL,
                             apply_native_state=lambda request: projected.append(request) or True)
        state.last_manual = A2
        state.edit_power(1)
        first, second = state.tx.pending
        self.assertEqual(state.tx.native_domain, (TTL, 0))
        sent = []
        state.pump_tx(lambda body: sent.append(body) or True)
        calls = len(projected)
        result = state.service_once(lambda body: sent.append(body) or True, native_mode=MAN)
        self.assertEqual(result.cancelled, (second,))
        self.assertEqual(sent, [first])
        self.assertEqual(state.tx.admitted, (first,))
        self.assertEqual(state.mode, MAN)
        self.assertEqual(len(projected), calls)  # Never push old TTL into native state.
        self.assertFalse(state.tx.active)

    def test_same_mode_camera_generation_and_roundtrip_invalidate(self):
        for roundtrip in (False, True):
            state = all_on_state("S")
            state.edit_power(1)
            pending = state.tx.pending
            if roundtrip:
                self.assertEqual(state.observe_native_domain(TTL, context=1), pending)
                self.assertEqual(state.observe_native_domain(MAN, context=2), ())
            else:
                self.assertEqual(state.observe_native_domain(MAN, context=1), pending)
            self.assertEqual(state.mode, MAN)
            self.assertFalse(state.tx.active)
            self.assertEqual(state.tx.admitted, ())

    def test_self_queue_busy_pauses_without_invalidating_domain(self):
        state = all_on_state("O")
        state.edit_power(1)
        plan = state.tx.pending
        sent = []
        state.service_once(lambda body: sent.append(body) or True)
        state.native_busy = True
        paused = state.service_once(lambda body: sent.append(body) or True)
        self.assertFalse(paused.admitted)
        self.assertEqual(paused.cancelled, ())
        self.assertEqual(state.tx.pending, plan[1:])
        state.native_busy = False
        while state.tx.active:
            state.service_once(lambda body: sent.append(body) or True)
        self.assertEqual(sent, list(plan))

    def test_projection_refusal_rolls_back_every_host_edit_without_native_write(self):
        edits = (lambda state: state.edit_power(1), lambda state: state.toggle_mode(),
                 lambda state: state.toggle_page(), lambda state: state.toggle_manual(),
                 lambda state: state.toggle_switch("head"), lambda state: state.select(2))
        for edit in edits:
            native = {"writes": 0, "mode": MAN, "head": 7}
            requests = []
            def refuse(request):
                requests.append(request)
                return False  # Backend checks all refusal conditions before any write.
            state = all_on_state("F", apply_native_state=refuse)
            state.relative, state.visible_mask = [1, 2, 3, 4, 5, 6], 63
            before = snapshot(state)
            domain = state.native_domain
            self.assertFalse(edit(state))
            self.assertEqual(snapshot(state), before)
            self.assertEqual(state.native_domain, domain)
            self.assertEqual(native, {"writes": 0, "mode": MAN, "head": 7})
            self.assertEqual(len(requests), 1)

    def test_projection_exception_rolls_back_and_propagates(self):
        def fail(request):
            raise RuntimeError("refused before native writes")
        state = all_on_state("F", native_mode=TTL, apply_native_state=fail)
        state.last_manual = A2
        before = snapshot(state)
        with self.assertRaisesRegex(RuntimeError, "before native writes"):
            state.edit_power(1)
        self.assertEqual(snapshot(state), before)
        self.assertFalse(state.tx.active or state._dispatching_gesture)

    def test_camera_event_during_projection_keeps_native_mode_and_aborts_edit(self):
        for outcome in (True, False, "exception"):
            state = all_on_state("F", native_mode=TTL)
            state.last_manual = A2
            targets, fec = list(state.targets), list(state.fec)
            def raced_projection(request):
                state.observe_native_domain(MAN, context=1)
                if outcome == "exception":
                    raise RuntimeError("camera interrupted before projection writes")
                return outcome
            state._apply_native_state = raced_projection
            if outcome == "exception":
                with self.assertRaises(RuntimeError):
                    state.edit_power(1)
            else:
                self.assertFalse(state.edit_power(1))
            self.assertEqual(state.mode, MAN)
            self.assertEqual(state.native_domain, (MAN, 1))
            self.assertEqual(state.targets, targets)
            self.assertEqual(state.fec, fec)
            self.assertFalse(state.tx.active)
            self.assertTrue(state.nv_dirty)

    def test_projection_success_selects_only_native_abc_fields(self):
        requests = []
        state = all_on_state("F", native_mode=TTL,
                             apply_native_state=lambda request: requests.append(request) or True)
        state.last_manual = A2
        state.edit_power(1)
        self.assertEqual(requests[-1].fields, 2)
        self.assertEqual(requests[-1].fec, (1, 1, 1))
        self.assertEqual((requests[-1].head_abc, requests[-1].model_abc), (7, 0))
        drain(state)
        state.toggle_mode()
        self.assertEqual(requests[-1].fields, 1)
        self.assertEqual(state.native_domain, (MAN, 0))

    def test_last_admitted_frame_still_forbids_nv_this_round(self):
        state = absolute_state()
        state.edit_power(1)
        readiness_calls = []
        def fresh():
            readiness_calls.append(True)
            return True
        result = state.service_once(lambda body: True, nv_backend_proven=True, fresh_nv_ready=fresh)
        self.assertTrue(result.admitted)
        self.assertFalse(state.tx.active)
        self.assertEqual(result.nv_reason, "admitted_this_round")
        self.assertEqual(readiness_calls, [])
        self.assertIsNone(result.nv_candidate)
        following = state.service_once(lambda body: True, nv_backend_proven=True, fresh_nv_ready=fresh)
        self.assertEqual(readiness_calls, [True])
        self.assertIsNotNone(following.nv_candidate)
        self.assertEqual(state.sequence, 0)
        self.assertTrue(state.nv_dirty)  # Candidate capture is not an NV commit.
        self.assertFalse(state.storage_backend_enabled)

    def test_nv_uses_fresh_readiness_and_rechecks_busy(self):
        state = absolute_state()
        state.nv_dirty = True
        for scenario in ("unproved", "refused", "became_busy", "ready"):
            state.camera_busy = False
            calls = []
            def fresh():
                calls.append(True)
                if scenario == "became_busy":
                    state.camera_busy = True
                return scenario != "refused"
            result = state.service_once(lambda body: True, nv_backend_proven=scenario != "unproved",
                                        fresh_nv_ready=fresh)
            self.assertEqual(calls, [] if scenario == "unproved" else [True])
            self.assertEqual(result.nv_candidate is not None, scenario == "ready")
            self.assertEqual(state.sequence, 0)
            self.assertTrue(state.nv_dirty)


class GestureTests(unittest.TestCase):
    def test_direct_key_during_pending_cancels_without_effect(self):
        for edit in (lambda state: state.edit_power(1), lambda state: state.select(2),
                     lambda state: state.toggle_switch("head"), lambda state: state.toggle_mode()):
            state = absolute_state()
            state.poll_keys(1, 0)
            before = snapshot(state)
            self.assertFalse(edit(state))
            self.assertEqual(snapshot(state), before)
            self.assertEqual(state.gestures.phase, "release")
            state.poll_keys(0, 20)
            state.poll_keys(0, 30)
            self.assertTrue(state.edit_power(1))

    def test_released_single_allows_immediate_next_press(self):
        keys = GestureClassifier()
        keys.poll(1, 0, 0)
        keys.poll(0, 20, 0)
        self.assertEqual(keys.poll(0, 30, 0), "select_c")
        self.assertEqual(keys.phase, "idle")
        keys.poll(4, 31, 0)
        keys.poll(0, 40, 0)
        self.assertEqual(keys.poll(0, 50, 0), "head")

    def test_native_first_key_released_before_secondary_sample(self):
        keys = GestureClassifier()
        self.assertIsNone(keys.poll(0, 0, 0, first=1))
        self.assertIsNone(keys.poll(0, 9, 0))
        self.assertEqual(keys.poll(0, 10, 0), "select_c")

    def test_same_mode_camera_event_cancels_pending(self):
        state = Air2State("F", native_mode=TTL)
        state.poll_keys(1, 0)
        state.cancel_secondary(5)
        self.assertIsNone(state.poll_keys(5, 20))
        self.assertEqual(state.page, 0)
        self.assertEqual(state.mode, TTL)
        state.poll_keys(0, 30)
        state.poll_keys(0, 40)
        self.assertEqual(state.gestures.phase, "idle")

    def test_chord_orders_and_modes(self):
        for raw, members, expected in ((3, (1, 2), "manual"), (5, (1, 4), "page")):
            for first in members:
                keys = GestureClassifier()
                self.assertIsNone(keys.poll(first, 0, (0,)))
                self.assertIsNone(keys.poll(raw, 20, (0,)))
                self.assertIsNone(keys.poll(raw, 29, (0,)))
                self.assertEqual(keys.poll(raw, 30, (0,)), expected)
                self.assertIsNone(keys.poll(raw, 50, (0,)))
        for mode in (TTL, MAN):
            state = Air2State("F", native_mode=mode)
            state.poll_keys(3, 0)
            action = state.poll_keys(3, 10)
            self.assertEqual(action, "swallowed" if mode == TTL else "manual")
            self.assertEqual(state.last_manual, A1 if mode == TTL else A2)

    def test_candidate_onset_199_finishes_after_window(self):
        keys = GestureClassifier()
        keys.poll(1, 0, 0)
        keys.poll(5, 199, 0)
        self.assertIsNone(keys.poll(5, 208, 0))
        self.assertEqual(keys.poll(5, 209, 0), "page")

    def test_candidate_onset_200_is_first_single(self):
        keys = GestureClassifier()
        keys.poll(4, 0, 0)
        self.assertEqual(keys.poll(5, 200, 0), "head")
        self.assertIsNone(keys.poll(5, 210, 0))

    def test_release_stability_and_held_timeout_single_once(self):
        for first, expected in ((1, "select_c"), (2, "model"), (4, "head")):
            for held in (False, True):
                keys = GestureClassifier()
                keys.poll(first, 0, 0)
                if held:
                    self.assertIsNone(keys.poll(first, 199, 0))
                    self.assertEqual(keys.poll(first, 200, 0), expected)
                else:
                    keys.poll(0, 20, 0)
                    self.assertIsNone(keys.poll(0, 29, 0))
                    self.assertEqual(keys.poll(0, 30, 0), expected)
                self.assertIsNone(keys.poll(first, 210, 0))

    def test_half_and_full_ring_rollover(self):
        for mask in (0x7FFF, 0xFFFF):
            keys = GestureClassifier(clock_mask=mask)
            start = mask - 15
            keys.poll(1, start, 0)
            keys.poll(5, (start + 100) & mask, 0)
            self.assertEqual(keys.poll(5, (start + 110) & mask, 0), "page")

    def test_invalid_initial_patterns_fail_closed(self):
        for raw in (6, 7, 0x80, 0xFF):
            keys = GestureClassifier()
            self.assertIsNone(keys.poll(raw, 0, 0))
            self.assertIsNone(keys.poll(5, 20, 0))
            self.assertEqual(keys.phase, "release")

    def test_domain_and_busy_cancel_until_stable_zero(self):
        for cause in ("mode", "manual", "page", "selection", "busy"):
            keys = GestureClassifier()
            domain = (MAN, A1, 0, ALL)
            keys.poll(1, 0, domain)
            changed = list(domain)
            if cause != "busy":
                changed[("mode", "manual", "page", "selection").index(cause)] ^= 1
            keys.poll(5, 20, tuple(changed), busy=cause == "busy")
            self.assertIsNone(keys.poll(5, 30, domain))
            keys.poll(0, 40, domain)
            keys.poll(0, 49, domain)
            self.assertEqual(keys.phase, "release")
            keys.poll(0, 50, domain)
            self.assertEqual(keys.phase, "idle")

    def test_chord_cannot_degrade_or_switch(self):
        for replacement in (0, 1, 2, 4, 5):
            keys = GestureClassifier()
            keys.poll(1, 0, 0)
            keys.poll(3, 20, 0)
            self.assertIsNone(keys.poll(replacement, 25, 0))
            self.assertIsNone(keys.poll(replacement, 40, 0))
            self.assertEqual(keys.phase, "release")
            if replacement == 0:
                keys.poll(0, 50, 0)
                self.assertEqual(keys.phase, "idle")

    def test_chord_latch_partial_release_not_new_gesture(self):
        keys = GestureClassifier()
        keys.poll(5, 0, 0)
        self.assertEqual(keys.poll(5, 10, 0), "page")
        for raw, tick in ((1, 20), (3, 30), (3, 50), (0, 60), (0, 69)):
            self.assertIsNone(keys.poll(raw, tick, 0))
        self.assertEqual(keys.phase, "release")
        keys.poll(0, 70, 0)
        self.assertEqual(keys.phase, "idle")

    def test_clock_stall_cancels_without_action(self):
        keys = GestureClassifier()
        keys.poll(1, 9, 0)
        for _ in range(4096):
            self.assertIsNone(keys.poll(1, 9, 0))
        self.assertEqual(keys.phase, "release")

    def test_page_chord_all_modes_has_no_radio_effect(self):
        for mode in (TTL, MAN):
            for subtype in (A1, A2):
                state = Air2State("F", native_mode=mode)
                state.last_manual = subtype
                state.poll_keys(1, 0)
                state.poll_keys(5, 20)
                self.assertEqual(state.poll_keys(5, 30), "page")
                self.assertEqual(state.page, 1)
                self.assertFalse(state.tx.active)
                self.assertEqual((state.mode, state.last_manual), (mode, subtype))


if __name__ == "__main__":
    unittest.main(verbosity=2)
