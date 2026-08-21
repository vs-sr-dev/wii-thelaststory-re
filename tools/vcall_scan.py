r"""Resolve INDIRECT CALLS in main.dol -- the enabler this project kept needing.

The game is C++ with virtual dispatch, and every interesting entry point is
reached through a vtable. Three grep-shaped attempts at finding the call sites
of `atn::ColliTree`'s query methods failed in session 11 (see docs/14-collision.md);
they failed for a structural reason, not for want of a cleverer pattern:

    lwz   r12, 0(rObj)      <- load the vptr out of the object
    lwz   r12, SLOT(r12)    <- pick a slot
    mtctr r12
    bctrl                   <- nothing here names the callee

No text search can answer "who calls this method", because the callee's address
never appears at the call site. What *does* appear is the SLOT NUMBER and an
expression for the object. That is enough, and this module turns it into an
answer in three steps.

--- STEP 1: read the register file, don't grep the bytes -------------------
`interpret()` walks a function's instructions forward keeping a symbolic value
per register, so by the time it reaches `bctrl` it knows what `mtctr` was fed.
Values are small expressions, not numbers:

    ('c', 0x807775c8)     a constant
    ('in', 3)             whatever r3 held on entry -- i.e. `this`
    ('add', e, off)       e + off       shown as `r3+0x1c`
    ('mem', e, off)       *(e + off)    shown as `[r3+0x1c]`

A virtual call is then just a shape: CTR fed by `('mem', ('mem', E, N), slot)`,
with the object at `E + N` -- N is not always 0, because for a sub-object the
compiler folds the `addi` into the vptr load itself.
The object expression falls out of the same pass, and so do the arguments in
r3..r10, which is what makes the *values* passed to a virtual method readable.

--- STEP 2: the vtable layout, measured --------------------------------------
From dol_classes.py a class record is `[name][back][next][0][fn0][fn1]...`, and
the constructor stores `record + 0x08` into the object. So the pointer a call
site dereferences is `record + 8`, method k lives at `vptr + 8 + 4k`, and a slot
offset converts to a method index by `(slot - 8) / 4`. That is what lets
`ColliTree`'s three query forms -- slots 1, 2, 3 -- be recognised as the byte
offsets 0x0c, 0x10, 0x14 seen in the instruction stream.

--- STEP 3: type the objects by watching the constructors --------------------
A call site says `[r3+0x1c]`, not `ColliTree`. The missing link is the store the
constructor makes: `stw rV, 0x1c(r3)` with rV a known vtable pointer says that
at offset 0x1c of the enclosing class sits an object of that class. `--vptr` runs
that scan over the whole text; `--resolve` joins the two tables and prints the
callee by name.

Usage:
    python vcall_scan.py --vptr                 # constructors: class @ this+off
    python vcall_scan.py --vcalls               # every virtual call site
    python vcall_scan.py --layout gmk::Trap     # recovered member layout
    python vcall_scan.py --resolve              # join the two, name the callee
    python vcall_scan.py --callers ColliTree    # who calls a class's methods
    python vcall_scan.py --slot 0x0c,0x10,0x14 --args 7,8
    python vcall_scan.py --xref 0x80057f28      # direct callers, with arguments
    python vcall_scan.py --at 0x803f1234        # dump one function's calls
    python vcall_scan.py --csv out.csv          # every call site, machine readable
"""
import bisect
import collections
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dol_classes import Dol, find_records  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNCS = os.path.join(ROOT, "ghidra_out_gekko", "functions.txt")

BCTRL = 0x4E800421
BCTR = 0x4E800420
BLR = 0x4E800020
VOLATILE = [0] + list(range(3, 13))

U = ("u",)


# --------------------------------------------------------------------------
# expressions
# --------------------------------------------------------------------------
def add(e, off):
    if e[0] == "c":
        return ("c", (e[1] + off) & 0xFFFFFFFF)
    if e[0] == "u":
        return U
    if e[0] == "add":
        off += e[2]
        e = e[1]
        return e if off == 0 else ("add", e, off)
    return e if off == 0 else ("add", e, off)


