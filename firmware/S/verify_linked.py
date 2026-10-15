#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Link and replay Sony in memory; never produce or execute an installer."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'shared'))
from build_variants import link
from test_integrated_firmware import verify_model


def main():
    profile = json.loads((HERE/'port_profile.json').read_text('utf-8'))
    linked = link('S', profile)
    sources = sorted(HERE.rglob('*.py')) + [HERE/'port_profile.json']
    for name in ('runtime_generator.py', 'gesture_runtime_codegen.py',
                 'record_runtime_codegen.py', 'persistence_backend.py', 'pic18_vm.py'):
        sources.append(HERE.parent/'shared'/name)
    report = verify_model('S', linked['image'], linked['mask'], profile,
                          linked['components'], hooks=linked['plan']['hooks'],
                          source_paths=sources)
    report['linked_code_end'] = linked['code_end']
    report['hook_sites'] = [h['address'] for h in linked['plan']['hooks']]
    (HERE/'linked_runtime_tests.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'cases_passed',
        'image_sha256', 'linked_code_end', 'full_integration_pass')}, indent=2))


if __name__ == '__main__':
    main()
