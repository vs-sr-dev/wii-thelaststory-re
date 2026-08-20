"""Parser for the LastWorld packs (The Last Story, Wii): .pfs (name tree) + .pkh (hash index) + .pk (data).

Layout recovered by RE:
  .pfs: 0x10 header (u32: ?, ?, numDirs, numFiles), then numDirs 24-byte dir entries
        (nameIdx, parentIdx, firstChildDir, numChildDirs, firstFileIdx, numFiles),
        then (numDirs + numFiles) u32 name offsets, then the string table (base =
        right before the first string; the root has an empty name).
  .pkh: u32 count, then count 16-byte entries (hashPath, offset, uncSize, compSize);
        sorted by ascending hash; compSize==0 => stored uncompressed (uncSize bytes).
  .pk : blob; compressed files use Nintendo LZ11 (magic 0x11 + 24-bit LE size).
"""
import os
import struct, os

def parse_pfs(path):
    data = open(path, 'rb').read()
    num_dirs, num_files = struct.unpack('>II', data[0x08:0x10])
    dirs = []
    off = 0x10
    for _ in range(num_dirs):
        dirs.append(struct.unpack('>6I', data[off:off+24]))
        off += 24
    name_offs = struct.unpack(f'>{num_dirs + num_files}I', data[off:off + 4*(num_dirs+num_files)])
    str_base = off + 4 * (num_dirs + num_files)
    def name(i):
        so = str_base + name_offs[i]
        end = data.index(b'\x00', so)
        return data[so:end].decode('ascii')
    dir_paths = {}
    def dir_path(i):
        if i in dir_paths:
            return dir_paths[i]
        nameIdx, parent = dirs[i][0], dirs[i][1]
        if parent == 0xFFFFFFFF:
            p = ''
        else:
            pp = dir_path(parent)
            p = (pp + '/' if pp else '') + name(nameIdx)
        dir_paths[i] = p
        return p
    files = [None] * num_files
    for di in range(num_dirs):
        _, _, _, _, first, count = dirs[di]
        dp = dir_path(di)
        for fi in range(first, first + count):
            files[fi] = (dp + '/' if dp else '') + name(num_dirs + fi)
    return files

def parse_pkh(path):
    data = open(path, 'rb').read()
    count = struct.unpack('>I', data[:4])[0]
    return [struct.unpack('>IIII', data[4+i*16:4+i*16+16]) for i in range(count)]

def lz11_decompress(data):
    assert data[0] == 0x11, f'not LZ11: {data[0]:#x}'
    size = data[1] | (data[2] << 8) | (data[3] << 16)
    pos = 4
    if size == 0:
        size = struct.unpack('<I', data[4:8])[0]
        pos = 8
    out = bytearray()
    n = len(data)
    while len(out) < size and pos < n:
        flags = data[pos]; pos += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                b0 = data[pos]
                ind = b0 >> 4
                if ind == 0:
                    length = (((b0 & 0xF) << 4) | (data[pos+1] >> 4)) + 0x11
                    disp = (((data[pos+1] & 0xF) << 8) | data[pos+2]) + 1
                    pos += 3
                elif ind == 1:
                    length = (((b0 & 0xF) << 12) | (data[pos+1] << 4) | (data[pos+2] >> 4)) + 0x111
                    disp = (((data[pos+2] & 0xF) << 8) | data[pos+3]) + 1
                    pos += 4
                else:
                    length = ind + 1
                    disp = (((b0 & 0xF) << 8) | data[pos+1]) + 1
                    pos += 2
                for _ in range(length):
                    out.append(out[-disp])
            else:
                out.append(data[pos]); pos += 1
    return bytes(out)

_CRC_TBL = None

def crc32_bzip2(data):
    """CRC-32/BZIP2: poly 0x04C11DB7, init/xorout 0xFFFFFFFF, non-reflected.
    This is the path hash (lowercased path, '/' separator) the packs use."""
    global _CRC_TBL
    if _CRC_TBL is None:
        _CRC_TBL = []
        for b in range(256):
            c = b << 24
            for _ in range(8):
                c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
            _CRC_TBL.append(c)
    c = 0xFFFFFFFF
    for byte in data:
        c = ((c << 8) ^ _CRC_TBL[((c >> 24) ^ byte) & 0xFF]) & 0xFFFFFFFF
    return c ^ 0xFFFFFFFF

def path_hash(path):
    return crc32_bzip2(path.lower().encode('ascii', 'replace'))

def match_names_to_entries(files, entries):
    """Deterministic mapping through the CRC-32/BZIP2 hash of the lowercased path.
    Returns a list of (path, hash, offset, uncSize, compSize) in .pfs order.
    Raises if any name fails to find its entry."""
    by_hash = {e[0]: e for e in entries}
    out = []
    missing = []
    for f in files:
        h = path_hash(f)
        e = by_hash.get(h)
        if e is None:
            missing.append(f)
            continue
        out.append((f,) + tuple(e))
    if missing:
        raise ValueError(f'{len(missing)} names with no hash entry, e.g.: {missing[:5]}')
    return out

if __name__ == '__main__':
    import sys
    base = os.path.join(os.environ.get('TLS_ROOT', '.'), 'extract', 'files', 'preload')
    stem = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, 'boot')
    files = parse_pfs(stem + '.pfs')
    entries = parse_pkh(stem + '.pkh')
    print(f'{len(files)} names, {len(entries)} pkh entries')
    matched = match_names_to_entries(files, entries)
    dup_offs = len(entries) - len(set(e[1] for e in entries))
    print(f'duplicate offsets (dedup): {dup_offs}')
    for m in matched[:10]:
        print(f'  {m[1]:08x} off={m[2]:#08x} unc={m[3]:7d} comp={m[4]:7d}  {m[0]}')
    print('  ...')
    for m in matched[-5:]:
        print(f'  {m[1]:08x} off={m[2]:#08x} unc={m[3]:7d} comp={m[4]:7d}  {m[0]}')