def load(e, off):
    if e[0] == "u":
        return U
    return ("mem", e, off)


def fmt(e):
    if e[0] == "c":
        return f"{e[1]:#x}"
    if e[0] == "in":
        return f"r{e[1]}"
    if e[0] == "ret":
        who = f"{e[1]:08x}" if e[1] else "?"
        arg = fmt(e[2]) if len(e) > 2 and e[2][0] != "u" else ""
        return f"ret({who}, {arg})" if arg else f"ret({who})"
    if e[0] == "u":
        return "?"
    if e[0] == "add":
        return f"{fmt(e[1])}{e[2]:+#x}"
    if e[0] == "mem":
        inner = fmt(e[1]) if e[2] == 0 else f"{fmt(e[1])}{e[2]:+#x}"
        return f"[{inner}]"
    return "?"


def base_reg(e):
    """The incoming register an expression is rooted at, or None."""
    while e[0] in ("add", "mem"):
        e = e[1]
    return e[1] if e[0] == "in" else None


# --------------------------------------------------------------------------
# the abstract interpreter
# --------------------------------------------------------------------------
def _simm(v):
    return v - 0x10000 if v & 0x8000 else v


def writes_r3(dol, start, size):
    """Does this function touch r3 at all? (Unknown if it calls anything.)

    CodeWarrior reaches its prologue helpers with a plain `bl` --
    `__save_gpr`/`__restore_gpr` only ever touch r11 and r14-r31 -- so treating
    every `bl` as clobbering r3 loses the receiver in most real functions. The
    most common "return value" in this binary is not a getter at all: it is
    `bl __save_gpr` seen through that assumption.
    """
    for off in range(0, size, 4):
        w = dol.w(start + off)
        if w is None:
            return True
        op = w >> 26
        if op == 18 and w & 1:                           # bl: gives up
            return True
        if w in (BCTRL, 0x4C000021):
            return True
        dest = None
        if op in (14, 15, 32, 34, 40, 42, 33, 35, 41, 7, 8, 12, 13):
            dest = (w >> 21) & 31
        elif op in (24, 25, 26, 27, 28, 29, 20, 21, 23):
            dest = (w >> 16) & 31
        elif op == 31:
            xo = (w >> 1) & 0x3FF
            if xo in (444, 28, 316, 24, 536, 792, 824, 124, 476, 412):
                dest = (w >> 16) & 31
            elif xo not in (0, 32, 4, 467, 151, 215, 407, 662, 918):
                dest = (w >> 21) & 31
        if dest == 3:
            return True
    return False


def transparent_calls(dol, sym):
    """The set of functions a caller can call without losing r3."""
    return {a for a, n in sym.funcs if n <= 0x100 and not writes_r3(dol, a, n)}


