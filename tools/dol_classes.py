r"""main.dol still carries its C++ CLASS NAMES -- and their vtables.

The retail DOL has no symbol table: every function comes out of Ghidra as
`FUN_8023c0c0`. But the binary was built with RTTI left on, so the *type name
strings* survive, and next to each one sits that class's method table.

    80783c18: 8074300c  -> "atn::EffectManager"
    80783c1c: 80783bf8     back pointer
    80783c20: 80783c58     next record
    80783c24: 00000000
    80783c28: 8023c080  \
    80783c2c: 8023c0c0   |  the vtable: 9 virtual methods
    ...                  /

So `FUN_8023c080` is `atn::EffectManager`'s first virtual. That turns a wall of
anonymous functions into named entry points across the whole engine.

--- WHY THESE ARE REALLY VTABLES -------------------------------------------
The risk is obvious: a string pointer followed by some words that happen to look
like addresses. Two independent tests say otherwise (`--proof`).

1. Against Ghidra's function list: 28.3% of the pointers are exact function
   ENTRY points, versus 0.59% for the same number of random 4-aligned text
   words -- a 37x lift. (28% is a floor, not the true rate: Ghidra's analysis
   leaves whole regions of this DOL without functions at all.)

2. Against the instruction stream, needing no symbols at all -- what does the
   first instruction at the target look like?

       stwu r1,-N(r1)   28.6%   real prologue        control 0.4%
       li r3 / blr      33.9%   one-line virtuals    control 2.1%
       lwz first        10.1%   getters              control 6.7%
       other            27.5%                        control 90.4%

   62.5% land on a prologue or a recognisable stub, against 2.8% by chance.
   The `li r3; blr` bulk is itself the giveaway: vtables are full of trivial
   overrides returning a constant, and random code is not.

--- WHAT IS IN THERE -------------------------------------------------------
704 records. Beyond `std::` and `boost::` template instantiations, the engine's
own classes are named, including whole subsystems this project had only seen
from the outside: `atn::EffectManager`, `SkillEffectManager`, `ColliAttrManager`
(see parse_colli_attr.py -- that name is what led to the surface table),
`ChaseManager`, `CrowdSimulation`, `CharaManager<EnemyTask>`, `gmk::*`,
`Event::Action*`, and 60-odd `AI::Script::AI_*` behaviours named after what they
do (`AI_fr_follow_player`, `AI_em_sword_attack01`, `AI_np_wait_reaction`).

--- LIMITS -----------------------------------------------------------------
Record detection is a heuristic: a data word pointing to a printable string,
followed by at least two text pointers. It over-collects -- strings like `END`
or `rightfrontarm2` are bone and state names, not classes -- so filter on `::`
or check the name yourself before trusting one. The `+0x08` field chains to a
neighbouring record but only within a blob, so it does not enumerate everything.

Usage:
    python dol_classes.py                    # every record
    python dol_classes.py Effect Colli       # filter by name substring
    python dol_classes.py --engine           # skip std:: / boost:: noise
    python dol_classes.py --proof            # run the two tests above
    python dol_classes.py --proof --funcs ghidra_out_gekko/functions.txt
    python dol_classes.py --csv out.csv      # class,address,index,function
"""
import collections
import io
import os
import random
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOL = os.path.join(ROOT, "extract", "sys", "main.dol")
FUNCS = os.path.join(ROOT, "ghidra_out", "functions.txt")

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:<>,\* &\[\]\.\-\+~]{1,250}$")

MFLR_R0 = 0x7C0802A6
BLR = 0x4E800020


class Dol:
    """The DOL's 18 sections, addressable by virtual address."""

    def __init__(self, path=DOL):
        self.d = open(path, "rb").read()
        u32 = lambda o: struct.unpack_from(">I", self.d, o)[0]
        self.secs = []
        for i in range(18):
            if i < 7:
                off, addr, size = u32(0x00 + i*4), u32(0x48 + i*4), u32(0x90 + i*4)
            else:
                j = i - 7
                off, addr, size = u32(0x1C + j*4), u32(0x64 + j*4), u32(0xAC + j*4)
            if size:
                self.secs.append(dict(off=off, addr=addr, size=size, text=i < 7))
        self.text = [s for s in self.secs if s["text"]]
        self.data = [s for s in self.secs if not s["text"]]

    def off(self, va):
        for s in self.secs:
            if s["addr"] <= va < s["addr"] + s["size"]:
                return s["off"] + (va - s["addr"])
        return None

    def w(self, va):
        o = self.off(va)
        return struct.unpack_from(">I", self.d, o)[0] if o is not None else None

    def in_text(self, va):
        return any(s["addr"] <= va < s["addr"] + s["size"] for s in self.text)

    def in_data(self, va):
        return any(s["addr"] <= va < s["addr"] + s["size"] for s in self.data)

    def cstr(self, va, limit=256):
        o = self.off(va)
        if o is None:
            return None
        end = self.d.find(b"\x00", o, o + limit)
        if end < 0:
            return None
        try:
            return self.d[o:end].decode("ascii") or None
        except UnicodeDecodeError:
            return None


