"""The FIFO log's BP registers: what was bound to each texture unit, and how
the TEV was configured, while the game was drawing.

The BP writes are the unexplored half of the log. This starts from the
**texture bindings**, because there the comparison closes on three facts that
come from different places:

  1. `TX_SETIMAGE3` gives a texture's ADDRESS (value << 5);
  2. that address falls inside a RAM block of the log, which we know is byte
     for byte one of our `.texture` files -> hence the NAME;
  3. `TX_SETIMAGE0`, a *different* register, declares the width, height and
     FORMAT, which must match that file's `chnkdata` header.

Point (3) is not a confirmation of point (2): it is a second witness.

Register map used (units 0-3 and 4-7 have two separate blocks):
    TX_SETMODE0   0x80-0x83 / 0xa0-0xa3     filters, wrap
    TX_SETMODE1   0x84-0x87 / 0xa4-0xa7     LOD levels
    TX_SETIMAGE0  0x88-0x8b / 0xa8-0xab     w-1 (10b), h-1 (10b), fmt (4b)
    TX_SETIMAGE1  0x8c-0x8f / 0xac-0xaf     TMEM even
    TX_SETIMAGE2  0x90-0x93 / 0xb0-0xb3     TMEM odd
    TX_SETIMAGE3  0x94-0x97 / 0xb4-0xb7     address >> 5
    GEN_MODE      0x00                      texgens, colour channels, TEV stages
    TEV combine   0xc0-0xdf                 colour/alpha, one every two regs
    TEV order     0x28-0x2f                 texmap and texcoord per stage pair

Usage:  python tools/fifo_tev.py fifo.dff
"""
import os, sys, struct, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_dff, dff_match, fifo_decode

ASSETS = os.path.join(os.environ.get('TLS_ROOT', '.'), 'assets')
be32 = lambda d, o: struct.unpack_from('>I', d, o)[0]
FMT = {0: 'I4', 1: 'I8', 2: 'IA4', 3: 'IA8', 4: 'RGB565', 5: 'RGB5A3',
       6: 'RGBA8', 8: 'C4', 9: 'C8', 0xA: 'C14X2', 0xE: 'CMPR'}

# register -> (texture unit, which of the four SETIMAGE)
TXIMG = {}
for i in range(4):
    TXIMG[0x88 + i] = (i, 0)
    TXIMG[0x8c + i] = (i, 1)
    TXIMG[0x90 + i] = (i, 2)
    TXIMG[0x94 + i] = (i, 3)
    TXIMG[0xa8 + i] = (4 + i, 0)
    TXIMG[0xac + i] = (4 + i, 1)
    TXIMG[0xb0 + i] = (4 + i, 2)
    TXIMG[0xb4 + i] = (4 + i, 3)


