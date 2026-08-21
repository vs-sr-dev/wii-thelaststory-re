r"""Who reads offset N of a struct? -- the field-level cross reference.

Every remaining question about this engine has the same shape. The `.eff`
curve channels are grouped and proved (docs/20-eff-channels.md), but three of
the groups are still unnamed, and what is missing is not another pass over the
data: it is knowing which code *reads* the runtime particle fields those
groups write -- `+0x098`, `+0x0cc`, `+0x0dc` -- and what it does with them.

Ghidra can answer that for a global. It cannot answer it for a struct member,
because `lfs f1, 0x98(r30)` names no struct: the type lives in the programmer's
head, and the binary only records an offset off a register. So the search
"find the readers of particle+0x98" degenerates into "find every 0x98 in the
binary", which is thousands of unrelated hits.

The fix is the one session 12 used twice: the register file already knows what
`r30` is. `vcall_scan.interpret()` walks a function keeping a symbolic value
per GPR, so at the moment of the load it can say the address is `[r3+0x1c]+0x98`
and not merely `0x98`. This module hangs a callback on the loads (`on_mem`,
added to the interpreter for this) and turns the whole text into a table of

    (function, base expression, offset, kind)

which is a *recovered struct usage*: group by (function, base) and you get the
set of offsets one pointer was used at, in one place, which is the closest
thing to a type declaration the binary still contains.

--- the discriminator: co-access, not the offset ---------------------------
`0x98` alone means nothing -- any class can have a field there. But a base read
at `0x98` *and* at `0xbc` (colour) *and* at `0xa4` (rotation) is a particle,
because nothing else has that combination. `--fingerprint` ranks every
(function, base) pair by how many offsets of a known set it touches, and that
is what promotes a coincidence to an identification. It is the same move as the
`.eff` bitmask proof: state a combination the format does not enforce, then see
who satisfies it.

--- a free bonus: r2/r13 are the float pool -------------------------------
CodeWarrior puts float literals in the small data area, and this binary's
`r2 = 0x808885a0` / `r13 = 0x808856c0` are known (docs/07-main-dol-ghidra.md).
So a load off those is not an unknown field at all -- it is a *constant*, and
the tool prints its value. That turns "where does the /255 happen" from a
question about control flow into a lookup: find the functions that load
0.003921569.

Usage:
    python field_xref.py --offset 0x98              # who touches +0x98
    python field_xref.py --offset 0x98 --near       # ...and what else, same base
    python field_xref.py --fingerprint 0x98,0xa4,0xbc,0xd0   # rank by co-access
    python field_xref.py --fn 802301ec              # struct views of one function
    python field_xref.py --const 0.003921569        # who loads a float constant
    python field_xref.py --consts                   # the float pool itself
    python field_xref.py --csv out.csv
"""
import argparse
import collections
import csv
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dol_classes import Dol                                        # noqa: E402
from vcall_scan import (Symbols, Types, fmt, interpret,            # noqa: E402
                        load_funcs, scan_calls, transparent_calls,
                        transparent_regs)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOL = os.path.join(ROOT, "extract", "sys", "main.dol")

SDA = {2: 0x808885A0, 13: 0x808856C0}     # r2 / r13, docs/07-main-dol-ghidra.md
FLOAT_KINDS = ("lfs", "lfsu", "lfd", "lfdu", "stfs", "stfsu", "stfd", "stfdu")


class Access:
    """One instruction's use of one field."""
    __slots__ = ("pc", "fn", "kind", "base", "off", "reg")

    def __init__(self, pc, fn, kind, base, off, reg):
        self.pc, self.fn, self.kind = pc, fn, kind
        self.base, self.off, self.reg = base, off, reg

    @property
    def is_store(self):
        return self.kind.startswith("st")

    @property
    def is_float(self):
        return self.kind in FLOAT_KINDS


def sda_const(dol, base, off, kind):
    """A float literal, when the base is the small data area."""
    if base[0] != "in" or base[1] not in SDA or kind not in ("lfs", "lfd"):
        return None
    va = (SDA[base[1]] + off) & 0xFFFFFFFF
    n = 8 if kind == "lfd" else 4
    o = dol.off(va)
    if o is None or o + n > len(dol.d):
        return None
    return struct.unpack_from(">d" if n == 8 else ">f", dol.d, o)[0]


def scan(dol, sym, keeps=None, preserved=None):
    """Every non-stack memory access in the text, with its base expression."""
    if keeps is None:
        keeps = transparent_calls(dol, sym)
    if preserved is None:
        preserved = transparent_regs(dol, sym)
    out = []
    for start, size in sym.funcs:
        def on_mem(pc, kind, base, off, val, reg, _fn=start, _o=out):
            if base[0] == "u":
                return
            _o.append(Access(pc, _fn, kind, base, off, reg))
        interpret(dol, start, start + size, on_mem=on_mem, keeps_r3=keeps,
                  preserved=preserved)
    return out


def views(accesses, skip_sda=True):
    """(function, base) -> {offset: [Access]} -- one recovered struct usage."""
    v = collections.defaultdict(lambda: collections.defaultdict(list))
    for a in accesses:
        if skip_sda and a.base[0] == "in" and a.base[1] in SDA:
            continue
        if a.base[0] == "c":                 # an absolute global, not a struct
            continue
        v[(a.fn, fmt(a.base))][a.off].append(a)
    return v


