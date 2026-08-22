"""The mesh<->texture bridge put in front of the running game.

`parse_material.py` claims a `.material` says which textures a model uses. The
FIFO log can contradict it: while drawing, the game bound specific textures to
specific units, and that draw's vertices came from a specific `.model`.

  - where the vertices came from -> CP registers + RAM blocks -> the `.model`
  - which texture was bound      -> BP registers + RAM blocks -> the `.texture`
  - what it should use           -> the `.material` with the same stem, read
                                    from the disc alone

The first two do not talk to each other (CP and BP are different registers of
different subsystems) and neither has ever seen the third.

Usage:  python tools/fifo_material_xref.py fifo.dff
"""
import os, sys, struct, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_dff, dff_match, fifo_decode, fifo_tev, fifo_model_xref
import parse_material

ASSETS = os.path.join(os.environ.get('TLS_ROOT', '.'), 'assets')


def stem(p):
    return os.path.splitext(os.path.basename(p))[0]


def material_for(model_path):
    """The .material with the same stem, looked for next door first."""
    st = stem(model_path)
    d = os.path.dirname(model_path)
    cand = os.path.join(os.path.dirname(d), 'material', st + '.material')
    if os.path.exists(cand):
        return cand
    for root, dirs, fs in os.walk(ASSETS):
        if st + '.material' in fs:
            return os.path.join(root, st + '.material')
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'fifo.dff'
    print('resolving the RAM blocks (vertices and textures)...')
    VB, ntot = fifo_model_xref.resolve_blobs(path)
    TB = fifo_tev.texture_blobs(path)
    print(f'  {len(VB)}/{ntot} vertex blocks, {len(TB)} texture blocks')

    draws, cp, bp = fifo_tev.state(path)
    print(f'  {len(draws)} draws\n')

    def model_of(base):
        for a, size, p, o in VB:
            if a <= base < a + size:
                return p
        return None

    def texture_of(addr):
        for a, size, p, aw, ah, af in TB:
            if a <= addr < a + size:
                return p
        return None

    used = collections.defaultdict(collections.Counter)
    ndraw = collections.Counter()
    no_model = no_tex = direct = 0
    pos_i = fifo_decode.ARRAY_NAME.index('Position')
    for x in draws:
        # If the positions are NOT indexed, the draw reads no array at all: the
        # base register still holds the previous model's value. Attributing it
        # is exactly the false positive that made a character look as though it
        # were drawing the interface fonts.
        if not any(a == 'Position' and m.startswith('index')
                   for a, m, _s in x['desc']):
            direct += 1
            continue
        m = model_of(x['bases'][pos_i])
        if m is None:
            no_model += 1
            continue
        ndraw[m] += 1
        for unit, b in x['bindings'].items():
            t = texture_of(b['addr'])
            if t is None:
                no_tex += 1
            else:
                used[m][stem(t)] += 1

    print(f'draws with DIRECT positions (no array, not attributable): {direct}')
    print(f'draws whose position array is in no known model: {no_model}')
    print(f'bindings to an unrecognised address: {no_tex}\n')

    print(f'{"model":<34s} {"draws":>5s} {"bound":>6s} {"in .material":>12s} '
          f'{"confirmed":>9s} {"unnamed":>7s}')
    tot_ok = tot_bad = 0
    detail = []
    for m in sorted(used, key=lambda k: -ndraw[k]):
        mat = material_for(m)
        if mat is None:
            print(f'{stem(m):<34s} {ndraw[m]:5d} {len(used[m]):6d} '
                  f'{"NO .material":>12s}')
            continue
        names = {os.path.splitext(n)[0].lower()
                 for n in parse_material.texture_names(
                     parse_material.parse_file(mat))}
        bound = set(used[m])
        ok = {b for b in bound if b.lower() in names}
        bad = bound - ok
        tot_ok += len(ok)
        tot_bad += len(bad)
        print(f'{stem(m):<34s} {ndraw[m]:5d} {len(bound):6d} {len(names):12d} '
              f'{len(ok):9d} {len(bad):7d}')
        if bad:
            detail.append((stem(m), sorted(bad), sorted(names)))

    print(f'\nRESULT: {tot_ok} bound textures the .material names, '
          f'{tot_bad} it does not')
    for st, bad, names in detail[:12]:
        print(f'\n  {st}: bound but not in the material: {bad}')
        print(f'    the material names: {names[:12]}')


if __name__ == '__main__':
    main()
