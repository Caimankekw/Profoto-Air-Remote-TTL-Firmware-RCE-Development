#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Link and replay the full Nikon port with real shared journal code, in RAM."""
from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent/'shared'
sys.path.insert(0,str(SHARED))
from build_variants import link
import test_integrated_firmware as verifier


def main():
    profile=json.loads((HERE/'port_profile.json').read_text('utf-8'))
    result=link('N',profile)
    # Explicit peripheral idle inputs, not successful helper replacements:
    # no pending hotshoe interrupt, no UART RX pending, TX shift register empty.
    verifier.MODEL['N']['defaults'].update({0xFF0:0,0xF9E:0,0xFAD:2})
    sources=[SHARED/name for name in ('runtime_generator.py','gesture_runtime_codegen.py',
                                     'record_runtime_codegen.py','persistence_backend.py')]
    sources += [HERE/'native_backend.py',HERE/'native_hooks.py',HERE/'port_profile.json']
    report=verifier.verify_model('N',result['image'],result['mask'],profile,result['components'],
                                hooks=result['components']['hooks']['hooks'],source_paths=sources)
    report['code_end_exclusive']=result['code_end']
    report['installer_generated']=False
    (HERE/'full_linked_replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'cases':report['cases_passed'],
                      'code_end':hex(result['code_end']),'image_sha256':report['image_sha256']},indent=2))


if __name__=='__main__':
    main()