def interpret(dol, start, end, on_store=None, on_call=None, track=None,
              keeps_r3=()):
    """Walk [start,end) keeping a symbolic value per GPR.

    Straight-line: the whole function body is swept in address order rather
    than along the CFG, which is unsound at joins and deliberately so -- this is
    a lead generator whose every hit is meant to be checked. To keep it honest
    where it is cheap to be, the volatile registers (r0, r3-r12) are dropped at
    every join and after every call, so only values a callee-saved register
    carries -- the `mr r31, r3` that CodeWarrior emits for `this` -- survive a
    block boundary. `crossed` counts the boundaries passed before a site, so a
    caller can prefer the clean ones.
    """
    regs = {r: ("in", r) for r in range(32)}
    stack = {}                       # frame offset -> value, for spilled locals
    ctr = U
    crossed = 0

    def slot(rn, off):
        """The frame offset a `d(rA)` addresses, when rA is the stack pointer."""
        e = regs[rn]
        if e == ("in", 1):
            return off
        if e[0] == "add" and e[1] == ("in", 1):
            return e[2] + off
        return None
    pc = start
    while pc < end:
        w = dol.w(pc)
        if w is None:
            break
        op = w >> 26
        rs = (w >> 21) & 31          # dest for loads/arith, source for stores
        ra = (w >> 16) & 31
        rb = (w >> 11) & 31
        d = _simm(w & 0xFFFF)

        if op == 14:                                     # addi / li
            regs[rs] = ("c", d & 0xFFFFFFFF) if ra == 0 else add(regs[ra], d)
        elif op == 15:                                   # addis / lis
            hi = (w & 0xFFFF) << 16
            regs[rs] = ("c", hi) if ra == 0 else add(regs[ra], d << 16)
        elif op in (24, 25):                             # ori / oris
            v = (w & 0xFFFF) << (16 if op == 25 else 0)
            regs[ra] = ("c", regs[rs][1] | v) if regs[rs][0] == "c" else U
        elif op == 32:                                   # lwz
            sl = slot(ra, d) if ra else None
            if sl is not None and sl in stack:
                regs[rs] = stack[sl]
            else:
                regs[rs] = load(regs[ra], d) if ra else ("c", d & 0xFFFFFFFF)
        elif op in (34, 40, 42, 33, 35, 41):             # other integer loads
            regs[rs] = U
        elif op == 36:                                   # stw
            if on_store is not None:
                on_store(pc, regs[rs], regs[ra] if ra else ("c", 0), d)
            sl = slot(ra, d) if ra else None
            if sl is not None:
                stack[sl] = regs[rs]
        elif op == 31:
            xo = (w >> 1) & 0x3FF
            if xo == 444 and rs == rb:                   # mr rA, rS
                regs[ra] = regs[rs]
            elif xo == 467:                              # mtspr
                sprf = (w >> 11) & 0x3FF
                if (((sprf & 0x1F) << 5) | (sprf >> 5)) == 9:
                    ctr = regs[rs]
            elif xo == 266 and regs[rb][0] == "c":       # add rD,rA,rB
                regs[rs] = add(regs[ra], regs[rb][1])
            elif xo in (0, 32, 4):                       # compares: no writeback
                pass
            elif xo == 151 and on_store is not None:     # stwx: unknown offset
                pass
            else:
                regs[rs if xo not in (444, 28, 316, 24, 536, 792, 824) else ra] = U
        elif op in (20, 21, 23):                         # rlwimi / rlwinm / rlwnm
            regs[ra] = U
        elif op in (7, 8, 12, 13, 26, 27, 28, 29):       # mulli, addic, xori...
            regs[rs if op in (7, 8, 12, 13) else ra] = U
        elif op == 16:                                   # bc
            crossed += 1
        elif op == 37:                                   # stwu: the prologue
            if on_store is not None:
                on_store(pc, regs[rs], regs[ra] if ra else ("c", 0), d)
            regs[ra] = add(regs[ra], d)
        elif op == 18:                                   # b / bl
            if w & 1:
                if on_call is not None:
                    on_call(pc, "bl", None, regs, crossed)
                li = w & 0x03FFFFFC
                if li & 0x02000000:
                    li -= 0x04000000
                for r in VOLATILE:
                    regs[r] = U
                arg3 = regs[3]
                tgt = (li if (w & 2) else pc + li) & 0xFFFFFFFF
                for r in VOLATILE:
                    regs[r] = U
                regs[3] = arg3 if tgt in keeps_r3 else ("ret", tgt, arg3)
            else:
                crossed += 1                             # falls into a join
                for r in VOLATILE:
                    regs[r] = U
        elif op == 19:
            if w in (BCTRL, BCTR):
                if on_call is not None:
                    on_call(pc, "bctrl" if w == BCTRL else "bctr", ctr, regs,
                            crossed)
                for r in VOLATILE:
                    regs[r] = U
                regs[3] = ("ret", None, U)
                if w == BCTR:
                    crossed += 1
            else:                                        # blr, bclr, bcctr
                if w == BLR:
                    crossed += 1
                for r in VOLATILE:
                    regs[r] = U
        if track is not None:
            track(pc, regs, ctr)
        pc += 4
    return regs


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
def load_funcs(path=FUNCS):
    fns = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            p = line.split(None, 2)
            if len(p) == 3:
                fns.append((int(p[0], 16), int(p[1])))
    fns.sort()
    return fns


