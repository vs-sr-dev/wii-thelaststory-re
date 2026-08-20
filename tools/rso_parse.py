"""Parser for the RSO format (Relocatable Shared Object, GameCube/Wii), for LastWorld_tools.rso."""
import os
import sys
import struct, sys

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get('TLS_ROOT', '.'), 'extract', 'files', 'LastWorld_tools.rso')
d = open(path, 'rb').read()
u32 = lambda o: struct.unpack('>I', d[o:o+4])[0]
u8 = lambda o: d[o]

print(f'file size: {len(d):#x} ({len(d)})')
h = {
    'next': u32(0x00), 'prev': u32(0x04),
    'sectionCount': u32(0x08), 'sectionInfoOffset': u32(0x0C),
    'nameOffset': u32(0x10), 'nameSize': u32(0x14),
    'version': u32(0x18), 'bssSize': u32(0x1C),
    'prologSection': u8(0x20), 'epilogSection': u8(0x21),
    'unresolvedSection': u8(0x22), 'bssSection': u8(0x23),
    'prolog': u32(0x24), 'epilog': u32(0x28), 'unresolved': u32(0x2C),
    'internalRelOffset': u32(0x30), 'internalRelSize': u32(0x34),
    'externalRelOffset': u32(0x38), 'externalRelSize': u32(0x3C),
    'exportTableOffset': u32(0x40), 'exportTableSize': u32(0x44),
    'exportTableNameOff': u32(0x48),
    'importTableOffset': u32(0x4C), 'importTableSize': u32(0x50),
    'importTableNameOff': u32(0x54),
}
print('=== header ===')
for k, v in h.items():
    print(f'  {k:20s} = {v:#x}' if isinstance(v, int) else f'  {k:20s} = {v}')

# module name
nm = d[h['nameOffset']:h['nameOffset']+h['nameSize']]
print(f"module name: {nm!r}")

# section table
print('\n=== sections ===')
secs = []
base = h['sectionInfoOffset']
for i in range(h['sectionCount']):
    off = u32(base + i*8)
    size = u32(base + i*8 + 4)
    exec_flag = off & 1
    off &= ~1
    secs.append((off, size, exec_flag))
    print(f'  sec{i:2d}: off={off:#08x} size={size:#08x} exec={exec_flag}')

# export table: 16-byte entries (nameOff, offset, section, elfHash)
print('\n=== EXPORT ===')
et, esz, enameoff = h['exportTableOffset'], h['exportTableSize'], h['exportTableNameOff']
exports = []
for o in range(et, et+esz, 16):
    name_o = u32(o)
    offset = u32(o+4)
    section = u32(o+8)
    ehash = u32(o+12)
    name_abs = enameoff + name_o
    end = d.index(b'\x00', name_abs)
    name = d[name_abs:end].decode('ascii', 'replace')
    exports.append((name, section, offset, ehash))
for name, section, offset, ehash in exports:
    print(f'  sec{section} +{offset:#06x} hash={ehash:#010x}  {name}')

# import table: 12-byte entries (nameOff, relOffset, ...) — try 12 then 8
print('\n=== IMPORT (names) ===')
it, isz, inameoff = h['importTableOffset'], h['importTableSize'], h['importTableNameOff']
for entsize in (12, 8):
    if isz % entsize == 0:
        print(f'-- trying {entsize}-byte entries ({isz//entsize} entries) --')
        names = []
        for o in range(it, it+isz, entsize):
            name_o = u32(o)
            name_abs = inameoff + name_o
            if name_abs >= len(d):
                names.append('?'); continue
            end = d.index(b'\x00', name_abs)
            names.append(d[name_abs:end].decode('ascii', 'replace'))
        for n in names:
            print('  ', n)
        break
