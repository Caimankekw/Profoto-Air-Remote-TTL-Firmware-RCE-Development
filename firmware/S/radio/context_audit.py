#!/usr/bin/env python3
"""Sony ISR/foreground scratch separation audit. Offline, no firmware mutation."""
from collections import deque
from pathlib import Path
import json
from test_support import CPU as DecoderCPU, IMAGE, VM as vm
from static_isr_audit import SKIPS, BRANCHES

HERE=Path(__file__).resolve().parent
SAVED=set(range(0x6B,0xC1))
HOOKS=(0x4E90,0x4EC0,0x87CC,0x6DDE,0x8062,0x807A,0x8116,0x52DE)
FILE_WRITES={'MOVWF','CLRF','SETF','BSF','BCF','BTG','NEGF'}


def closure():
    c=DecoderCPU(IMAGE);queue=deque([0x4108]);seen=set();direct=[];banked=[];fsr0=[];indirect=[]
    while queue:
        pc=queue.popleft()
        if pc in seen:continue
        seen.add(pc);r=c.decode(pc);op=r.mnemonic;n=pc+r.length;p=r.args
        d=None
        if op=='MOVFF':
            d=p[1]
            if d in SAVED:direct.append(pc)
            if p[0] in range(0xFE9,0xFF0) or d in range(0xFE9,0xFF0):fsr0.append(pc)
        elif op in {*vm.FILE_A.values(),*vm.FILE_DA.values(),*vm.BITS.values()}:
            f=p[0]
            if p[-1]==0 and 0xE9<=f<=0xEF:fsr0.append(pc)
            if op in FILE_WRITES or (op in vm.FILE_DA.values() and p[1]==1):
                if p[-1]==1 and f in SAVED:banked.append(pc)
                elif p[-1]==0:
                    d=f if f<0x60 else f|0xF00
                    if d in SAVED:direct.append(pc)
        if op=='LFSR' and p[0]==0:fsr0.append(pc)
        if d in (*range(0xFDB,0xFE0),*range(0xFE3,0xFE8)):indirect.append(pc)
        if op in ('RETURN','RETLW','RETFIE','RESET'):ds=[]
        elif op in ('GOTO','BRA'):ds=[r.target]
        elif op in BRANCHES|{'CALL','RCALL'}:ds=[r.target,n]
        elif op in SKIPS:ds=[n,n+c.decode(n).length]
        else:ds=[n]
        queue.extend(ds)
    assert direct==[] and sorted(banked)==[0x41BE,0x41F0] and fsr0==[]
    # Each apparent banked94 write is immediately preceded by MOVLB1. Neither
    # path calls another function between setting BSR and the write.
    for pc in banked:
        r=c.decode(pc-2)
        assert r.mnemonic=='MOVLB' and r.args==(1,)
    assert not (seen&set(HOOKS))
    return {'reachable_instructions':len(seen),'direct_writes_in_saved_range':direct,
            'apparent_banked_writes':[{'pc':p,'bsr':1,'actual_address':0x194} for p in sorted(banked)],
            'fsr0_use_sites':fsr0,'indirect_write_sites':sorted(indirect),
            'hook_isr_reachability':{hex(a):a in seen for a in HOOKS}}


def cpu():
    c=vm.CPU(IMAGE)
    c.m[0xD2:0xD4]=bytes((0x93,1));c.m[0x193]=1;c.m[0xC1]=1
    c.m[0xE6:0xEC]=bytes((0,0,0,100,0,4))
    c.m[0x1AC:0x1B2]=bytes((0,0,0,50,0xBB,3))
    return c


