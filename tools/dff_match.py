"""Compare the RAM blocks captured in a FIFO log with the assets extracted
from the disc.

Alongside the GX commands, a FIFO log records the CONTENTS of the memory the
game was using: the loaded textures and the vertex arrays. If those bytes are
the same as our extracted files, the chain disc -> pack -> LZ11 -> file is
proven against a real run, without going through any decoder of ours.

Usage:  python tools/dff_match.py fifo.dff
"""
import os, sys, struct, hashlib, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_dff

ASSETS = os.path.join(os.environ.get('TLS_ROOT', '.'), 'assets')
be32 = lambda d, o: struct.unpack_from('>I', d, o)[0]
KEY = 64          # header bytes used as the index key


def blobs(path):
    d = open(path, 'rb').read()
    h = parse_dff.header(d)
    fr = parse_dff.frames(d, h)[0]
    U = parse_dff.mem_updates(d, fr, 24)
    for u in U:
        u['data'] = d[u['data_off']:u['data_off'] + u['size']]
    return h, fr, U


def texture_index():
    """key = first KEY bytes of the payload -> (path, payload)"""
    idx = {}
    for root, dirs, fs in os.walk(ASSETS):
        for f in fs:
            if not f.endswith('.texture'):
                continue
            p = os.path.join(root, f)
            d = open(p, 'rb').read()
            if d[:8] != b'chnkdata':
                continue
            payload = d[be32(d, 0x34):]
            if len(payload) >= KEY:
                idx.setdefault(payload[:KEY], []).append((p, payload))
    return idx


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'fifo.dff'
    h, fr, U = blobs(path)
    byt = collections.defaultdict(list)
    for u in U:
        byt[u['type']].append(u)
    for t, v in sorted(byt.items()):
        sz = [x['size'] for x in v]
        print(f'{parse_dff.MEM_TYPE.get(t, t):<14s} {len(v):4d} blocks, '
              f'{sum(sz)/1e6:.2f} MB, {min(sz)}..{max(sz)} bytes')

    tex = byt.get(1, [])
    print(f'\n--- {len(tex)} TEXTURE_MAP blocks against the assets ---')
    idx = texture_index()
    print(f'index: {len(idx)} textures distinct by their first {KEY} bytes')

    uniq = {}
    for u in tex:
        uniq.setdefault(hashlib.sha1(u['data']).hexdigest(), u)
    print(f'{len(uniq)} distinct blocks (out of {len(tex)} uploads)')

    hit = []
    missing = []
    for k, u in uniq.items():
        cands = idx.get(u['data'][:KEY], [])
        found = None
        for p, payload in cands:
            # The payload must be AT LEAST as long as the region the GP read.
            # Comparing only min(len) "identifies" a small texture inside a
            # large block that happens to start with the same bytes (a black
            # mask does that with almost anything): a false positive, caught by
            # the BP registers, which declare w/h/format independently.
            if len(payload) < len(u['data']):
                continue
            if payload[:len(u['data'])] == u['data']:
                found = (p, len(u['data']), len(payload), len(u['data']))
                break
        if found:
            hit.append((u, found))
        else:
            missing.append(u)

    print(f'\nIDENTICAL: {len(hit)}/{len(uniq)}   NOT FOUND: {len(missing)}')
    exact_len = sum(1 for _, f in hit if f[2] == f[3])
    print(f'  of which with the exact payload length: {exact_len}')
    names = sorted(set(os.path.basename(f[0]) for _, f in hit))
    print(f'\n  {len(names)} distinct assets recognised:')
    for n in names:
        print('   ', n)
    if missing:
        print(f'\n  not found ({len(missing)}), first 10:')
        for u in missing[:10]:
            print(f'    addr 0x{u["addr"]:08x} {u["size"]:8d} bytes  '
                  f'starts {u["data"][:16].hex()}')


if __name__ == '__main__':
    main()