def name(sym, types, fn):
    cls = types.of_fn.get(fn) if types else None
    return f"FUN_{fn:08x}" + (f"  [{cls}]" if cls else "")


def parse_offs(text):
    return [int(x, 0) for x in text.replace(" ", "").split(",") if x]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offset")
    ap.add_argument("--near", action="store_true")
    ap.add_argument("--fingerprint")
    ap.add_argument("--fn")
    ap.add_argument("--const", type=float)
    ap.add_argument("--consts", action="store_true")
    ap.add_argument("--csv")
    ap.add_argument("--min", type=int, default=2,
                    help="fingerprint: least offsets of the set to report")
    ap.add_argument("--max-offsets", type=int, default=0,
                    help="drop bases used at more offsets than this. A "
                         "constructor or a memcpy sweeps a whole struct and so "
                         "satisfies any fingerprint by brute force; a base that "
                         "touches six fields and stops is making a claim.")
    ap.add_argument("--absent", default="",
                    help="fingerprint: require these offsets NOT be touched")
    ap.add_argument("--dol", default=DOL)
    a = ap.parse_args()

    dol = Dol(a.dol)
    sym = Symbols(dol, load_funcs())
    acc = scan(dol, sym)
    print(f"# {len(acc):,} memory accesses over {len(sym.funcs):,} functions",
          file=sys.stderr)

    types = None
    if a.offset or a.fingerprint or a.fn:
        types = Types(dol, sym, scan_calls(dol, sym))

    if a.consts or a.const is not None:
        pool = collections.defaultdict(set)
        for x in acc:
            c = sda_const(dol, x.base, x.off, x.kind)
            if c is not None:
                pool[c].add(x.fn)
        if a.const is not None:
            hits = [(c, f) for c, f in pool.items()
                    if abs(c - a.const) <= abs(a.const) * 1e-6 + 1e-12]
            for c, fns in sorted(hits):
                print(f"{c!r}: {len(fns)} functions")
                for fn in sorted(fns):
                    print(f"    {name(sym, types, fn)}")
        else:
            for c, fns in sorted(pool.items(), key=lambda kv: -len(kv[1]))[:60]:
                print(f"{len(fns):5d}  {c!r}")
        return

    if a.fn:
        want = int(a.fn, 16)
        v = views([x for x in acc if x.fn == want])
        for (_, base), offs in sorted(v.items(), key=lambda kv: -len(kv[1])):
            print(f"\n  base {base}   ({len(offs)} offsets)")
            for off in sorted(offs):
                ks = collections.Counter(x.kind for x in offs[off])
                pcs = " ".join(f"{x.pc:08x}" for x in offs[off][:6])
                print(f"    +{off:#06x}  {','.join(ks):<12} {pcs}")
        return

    if a.offset:
        offs = parse_offs(a.offset)
        v = views(acc)
        rows = [(k, o) for k, o in v.items() if all(t in o for t in offs)]
        rows.sort()
        print(f"# {len(rows)} (function, base) pairs touch all of "
              f"{[hex(o) for o in offs]}")
        for (fn, base), o in rows:
            first = min(x.pc for t in offs for x in o[t])
            print(f"\n{name(sym, types, fn)}  base {base}  @{first:08x}")
            for t in (sorted(o) if a.near else offs):
                ks = collections.Counter(x.kind for x in o[t])
                mark = "  <--" if t in offs else ""
                print(f"    +{t:#06x}  {','.join(sorted(ks)):<20}"
                      f"{sum(ks.values())}x{mark}")
        return

    if a.fingerprint:
        want = set(parse_offs(a.fingerprint))
        no = set(parse_offs(a.absent)) if a.absent else set()
        v = views(acc)
        rows = []
        for (fn, base), o in v.items():
            hit = want & set(o)
            if len(hit) < a.min:
                continue
            if a.max_offsets and len(o) > a.max_offsets:
                continue
            if no & set(o):
                continue
            rows.append((len(hit), fn, base, hit, set(o)))
        rows.sort(key=lambda r: (-r[0], r[1]))
        print(f"# offsets sought: {sorted(hex(x) for x in want)}")
        print(f"# {len(rows)} (function, base) pairs hit >= {a.min} of them\n")
        for n, fn, base, hit, all_off in rows:
            print(f"{n}/{len(want)}  {name(sym, types, fn):<44} base {base}")
            print(f"        hit  {' '.join(f'{x:#x}' for x in sorted(hit))}")
            print(f"        all  {len(all_off)} offsets "
                  f"{' '.join(f'{x:#x}' for x in sorted(all_off)[:24])}")
        return

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["pc", "fn", "kind", "base", "offset", "sda_const"])
            for x in acc:
                w.writerow([f"{x.pc:08x}", f"{x.fn:08x}", x.kind, fmt(x.base),
                            f"{x.off:#x}", sda_const(dol, x.base, x.off, x.kind)])
        print(f"wrote {a.csv}: {len(acc):,} rows")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
