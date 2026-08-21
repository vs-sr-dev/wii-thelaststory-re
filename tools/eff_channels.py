r"""The 22 `.eff` curve channels: what each one drives, read out of main.dol.

Session 8 established the shape of the curve block -- 22 pairs of
(key count, offset) per emitter, keys on normalised particle life [0,1] -- but
not the meaning of a single channel, and a data-only attempt to pair channels
with the static emitter parameters failed (see docs/17-eff-binary.md).
Session 10 read the simulation code instead, which became possible once Ghidra
was taught the Gekko paired-single instructions (docs/19-gekko-sleigh.md).

The evaluator is `FUN_8023329c`:

    float eval(float t, float base, int channel, int emitter, Eff *e, int mul)
        tab = e->curveTables + emitter * 0xb0     // 22 * 8 bytes
        n   = tab[channel].count
        p   = tab[channel].keys                   // (float t, float v) pairs
        walk the keys, find the bracket p[i].t <= t <= p[i+1].t,
        v = lerp(p[i].v, p[i+1].v, (t - p[i].t) / (p[i+1].t - p[i].t))
        return mul ? v * base : v + base          // combined with a base value

Every call site is guarded by a bit of the `A*4` table at header +0x28 -- the
table session 8 recorded as unknown. It is a **per-emitter bitmask saying which
channel groups are keyed**; when a bit is clear the engine uses a static field
of the 620-byte emitter record instead, and in the per-frame path integrates
that field's companion RATE. Nine bits cover all 22 channels:

    bit 0 (0x001)  ch 12,13,14   emitter displacement over time
    bit 1 (0x002)  ch 15,16,17   rotation, degrees
    bit 2 (0x004)  ch 0,1,2      scale
    bit 3 (0x008)  ch 7,8,9      the particle's VELOCITY, world space
    bits 4,5       ch 3,4,5 + 6  colour: popcount 1 -> alpha only,
                                 popcount 2 -> rgb as well
    bit 6 (0x040)  ch 18         (world-space scalar, unnamed)
    bit 7 (0x080)  ch 19,20,21   rotation with a spin rate, degrees
    bit 8 (0x100)  ch 10,11      (pair, no static fallback)

`--proof` turns that into a falsifiable prediction and checks it against every
shipped emitter: the bit must be set exactly when those channels carry keys.
Nothing in the file format enforces it -- it is the DOL's claim about the data.
It holds 77,733 times out of 77,733.

Two independent supports for the naming, both from the data alone (`--statics`):
the static default the engine falls back to for channel 6 has median exactly
255.0 (an alpha), and the three statics of group {0,1,2} have median exactly
1.0 (scale factors). `--profile` adds the shape of each channel and the
co-occurrence matrix, which is block-diagonal on exactly these groups.

SESSION 13 names group {7,8,9}: it is the particle's **velocity**. The update
integrates the position by it (`pos.y += dt * p[0x9c]`, at 0x80231c8c), then
subtracts gravity from the y component, tests the result against a floor plane,
and on contact multiplies the velocity by a negated restitution, applies a
friction term to x and z with a clamp that stops friction from reversing them,
and accumulates a rolling angle s/r about `cross(velocity, down)`. Every one of
those constants is a field in the tail of the emitter record; `--physics` shows
them and checks them against the shipped data. Two independent supports come
from the data alone: the emitters that key the group are `火花` (sparks), `石`
(stones), `土煙` (dust) at 5x the base rate, and channels 7 and 9 end their
curves at exactly 0 in 87 % and 77 % of cases against 12 % for channel 8 --
the two horizontal components are the ones friction stops.

Usage:
    python eff_channels.py --map        # the channel map and struct offsets
    python eff_channels.py --physics    # the bounce/friction/roll block
    python eff_channels.py --proof      # bitmask <-> keyed groups, all files
    python eff_channels.py --profile    # per-channel shape + co-occurrence
    python eff_channels.py --statics    # the static/rate fields main.dol names
"""
import collections
import os
import statistics
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_eff

# bit -> channels, from the call sites of FUN_8023329c in main.dol
BITS = {
    0x001: (12, 13, 14),
    0x002: (15, 16, 17),
    0x004: (0, 1, 2),
    0x008: (7, 8, 9),
    0x040: (18,),
    0x080: (19, 20, 21),
    0x100: (10, 11),
}
RGB, ALPHA = (3, 4, 5), 6

# channels -> (what it drives, particle field, static field, rate field)
GROUPS = [
    ((12, 13, 14), "emitter displacement (x,y,z)", None, 0x0a4, None),
    ((15, 16, 17), "rotation, degrees (x,y,z)", 0x0a4, 0x0e0, None),
    ((0, 1, 2), "scale (x,y,z), x world-scaled", 0x0b0, 0x11c, 0x134),
    ((7, 8, 9), "VELOCITY (x,y,z), world space", 0x098, 0x158, None),
    ((3, 4, 5, 6), "colour R,G,B,A (0-255)", 0x0bc, 0x194, 0x1b4),
    ((18,), "world-space scalar, unnamed", 0x0cc, 0x1e4, 0x1ec),
    ((19, 20, 21), "rotation with spin rate, degrees", 0x0d0, 0x1f8, 0x210),
    ((10, 11), "pair, no static fallback", 0x0dc, None, None),
]