class BP:
    """The Blitting Processor register state we need."""

    def __init__(self):
        self.reg = {}
        self.img = collections.defaultdict(dict)   # unit -> {0..3: value}

    def write(self, r, v):
        self.reg[r] = v
        if r in TXIMG:
            unit, which = TXIMG[r]
            self.img[unit][which] = v

    def active_texmaps(self):
        """The units the ACTIVE TEV stages actually reference.

        Without this you read LEFTOVER state: the game only rewrites the
        registers of the unit it is about to use, so the others hold a
        SETIMAGE0 and a SETIMAGE3 written at different times, for different
        textures. Pairing them produces bindings that never existed.
        RAS1_TREF (0x28-0x2f) holds two stages per register:
            bits 0-2 texmap, 3-5 texcoord, 6 enable, 7-9 colour channel
            bits 12-14, 15-17, 18, 19-21  for the odd stage
        """
        n = (self.gen_mode() or {}).get('ntev', 0)
        out = set()
        for st in range(n):
            v = self.reg.get(0x28 + st // 2)
            if v is None:
                continue
            sh = 0 if st % 2 == 0 else 12
            if (v >> (sh + 6)) & 1:              # stage samples a texture
                out.add((v >> sh) & 7)
        return out

    def bindings(self):
        """{unit: dict} for the units the active stages use."""
        out = {}
        active = self.active_texmaps()
        for unit, d in self.img.items():
            if unit not in active or 0 not in d or 3 not in d:
                continue
            i0 = d[0]
            out[unit] = dict(
                w=(i0 & 0x3ff) + 1,
                h=((i0 >> 10) & 0x3ff) + 1,
                fmt=(i0 >> 20) & 0xf,
                addr=d[3] << 5)
        return out

    def gen_mode(self):
        v = self.reg.get(0x00)
        if v is None:
            return None
        return dict(ntexgen=v & 0xf, ncolchan=(v >> 4) & 0x7,
                    ntev=((v >> 10) & 0xf) + 1, cullmode=(v >> 14) & 0x3)

    def tev_stages(self):
        n = (self.gen_mode() or {}).get('ntev', 0)
        out = []
        for s in range(n):
            out.append((self.reg.get(0xc0 + 2 * s), self.reg.get(0xc1 + 2 * s)))
        return tuple(out)


def walk(fifo, cp, bp):
    """Walk the stream keeping BP state too; one record per draw."""
    p, n, out = 0, len(fifo), []
    while p < n:
        op = fifo[p]
        if op == 0x00:
            p += 1
        elif op == 0x08:
            cp.write(fifo[p + 1], struct.unpack_from('>I', fifo, p + 2)[0])
            p += 6
        elif op == 0x10:
            p += 5 + ((struct.unpack_from('>H', fifo, p + 1)[0] & 0xf) + 1) * 4
        elif op in (0x20, 0x28, 0x30, 0x38):
            p += 5
        elif op == 0x40:
            p += 9
        elif op in (0x44, 0x48):
            p += 1
        elif op == 0x61:
            v = struct.unpack_from('>I', fifo, p + 1)[0]
            bp.write(v >> 24, v & 0xffffff)
            p += 5
        elif 0x80 <= op < 0xc0:
            vat = op & 7
            cnt = struct.unpack_from('>H', fifo, p + 1)[0]
            out.append(dict(pos=p, count=cnt, vat=vat,
                            desc=tuple(cp.descriptor(vat)),
                            bases=tuple(cp.base),
                            bindings=bp.bindings(),
                            gen=bp.gen_mode(), tev=bp.tev_stages()))
            p += 3 + cnt * cp.vsize(vat)
        else:
            raise ValueError(f'opcode 0x{op:02x} at 0x{p:x}')
    return out


def texture_blobs(path):
    """[(addr, size, file, w, h, fmt)] from the recognised TEXTURE_MAP blocks."""
    h, fr, U = dff_match.blobs(path)
    idx = dff_match.texture_index()
    out = []
    for u in U:
        if u['type'] != 1:
            continue
        for p, payload in idx.get(u['data'][:dff_match.KEY], []):
            if len(payload) < len(u['data']):
                continue                       # see the note in dff_match.py
            if payload[:len(u['data'])] == u['data']:
                d = open(p, 'rb').read(0x40)
                out.append((u['addr'], u['size'], p,
                            be32(d, 0x24), be32(d, 0x28), be32(d, 0x20)))
                break
    return out


def state(path):
    """Replay the frame; returns (draws, cp, bp)."""
    d = open(path, 'rb').read()
    h = parse_dff.header(d)
    fr = parse_dff.frames(d, h)[0]
    fifo = d[fr['fifo_off']:fr['fifo_off'] + fr['fifo_size']]
    cp = fifo_decode.CP()
    cpmem = d[h['cp_off']:h['cp_off'] + h['cp_size'] * 4]
    for i in range(h['cp_size']):
        cp.write(i, struct.unpack_from('<I', cpmem, i * 4)[0])
    bp = BP()
    bpmem = d[h['bp_off']:h['bp_off'] + h['bp_size'] * 4]
    for i in range(h['bp_size']):
        bp.write(i, struct.unpack_from('<I', bpmem, i * 4)[0] & 0xffffff)
    return walk(fifo, cp, bp), cp, bp


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'fifo.dff'
    draws, cp, bp = state(path)
    print(f'{len(draws)} draws replayed with BP state')

    g = collections.Counter((x['gen'] or {}).get('ntev') for x in draws)
    print('\nTEV stages per draw (GEN_MODE):',
          {k: v for k, v in sorted(g.items(), key=lambda kv: -kv[1])})
    tg = collections.Counter((x['gen'] or {}).get('ntexgen') for x in draws)
    print('texgens per draw:', dict(sorted(tg.items())))
    nb = collections.Counter(len(x['bindings']) for x in draws)
    print('texture units bound per draw:', dict(sorted(nb.items())))

    print('\n--- distinct bindings (unit, address, w, h, format) ---')
    binds = collections.Counter()
    for x in draws:
        for unit, b in x['bindings'].items():
            binds[(unit, b['addr'], b['w'], b['h'], b['fmt'])] += 1
    print(f'{len(binds)} distinct bindings over {sum(binds.values())} uses')

    TB = texture_blobs(path)
    print(f'{len(TB)} texture blocks recognised as our assets')

    ok = wrong = unknown = 0
    named = collections.Counter()
    bad = []
    for (unit, addr, w, hh, fmt), n in binds.most_common():
        owner = None
        for a, size, p, aw, ah, af in TB:
            if a <= addr < a + size:
                owner = (p, aw, ah, af, addr - a)
                break
        if owner is None:
            unknown += 1
            continue
        p, aw, ah, af, off = owner
        if (aw, ah, af) == (w, hh, fmt) and off == 0:
            ok += 1
            named[os.path.basename(p)] += n
        else:
            wrong += 1
            bad.append((unit, addr, w, hh, fmt, p, aw, ah, af, off))

    print('\nRESULT on the bindings')
    print(f'  address inside a recognised block: {ok + wrong}/{len(binds)}')
    print(f'  CONFIRMED (register w, h, format == file header, exact address): '
          f'{ok}')
    print(f'  discordant: {wrong}')
    print(f'  address in no recognised block: {unknown}')
    for unit, addr, w, hh, fmt, p, aw, ah, af, off in bad[:15]:
        print(f'    tex{unit} 0x{addr:08x} {w}x{hh} {FMT.get(fmt, fmt)} -> '
              f'{os.path.basename(p)} {aw}x{ah} {FMT.get(af, af)} (+{off})')

    print(f'\n  {len(named)} distinct textures named by the BP registers, '
          f'by draw count:')
    for nm, n in named.most_common(20):
        print(f'    {nm:<44s} {n}')


if __name__ == '__main__':
    main()