class Symbols:
    """Class records, their vtable pointers, and function -> owner lookup."""

    def __init__(self, dol, funcs):
        self.dol = dol
        self.recs = find_records(dol)
        self.by_vptr = {}
        self.fn_owner = {}
        for r in self.recs:
            self.by_vptr[r["at"] + 8] = r
            for i, m in enumerate(r["methods"]):
                self.fn_owner.setdefault(m, (r["name"], i))
        self.funcs = funcs
        self.starts = [a for a, _ in funcs]

    def enclosing(self, va):
        i = bisect.bisect_right(self.starts, va) - 1
        if i >= 0 and va < self.funcs[i][0] + self.funcs[i][1]:
            return self.funcs[i][0]
        return None

    def fname(self, va):
        own = self.fn_owner.get(va)
        return f"{own[0]}::v{own[1]}" if own else f"FUN_{va:08x}"

    def method(self, vptr, slot):
        """(class, index, target function) for a vptr + byte offset."""
        r = self.by_vptr.get(vptr)
        if r is None or slot < 8 or (slot - 8) % 4:
            return None
        k = (slot - 8) // 4
        if k >= len(r["methods"]):
            return None
        return r["name"], k, r["methods"][k]


# --------------------------------------------------------------------------
# scan 1 -- vptr stores (constructors)
# --------------------------------------------------------------------------
def scan_vptr(dol, sym, keeps=None):
    """-> [(pc, fn, class, object expr, offset)] for every vtable store."""
    if keeps is None:
        keeps = transparent_calls(dol, sym)
    out = []
    for start, size in sym.funcs:
        cur = start

        def on_store(pc, val, base, off, _cur=lambda: cur):
            if val[0] != "c":
                return
            r = sym.by_vptr.get(val[1])
            if r is None:
                return
            out.append((pc, _cur(), r["name"], base, off))

        interpret(dol, start, start + size, on_store=on_store,
                  keeps_r3=keeps)
    return out


# --------------------------------------------------------------------------
# scan 2 -- indirect call sites
# --------------------------------------------------------------------------
class Site:
    __slots__ = ("pc", "fn", "kind", "slot", "obj", "args", "crossed", "ctr")

    def __init__(self, pc, fn, kind, slot, obj, args, crossed, ctr):
        self.pc, self.fn, self.kind = pc, fn, kind
        self.slot, self.obj, self.args = slot, obj, args
        self.crossed, self.ctr = crossed, ctr

    def __repr__(self):
        s = f"{self.slot:#x}" if self.slot is not None else "-"
        return f"<{self.pc:08x} slot={s} obj={fmt(self.obj)}>"