# The bounce/friction/roll block at the tail of the emitter record, read out of
# FUN_8023193c (see docs/20-eff-channels.md). Offsets are into the 620-byte
# record; the addresses are where main.dol loads each one.
PHYSICS = [
    (0x240, "enable", "gates the whole block", "80232004"),
    (0x244, "gravity", "subtracted from vy each frame, x dt x scale", "80232048"),
    (0x248, "radius", "particle rests this far above the floor", "80232028"),
    (0x24c, "restitution", "velocity is multiplied by -this on contact", "8023208c"),
    (0x250, "friction", "scales vx and vz, with a sign-flip clamp", "80232198"),
    (0x254, "roll gain", "multiplies the rolling angle s/r", "802322fc"),
    (0x258, "floor Y", "the plane the test is against", "8023205c"),
]


def _emitters():
    for p in parse_eff._files():
        try:
            e = parse_eff.parse_file(p)
        except Exception:
            continue
        for i, em in enumerate(e["emitters"]):
            yield os.path.basename(p), i, em


def show_map():
    print(__doc__.split("Usage:")[0].rstrip())
    print("\nGroup detail (offsets are into the 620-byte emitter record, and")
    print("into the runtime particle struct):\n")
    print(f"{'channels':<16}{'drives':<34}{'particle':>9}{'static':>8}{'rate':>7}")
    print("-" * 74)
    for ch, what, part, stat, rate in GROUPS:
        cs = ",".join(str(c) for c in ch)
        f = (lambda v: f"{v:#05x}" if v is not None else "-")
        print(f"{cs:<16}{what:<34}{f(part):>9}{f(stat):>8}{f(rate):>7}")


def proof():
    ok = collections.Counter()
    bad = collections.Counter()
    example = {}
    masks = collections.Counter()
    outside = 0
    for name, i, em in _emitters():
        m = em["tab28"]
        masks[m] += 1
        keyed = [bool(em["curves"][k]) for k in range(22)]
        for bit, chans in BITS.items():
            want = bool(m & bit)
            got = all(keyed[c] for c in chans)
            got_any = any(keyed[c] for c in chans)
            tag = f"bit {bit:#05x} <-> channels {chans}"
            if want == got == got_any:
                ok[tag] += 1
            else:
                bad[tag] += 1
                example.setdefault(tag, (name, i, hex(m)))
        n = (1 if m & 0x10 else 0) + (1 if m & 0x20 else 0)
        for tag, cond in (
                ("bits 4|5 popcount >=1 <-> alpha (ch 6) keyed",
                 keyed[ALPHA] == (n >= 1)),
                ("bits 4|5 popcount ==2 <-> rgb (ch 3,4,5) keyed",
                 all(keyed[c] for c in RGB) == (n == 2))):
            (ok if cond else bad)[tag] += 1
            if not cond:
                example.setdefault(tag, (name, i, hex(m)))
        if m & ~0x1ff:
            outside += 1

    print(f"{'prediction':<52}{'holds':>9}{'fails':>8}")
    print("-" * 71)
    to, tb = 0, 0
    for tag in sorted(set(ok) | set(bad)):
        o, b = ok[tag], bad[tag]
        to, tb = to + o, tb + b
        print(f"{tag:<52}{o:>9,}{b:>8,}{'' if b == 0 else '   <-- FAILS'}")
        if b:
            print(f"    first counter-example: {example[tag]}")
    print("-" * 71)
    print(f"{'TOTAL':<52}{to:>9,}{tb:>8,}")
    print(f"\nemitters with a bit outside 0x1ff set: {outside} "
          f"(the mask uses exactly 9 bits)")
    print(f"distinct mask values in the shipped data: {len(masks)}")
    for m, c in masks.most_common(8):
        print(f"  {m:#07x}  {c:>6,}")


def profile():
    n = 0
    rows = [dict(used=0, const=0, vals=[], last=[]) for _ in range(22)]
    co = [[0] * 22 for _ in range(22)]
    for _, _, em in _emitters():
        n += 1
        used = [k for k in range(22) if em["curves"][k]]
        for a in used:
            for b in used:
                co[a][b] += 1
        for k in used:
            vs = [v for _, v in em["curves"][k]]
            r = rows[k]
            r["used"] += 1
            r["const"] += (max(vs) == min(vs))
            r["vals"].extend(vs)
            r["last"].append(vs[-1])
    print(f"emitters: {n:,}\n")
    hdr = (f"{'ch':>3}{'group':<16}{'used':>8}{'%use':>7}{'%const':>8}"
           f"{'min':>11}{'max':>11}{'median':>10}{'%[0,255]':>9}{'last=0':>8}")
    print(hdr)
    print("-" * len(hdr))
    gof = {c: ",".join(map(str, g[0])) for g in GROUPS for c in g[0]}
    for k, r in enumerate(rows):
        if not r["used"]:
            continue
        v = r["vals"]
        p255 = sum(1 for x in v if 0.0 <= x <= 255.0) / len(v)
        l0 = sum(1 for x in r["last"] if x == 0.0) / r["used"]
        print(f"{k:>3}{'{' + gof.get(k, '?') + '}':<16}{r['used']:>8,}"
              f"{r['used']/n:>7.1%}{r['const']/r['used']:>8.1%}"
              f"{min(v):>11.3f}{max(v):>11.3f}{statistics.median(v):>10.3f}"
              f"{p255:>9.1%}{l0:>8.1%}")
    print("\nco-occurrence: % of row-channel's uses that also use the column "
          "channel.\nIt is block-diagonal on exactly the groups above.")
    print("    " + "".join(f"{j:>5}" for j in range(22)))
    for i in range(22):
        if not rows[i]["used"]:
            continue
        print(f"{i:>3} " + "".join(
            f"{co[i][j] / rows[i]['used'] * 100:>5.0f}" for j in range(22)))


