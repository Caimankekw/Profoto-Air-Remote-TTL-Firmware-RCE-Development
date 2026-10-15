#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Two-pass O AIR2 component assembly. No executable/image is written here."""
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'shared'))
import runtime_generator
import persistence_backend
import native_backend
import native_hooks


def construct(original, *, profile, persistence_proof=None, code_base=0xABF0):
    """Root packager must independently enforce all reported proof statuses."""
    if code_base<0xABF0 or code_base&1: raise ValueError('unproved original code overlap')
    core0=runtime_generator.construct(original,code_base=code_base,profile=profile,
            backend={name:0x4000 for name in runtime_generator.IMPORTS})
    cursor=code_base+len(core0['sections'][0]['data'])
    backend=native_backend.construct(original,code_base=cursor,profile=profile,
                                    imports={'display_row':core0['exports']['display_row']})
    cursor+=len(backend['sections'][0]['data'])
    persistence=persistence_backend.construct(original,code_base=cursor,profile=profile,
            imports={'read_inputs':backend['exports']['read_inputs']},
            backend={'persistence':dict(persistence_proof or {})})
    cursor+=sum(len(s['data']) for s in persistence['sections'])
    imports=dict(backend['exports'])
    imports.update(persistence['exports'])
    core=runtime_generator.construct(original,code_base=code_base,profile=profile,backend=imports)
    if core['exports']!=core0['exports'] or len(core['sections'][0]['data'])!=len(core0['sections'][0]['data']):
        raise ValueError('core two-pass layout changed')
    hooks=native_hooks.construct(original,code_base=cursor,profile=profile,
                                imports={**core['exports'],**backend['exports']})
    components={'core':core,'backend':backend,'persistence':persistence,'hooks':hooks}
    sections=[s for c in components.values() for s in c['sections']]
    cursor=max(s['address']+len(s['data']) for s in sections)
    if cursor>profile['code_limit']: raise ValueError('complete O adapter exceeds code limit')
    for section in sections:
        off=section['address']-0x4000
        if original[off:off+len(section['data'])]!=b'\xff'*len(section['data']):
            raise ValueError('component is not within known erased image extent')
    unresolved=[name+':'+item for name,c in components.items() for item in c.get('unresolved_imports',[])]
    return {'sections':sections,'hooks':hooks['hooks'],
            'exports':core['exports'],'components':components,
            'protected_ranges':hooks['protected_ranges'],
            'reserved_ram':[{'start':profile['state_base'],'end':profile['state_base']+0x180,
                             'owner':'O AIR2 shared core/backend/hooks'}],
            'unresolved_imports':unresolved,
            'metadata':{'model_tag':'O','code_range':[code_base,cursor],
                        'native_hss_implementation_replaced':False,
                        'hardware_accessed':False,
                        'hardware_boot_verified':False,
                        'qualification_is_root_packager_responsibility':True}}