def find_records(dol):
    """-> [{'at','name','methods'}] for every candidate class record."""
    out = []
    for s in dol.data:
        base, off, size = s["addr"], s["off"], s["size"]
        for o in range(0, size - 4, 4):
            name_ptr = struct.unpack_from(">I", dol.d, off + o)[0]
            if not (0x80000000 <= name_ptr < 0x81800000):
                continue
            nm = dol.cstr(name_ptr)
            if not nm or not NAME_RE.match(nm):
                continue
            at = base + o
            methods = []
            k = at + 0x10
            while len(methods) < 400:
                v = dol.w(k)
                if v is None or not dol.in_text(v):
                    break
                methods.append(v)
                k += 4
            if len(methods) >= 2:
                out.append({"at": at, "name": nm, "methods": methods})
    return out


def classify(dol, va):
    """What does the first instruction at `va` look like?"""
    w0 = dol.w(va)
    if w0 is None:
        return "unmapped"
    if w0 == MFLR_R0:
        return "mflr r0"
    if (w0 & 0xFFFF0000) == 0x94210000:
        return "stwu r1"
    if w0 == BLR:
        return "blr (stub)"
    op = w0 >> 26
    if op == 14 and ((w0 >> 21) & 31) == 3 and ((w0 >> 16) & 31) == 0:
        return "li r3 (stub)"
    if op == 32:
        return "lwz first"
    return "other"


def proof(dol, recs, funcs=None):
    global FUNCS
    if funcs:
        FUNCS = funcs
    ptrs = [m for r in recs for m in r["methods"]]
    n = len(ptrs)
    print(f"records: {len(recs)}   vtable pointers: {n}\n")

    if os.path.exists(FUNCS):
        ent = set()
        with open(FUNCS, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                p = line.split(None, 2)
                if len(p) == 3:
                    ent.add(int(p[0], 16))
        words = sum(s["size"] for s in dol.text) // 4
        hit = sum(1 for p in ptrs if p in ent)
        print("TEST 1 -- against Ghidra's function list")
        print(f"  functions known      : {len(ent)}")
        print(f"  pointers that are an ENTRY point : {hit} ({hit/n:.2%})")
        print(f"  null model P(random word is entry): {len(ent)/words:.4%}")
        print(f"  lift                 : {(hit/n)/(len(ent)/words):.0f}x\n")
    else:
        print("TEST 1 skipped: ghidra_out/functions.txt not present\n")

    print("TEST 2 -- first instruction at the target (no symbols needed)")
    got = collections.Counter(classify(dol, p) for p in ptrs)
    random.seed(4242)
    pool = [(s["addr"], s["size"]) for s in dol.text]
    ctl = collections.Counter()
    for _ in range(n):
        b, sz = random.choice(pool)
        ctl[classify(dol, b + 4 * random.randrange(sz // 4))] += 1
    print(f"  {'pattern':14} {'vtable':>9} {'control':>9}")
    for k in ("stwu r1", "mflr r0", "li r3 (stub)", "blr (stub)",
              "lwz first", "other"):
        print(f"  {k:14} {got[k]/n:8.2%} {ctl[k]/n:9.2%}")
    good = got["stwu r1"] + got["mflr r0"] + got["li r3 (stub)"] + got["blr (stub)"]
    cgood = ctl["stwu r1"] + ctl["mflr r0"] + ctl["li r3 (stub)"] + ctl["blr (stub)"]
    print(f"\n  prologue or stub : {good/n:.2%}   control {cgood/n:.2%}"
          f"   ({(good/n)/(cgood/n):.0f}x)")


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    dol = Dol()
    recs = find_records(dol)
    args = sys.argv[1:]

    if args and args[0] == "--proof":
        funcs = None
        if "--funcs" in args:
            funcs = args[args.index("--funcs") + 1]
        proof(dol, recs, funcs)
        return

    if args and args[0] == "--csv":
        import csv as _csv
        out = args[1] if len(args) > 1 else "dol_classes.csv"
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["class", "record", "slot", "function"])
            for r in sorted(recs, key=lambda r: r["name"]):
                for i, m in enumerate(r["methods"]):
                    w.writerow([r["name"], f"{r['at']:08x}", i, f"{m:08x}"])
        print(f"wrote {out}: {sum(len(r['methods']) for r in recs)} rows")
        return

    if args and args[0] == "--engine":
        recs = [r for r in recs
                if not r["name"].startswith(("std::", "boost::"))]
        args = []
    if args:
        low = [a.lower() for a in args]
        recs = [r for r in recs if any(f in r["name"].lower() for f in low)]

    print(f"class records: {len(recs)}\n")
    for r in sorted(recs, key=lambda r: r["name"]):
        print(f"{r['at']:08x}  {len(r['methods']):3d} fn  {r['name']}")


if __name__ == "__main__":
    main()
