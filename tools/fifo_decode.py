"""Decode the GX command stream inside a Dolphin FIFO log.

The stream is what the hardware actually received. Among other things it
contains the CP registers, which declare WHERE the vertex arrays live in
memory, with what stride, and in what format — exactly the things parse_model
has to infer on its own from the file structure.

CRITERION: the decode must land EXACTLY at the end of the stream. The size of
each vertex is computed from the CP registers; if the reading of VCD/VAT were
wrong the pointer would desynchronise and hit an illegal opcode well before
the end. It is not a soft test.

Usage:  python tools/fifo_decode.py fifo.dff
"""
import os, struct, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_dff

# --- attribute names, in the order they appear in a vertex
ATTR = ['PosMatIdx'] + [f'Tex{i}MatIdx' for i in range(8)] + \
       ['Position', 'Normal', 'Color0', 'Color1'] + [f'Tex{i}' for i in range(8)]
# CP arrays: 0=Pos 1=Nrm 2=Clr0 3=Clr1 4..11=Tex0..7, 12..15 = XF indexed
ARRAY_NAME = ['Position', 'Normal', 'Color0', 'Color1'] + \
             [f'Tex{i}' for i in range(8)] + ['IndexA', 'IndexB', 'IndexC', 'IndexD']

CFMT_SIZE = {0: 2, 1: 3, 2: 4, 3: 2, 4: 3, 5: 4}      # RGB565 RGB8 RGBX8 RGBA4 RGBA6 RGBA8
CFMT_NAME = {0: 'RGB565', 1: 'RGB888', 2: 'RGB888x', 3: 'RGBA4444',
             4: 'RGBA6666', 5: 'RGBA8888'}
NFMT_SIZE = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4}            # u8 s8 u16 s16 f32
NFMT_NAME = {0: 'u8', 1: 's8', 2: 'u16', 3: 's16', 4: 'f32'}
PRIM = {0: 'QUADS', 1: 'QUADS2', 2: 'TRIANGLES', 3: 'TRISTRIP',
        4: 'TRIFAN', 5: 'LINES', 6: 'LINESTRIP', 7: 'POINTS'}


class CP:
    """Command Processor register state."""

    def __init__(self):
        # NOTE: there is only ONE vertex descriptor, shared by all 8 VATs
        # (registers 0x50 and 0x60). Only the FORMAT is per-VAT.
        self.vcd_lo = 0
        self.vcd_hi = 0
        self.vat_a = [0] * 8
        self.vat_b = [0] * 8
        self.vat_c = [0] * 8
        self.base = [0] * 16
        self.stride = [0] * 16

    def write(self, addr, val):
        g, i = addr & 0xf0, addr & 0x0f
        if g in (0x70, 0x80, 0x90) and i > 7:
            return                      # only 8 VATs exist
        if g == 0x50:
            self.vcd_lo = val
        elif g == 0x60:
            self.vcd_hi = val
        elif g == 0x70:
            self.vat_a[i] = val
        elif g == 0x80:
            self.vat_b[i] = val
        elif g == 0x90:
            self.vat_c[i] = val
        elif g == 0xa0:
            self.base[i] = val
        elif g == 0xb0:
            self.stride[i] = val

    def descriptor(self, vat):
        """Return [(attribute, mode, bytes)] in vertex order."""
        lo, hi = self.vcd_lo, self.vcd_hi
        a, b, c = self.vat_a[vat], self.vat_b[vat], self.vat_c[vat]
        d = []
        # matrix indices: one bit each, always direct (u8)
        if lo & 1:
            d.append(('PosMatIdx', 'direct', 1))
        for i in range(8):
            if (lo >> (1 + i)) & 1:
                d.append((f'Tex{i}MatIdx', 'direct', 1))

        def two(mode, name, direct_size, nidx=1):
            # nidx: with NormalIndex3 an indexed normal uses THREE indices
            if mode == 0:
                return
            if mode == 1:
                d.append((name, 'direct', direct_size))
            elif mode == 2:
                d.append((name, 'index8', 1 * nidx))
            elif mode == 3:
                d.append((name, 'index16', 2 * nidx))

        pos_e = 2 + (a & 1)                       # 0 -> xy, 1 -> xyz
        pos_f = (a >> 1) & 7
        two((lo >> 9) & 3, 'Position', pos_e * NFMT_SIZE[pos_f])
        nrm_e = 3 if not ((a >> 9) & 1) else 9    # 0 -> nrm, 1 -> nrm+bin+tan
        nrm_f = (a >> 10) & 7
        nidx = 3 if ((a >> 31) & 1) and ((a >> 9) & 1) else 1   # NormalIndex3
        two((lo >> 11) & 3, 'Normal', nrm_e * NFMT_SIZE[nrm_f], nidx)
        c0_f = (a >> 14) & 7
        two((lo >> 13) & 3, 'Color0', CFMT_SIZE.get(c0_f, 4))
        c1_f = (a >> 18) & 7
        two((lo >> 15) & 3, 'Color1', CFMT_SIZE.get(c1_f, 4))
        for i in range(8):
            if i == 0:
                el, fm = (a >> 21) & 1, (a >> 22) & 7
            elif i == 1:
                el, fm = b & 1, (b >> 1) & 7
            elif i == 2:
                el, fm = (b >> 9) & 1, (b >> 10) & 7
            elif i == 3:
                el, fm = (b >> 18) & 1, (b >> 19) & 7
            elif i == 4:
                el, fm = (b >> 27) & 1, (b >> 28) & 7
            elif i == 5:
                el, fm = (c >> 5) & 1, (c >> 6) & 7
            elif i == 6:
                el, fm = (c >> 14) & 1, (c >> 15) & 7
            else:
                el, fm = (c >> 23) & 1, (c >> 24) & 7
            two((hi >> (2 * i)) & 3, f'Tex{i}', (1 + el) * NFMT_SIZE[fm])
        return d

    def vsize(self, vat):
        return sum(x[2] for x in self.descriptor(vat))

    def fmt_summary(self, vat):
        a = self.vat_a[vat]
        return dict(pos_elem=2 + (a & 1), pos_fmt=NFMT_NAME[(a >> 1) & 7],
                    pos_frac=(a >> 4) & 0x1f,
                    nrm_fmt=NFMT_NAME[(a >> 10) & 7],
                    clr0=CFMT_NAME.get((a >> 14) & 7),
                    tex0_elem=1 + ((a >> 21) & 1),
                    tex0_fmt=NFMT_NAME[(a >> 22) & 7],
                    tex0_frac=(a >> 25) & 0x1f,
                    byte_dequant=(a >> 30) & 1)