def scan_calls(dol, sym, keeps_r3=None):
    if keeps_r3 is None:
        keeps_r3 = transparent_calls(dol, sym)
    out = []
    for start, size in sym.funcs:
        here = []

        def on_call(pc, kind, ctr, regs, crossed, _h=here):
            if kind == "bl":
                w = dol.w(pc)
                li = w & 0x03FFFFFC
                if li & 0x02000000:
                    li -= 0x04000000
                tgt = li if (w & 2) else pc + li
                _h.append(Site(pc, None, "bl", None, ("c", tgt & 0xFFFFFFFF),
                               {r: regs[r] for r in range(3, 11)}, crossed,
                               ("c", tgt & 0xFFFFFFFF)))
                return
            if ctr is None:
                return
            slot = obj = None
            if ctr[0] == "mem" and ctr[1][0] == "mem":
                # the virtual-call shape. The vptr load is NOT always at
                # offset 0: for a sub-object the compiler folds the `addi`
                # into it, so `lwz r12,0x14b0(r28)` loads the vptr of the
                # object at r28+0x14b0. Fold it back or the site is missed.
                slot, obj = ctr[2], add(ctr[1][1], ctr[1][2])
            elif ctr[0] == "mem":
                slot, obj = ctr[2], ("indirect", ctr[1])
            args = {r: regs[r] for r in range(3, 11)}
            _h.append(Site(pc, None, kind, slot, obj if obj is not None else U,
                           args, crossed, ctr))

        interpret(dol, start, start + size, on_call=on_call, keeps_r3=keeps_r3)
        for s in here:
            s.fn = start
        out.extend(here)
    return out


