"""The FIFO log's VERTEX_STREAM blocks against our extracted .model files.

Every memory update says: "at address A these bytes were present". If those
bytes sit at offset O of one of our files, then A - O is the address the game
loaded that file at. The CLOSURE is that the difference must be the SAME for
every block of the same file: a coincidental match does not respect it, and
with hundreds of blocks the chance of it doing so is nil.

Usage:  python tools/dff_vertex_match.py fifo.dff [comma,separated,prefixes]
"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_dff
import dff_match

ASSETS = os.path.join(os.environ.get('TLS_ROOT', '.'), 'assets')
MINLEN = 16          # below this length a block is not identifiable


def candidates(prefixes):
    out = []
    for root, dirs, fs in os.walk(ASSETS):
        for f in fs:
            if not f.endswith('.model'):
                continue
            if prefixes and not any(f.startswith(p) for p in prefixes):
                continue
            out.append(os.path.join(root, f))
    return sorted(out)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'fifo.dff'
    prefixes = (sys.argv[2].split(',') if len(sys.argv) > 2
                else ['dg004', 'pc1', 'pc0', 'ws0', 'em3', 'np', 'sky', 'og_'])
    h, fr, U = dff_match.blobs(path)
    V = [u for u in U if u['type'] == 4]
    short = [u for u in V if u['size'] < MINLEN]
    V = [u for u in V if u['size'] >= MINLEN]
    print(f'{len(V)} VERTEX_STREAM blocks to look for '
          f'({len(short)} under {MINLEN} bytes, not identifiable)')

    C = candidates(prefixes)
    tot = sum(os.path.getsize(p) for p in C)
    print(f'{len(C)} candidate .model files, {tot/1e6:.1f} MB '
          f'(prefixes: {",".join(prefixes)})')

    found = {}
    for i, p in enumerate(C):
        d = open(p, 'rb').read()
        for j, u in enumerate(V):
            if j in found:
                continue
            o = d.find(u['data'])
            if o >= 0:
                found[j] = (p, o)
        if (i + 1) % 200 == 0:
            print(f'  ...{i+1}/{len(C)} files, {len(found)}/{len(V)} found',
                  flush=True)

    print(f'\nFOUND: {len(found)}/{len(V)} blocks')
    byfile = collections.defaultdict(list)
    for j, (p, o) in found.items():
        byfile[p].append((V[j], o))

    print('\n--- closure: load base per file ---')
    ok = bad = 0
    for p, items in sorted(byfile.items(), key=lambda kv: -len(kv[1])):
        bases = collections.Counter(u['addr'] - o for u, o in items)
        b, n = bases.most_common(1)[0]
        ok += n
        bad += len(items) - n
        flag = 'CONSTANT' if len(bases) == 1 else f'{len(bases)} different bases'
        print(f'  {os.path.relpath(p, ASSETS):<58s} {len(items):4d} blocks  '
              f'base 0x{b & 0xffffffff:08x}  {flag}')
    print(f'\n  blocks respecting their file\'s base: {ok}/{ok+bad}')

    miss = [V[j] for j in range(len(V)) if j not in found]
    if miss:
        print(f'\n--- {len(miss)} not found ---')
        sz = collections.Counter(u['size'] for u in miss)
        print('  most common sizes:', sz.most_common(8))
        for u in miss[:10]:
            print(f'    addr 0x{u["addr"]:08x} {u["size"]:6d} bytes  '
                  f'{u["data"][:24].hex()}')


if __name__ == '__main__':
    main()
