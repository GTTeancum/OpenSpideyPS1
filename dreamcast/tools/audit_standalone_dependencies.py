#!/usr/bin/env python3
"""Inspect actual .NET single-file payloads; fail on an unbundled non-Windows native import.
Requires pefile. Does not execute the target or modify the host runtime.
"""
import argparse, json, struct, zlib
from pathlib import Path
import pefile
SIGNATURE=bytes.fromhex('8b1202b96a612038727b930214d7a03213f5b9e6efae3318ee3b2dce24b36aae')
SYSTEM=set("advapi32 bcrypt bcryptprimitives cabinet cfgmgr32 combase comdlg32 crypt32 cryptnet cryptsp dbghelp dnsapi dwmapi dxgi gdi32 glu32 hid imagehlp imm32 iphlpapi kernel32 mpr mscoree msimg32 msvcrt ncrypt netapi32 normaliz ntdll ole32 oleacc oleaut32 opengl32 powrprof propsys psapi rpcrt4 secur32 setupapi shell32 shlwapi synchronization ucrtbase user32 userenv usp10 uxtheme version winhttp wininet winmm winspool wintrust wldap32 ws2_32 wtsapi32".split())
def audit(exe):
    data=exe.read_bytes(); pos=struct.unpack_from('<Q',data,data.index(SIGNATURE)-8)[0]
    major,minor,count=struct.unpack_from('<IIi',data,pos);pos+=12
    def string():
        nonlocal pos
        size=shift=0
        while True:
            b=data[pos];pos+=1;size|=(b&127)<<shift;shift+=7
            if b<128:break
        value=data[pos:pos+size].decode();pos+=size;return value
    assert major>=6, 'unsupported bundle format'
    bundle=string();pos+=40;entries={}
    for _ in range(count):
        offset,size,compressed=struct.unpack_from('<qqq',data,pos);pos+=25
        entries[string()]=(offset,size,compressed)
    names={Path(name).name.lower() for name in entries};imports={};missing=set()
    payloads={'<apphost>':data}
    for name,(offset,size,compressed) in entries.items():
        if not name.lower().endswith('.dll'):continue
        payload=data[offset:offset+(compressed or size)]
        payloads[name]=zlib.decompress(payload,-15) if compressed else payload
    for name,payload in payloads.items():
        pe=pefile.PE(data=payload,fast_load=True);pe.parse_data_directories(directories=[1,13])
        deps=sorted({x.dll.decode().lower() for x in getattr(pe,'DIRECTORY_ENTRY_IMPORT',[])+getattr(pe,'DIRECTORY_ENTRY_DELAY_IMPORT',[])})
        if not deps:continue
        bundled=[d for d in deps if d in names]; external=[d for d in deps if d not in names]
        missing.update(d for d in external if not d.startswith(('api-ms-win-','ext-ms-win-')) and Path(d).stem not in SYSTEM)
        imports[name]={'bundled':bundled,'system':external}
    for dll in ['vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll']: assert dll in names,dll
    result={'exe':str(exe),'bundleId':bundle,'entries':count,'nativeImports':imports,'unresolvedNonSystem':sorted(missing)}
    assert not missing,result
    return result
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('exe',type=Path,nargs='+');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=[audit(p.resolve()) for p in args.exe];args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2));print('PASS: all native imports resolve to bundled or Windows libraries')
