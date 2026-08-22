"""Differential test: textures dumped by Dolphin during a REAL run of the game,
against our decoder (gxtex.py) on the assets extracted from the disc.

It is the only point in the project validated against an EXTERNAL witness
rather than by internal consistency. It has already caught two decoder errors
that the images did not betray (CMPR interpolation, alpha of the I formats).

How it can be falsified: a dump whose decoded content matches no asset, or
matches one with a non-zero delta.

Usage:  python tools/dolphin_texdiff.py [dump_dir]
"""
import os, sys, struct, glob, json, hashlib, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gxtex
from PIL import Image

ASSETS = os.path.join(os.environ.get('TLS_ROOT', '.'), 'assets')
DUMP = os.environ.get('TLS_DUMP', 'Dump/Textures/SLSP01')
u32 = lambda d, o: struct.unpack_from('>I', d, o)[0]
FMT = {0: 'I4', 1: 'I8', 2: 'IA4', 3: 'IA8', 4: 'RGB565', 5: 'RGB5A3',
       6: 'RGBA8', 0xE: 'CMPR'}

# bytes per level: mips are packed after level 0, each rounded up to the
# format's block geometry
BPP = {0: 0.5, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 4, 0xE: 0.5}


def level_size(fmt, w, h):
    bw, bh = gxtex.BLOCK[fmt]
    pw = (w + bw - 1) // bw * bw
    ph = (h + bh - 1) // bh * bh
    return int(pw * ph * BPP[fmt])


def mip_offset(fmt, w, h, level):
    off = 0
    for n in range(level):
        off += level_size(fmt, max(w >> n, 1), max(h >> n, 1))
    return off


def parse_dump_name(name):
    """tex1_WxH[_m]_<hash>[_<tlut>]_<fmt>[_mipN].png -> dict, or None."""
    b = name[:-4] if name.endswith('.png') else name
    t = b.split('_')
    if not t[0].startswith('tex'):
        return None            # efb1_/xfb1_: does not come from game memory
    try:
        w, h = map(int, t[1].split('x'))
    except ValueError:
        return None
    level = 0
    if t[-1].startswith('mip'):
        level = int(t[-1][3:])
        t = t[:-1]
    try:
        fmt = int(t[-1])
    except ValueError:
        return None
    return dict(name=name, w=max(w >> level, 1), h=max(h >> level, 1),
                base_w=w, base_h=h, fmt=fmt, level=level, hash=t[-2])


def dumps(d):
    out = []
    for p in sorted(glob.glob(os.path.join(d, '*.png'))):
        i = parse_dump_name(os.path.basename(p))
        if i:
            i['path'] = p
            out.append(i)
    return out


def asset_headers():
    for root, dirs, fs in os.walk(ASSETS):
        for f in fs:
            if not f.endswith('.texture'):
                continue
            p = os.path.join(root, f)
            d = open(p, 'rb').read(0x40)
            if d[:8] != b'chnkdata':
                continue
            yield p, dict(fmt=u32(d, 0x20), w=u32(d, 0x24), h=u32(d, 0x28),
                          mips=u32(d, 0x2c), doff=u32(d, 0x34))


def decode_asset(path, h, level=0):
    raw = open(path, 'rb').read()
    w = max(h['w'] >> level, 1)
    ht = max(h['h'] >> level, 1)
    off = h['doff'] + mip_offset(h['fmt'], h['w'], h['h'], level)
    return bytes(gxtex.decode(h['fmt'], w, ht, raw[off:]))


def main():
    dump_dir = sys.argv[1] if len(sys.argv) > 1 else DUMP
    D = dumps(dump_dir)
    print(f'{len(D)} dumps from {dump_dir}')
    print('  by mip level:',
          dict(sorted(collections.Counter(d['level'] for d in D).items())))
    print('  by format:', {FMT.get(k, k): v for k, v in
                           collections.Counter(d['fmt'] for d in D).most_common()})

    need = collections.defaultdict(list)
    for d in D:
        need[(d['base_w'], d['base_h'], d['fmt'], d['level'])].append(d)

    hdrs = {}
    byfmt = collections.defaultdict(list)
    for p, h in asset_headers():
        hdrs[p] = h
        byfmt[(h['w'], h['h'], h['fmt'])].append(p)
    print(f'{len(hdrs)} .texture files in the assets')

    todo = set()
    for (bw, bh, fmt, level) in need:
        for p in byfmt.get((bw, bh, fmt), []):
            todo.add((p, level))
    print(f'{len(todo)} (asset, level) pairs to decode...')

    index = {}          # sha1(rgba) -> [(path, level)]
    for i, (p, level) in enumerate(sorted(todo)):
        h = hdrs[p]
        if level and level >= max(h['mips'], 1):
            continue
        try:
            rgba = decode_asset(p, h, level)
        except Exception:
            continue
        index.setdefault(hashlib.sha1(rgba).hexdigest(), []).append((p, level))
        if (i + 1) % 500 == 0:
            print(f'  ...{i+1}/{len(todo)}', flush=True)

    print('\n--- comparison ---')
    exact = []
    miss = []
    for d in D:
        ref = Image.open(d['path']).convert('RGBA').tobytes()
        k = hashlib.sha1(ref).hexdigest()
        if k in index:
            exact.append((d, index[k][0]))
        else:
            miss.append(d)
    print(f'IDENTICAL (byte for byte): {len(exact)}/{len(D)}')
    print(f'NOT FOUND:                 {len(miss)}/{len(D)}')

    if exact:
        pf = collections.Counter((FMT.get(d['fmt'], d['fmt']), d['level'])
                                 for d, _ in exact)
        print('\n  identical by (format, mip level):')
        for (f, l), n in sorted(pf.items()):
            print(f'    {f:<8s} mip{l}: {n}')
    if miss:
        pf = collections.Counter((FMT.get(d['fmt'], d['fmt']), d['level'])
                                 for d in miss)
        print('\n  not found by (format, mip level):')
        for (f, l), n in sorted(pf.items()):
            print(f'    {f:<8s} mip{l}: {n}')
        print('\n  first 25 not found, with the closest candidate:')
        for d in miss[:25]:
            ref = Image.open(d['path']).convert('RGBA').tobytes()
            best = None
            for p in byfmt.get((d['base_w'], d['base_h'], d['fmt']), []):
                h = hdrs[p]
                if d['level'] and d['level'] >= max(h['mips'], 1):
                    continue
                try:
                    dec = decode_asset(p, h, d['level'])
                except Exception:
                    continue
                if len(dec) != len(ref):
                    continue
                diff = sum(1 for i in range(0, len(dec), 4)
                           if dec[i:i+4] != ref[i:i+4])
                if best is None or diff < best[1]:
                    best = (p, diff, max((abs(a - b) for a, b in zip(dec, ref)),
                                         default=0))
            if best is None:
                print(f'    {d["name"]:<50s} 0 candidates with that signature')
            else:
                print(f'    {d["name"]:<50s} {best[1]} px differ '
                      f'(max delta {best[2]}) vs {os.path.relpath(best[0], ASSETS)}')

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'texdiff_report.json')
    with open(out, 'w') as f:
        json.dump(dict(total=len(D), exact=len(exact),
                       matches=[[d['name'], os.path.relpath(p, ASSETS), l]
                                for d, (p, l) in exact],
                       missing=[d['name'] for d in miss]), f, indent=1)
    print(f'\nreport -> {out}')


main()