# --------------------------------------------------------------------------
# step 3 -- give the objects a type
# --------------------------------------------------------------------------
class Types:
    """Which class does a function belong to, and what does it hold where.

    Three sources, in order of how much they can be trusted:

    * a function that stores class X's vtable at `this+0` IS a constructor of X;
    * a store of class Y's vtable at `this+OFF` inside a constructor of X says
      X holds a Y at OFF -- CodeWarrior inlines small constructors, so most
      members show up this way;
    * a `bl` to a known constructor of Y with `r3 = this+OFF` says the same
      thing for the members whose constructor was too big to inline.

    Method-to-class comes from the vtables, then propagates once through direct
    calls that forward `this` unchanged: `bl f` with `r3 = r3` inside a method
    of X makes f a method of X too. One round only -- it is a lead, and each
    extra round multiplies the chance of carrying a wrong name along.
    """

    def __init__(self, dol, sym, sites):
        self.sym = sym
        self.layout = collections.defaultdict(dict)
        self.of_fn = {}
        self.ctors = collections.defaultdict(list)
        self.rec_by_name = {r["name"]: r for r in sym.recs}

        # A constructor writes the BASE class's vtable first and its own last,
        # so the last store to a given slot is the one that names the object.
        stores = scan_vptr(dol, sym)
        at_slot = {}
        for pc, fn, cls, base, off in sorted(stores):
            at = None
            if base == ("in", 3):
                at = off
            elif base[0] == "add" and base[1] == ("in", 3):
                at = base[2] + off
            if at is not None:
                at_slot[(fn, at)] = cls
        for (fn, at), cls in at_slot.items():                   # constructors
            if at == 0:
                self.of_fn[fn] = cls
                self.ctors[cls].append(fn)
        for fn, (cls, _i) in sym.fn_owner.items():              # vtable slots
            self.of_fn.setdefault(fn, cls)
        for (fn, at), cls in at_slot.items():                   # inlined members
            owner = self.of_fn.get(fn)
            if owner and at:
                self.layout[owner].setdefault(at, cls)
        ctor_class = {}
        for cls, fns in self.ctors.items():
            for fn in fns:
                ctor_class.setdefault(fn, cls)
        for s in sites:                                         # called members
            if s.kind != "bl":
                continue
            owner = self.of_fn.get(s.fn)
            sub = ctor_class.get(s.ctr[1])
            e = s.args[3]
            if owner and sub and e[0] == "add" and e[1] == ("in", 3):
                self.layout[owner].setdefault(e[2], sub)
        for s in sites:                                         # one propagation
            if s.kind == "bl" and s.args[3] == ("in", 3):
                owner = self.of_fn.get(s.fn)
                if owner:
                    self.of_fn.setdefault(s.ctr[1], owner)

    def ctor_count(self, cls):
        return len(self.ctors.get(cls, ()))

    def class_of_object(self, s):
        owner = self.of_fn.get(s.fn)
        if owner is None:
            return None
        if s.obj == ("in", 3):
            return owner
        if s.obj[0] == "add" and s.obj[1] == ("in", 3):
            return self.layout.get(owner, {}).get(s.obj[2])
        return None

    def resolve(self, s):
        cls = self.class_of_object(s)
        r = self.rec_by_name.get(cls) if cls else None
        return self.sym.method(r["at"] + 8, s.slot) if r else None

    def resolve_exact(self, s, dol):
        """CTR = *(fixed address + slot): no heuristic, just read the word.

        These are not vtables but plain function-pointer tables built into the
        data sections, so the callee is simply sitting there to be read. Tables
        that live in BSS are filled at run time and read back as a non-text
        word; those are reported as unresolved rather than guessed at.
        """
        if s.slot is None or s.obj[0] != "indirect" or s.obj[1][0] != "c":
            return None
        tgt = dol.w((s.obj[1][1] + s.slot) & 0xFFFFFFFF)
        return tgt if tgt and dol.in_text(tgt) else None


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------
def show_site(sym, s, target=None):
    args = " ".join(f"r{r}={fmt(v)}" for r, v in sorted(s.args.items())
                    if v[0] != "u" and v != ("in", r))
    tgt = f"  -> {target}" if target else ""
    warn = "" if s.crossed == 0 else f"  (~{s.crossed}br)"
    if s.kind == "bl":
        what = f"bl {sym.fname(s.ctr[1])}"
    else:
        slot = f"vt+{s.slot:#04x}" if s.slot is not None else "vt+?  "
        what = f"{slot} obj={fmt(s.obj)}"
    print(f"  {s.pc:08x} in {sym.fname(s.fn):32s} {what:34s}{tgt}{warn}")
    if args:
        print(f"           {args}")


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    funcs_path = FUNCS
    if "--funcs" in args:
        funcs_path = args[args.index("--funcs") + 1]
    if not os.path.exists(funcs_path):
        sys.exit(f"need {funcs_path} -- see docs/19-gekko-sleigh.md")
    dol = Dol()
    sym = Symbols(dol, load_funcs(funcs_path))

    if args[0] == "--vptr":
        rows = scan_vptr(dol, sym)
        want = args[1].lower() if len(args) > 1 and not args[1].startswith("-") else None
        byclass = collections.Counter(r[2] for r in rows)
        print(f"vtable stores: {len(rows)} in {len({r[1] for r in rows})} functions, "
              f"{len(byclass)} classes\n")
        for pc, fn, cls, base, off in rows:
            if want and want not in cls.lower():
                continue
            print(f"  {pc:08x} in {sym.fname(fn):32s} "
                  f"{fmt(base)}{off:+#06x} = {cls}")
        return

    sites = scan_calls(dol, sym)
    virt = [s for s in sites if s.slot is not None and s.kind != "bl"]
    ind = [s for s in sites if s.kind != "bl"]
    print(f"indirect call sites: {len(ind)}   with a vtable shape: {len(virt)}\n")

    if args[0] == "--vcalls":
        counts = collections.Counter(s.slot for s in virt)
        print("most used slots:")
        for slot, n in counts.most_common(20):
            print(f"  vt+{slot:#04x}  (method {(slot-8)//4 if slot >= 8 else '?'}): {n}")
        return

    if args[0] == "--slot":
        want = {int(x, 0) for x in args[1].split(",")}
        need = []
        if "--args" in args:
            need = [int(x) for x in args[args.index("--args") + 1].split(",")]
        sel = [s for s in virt if s.slot in want
               and all(s.args[r][0] != "u" and s.args[r] != ("in", r) for r in need)]
        print(f"slots {sorted(want)}, args {need} known: {len(sel)} sites\n")
        for s in sel:
            show_site(sym, s)
        return

    if args[0] == "--xref":
        tgt = int(args[1], 0)
        sel = [s for s in sites if s.kind == "bl" and s.ctr[1] == tgt]
        print(f"direct calls to {sym.fname(tgt)} @ {tgt:08x}: {len(sel)}")
        for s in sel:
            a = " ".join(f"r{r}={fmt(v)}" for r, v in sorted(s.args.items())
                         if v[0] != "u" and v != ("in", r))
            print(f"  {s.pc:08x} in {sym.fname(s.fn):32s} {a}")
        return

    if args[0] == "--at":
        va = int(args[1], 0)
        fn = sym.enclosing(va) or va
        print(f"calls inside {sym.fname(fn)} @ {fn:08x}\n")
        for s in sites:
            if s.fn == fn:
                show_site(sym, s)
        return

    if args[0] == "--csv":
        import csv as _csv
        out = args[1] if len(args) > 1 else "vcalls.csv"
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["site", "function", "owner", "slot", "method", "object"]
                       + [f"r{r}" for r in range(3, 11)] + ["branches"])
            for s in ind:
                w.writerow([f"{s.pc:08x}", f"{s.fn:08x}", sym.fname(s.fn),
                            f"{s.slot:#x}" if s.slot is not None else "",
                            (s.slot - 8) // 4 if s.slot and s.slot >= 8 else "",
                            fmt(s.obj)]
                           + [fmt(s.args[r]) for r in range(3, 11)]
                           + [s.crossed])
        print(f"wrote {out}: {len(ind)} rows")
        return

    types = Types(dol, sym, sites)

    if args[0] == "--layout":
        want = args[1].lower() if len(args) > 1 else ""
        print(f"classes with a recovered layout: {len(types.layout)}\n")
        for cls in sorted(types.layout):
            if want and want not in cls.lower():
                continue
            print(f"{cls}   ({types.ctor_count(cls)} ctor)")
            for off in sorted(types.layout[cls]):
                print(f"    +{off:#06x}  {types.layout[cls][off]}")
        return

    if args[0] == "--names":
        import csv as _csv
        out = args[1] if len(args) > 1 else "dol_fn_classes.csv"
        src = {}
        for fn in types.of_fn:
            src[fn] = ("vtable" if fn in sym.fn_owner
                       else "constructor" if fn in
                       {f for fs in types.ctors.values() for f in fs}
                       else "forwarded this")
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["function", "class", "slot", "evidence"])
            for fn in sorted(types.of_fn):
                own = sym.fn_owner.get(fn)
                w.writerow([f"{fn:08x}", types.of_fn[fn],
                            own[1] if own else "", src[fn]])
        print(f"wrote {out}: {len(types.of_fn)} functions")
        print(collections.Counter(src.values()).most_common())
        return

    if args[0] in ("--resolve", "--callers"):
        want = args[1].lower() if len(args) > 1 else None
        hits = exact = shown = 0
        for s in virt:
            m = types.resolve(s)
            t = types.resolve_exact(s, dol)
            exact += bool(t)
            if not m:
                if t and not want:
                    shown += 1
                    if shown <= 400:
                        show_site(sym, s, f"{sym.fname(t)}  {t:08x}  [exact]")
                continue
            hits += 1
            if want and want not in (m[0] + " " + types.of_fn.get(s.fn, "")).lower():
                continue
            shown += 1
            if shown <= 400:
                show_site(sym, s, f"{m[0]}::v{m[1]}  {m[2]:08x}")
        print(f"\nfunctions given a class     : {len(types.of_fn)} of {len(sym.funcs)}")
        print(f"indirect call sites         : {len(ind)}")
        print(f"  with a vtable shape       : {len(virt)}")
        print(f"  callee read out of a fixed pointer table : {exact}")
        print(f"  callee named via the object's class      : {hits}")
        print(f"  resolved, total           : {hits + exact}"
              f"   ({(hits + exact) / len(ind):.1%} of all indirect calls)")
        if want:
            print(f"  matching {want!r}: {shown}")
        return

    sys.exit(f"unknown option {args[0]}")


if __name__ == "__main__":
    main()