def decode(fifo, cp=None, verbose=False):
    """Return (draws, stats, consumed, error_or_None)."""
    cp = cp or CP()
    p = 0
    n = len(fifo)
    draws = []
    stats = collections.Counter()
    while p < n:
        op = fifo[p]
        if op == 0x00:
            p += 1
            stats['NOP'] += 1
        elif op == 0x08:
            addr = fifo[p + 1]
            val = struct.unpack_from('>I', fifo, p + 2)[0]
            cp.write(addr, val)
            p += 6
            stats['CP'] += 1
        elif op == 0x10:
            # the dword count is in bits 16-19 of the header: 4 bits, max 16
            cnt = (struct.unpack_from('>H', fifo, p + 1)[0] & 0xf) + 1
            p += 5 + cnt * 4
            stats['XF'] += 1
        elif op in (0x20, 0x28, 0x30, 0x38):
            p += 5
            stats['INDX'] += 1
        elif op == 0x40:
            stats['CALL_DL'] += 1
            p += 9
        elif op == 0x44:
            p += 1
            stats['CMD_UNK44'] += 1
        elif op == 0x48:
            p += 1
            stats['INVL_VC'] += 1
        elif op == 0x61:
            p += 5
            stats['BP'] += 1
        elif 0x80 <= op < 0xc0:
            prim = (op >> 3) & 7
            vat = op & 7
            cnt = struct.unpack_from('>H', fifo, p + 1)[0]
            vs = cp.vsize(vat)
            draws.append(dict(pos=p, prim=PRIM[prim], vat=vat, count=cnt,
                              vsize=vs,
                              desc=tuple(cp.descriptor(vat)),
                              bases=tuple(cp.base), strides=tuple(cp.stride),
                              fmt=tuple(sorted(cp.fmt_summary(vat).items()))))
            p += 3 + cnt * vs
            stats['DRAW'] += 1
        else:
            return draws, stats, p, f'illegal opcode 0x{op:02x} at 0x{p:x}'
    return draws, stats, p, None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'fifo.dff'
    d = open(path, 'rb').read()
    h = parse_dff.header(d)
    fr = parse_dff.frames(d, h)[0]
    fifo = d[fr['fifo_off']:fr['fifo_off'] + fr['fifo_size']]
    print(f'FIFO stream: {len(fifo)} bytes')

    # initial state: the .dff stores the CP registers as of the frame start
    cp = CP()
    cpmem = d[h['cp_off']:h['cp_off'] + h['cp_size'] * 4]
    for i in range(h['cp_size']):
        cp.write(i, struct.unpack_from('<I', cpmem, i * 4)[0])

    draws, stats, consumed, err = decode(fifo, cp)
    print(f'CLOSURE: decoded {consumed}/{len(fifo)} bytes '
          f'({100*consumed/len(fifo):.1f}%) '
          f'-> {"OK" if consumed == len(fifo) else "DESYNC: " + err}')
    if err and draws:
        print('  last 3 draws before the break:')
        for x in draws[-3:]:
            print(f'    @0x{x["pos"]:06x} {x["prim"]:<9s} vat{x["vat"]} '
                  f'{x["count"]:5d} vertices x {x["vsize"]}B')
    print('opcodes:', dict(stats))
    print(f'{len(draws)} draw calls, {sum(x["count"] for x in draws)} vertices')
    print('primitives:', dict(collections.Counter(x['prim'] for x in draws)))
    print('VATs used:', dict(sorted(collections.Counter(
        x['vat'] for x in draws).items())))

    print('\n--- distinct vertex descriptors ---')
    for desc, n in collections.Counter(x['desc'] for x in draws).most_common():
        tot = sum(a[2] for a in desc)
        print(f'  {n:5d} draws, {tot:2d} B/vertex: '
              + ', '.join(f'{a}:{m}({s}B)' for a, m, s in desc))

    print('\n--- distinct VAT formats ---')
    for f, n in collections.Counter(x['fmt'] for x in draws).most_common():
        print(f'  {n:5d} draws: {dict(f)}')

    print('\n--- arrays declared by the CP registers (base, stride) ---')
    used = collections.Counter()
    for x in draws:
        for a, m, s in x['desc']:
            if m.startswith('index') and a in ARRAY_NAME:
                i = ARRAY_NAME.index(a)
                used[(a, x['bases'][i], x['strides'][i])] += 1
    for (a, b, s), n in sorted(used.items(), key=lambda kv: -kv[1])[:30]:
        print(f'  {a:<9s} base 0x{b:08x} stride {s:2d}  ({n} draws)')
    print(f'  ...{len(used)} distinct (array, base) pairs in total')


if __name__ == '__main__':
    main()
