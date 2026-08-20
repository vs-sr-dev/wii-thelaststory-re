"""Parses the RSO relocations and shows what the Tools_*Exec thunks import.
For each exported function it reveals which import (a main.dol function) it calls."""
import os
import sys
import struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

path = os.path.join(os.environ.get('TLS_ROOT', '.'), 'extract', 'files', 'LastWorld_tools.rso')
d = open(path, 'rb').read()
u32 = lambda o: struct.unpack('>I', d[o:o+4])[0]

hdr = dict(
    exportTableOffset=u32(0x40), exportTableSize=u32(0x44), exportTableNameOff=u32(0x48),
    importTableOffset=u32(0x4C), importTableSize=u32(0x50), importTableNameOff=u32(0x54),
    internalRelOffset=u32(0x30), internalRelSize=u32(0x34),
    externalRelOffset=u32(0x38), externalRelSize=u32(0x3C),
    sectionInfoOffset=u32(0x58), sectionCount=u32(0x08),
)

def cstr(base, rel):
    a = base + rel
    end = d.index(b'\x00', a)
    return d[a:end].decode('ascii', 'replace')

# sections
secs = []
for i in range(hdr['sectionCount']):
    o = u32(hdr['sectionInfoOffset']+i*8) & ~1
    s = u32(hdr['sectionInfoOffset']+i*8+4)
    secs.append((o, s))

# import: 12 bytes (nameOff, relOff, ?) -> name
imports = []
it, isz, ino = hdr['importTableOffset'], hdr['importTableSize'], hdr['importTableNameOff']
for k, o in enumerate(range(it, it+isz, 12)):
    imports.append(cstr(ino, u32(o)))

# export: 16 bytes (nameOff, offset, section, hash)
exports = []
et, esz, eno = hdr['exportTableOffset'], hdr['exportTableSize'], hdr['exportTableNameOff']
for o in range(et, et+esz, 16):
    exports.append((cstr(eno, u32(o)), u32(o+8), u32(o+4), u32(o+12)))  # name, sec, off, hash

# external relocations: REL format (u32 offset, u32 info, u32 addend) — 12 bytes
# info: (type<<0)|(section<<8)? In REL: r_offset, r_info(type|sym<<8), addend.
# For RSO the external ones reference the import index. Try (offset, type, symIdx, addend)?
print('=== external relocations (raw, 8-byte REL entries: off, info) ===')
er, ersz = hdr['externalRelOffset'], hdr['externalRelSize']
# try 8-byte entries: off(u32), info(u32) with type=info>>24? or info&0xff
# In OS REL: struct { u16 offset; u8 type; u8 section; u32 addend; } = 8 bytes
def show(entsize, layout):
    print(f'-- entry {entsize}b {layout} --')
    for o in range(er, min(er+ersz, er+8*20), entsize):
        if layout == 'rel8':
            off = struct.unpack('>H', d[o:o+2])[0]
            typ = d[o+2]; sec = d[o+3]; add = u32(o+4)
            print(f'  off={off:#06x} type={typ:3d} sec={sec} addend={add:#x}')
show(8, 'rel8')

print('\n=== EXPORT -> minimal disassembly (the thunk\'s first instructions) ===')
def dis_branch(addr_in_sec1):
    # section 1 file base = secs[1][0]
    fo = secs[1][0] + addr_in_sec1
    out = []
    for i in range(6):
        w = u32(fo + i*4)
        op = w >> 26
        mn = f'{w:#010x}'
        if op == 18:  # b/bl
            li = w & 0x03fffffc
            if li & 0x02000000: li -= 0x04000000
            lk = w & 1
            mn = f'{"bl" if lk else "b"} {li:+#x}'
        elif op == 16:
            mn = 'bc...'
        elif w == 0x4e800020:
            mn = 'blr'
        out.append(f'    +{addr_in_sec1+i*4:#05x}: {mn}')
        if w == 0x4e800020: break
    return '\n'.join(out)

for name, sec, off, h in sorted(exports, key=lambda e: e[2]):
    if name.startswith('Tools_DebugMenu') or name == 'Tools_NekoRegisterGameHandlers':
        print(f'  {name} (sec{sec}+{off:#x}):')
        print(dis_branch(off))

print('\ntotal imports:', len(imports))
for i, n in enumerate(imports):
    if 'SequenceDebugMenu' in n or 'DebugMenu' in n:
        print(f'  import[{i}] = {n}')
