# AIR2-P8 port for Air Remote TTL-S A6

Developer: Caimankekw. Authored code is AGPL-3.0-only; original firmware and third-party material remain subject to their owners' rights.

This independent Sony A6 adapter connects the shared six-group AIR2-P8 core. It does not import the Canon HSS modifications. Sony's original camera protocol, HSS code, RF consumer and scheduler remain unchanged. This directory contains source and offline evidence; it does not establish successful device boot.

## Behavior and implementation

- Retains TTL, MAN/AIR1 and MAN/AIR2. AIR2 displays three absolute targets and sends a complete six-group snapshot after an adjustment.
- C+MODEL selects AIR1/AIR2; C+HEAD selects ABC/DEF. A, B and power +/- do not enter the chord delay.
- ALL affects six groups. TTL ABC uses compensation; DEF uses the remembered manual subtype.
- AIR1 relative values expire through the original idle deadline; AIR2 absolute values remain visible. Displaying DEF never changes the meaning of native camera-facing ABC state.
- A separate two-page journal stores mode, six AIR2 targets, Head/Model states and page. The original settings journal and channel persistence remain intact.

## Source organization

`native_backend.py` connects native state, LCD primitives, six-group rendering and the native queue. `native_hooks.py` connects startup, foreground service, normal keys, power adjustment and display boundaries. `port_profile.json` records addresses and capability evidence. Shared policy and persistence code are in `../shared/`.

`radio/fast_empty_queue.py` admits one complete 17-byte record only when the native queue is empty and camera/RF software gates permit it. A short critical section checks again and publishes the complete record for the original scheduler. Acceptance is not an RF or lamp execution acknowledgement. Native interrupt-driven queue aborts remain authoritative.

Persistence requires released keys and stable software-idle conditions, and checks again before each flash operation. Flash can briefly stall the CPU, and atomic admission adds bounded interrupt latency. Preserving HSS means retaining its algorithm and sending flow, not claiming zero timing overhead. Device boot, keys, six-group control, power-cycle persistence and camera TTL/HSS still require hardware testing.

## Evidence boundaries

The shared audit supports private RAM `0x680..0x7FF` under valid native object/index invariants; this is not a formal proof for corrupted states. New journal pages are `0xF800` and `0xFC00`; native `0x1F800..0x1FBFF` remains unchanged. Family capabilities are cross-checked against original SFR signatures, device definitions and primary datasheets; the exact chip has not been read from a physical unit.

Component tests identify executed original instructions and explicit simulated boundaries. Release qualification must test the exact final linked image; engineering evidence flags in `port_profile.json` alone do not authorize a release.
