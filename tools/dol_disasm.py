r"""A Gekko-tolerant disassembler for main.dol -- and the diagnosis that led to the fix.

Ghidra 12 ships no Gekko/Broadway processor language *out of the box*. The Wii's
CPU adds **paired-single** instructions (two f32 in one 64-bit FPR) that stock
`PowerPC:BE:32` does not know. When the disassembler meets one it reports
"bad instruction data" and stops, so the function containing it is never
created -- and the decompiler answers `halt_baddata()`.

**This is now fixable, and fixed: install a Gekko SLEIGH language and coverage
goes from 44.1 % to 97.6 % -- see docs/19-gekko-sleigh.md.** This module stays
useful for quick look-ups without opening a project, and `--coverage` is the
measurement that tells you which of the two setups you are running.

That is not a nuisance at the edges. Run `--coverage` against a stock-PowerPC
export:

    text bytes                : 7,501,824
    covered by a Ghidra fn    : 3,305,399   (44.1 %)
    NOT covered               : 4,196,425   (55.9 %)

    paired-single instructions: 56,156 -- of which 96.1 % lie OUTSIDE any
    function Ghidra found. Density is 5.14 % of words in uncovered regions
    against 0.27 % inside them: a 19x concentration in exactly the blind spots.

So a stock-PowerPC `functions.txt` is a **floor, not an inventory**, and any
statistic computed against it -- such as the vtable check in dol_classes.py --
is understated by that much. Vector maths, particle simulation and animation
blending are precisely the code that uses paired singles, which is to say
precisely the code this project most wants to read. With the Gekko language
installed the same measurement reads 97.6 % covered and 0.7 % of paired-singles
stranded, and those statistics can be recomputed for real.

This module decodes enough PowerPC to follow data flow -- loads, stores,
arithmetic, branches, comparisons, scalar FP -- and *labels* paired-singles
rather than dying on them. Anything it does not recognise prints as `.word`,
so nothing is silently mis-decoded.

    ps_*     opcode 4     paired-single arithmetic
    psq_l    opcode 56    load quantised paired single
    psq_lu   opcode 57
    psq_st   opcode 60    store quantised paired single
    psq_stu  opcode 61

Opcodes 56-61 are unassigned in stock 32-bit PowerPC, which is what makes them
an unambiguous marker for Gekko code.

Usage:
    python dol_disasm.py 0x8022fac4 120     # disassemble N instructions
    python dol_disasm.py --func 0x8022fbbc  # find the enclosing function first
    python dol_disasm.py --coverage         # the measurement above
    python dol_disasm.py --coverage <path>  # ...against another functions.txt
"""
import bisect
import collections
import io
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOL = os.path.join(ROOT, "extract", "sys", "main.dol")
FUNCS = os.path.join(ROOT, "ghidra_out", "functions.txt")

BLR = 0x4E800020
PSQ_OPS = {56: "psq_l", 57: "psq_lu", 60: "psq_st", 61: "psq_stu"}

DFORM = {32: "lwz", 33: "lwzu", 34: "lbz", 35: "lbzu", 36: "stw", 37: "stwu",
         38: "stb", 39: "stbu", 40: "lhz", 41: "lhzu", 42: "lha", 43: "lhau",
         44: "sth", 45: "sthu", 46: "lmw", 47: "stmw", 48: "lfs", 49: "lfsu",
         50: "lfd", 51: "lfdu", 52: "stfs", 53: "stfsu", 54: "stfd", 55: "stfdu"}
ARITH = {7: "mulli", 8: "subfic", 12: "addic", 13: "addic.", 14: "addi",
         15: "addis", 24: "ori", 25: "oris", 26: "xori", 27: "xoris",
         28: "andi.", 29: "andis."}