def statics():
    fields = []
    for ch, what, _, stat, rate in GROUPS:
        if stat is not None:
            for j, c in enumerate(ch):
                fields.append((stat + j * 4, f"ch{c} static", what))
        if rate is not None:
            fields.append((rate, f"ch{ch[0]} rate", what))
    vals = {o: [] for o, _, _ in fields}
    for _, _, em in _emitters():
        pr = em["params"]                 # from record offset 0x40
        for o, _, _ in fields:
            i = o - 64
            if 0 <= i <= len(pr) - 4:
                vals[o].append(struct.unpack_from("<f", pr, i)[0])
    print(f"{'off':>6} {'field':<14}{'min':>12}{'max':>12}{'median':>11}"
          f"{'%==0':>7}{'%<=255':>8}  what the group drives")
    print("-" * 100)
    for o, lab, what in fields:
        v = [x for x in vals[o] if x == x and abs(x) < 1e30]
        if not v:
            continue
        z = sum(1 for x in v if x == 0.0) / len(v)
        b = sum(1 for x in v if 0.0 <= x <= 255.0) / len(v)
        print(f"{o:#06x} {lab:<14}{min(v):>12.3f}{max(v):>12.3f}"
              f"{statistics.median(v):>11.3f}{z:>7.1%}{b:>8.1%}  {what}")
    print("\nThe two medians that name two groups on their own: the ch6 "
          "fallback is 255.0 (an alpha)\nand the {0,1,2} fallbacks are 1.0 "
          "(scale factors). Neither is forced by the format.")


def physics():
    """The physics block, and the check that names its fields from the data.

    Reading the code gives seven candidate fields. The test that they are what
    they look like is not that the values are plausible -- almost anything is
    plausible for a float -- but that they behave like the fields of a dialog
    box whose checkbox is off: when `enable` is 0 nobody edits them, so they
    should collapse onto a single authoring default, and when it is 1 they
    should spread out. That is a property of the *authoring*, and nothing in
    the file format produces it.
    """
    rows = []
    for _, _, em in _emitters():
        pr = em["params"]                     # from record offset 0x40
        vals = {}
        for off, _, _, _ in PHYSICS:
            i = off - 64
            vals[off] = (struct.unpack_from("<f", pr, i)[0],
                         struct.unpack_from("<I", pr, i)[0])
        rows.append(vals)
    n = len(rows)
    flag = [r[0x240][1] for r in rows]
    on = [r for r, f in zip(rows, flag) if f]
    off = [r for r, f in zip(rows, flag) if not f]
    print(f"{n:,} emitters\n")
    print("the enable flag is a flag: distinct u32 values at +0x240 ->",
          dict(collections.Counter(flag).most_common()))
    print(f"  enable = 1 : {len(on):,}    enable = 0 : {len(off):,}\n")
    print(f"{'off':>6} {'field':<12}{'distinct':>9}{'min':>10}{'max':>10}"
          f"  default when off (share)      spread when on")
    print("-" * 104)
    for o, lab, _, _ in PHYSICS[1:]:
        v = [r[o][0] for r in rows]
        c_off = collections.Counter(r[o][0] for r in off)
        c_on = collections.Counter(r[o][0] for r in on)
        d, k = c_off.most_common(1)[0]
        top = " ".join(f"{x:g}x{m}" for x, m in c_on.most_common(4))
        print(f"{o:#06x} {lab:<12}{len(set(v)):>9}{min(v):>10.4g}{max(v):>10.4g}"
              f"  {d:<8g} {k / len(off):>6.1%}   {top}")
    print("\nWith the checkbox off every field sits on one value; with it on the "
          "same field\nfans out. A default restitution of 0.7, a default "
          "friction of 0.1, a default radius\nof 0.5 and a roll gain whose "
          "default is exactly 1.0 are what those things are.")


def main():
    sys.stdout = __import__("io").TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    if not a or a[0] == "--map":
        show_map()
    elif a[0] == "--proof":
        proof()
    elif a[0] == "--profile":
        profile()
    elif a[0] == "--statics":
        statics()
    elif a[0] == "--physics":
        physics()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
