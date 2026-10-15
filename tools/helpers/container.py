# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Strict read-only Intel HEX parser, adapted from the C11 container helper.

Adapted from the project's authored c11_container_roundtrip.py and container.py.
The original updater is read as data and never executed. Container replacement
methods are omitted from this read-only tool. This parser does not establish
device acceptance, bootability, or vendor endorsement.
"""
from dataclasses import dataclass
import hashlib
import json
import re


LAYOUT_SHA256 = "59e18b8641506461cfe137ab5103cf7e1fa5c6b2c9a706b365117a94740a71bb"
SPANS = [(0x4000, 0x1FC10), (0x1FFF0, 0x20000)]


class RepackError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RepackError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Record:
    index: int
    offset: int
    original: bytes
    ending: bytes
    raw: bytes
    kind: int
    address: int
    absolute: object

    @property
    def count(self):
        return self.raw[0]

    @property
    def payload(self):
        return self.raw[4:-1]


class HexImage:
    """Retain sparse addresses, record order, spelling and line endings."""

    def __init__(self, text):
        require(isinstance(text, bytes), "HEX input must be bytes")
        require(bool(text), "Empty HEX")
        self.text = text
        self.records = []
        self.memory = {}
        upper, offset, eof = 0, 0, False
        for number, line in enumerate(text.splitlines(keepends=True), 1):
            require(not eof, "Record or extra line after EOF")
            ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
            content = line[:-len(ending)] if ending else line
            require(re.fullmatch(rb":[0-9a-fA-F]+", content) is not None,
                    "Invalid HEX spelling at line %d" % number)
            require((len(content) - 1) % 2 == 0, "Odd HEX digit count")
            raw = bytes.fromhex(content[1:].decode("ascii"))
            require(len(raw) >= 5 and len(raw) == raw[0] + 5, "Wrong HEX byte count")
            require(sum(raw) % 256 == 0, "Bad HEX checksum at line %d" % number)
            count, address, kind = raw[0], int.from_bytes(raw[1:3], "big"), raw[3]
            payload, absolute = raw[4:-1], None
            if kind == 0:
                require(address + count <= 0x10000, "Data record crosses 64 KiB boundary")
                absolute = upper + address
                for i, value in enumerate(payload):
                    require(absolute + i not in self.memory, "Overlapping HEX address")
                    self.memory[absolute + i] = value
            elif kind in (2, 4):
                require(count == 2 and address == 0, "Invalid extended-address record")
                upper = int.from_bytes(payload, "big") << (4 if kind == 2 else 16)
            elif kind == 1:
                require(count == 0 and address == 0, "Invalid EOF record")
                eof = True
            else:
                raise RepackError("Unsupported HEX type %d; not silently discarded" % kind)
            self.records.append(Record(number, offset, line, ending, raw, kind, address, absolute))
            offset += len(line)
        require(eof, "Missing EOF")
        require(bool(self.memory), "HEX contains no data")

    def layout(self):
        return [(r.kind, r.address, r.count, r.absolute, r.ending,
                 r.payload if r.kind != 0 else None) for r in self.records]

    def layout_sha256(self):
        rows = [[r.kind, r.address, r.count, r.absolute, r.ending.hex(),
                 r.payload.hex() if r.kind else None] for r in self.records]
        return sha(json.dumps(rows, separators=(",", ":")).encode("ascii"))

    def spans(self):
        ordered = sorted(self.memory)
        start = last = ordered[0]
        result = []
        for address in ordered[1:]:
            if address != last + 1:
                result.append((start, last + 1))
                start = address
            last = address
        result.append((start, last + 1))
        return result