def main():
    report=closure();observed={};cases=0
    def record(entry,c,role):
        nonlocal cases
        c.run(entry);cases+=1
        row=observed.setdefault(hex(entry),{'role':role,'cases':0,'saved_range_writes':set(),'fsr0_writes':set()})
        row['cases']+=1
        writes={a for a,v in c.writes}
        row['saved_range_writes']|=writes&SAVED
        row['fsr0_writes']|=writes&set(range(0xFE9,0xFF0))
        if role=='original_ISR_callable':assert not writes&SAVED and not row['fsr0_writes']
    for entry in (0x7584,0x97D8):
        for row in (0x4A,0x4C,0x4E):
            for value in (range(1,101) if entry==0x7584 else (0x19,)):
                c=cpu();c.m[0x6F:0x72]=bytes((0x49,row,value));record(entry,c,'foreground_formatter')
    for mode in (0,1):
        for selected in (1,2,3,7):
            for entry in (0x7B3A,0x5CD8,0x8816):
                c=cpu();c.m[0x193]=mode;c.m[0xC1]=selected;c.w=selected
                record(entry,c,'foreground_state_helper')
    for value in range(256):
        c=cpu();c.w=value;record(0x980C,c,'original_ISR_callable')
        c=cpu();c.w=value;record(0xABD2,c,'original_ISR_callable')
    for value in (0,1):
        for category in range(4):
            c=cpu();c.w=value;c.m[0x23]=category;record(0x7D9E,c,'original_ISR_callable')
    c=cpu();record(0xA5A4,c,'original_ISR_callable')
    for pointer in range(0x251,0x26F):
        c=cpu();c.m[0x3E:0x40]=pointer.to_bytes(2,'little')
        c.allowed_sfr.add(0xF75);c.m[0xF75]=0x55
        record(0x9ABE,c,'original_ISR_callable')
    for row in observed.values():
        row['saved_range_writes']=sorted(row['saved_range_writes'])
        row['fsr0_writes']=sorted(row['fsr0_writes'])
    report.update({'status':'PASS_SONY_ISR_FOREGROUND_CONTEXT_PARTITION','native_execution_cases':cases,
        'observed_native_writes':observed,
        'indirect_target_contracts':[
          {'writers':'4592 printf internal stores','sources':['7D9E uses destination025 and format44EA','980C uses destination024 and format44DF'],
           'bounds':'two-digit unsigned byte hex; output plusNUL lies below02F; all256980C inputs replayed'},
          {'writers':'587A/58C8/6EEE/9074','target':'camera object0193+1 =0194; ISR4142..4162 binds039/03A'},
          {'writers':'5B82/5BC0/6EE8/AD80','target':'handshake byte056 fromISR038 or01 pointer'},
          {'writers':'7002 stores7038/703E/704C/7064','target':'TX descriptorE6..EB,data400..463 orRX descriptor1AC..1B1,data3BB..3EC; init668A..66B4'},
          {'writers':'9D46/9D4E','target':'A906 passesE6; drop queued bytes throughread/count fields'},
          {'writers':'9AC6','target':'SPI pointer3E/3F initialized251 by5BF2, wrapped at26F; all30positions replayed'}],
        'architectural_context':'ISR410A..412E savesFSR1/2,PROD,TBLPTR,TABLAT;4226..424A restores them;4250 RETFIE1 restoresW/STATUS/BSR. NoFSR0 use in closure.',
        'core_write_policy':'runtime_generator.Codegen writesstate_base+offset and architectural W/STATUS/BSR; it does not directly write original06B..C0. Native renderer/state helper scratch overlapsSAVE_REGISTERS by design.',
        'projection_outputs_not_restored':['193mode','197..199FEC','C1selector','CA..CFhandlers','DBhead','F3model','49..53LCD'],
        'recommendation':'No evidence to shrink06B..C0 saves. Keep ISR access scratch001..060 out of foreground save/restore. Preserve proven original pointer bounds and prohibit lifecycle/context helper reentry.',
        'limits':'Static direct-flow closure plus specified native-function replay; not arbitrary corrupt pointer memory or complete hardware ISR simulation.'})
    (HERE/'context_audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('observed_native_writes','indirect_target_contracts')},indent=2))


if __name__=='__main__':main()
