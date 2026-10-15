#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Executable, target-independent AIR2 behavior contract for F/N/O/S.

This module emits 16-byte native queue *bodies*, never UART frames. It neither
changes HSS nor implements a storage driver. Adapters must supply native clock,
busy gates, native startup values and an enqueue callback. Queue acceptance is
not RF delivery acknowledgement. No addresses, I/O or device operations occur.

Power and FEC units are tenths. Canonical mode is 0=TTL, 1=MAN, independently of
the legacy target's mode encoding. The remembered manual kind is 1=A1, 2=A2.
"""
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

TTL, MAN, A1, A2, ALL = 0, 1, 1, 2, 7
MODEL_TAGS = frozenset("FNOS")
RELATIVE_COMMANDS = {1: 0x06, -1: 0x07, 10: 0x0D, -10: 0x0E}


def _range(value: int, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(name)
    return value


def _values(values: Sequence[int], count: int, low: int, high: int,
            name: str) -> Tuple[int, ...]:
    result = tuple(values)
    if len(result) != count:
        raise ValueError(name)
    return tuple(_range(v, low, high, name) for v in result)


def crc_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


@dataclass(frozen=True)
class NvRecord:
    """V5 candidate record; serializing does not authorize or perform storage."""

    model_tag: str
    mode: int
    last_manual: int
    targets: Tuple[int, ...]
    head_mask: int
    model_mask: int
    page: int
    sequence: int = 0

    def __post_init__(self):
        if self.model_tag not in MODEL_TAGS:
            raise ValueError("model tag")
        _range(self.mode, 0, 1, "mode")
        _range(self.last_manual, 1, 2, "manual kind")
        object.__setattr__(self, "targets", _values(self.targets, 6, 1, 100, "targets"))
        _range(self.head_mask, 0, 0x3F, "head mask")
        _range(self.model_mask, 0, 0x3F, "model mask")
        _range(self.page, 0, 1, "page")
        _range(self.sequence, 0, 0xFFFF, "sequence")

    def encode(self) -> bytes:
        data = bytearray(32)
        data[:3] = b"A2\x05"
        data[3] = 0 if self.mode == TTL else self.last_manual
        data[4:6] = self.sequence.to_bytes(2, "little")
        data[6:12] = bytes(self.targets)
        data[12:17] = bytes((self.head_mask, self.model_mask, self.page,
                             self.last_manual, ord(self.model_tag)))
        data[28:30] = crc_ccitt_false(data[:28]).to_bytes(2, "little")
        data[30:32] = bytes.fromhex("5a a5")
        return bytes(data)

    @classmethod
    def decode(cls, data: bytes, model_tag: str) -> "NvRecord":
        if model_tag not in MODEL_TAGS:
            raise ValueError("expected model tag")
        if len(data) != 32 or data[:3] != b"A2\x05" or data[30:] != b"\x5a\xa5":
            raise ValueError("record envelope")
        if data[16] != ord(model_tag) or any(data[17:28]):
            raise ValueError("record model/reserved bytes")
        if int.from_bytes(data[28:30], "little") != crc_ccitt_false(data[:28]):
            raise ValueError("record CRC")
        effective = data[3]
        if effective not in (0, 1, 2) or (effective and effective != data[15]):
            raise ValueError("record effective mode")
        return cls(model_tag, TTL if effective == 0 else MAN, data[15],
                   tuple(data[6:12]), data[12], data[13], data[14],
                   int.from_bytes(data[4:6], "little"))


def group_command(group: int, command: int) -> bytes:
    _range(group, 1, 6, "physical group")
    if command not in (0, 1, 2, 3, 6, 7, 13, 14):
        raise ValueError("group command")
    return bytes((group, 0xFF, 0xFF, 0xFF, 1, command, group)) + bytes(9)


def absolute_snapshot(targets: Sequence[int], head_mask: int, model_mask: int) -> bytes:
    targets = _values(targets, 6, 1, 100, "targets")
    _range(head_mask, 0, 0x3F, "head mask")
    _range(model_mask, 0, 0x3F, "model mask")
    return bytes((0x27, 0xFF, 0xFF, 0xFF, 1, 0x11, *targets,
                  head_mask, model_mask, 0, 0))


def fec_snapshot(fec: Sequence[int]) -> bytes:
    fec = _values(fec, 3, -20, 20, "FEC")
    return bytes((0x27, 0xFF, 0xFF, 0xFF, 1, 0x25,
                  *(v & 0xFF for v in fec))) + bytes(7)


class TxPlan:
    """One immutable, ordered edit plan. Retry exactly the unaccepted body."""

    def __init__(self):
        self._packets: Tuple[bytes, ...] = ()
        self._next = 0
        self.native_domain = None
        self._admitted: List[bytes] = []
        self._revision = 0

    @property
    def active(self) -> bool:
        return self._next < len(self._packets)

    @property
    def pending(self) -> Tuple[bytes, ...]:
        return self._packets[self._next:]

    @property
    def admitted(self) -> Tuple[bytes, ...]:
        return tuple(self._admitted)

    def begin(self, packets: Sequence[bytes], *, native_domain=None):
        if self.active:
            raise RuntimeError("active TX plan")
        bodies = tuple(bytes(packet) for packet in packets)
        if any(len(packet) != 16 for packet in bodies):
            raise ValueError("native queue body must be 16 bytes")
        self._packets, self._next = bodies, 0
        self.native_domain = None if native_domain is None else tuple(native_domain)
        self._admitted = []
        self._revision += 1

    def cancel_unadmitted(self) -> Tuple[bytes, ...]:
        """Drop only the unsent tail. There is deliberately no queue retract API."""
        cancelled = self.pending
        self._packets, self._next = (), 0
        self._revision += 1
        return cancelled

    def pump(self, enqueue: Callable[[bytes], bool], *, native_domain=None) -> bool:
        """Attempt at most one body; false/exception leaves the same body pending."""
        if not self.active:
            return False
        if native_domain is not None and native_domain != self.native_domain:
            self.cancel_unadmitted()
            return False
        body, revision = self._packets[self._next], self._revision
        if not enqueue(body):
            return False
        self._admitted.append(body)
        if revision == self._revision:
            self._next += 1
        return True


@dataclass(frozen=True)
class NativeProjection:
    """RAM projection request, never an RF request.

    fields: 1=mode, 2=ABC FEC, 4=selector, 8=ABC Head/Model. Zero is a
    no-native-field edit admission check. Callback false/exception MUST mean
    no native writes occurred; host rollback cannot undo a partial backend.
    """

    fields: int
    mode: int
    selected: int
    fec: Tuple[int, int, int]
    head_abc: int
    model_abc: int


@dataclass(frozen=True)
class ServiceResult:
    admitted: bool
    cancelled: Tuple[bytes, ...]
    nv_candidate: Optional[bytes]
    nv_reason: str


@dataclass(frozen=True)
class DisplayRow:
    group: str
    domain: str
    value: Optional[int]
    text: str
    head_on: bool
    model_on: bool
    selected: bool


class Air2State:
    """Pure UI/radio/NV contract. Native HSS remains entirely outside this API."""

    storage_backend_enabled = False

    def __init__(self, model_tag: str, *, native_mode: int = MAN,
                 native_head_abc: int = 7, native_model_abc: int = 0,
                 native_fec: Sequence[int] = (0, 0, 0),
                 native_selected: int = ALL, nv_record: Optional[bytes] = None,
                 native_clock_mask: Optional[int] = None,
                 native_window_counts: int = 200,
                 native_stable_counts: Optional[int] = None,
                 apply_native_state: Optional[Callable[[NativeProjection], bool]] = None):
        if model_tag not in MODEL_TAGS:
            raise ValueError("model tag")
        self.model_tag = model_tag
        self.mode = _range(native_mode, 0, 1, "native mode")
        self.native_domain = (native_mode, 0)
        self._native_revision = 0
        self._apply_native_state = apply_native_state
        # As in P8 first install, preserve native ABC and leave DEF disabled.
        self.head_mask = _range(native_head_abc, 0, 7, "native Head ABC")
        self.model_mask = _range(native_model_abc, 0, 7, "native Model ABC")
        self.fec = list(_values(native_fec, 3, -20, 20, "native FEC"))
        if type(native_selected) is not int or native_selected not in (1, 2, 3, ALL):
            raise ValueError("native selected row")
        self.last_manual, self.page, self.selected = A1, 0, native_selected
        self.targets, self.relative = [50] * 6, [0] * 6
        self.visible_mask, self.sequence, self.nv_dirty = 0, 0, False
        self.native_busy, self.camera_busy = False, False
        self._dispatching_gesture = False
        # Defaults mirror the reviewed per-mount profiles; custom clock proofs
        # may explicitly supply different counts. These are not milliseconds.
        if native_clock_mask is None:
            native_clock_mask = 0xFFFF if model_tag == 'N' else 0x7FFF
        if native_stable_counts is None:
            native_stable_counts = 20 if model_tag == 'N' else 10
        self.tx = TxPlan()
        self.gestures = GestureClassifier(clock_mask=native_clock_mask,
                                         window_counts=native_window_counts,
                                         stable_counts=native_stable_counts)
        self.nv_loaded = False
        if nv_record is not None:
            try:
                record = NvRecord.decode(nv_record, model_tag)
            except ValueError:
                pass  # Bad/incompatible data never overrides native startup state.
            else:
                self.mode, self.last_manual, self.page = record.mode, record.last_manual, record.page
                self.targets = list(record.targets)
                self.head_mask, self.model_mask = record.head_mask, record.model_mask
                self.sequence, self.nv_loaded = record.sequence, True

    @property
    def busy(self) -> bool:
        return self.native_busy or self.camera_busy or self.tx.active

    @property
    def domain_token(self) -> Tuple[int, int, int, int]:
        return self.mode, self.last_manual, self.page, self.selected

    def capture_record(self, sequence: Optional[int] = None) -> bytes:
        """Capture only. No NVM driver, write, sequence advance or dirty clear."""
        return NvRecord(self.model_tag, self.mode, self.last_manual, tuple(self.targets),
                        self.head_mask, self.model_mask, self.page,
                        self.sequence if sequence is None else sequence).encode()

    def pump_tx(self, enqueue: Callable[[bytes], bool]) -> bool:
        if self.native_busy or self.camera_busy or self.mode != self.native_domain[0]:
            return False
        return self.tx.pump(enqueue, native_domain=self.native_domain)

    def project_native_startup(self) -> bool:
        """Explicit optional RAM projection handshake after NV restoration.

        This is not an NV write or RF update. Until an accepted projection or
        a fresh native snapshot reconciles a restored mode mismatch, edits/TX
        and NV candidates stay gated. A missing callback simulates acceptance
        only in this pure reference model, never a hardware proof.
        """
        if self.busy or self.gestures.phase != "idle":
            return False
        return self._project_or_restore(self._canonical_before(), 1 | 4 | 8)

    def observe_native_domain(self, mode: int, *, context: Optional[int] = None,
                              native_tick: Optional[int] = None) -> Tuple[bytes, ...]:
        """Reconcile an external camera/native snapshot before servicing TX.

        context is a caller-owned camera/context generation, not queue depth or
        a busy flag. Advance it for same-mode camera requests and mode round
        trips between snapshots. Native mode wins without calling projection.
        Frames already admitted remain owned by the original native scheduler.
        """
        mode = _range(mode, 0, 1, "observed native mode")
        context = self.native_domain[1] if context is None else _range(context, 0, 0xFFFFFFFF, "native context")
        domain = mode, context
        changed = domain != self.native_domain or self.mode != mode
        cancelled = ()
        if changed:
            self._native_revision += 1
            cancelled = self.tx.cancel_unadmitted()
            self.cancel_secondary(self.gestures.last_tick if native_tick is None else native_tick)
            mode_changed = self.mode != mode
            self.mode, self.native_domain = mode, domain
            if mode_changed:
                if mode == MAN and self.last_manual == A1:
                    self._clear_relative()
                self.nv_dirty = True
        return cancelled

    def service_once(self, enqueue: Callable[[bytes], bool], *, native_mode: Optional[int] = None,
                     native_context: Optional[int] = None, nv_backend_proven: bool = False,
                     fresh_nv_ready: Optional[Callable[[], bool]] = None) -> ServiceResult:
        """One queue attempt; optionally produce an NV *candidate*, never write.

        nv_backend_proven is an externally established precondition, not proof
        supplied by this model. Storage remains absent. Even the final accepted
        frame forbids NV this round. A fresh readiness callback is queried only
        after TX decisions, and busy/domain conditions are checked again after
        it. Candidate capture does not advance sequence or clear dirty state.
        """
        cancelled = ()
        if native_mode is not None or native_context is not None:
            cancelled = self.observe_native_domain(
                self.native_domain[0] if native_mode is None else native_mode,
                context=native_context)
        if self.mode != self.native_domain[0]:
            return ServiceResult(False, cancelled, None, "native_mode_unreconciled")
        admitted = self.pump_tx(enqueue)
        if admitted:
            return ServiceResult(True, cancelled, None, "admitted_this_round")
        if self.busy or self.gestures.phase != "idle":
            return ServiceResult(False, cancelled, None, "busy")
        if not nv_backend_proven:
            return ServiceResult(False, cancelled, None, "storage_unproved")
        if not self.nv_dirty:
            return ServiceResult(False, cancelled, None, "clean")
        domain, revision = self.native_domain, self._native_revision
        if fresh_nv_ready is None or not fresh_nv_ready():
            return ServiceResult(False, cancelled, None, "not_fresh_ready")
        if (self.busy or self.gestures.phase != "idle" or self.native_domain != domain
                or self._native_revision != revision):
            return ServiceResult(False, cancelled, None, "readiness_changed")
        return ServiceResult(False, cancelled, self.capture_record((self.sequence + 1) & 0xFFFF), "candidate_only")

    def _domain(self, group: int) -> str:
        if self.mode == TTL and group < 3:
            return "FEC"
        return "ABS" if self.last_manual == A2 else "REL"

    def _groups(self, enabled: bool = False) -> List[int]:
        groups = range(6) if self.selected == ALL else (self.page * 3 + self.selected - 1,)
        return [g for g in groups if not enabled or self.head_mask & (1 << g)]

    def _clear_relative(self):
        self.relative[:] = [0] * 6
        self.visible_mask = 0

    def _canonical_before(self):
        return (self.mode, self.last_manual, self.page, self.selected, self.head_mask,
                self.model_mask, tuple(self.targets), tuple(self.relative), tuple(self.fec),
                self.visible_mask, self.nv_dirty, self.native_domain, self._native_revision)

    def _restore_canonical(self, before):
        (self.mode, self.last_manual, self.page, self.selected, self.head_mask,
         self.model_mask, targets, relative, fec, self.visible_mask, self.nv_dirty,
         prior_domain, prior_revision) = before
        self.targets[:], self.relative[:], self.fec[:] = targets, relative, fec
        if self.native_domain != prior_domain or self._native_revision != prior_revision:
            # Roll back the host edit, never roll back an intervening camera
            # mode/context event. A backend must still satisfy atomic W=0.
            previous_mode = self.mode
            self.mode = self.native_domain[0]
            if self.mode != previous_mode:
                self.nv_dirty = True
                if self.mode == MAN and self.last_manual == A1:
                    self._clear_relative()

    def _project_or_restore(self, before, fields: int) -> bool:
        request = NativeProjection(fields, self.mode, self.selected, tuple(self.fec),
                                   self.head_mask & 7, self.model_mask & 7)
        try:
            accepted = self._apply_native_state is None or self._apply_native_state(request)
        except Exception:
            self._restore_canonical(before)
            raise
        if not accepted or self.native_domain != before[-2] or self._native_revision != before[-1]:
            self._restore_canonical(before)
            return False
        if fields & 1:
            self.native_domain = self.mode, self.native_domain[1]
        return True

    def _ready_edit(self) -> bool:
        if self.busy or self.mode != self.native_domain[0]:
            return False
        if not self._dispatching_gesture and self.gestures.phase != "idle":
            # An extra direct key during secondary arbitration cancels the
            # entire gesture; it must not leak either the first or second key.
            if self.gestures.phase == "pending":
                self.gestures.cancel(self.gestures.last_tick)
            return False
        return True

    def cancel_secondary(self, native_tick: int):
        """Native camera/context event, including a same-mode camera request."""
        if self.gestures.phase != "idle":
            self.gestures.cancel(native_tick)

    def select(self, local_row: int) -> bool:
        if local_row not in (1, 2, 3, ALL):
            raise ValueError("local row")
        if not self._ready_edit():
            return False
        before = self._canonical_before()
        self.selected = ALL if self.selected == local_row else local_row
        if self._domain(self.page * 3) == "REL":
            self._clear_relative()
        return self._project_or_restore(before, 4)

    def toggle_page(self) -> bool:
        if not self._ready_edit():
            return False
        before = self._canonical_before()
        self.page ^= 1
        if not self._project_or_restore(before, 0):
            return False
        self.nv_dirty = True
        return True

    def toggle_mode(self) -> bool:
        if not self._ready_edit():
            return False
        before = self._canonical_before()
        self.mode ^= 1
        if self.mode == MAN and self.last_manual == A1:
            self._clear_relative()
        if not self._project_or_restore(before, 1):
            return False
        self.nv_dirty = True
        return True

    def toggle_manual(self) -> bool:
        if not self._ready_edit() or self.mode == TTL:
            return False
        before = self._canonical_before()
        self.last_manual ^= 3
        if self.last_manual == A1:
            self._clear_relative()
        if not self._project_or_restore(before, 0):
            return False
        self.nv_dirty = True
        return True

    def native_idle(self) -> bool:
        """Called by the original idle deadline, never by an invented timeout."""
        if self.busy or self.last_manual != A1:
            return False
        changed = bool(self.visible_mask or any(self.relative))
        self._clear_relative()
        return changed

    def edit_power(self, step: int) -> bool:
        if step not in RELATIVE_COMMANDS:
            raise ValueError("step must be +/-1 or +/-10")
        if not self._ready_edit():
            return False
        groups = self._groups(enabled=True)
        if not groups:
            return False
        before = self._canonical_before()
        edits = []
        for group in groups:
            domain = self._domain(group)
            values, low, high = {"FEC": (self.fec, -20, 20),
                                 "ABS": (self.targets, 1, 100),
                                 "REL": (self.relative, -99, 99)}[domain]
            value = values[group] + step
            if not low <= value <= high:
                return False  # All-or-nothing, including mixed TTL ALL.
            edits.append((group, domain, values, value))
        for group, domain, values, value in edits:
            values[group] = value
            if domain == "REL":
                self.visible_mask |= 1 << group
        if not self._project_or_restore(before, 2 if any(edit[1] == "FEC" for edit in edits) else 0):
            return False
        packets = []
        if any(domain == "FEC" for _, domain, _, _ in edits):
            packets.append(fec_snapshot(self.fec))
        if any(domain == "ABS" for _, domain, _, _ in edits):
            # TTL DEF still sends ABC fields, masks and DEF targets: not a
            # per-group command, and not an assertion of zero ABC RF effect.
            packets.append(absolute_snapshot(self.targets, self.head_mask, self.model_mask))
        for group, domain, _, _ in edits:
            if domain == "REL":
                packets.append(group_command(group + 1, RELATIVE_COMMANDS[step]))
        self.tx.begin(packets, native_domain=self.native_domain)
        self.nv_dirty = True
        return True

    def toggle_switch(self, kind: str) -> bool:
        if kind not in ("head", "model"):
            raise ValueError("switch kind")
        if not self._ready_edit():
            return False
        before = self._canonical_before()
        mask = self.head_mask if kind == "head" else self.model_mask
        groups = self._groups()
        mask = (0 if mask == 0x3F else 0x3F) if self.selected == ALL else mask ^ (1 << groups[0])
        if kind == "head":
            self.head_mask = mask
        else:
            self.model_mask = mask
        if not self._project_or_restore(before, 8):
            return False
        packets = []
        for group in groups:
            on = bool(mask & (1 << group))
            packets.append(group_command(group + 1, (0 if on else 1) if kind == "head"
                                         else (2 if on else 3)))
            if kind == "head" and on:
                packets.append(group_command(group + 1, 2 if self.model_mask & (1 << group) else 3))
        self.tx.begin(packets, native_domain=self.native_domain)
        self.nv_dirty = True
        return True

    def display(self) -> Tuple[DisplayRow, ...]:
        rows = []
        for local in range(3):
            group = self.page * 3 + local
            domain = self._domain(group)
            head, model = bool(self.head_mask & (1 << group)), bool(self.model_mask & (1 << group))
            value = {"FEC": self.fec, "ABS": self.targets, "REL": self.relative}[domain][group]
            if not head:
                text, visible_value = "--", None
            elif domain == "REL" and not self.visible_mask & (1 << group):
                text, visible_value = "", None
            else:
                visible_value = value
                text = ("" if domain == "ABS" else ("+" if value >= 0 else "-")) + "%d.%d" % (abs(value) // 10, abs(value) % 10)
            rows.append(DisplayRow("ABCDEF"[group], domain, visible_value, text, head,
                                   model, self.selected in (local + 1, ALL)))
        return tuple(rows)

    def poll_keys(self, raw: int, native_tick: int, *, first: Optional[int] = None) -> Optional[str]:
        """Only C/MODEL/HEAD. A/B/+/- use select/edit_power directly."""
        action = self.gestures.poll(raw, native_tick, self.domain_token, busy=self.busy, first=first)
        self._dispatching_gesture = True
        try:
            if action == "select_c":
                self.select(3)
            elif action == "model":
                self.toggle_switch("model")
            elif action == "head":
                self.toggle_switch("head")
            elif action == "page":
                self.toggle_page()
            elif action == "manual":
                if self.mode == TTL:
                    return "swallowed"
                self.toggle_manual()
        finally:
            self._dispatching_gesture = False
        return action


class GestureClassifier:
    """Nonblocking P8 key arbitration over caller-supplied native clock counts.

    Raw bit1=C, bit2=MODEL, bit4=HEAD. The two latter bits are logical results
    of a target ADC decoder, not proof they can coexist electrically. Inputs
    6/7, other-key 0x80, and fault 0xFF cancel. Only 3 and 5 are chords.
    Tick input is uint16. Default elapsed uses P8's 0x7FFF native half-ring;
    a separately proven target may explicitly use clock_mask=0xFFFF. Neither
    choice asserts the new target clock has been verified. Counts have no
    asserted conversion to milliseconds.
    """

    WINDOW, STABLE, STALL_POLLS = 200, 10, 4096
    SINGLE = {1: "select_c", 2: "model", 4: "head"}

    def __init__(self, *, clock_mask: int = 0x7FFF,
                 window_counts: int = 200, stable_counts: int = 10):
        if clock_mask not in (0x7FFF, 0xFFFF):
            raise ValueError("native clock mask")
        self.clock_mask = clock_mask
        self.WINDOW = _range(window_counts, 1, clock_mask, "native gesture window")
        self.STABLE = _range(stable_counts, 1, clock_mask, "native gesture stability")
        self.phase = "idle"
        self.first, self.started, self.candidate, self.stable_since = 0, 0, 0, 0
        self.domain = None
        self.last_tick, self.stalled = 0, 0

    def elapsed(self, now: int, then: int) -> int:
        return (now - then) & self.clock_mask

    def _latch(self, tick: int):
        self.phase, self.candidate, self.stable_since = "release", 0xFF, tick

    def cancel(self, native_tick: int):
        self._latch(_range(native_tick, 0, 0xFFFF, "native clock"))

    def _dispatch(self, action: str, tick: int) -> str:
        self._latch(tick)
        return action

    def poll(self, raw: int, native_tick: int, domain, *, busy: bool = False,
             first: Optional[int] = None) -> Optional[str]:
        _range(raw, 0, 0xFF, "raw key pattern")
        tick = _range(native_tick, 0, 0xFFFF, "native clock")
        if self.phase == "release":
            if raw != 0:
                self.candidate = 0xFF
            elif self.candidate != 0:
                self.candidate, self.stable_since = 0, tick
            elif self.elapsed(tick, self.stable_since) >= self.STABLE:
                self.phase = "idle"
            return None
        if self.phase == "idle":
            if raw == 0 and first is None:
                return None
            first_key = first if first is not None else (1 if raw in (3, 5) else raw)
            if raw not in (0, 1, 2, 3, 4, 5) or first_key not in self.SINGLE or (raw and not raw & first_key) or busy:
                self._latch(tick)
                return None
            self.phase, self.first, self.started = "pending", first_key, tick
            self.candidate, self.stable_since, self.domain = raw, tick, domain
            self.last_tick, self.stalled = tick, 0
            return None
        if tick == self.last_tick:
            self.stalled += 1
        else:
            self.last_tick, self.stalled = tick, 0
        if busy or domain != self.domain or self.stalled >= self.STALL_POLLS or raw not in (0, 1, 2, 3, 4, 5):
            self._latch(tick)
            return None
        if raw != self.candidate:
            if self.candidate in (3, 5):
                self._latch(tick)
                return None  # A chord cannot degrade or switch to another chord.
            if raw in (3, 5):
                if not raw & self.first:
                    self._latch(tick)
                    return None
                if self.elapsed(tick, self.started) >= self.WINDOW:
                    return self._dispatch(self.SINGLE[self.first], tick)
            elif raw not in (0, self.first):
                self._latch(tick)
                return None
            self.candidate, self.stable_since = raw, tick
            return None
        if self.elapsed(tick, self.stable_since) < self.STABLE:
            return None
        if raw == 0:
            # The release itself is already stable: accept the next press
            # immediately, without inventing a second release delay.
            self.phase = "idle"
            return self.SINGLE[self.first]
        if raw in (3, 5):
            return self._dispatch("manual" if raw == 3 else "page", tick)
        if self.elapsed(tick, self.started) >= self.WINDOW:
            return self._dispatch(self.SINGLE[self.first], tick)
        return None