XO31 = {23: "lwzx", 87: "lbzx", 151: "stwx", 215: "stbx", 279: "lhzx",
        407: "sthx", 535: "lfsx", 599: "lfdx", 663: "stfsx", 727: "stfdx",
        266: "add", 40: "subf", 235: "mullw", 491: "divw", 444: "or",
        28: "and", 316: "xor", 24: "slw", 536: "srw", 792: "sraw",
        824: "srawi", 339: "mfspr", 467: "mtspr", 0: "cmpw", 32: "cmplw",
        534: "lwbrx", 662: "stwbrx", 790: "lhbrx", 918: "sthbrx",
        104: "neg", 124: "nor", 8: "subfc", 10: "addc", 138: "adde"}
XO63 = {72: "fmr", 21: "fadd", 20: "fsub", 25: "fmul", 18: "fdiv", 12: "frsp",
        40: "fneg", 264: "fabs", 32: "fcmpo", 0: "fcmpu"}
XO59 = {21: "fadds", 20: "fsubs", 25: "fmuls", 18: "fdivs", 29: "fmadds",
        28: "fmsubs", 31: "fnmadds"}


class Dol:
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

    def off(self, va):
        for s in self.secs:
            if s["addr"] <= va < s["addr"] + s["size"]:
                return s["off"] + (va - s["addr"])
        return None

    def w(self, va):
        o = self.off(va)
        return struct.unpack_from(">I", self.d, o)[0] if o is not None else None


def _simm(v):
    return v - 0x10000 if v & 0x8000 else v


def disasm(w, pc):
    op = w >> 26
    rd, ra, rb = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
    d = _simm(w & 0xFFFF)
    if op in DFORM:
        reg = "f" if 48 <= op <= 55 else "r"
        return f"{DFORM[op]:8s} {reg}{rd}, {d}(r{ra})"
    if op in ARITH:
        if op == 14 and ra == 0:
            return f"{'li':8s} r{rd}, {d}"
        if op == 15 and ra == 0:
            return f"{'lis':8s} r{rd}, {w & 0xFFFF:#06x}"
        return f"{ARITH[op]:8s} r{rd}, r{ra}, {d}"
    if op == 18:
        li = w & 0x03FFFFFC
        if li & 0x02000000:
            li -= 0x04000000
        tgt = li if (w & 2) else pc + li
        return f"{'bl' if w & 1 else 'b':8s} {tgt:#010x}"
    if op == 16:
        bd = w & 0xFFFC
        if bd & 0x8000:
            bd -= 0x10000
        return f"{'bc':8s} {rd},{ra}, {pc + bd:#010x}"
    if op == 19:
        return {0x4E800020: "blr", 0x4E800420: "bctr",
                0x4E800421: "bctrl"}.get(w, "b?? (19)")
    if op == 11:
        return f"{'cmpwi':8s} r{ra}, {d}"
    if op == 10:
        return f"{'cmplwi':8s} r{ra}, {w & 0xFFFF}"
    if op in (20, 21):
        m = "rlwimi" if op == 20 else "rlwinm"
        return (f"{m:8s} r{ra}, r{rd}, {(w >> 11) & 31},"
                f"{(w >> 6) & 31},{(w >> 1) & 31}")
    if op == 31:
        m = XO31.get((w >> 1) & 0x3FF)
        return (f"{m:8s} r{rd}, r{ra}, r{rb}" if m
                else f".word    {w:#010x}   # 31/{(w >> 1) & 0x3FF}")
    if op == 63:
        m = XO63.get((w >> 1) & 0x3FF)
        return f"{m:8s} f{rd}, f{ra}, f{rb}" if m else f".word    {w:#010x}   # 63"
    if op == 59:
        m = XO59.get((w >> 1) & 0x1F)
        return f"{m:8s} f{rd}, f{ra}, f{rb}" if m else f".word    {w:#010x}   # 59"
    if op in PSQ_OPS:
        return (f"{PSQ_OPS[op]:8s} f{rd}, {_simm(w & 0xFFF)}(r{ra})"
                f"      # GEKKO paired single")
    if op == 4:
        return f"{'ps_*':8s} f{rd}, f{ra}, f{rb}      # GEKKO paired single"
    return f".word    {w:#010x}   # op {op}"


