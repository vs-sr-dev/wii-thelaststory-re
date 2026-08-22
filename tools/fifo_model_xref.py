"""The test that closes the loop on geometry.

Three independent statements are put against one another:

  1. a CP register in the FIFO log says: "the position array is at address A,
     with stride S";
  2. a RAM block in the FIFO log contains bytes that occur, identically, at
     offset O of one of our extracted .model files;
  3. parse_model, reading ONLY the file on disc, says there is a `strm` chunk
     of that attribute at offset O, with that many bytes per element.

If the reverse engineering is right: the offset obtained from (2) is exactly
the dataOff that (3) declares, and S is exactly its bytes per element. Two
numbers per attribute, decided by three sources that never talked to each
other.

ATTRIBUTION. An array address is attributed to a file through THE RAM BLOCK
THAT CONTAINS IT, whose file and offset are both known exactly. An earlier
version extrapolated from the file's "load base" (A_block - offset) instead:
that base exists and is constant (it is measured below as a closure in its own
right), but using it to attribute addresses produces false pairings, because
file ranges overlap. The 50 discordances of the first version were all that
heuristic's; none were the format's.

Usage:  python tools/fifo_model_xref.py fifo.dff
"""
import os, sys, struct, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_dff, dff_match, dff_vertex_match, fifo_decode, parse_model

ASSETS = os.path.join(os.environ.get('TLS_ROOT', '.'), 'assets')
PREFIXES = ['dg004', 'pc1', 'pc0', 'ws0', 'em3', 'np', 'sky', 'og_']


def resolve_blobs(path):
    """[(addr, size, file, offset)] for every recognised RAM block."""
    h, fr, U = dff_match.blobs(path)
    V = [u for u in U if u['type'] == 4 and u['size'] >= dff_vertex_match.MINLEN]
    found = {}
    for p in dff_vertex_match.candidates(PREFIXES):
        d = open(p, 'rb').read()
        for j, u in enumerate(V):
            if j not in found:
                o = d.find(u['data'])
                if o >= 0:
                    found[j] = (p, o)
    B = sorted((V[j]['addr'], V[j]['size'], p, o) for j, (p, o) in found.items())
    return B, len(V)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'fifo.dff'
    print("looking for the FIFO log's RAM blocks inside the .model files...")
    B, ntot = resolve_blobs(path)
    print(f'  {len(B)}/{ntot} blocks recognised, '
          f'{len(set(x[2] for x in B))} distinct files')

    # closure in its own right: A - O must be constant per file (the load
    # address). A coincidental pairing does not respect it.
    per = collections.defaultdict(collections.Counter)
    for addr, size, p, o in B:
        per[p][addr - o] += 1
    const = sum(c.most_common(1)[0][1] for c in per.values())
    print(f"  blocks respecting their file's constant base: {const}/{len(B)}")

    d = open(path, 'rb').read()
    h = parse_dff.header(d)
    fr = parse_dff.frames(d, h)[0]
    fifo = d[fr['fifo_off']:fr['fifo_off'] + fr['fifo_size']]
    cp = fifo_decode.CP()
    cpmem = d[h['cp_off']:h['cp_off'] + h['cp_size'] * 4]
    for i in range(h['cp_size']):
        cp.write(i, struct.unpack_from('<I', cpmem, i * 4)[0])
    draws, stats, consumed, err = fifo_decode.decode(fifo, cp)
    print(f'  GX stream: {consumed}/{len(fifo)} bytes decoded '
          f'({"closed" if consumed == len(fifo) else err}), {len(draws)} draws')

    used = collections.Counter()
    for x in draws:
        for a, m, s in x['desc']:
            if m.startswith('index') and a in fifo_decode.ARRAY_NAME:
                i = fifo_decode.ARRAY_NAME.index(a)
                used[(a, x['bases'][i], x['strides'][i])] += x['count']
    print(f'  {len(used)} distinct (attribute, array address) pairs\n')

    strm = {}
    for _, _, p, _ in B:
        if p not in strm:
            strm[p] = parse_model.parse_file(p)['chunks']['strm']

    ok = ko = out = 0
    okf = collections.Counter()
    bad = []
    for (a, base, stride), nvert in sorted(used.items(), key=lambda kv: -kv[1]):
        owner = None
        for addr, size, p, o in B:
            if addr <= base < addr + size:
                owner = (p, o + (base - addr))
                break
        if owner is None:
            out += 1
            continue
        p, off = owner
        hit = [s for s in strm[p] if s['dataOff'] == off]
        if hit and hit[0]['perElem'] == stride:
            ok += 1
            okf[(os.path.basename(p), a, stride, hit[0]['attr'])] += 1
        else:
            ko += 1
            bad.append((a, base, stride, p, off, hit))

    print(f'{"attribute":<9s} {"stride":>6s}  '
          f'{"what parse_model calls it":<32s} {"n":>4s}')
    agg = collections.Counter()
    for (f, a, s, at), n in okf.items():
        agg[(a, s, at)] += n
    for (a, s, at), n in sorted(agg.items(), key=lambda kv: -kv[1]):
        print(f'{a:<9s} {s:6d}  {at:<32s} {n:4d}')

    print('\nRESULT')
    print(f'  attributed to a file via the block containing them: '
          f'{ok + ko}/{len(used)}')
    print(f'  CONFIRMED (exact offset AND exact stride): {ok}')
    print(f'  discordant: {ko}')
    print(f'  address in no recognised block: {out}')
    for a, base, stride, p, off, hit in bad[:15]:
        msg = (f'strm says {hit[0]["perElem"]}B' if hit
               else 'no strm at that offset')
        print(f'    {a:<9s} 0x{base:08x} stride {stride} -> '
              f'{os.path.basename(p)}+{off}: {msg}')

    print('\n  confirmed per file:')
    pf = collections.Counter()
    for (f, a, s, at), n in okf.items():
        pf[f] += n
    for f, n in pf.most_common():
        print(f'    {f:<40s} {n}')


if __name__ == '__main__':
    main()