def enclosing(dol, va, back=0x2000):
    """Find a function start by scanning back for a prologue after a terminator."""
    def prologue(w):
        return w is not None and (w & 0xFFFF0000) == 0x94210000

    def terminator(w):
        return w is None or w == BLR or w == 0 or ((w >> 26) == 18 and not w & 1)

    for delta in range(0, back, 4):
        a = va - delta
        if prologue(dol.w(a)) and terminator(dol.w(a - 4)):
            return a
    return None


def coverage(dol, funcs=FUNCS):
    if not os.path.exists(funcs):
        sys.exit(f"need {funcs} -- see docs/07-main-dol-ghidra.md")
    rs = []
    print(f"functions from         : {funcs}")
    with open(funcs, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            p = line.split(None, 2)
            if len(p) == 3:
                a, n = int(p[0], 16), int(p[1])
                rs.append((a, a + n))
    rs.sort()
    cov = []
    for a, b in rs:
        if cov and a <= cov[-1][1]:
            cov[-1] = (cov[-1][0], max(cov[-1][1], b))
        else:
            cov.append((a, b))
    starts = [a for a, _ in cov]

    def inside(va):
        i = bisect.bisect_right(starts, va) - 1
        return i >= 0 and va < cov[i][1]

    total = sum(s["size"] for s in dol.text)
    covered = sum(b - a for a, b in cov)
    print(f"text bytes             : {total:,}")
    print(f"covered by a Ghidra fn : {covered:,}  ({covered/total:.1%})")
    print(f"NOT covered            : {total-covered:,}  ({1-covered/total:.1%})\n")

    c = collections.Counter()
    for s in dol.text:
        base, off, size = s["addr"], s["off"], s["size"]
        for o in range(0, size - 3, 4):
            va = base + o
            w = struct.unpack_from(">I", dol.d, off + o)[0]
            op = w >> 26
            key = "in" if inside(va) else "out"
            c[f"words_{key}"] += 1
            if op in PSQ_OPS or (op == 4 and w):
                c[f"ps_{key}"] += 1

    ni, no = c["words_in"], c["words_out"]
    pi, po = c["ps_in"], c["ps_out"]
    print(f"{'':24}{'inside fns':>13}{'outside fns':>13}")
    print(f"{'words':24}{ni:13,}{no:13,}")
    print(f"{'paired-singles':24}{pi:13,}{po:13,}")
    print(f"{'  density':24}{pi/max(1,ni):12.4%}{po/max(1,no):13.4%}")
    print(f"\ntotal paired-singles   : {pi+po:,}")
    print(f"  of them outside a fn : {po/max(1,pi+po):.1%}"
          f"   (uncovered text is only {1-covered/total:.1%})")
    print(f"  density ratio        : {(po/max(1,no))/max(pi/max(1,ni),1e-12):.0f}x")


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    if not os.path.exists(DOL):
        sys.exit(f"need {DOL} -- see docs/07-main-dol-ghidra.md")
    dol = Dol()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--coverage":
        coverage(dol, args[1] if len(args) > 1 else FUNCS)
        return
    if args[0] == "--func":
        va = int(args[1], 0)
        st = enclosing(dol, va)
        if st is None:
            print(f"{va:#010x}: no prologue found above it")
            return
        print(f"{va:#010x} is inside the function starting {st:#010x}\n")
        args = [hex(st), args[2] if len(args) > 2 else "80"]
    start = int(args[0], 0)
    n = int(args[1], 0) if len(args) > 1 else 80
    for i in range(n):
        pc = start + i * 4
        w = dol.w(pc)
        if w is None:
            print(f"{pc:08x}: <unmapped>")
            break
        print(f"{pc:08x}: {w:08x}  {disasm(w, pc)}")


if __name__ == "__main__":
    main()
