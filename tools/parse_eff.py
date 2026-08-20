r"""The Last Story effects, BINARY side: `.eff` (`@EFF$`), 2,210 files.

This is the effect definition itself: particle emitters, materials and
animation curves. The layer that drives it is the `.efp` XML (see
parse_efp.py); `.gmk` files reference the `.efp`, never these.

--- THE TRAP: IT IS LITTLE-ENDIAN -------------------------------------------
After eight sessions of big-endian data on a PowerPC console, this format is
**little-endian**, and that has to come before everything else because it is
the thing that costs an hour.
Proof: the word at +0x08 read LE is the file size, on **2210/2210** files. Read
big-endian it is nothing. It fits the rest: the magic is `@EFF$` in reading
order, NOT byte-swapped the way `@HOC` ships as `COH@` (see parse_hocb.py) -
a sign this data comes out of a Windows tool and is shipped as-is.
Second departure from the collision formats: **the offsets are ABSOLUTE**, not
self-relative.

--- header: 72 bytes --------------------------------------------------------
    +0x00  char[8]  '@EFF$\0\0\0'
    +0x08  u32      file size                     2210/2210
    +0x0c  u32      A = number of EMITTERS
    +0x10  u32      B = number of MATERIALS
    +0x14  u32      72, always (start of data)    2210/2210
    +0x18 .. +0x44  section offsets, monotonic    2210/2210
                    (+0x1c and +0x24 are zero in every file)

Sections carry no size field: a section's length is the distance to the next
offset. And it works out exactly, on **2210/2210 files**:

    [+0x14, +0x18)   B * 312   materials
    [+0x18, +0x20)   A * 620   emitters
    [+0x20, +0x28)   0         (empty in every file)
    [+0x28, +0x2c)   A * 4     one u32 per emitter
    [+0x2c, +0x30)   A * 176   curve tables, one per emitter
    [+0x30, +0x34)   A * 4     one u32 per emitter (always 1)
    [+0x34, +0x40)   0         (empty in every file)
    [+0x40, +0x44)   A * 4     one u32 per emitter
    [+0x44, EOF)     tail: the curve KEY DATA

These six exact equalities are what establish that A and B are counters and
that the records are 312, 620, 176 and 4 bytes. None of them was guessed from
looking at one file - they hold on all of them. 6 files of 2,210 are empty
(A = B = 0, 72 bytes total, every offset equal to the file size).

--- MATERIAL: 312 bytes -----------------------------------------------------
    +0x000  char[128]  COLOUR texture name   (`..._c.texture`)
    +0x080  char[128]  ALPHA texture name    (`..._a.texture`)
    +0x100  56 bytes   parameters (u32 and f32: blend mode, uv, scale)
128 + 128 + 56 = exactly 312. The two slots follow the suffix convention
already known from the disc (`_c` colour, `_a` alpha), and some hold a `.model`
instead of a texture: effects can use meshes, not only billboards.

**Cross-check (--check-res)**: the names must be real files. 727 distinct names
over 8,250 references, and **721 exist on disc** under `data/texture/` or
`data/model/`. The 6 that do not are informative and are NOT misreads: two are
the author's own typos (`ef_waa04n_a.textuer`, with "er" transposed, and
`ef_hkr21n_c` with no extension at all) and the rest (`Mb243_*`) live in the
recursive `levels`/`eventpacks` packs that are still unexploded.

--- EMITTER: 620 bytes ------------------------------------------------------
    +0x000  char[64]   NAME, NUL-terminated, Shift-JIS
    +0x040  ...        parameters: lifetime, count, gravity, sizes,
                       RGBA colour as floats in 0..255, rotation in degrees...
The name is hand-authored and Japanese: `煙` (smoke, 94 times), `土煙` (dust
cloud), `軌跡` (trail), `フラッシュ` (flash), `クロモヤ` (black haze), `石`
(stone), mixed with romaji (`line00`, `tub00`, `smoke10`). 2,570 distinct names
across 8,637 emitters.
**Careful reading it**: in 3,553 of the 8,637 records the bytes AFTER the
terminator are not zero - they are the remains of a longer name written earlier
into the same buffer and never cleared (`波門_大\0E\x83C`). You must cut at the
first NUL; stripping zeros, or reading all 64 bytes, gives dirty names.

--- CURVES: the part that can be PROVEN -------------------------------------
Each emitter owns a 176-byte record = **22 pairs of (keyCount, offset)**, one
per animatable channel (22 * 8 = exactly 176). The offset points into the tail,
where each key is **8 bytes = (f32 t, f32 value)**.

Five independent counts say this reading is right, over 36,705 curves and
105,557 keys:
  - every pointer lands inside the tail and `offset + keyCount*8` does not
    overrun it: **2204/2204 files**;
  - key blocks **never overlap**: 2204/2204;
  - **every byte of the tail the curves do not cover is zero: 2204/2204.**
    That is, the curves tile the tail and the remainder is padding. It is never
    covered 100%: 4 to a few dozen zero bytes are left, always a multiple of 4;
  - **the first key has t = 0.0 on 36,705/36,705 curves - 100%**;
  - **the last key has t = 1.0 on 36,705/36,705 curves - 100%**.

The last two also say WHAT the time axis is: the domain is not frames, it is
the **particle's normalised lifetime, [0,1]** - the standard particle-system
convention. A misread field does not produce 36,705 curves that all start at
0.0 and all end at 1.0.
62% of curves have just 2 keys (start and end); the largest has 78.
Time is non-decreasing on 36,659/36,705 (99.87%): the 46 exceptions are tiny
inversions between adjacent keys (0.37224 then 0.36909) - authoring noise, not
a parsing error.

--- the 22 channels: what is known and what is NOT -------------------------
They look grouped by component (0-2, 3-5, 7-9, 12-14, 15-17, 19-21, with 6 and
18 standing alone), but **the key counts within a group do not always match**
(79% for the first group, ~99% for the others): each component is keyed
independently, so a group is not one vector curve.

**TRIED AND FALSIFIED, do not redo it** (--channels): the idea was that if a
channel animates a parameter, the curve's value at t=0 should equal the
corresponding STATIC parameter inside the emitter's 620 bytes - which would
pair channel <-> offset through a recomputable invariant. A first count looked
like it worked (>90% on some channels) but it was **entirely an artefact**:
those matches were on the values 0.0 and 1.0, which occupy dozens of static
slots and match by chance. Repeating the count **on distinctive values only**
(excluding 0, +-1, 0.5, 255, 360) the signal disappears: the best offset
reaches 4% and in the vast majority of cases NO static offset matches at all
(channel 0: 3,056 of 3,236 cases with no match). So the curve's initial value
is **not duplicated** in the static block: the curve replaces the parameter
rather than shadowing it. This really does need the DOL or an on-screen
comparison.

What can be stated as fact (--channels):
  - **channel 6 is the universal one**: animated on 7,992 of 8,637 emitters
    (92%), constant in only 0.7% of cases, and **ending at exactly 0 on 94.4%
    of its 7,992 curves**. It is a quantity that dies out at end of life. It
    stays within [0,255] on 99.6% of curves and within [0,1] on 0.0%, so it is
    on a 0-255 scale.
  - channels 19-21 hit -360, -403, 720 and 848: multiples of 360, so degrees.
    But they are used only 45 times - far too few to conclude.
  - channels 1 and 2 are constant in 51% and 81% of cases: multipliers left
    at 1.
Which quantity each one drives is NOT settled and is not guessed here.

--- not decoded -------------------------------------------------------------
Most of the emitter's 620 bytes and the material's 56 are readable floats with
no names attached. Of the three A*4 tables, the one at +0x30 is **1 in all
8,637 records**; the other two have 68 and 76 distinct values.

Usage:
    python parse_eff.py FILE.eff        # summary: materials, emitters, curves
    python parse_eff.py --check         # structure: the six section equalities
    python parse_eff.py --check-curves  # tiling and the [0,1] domain
    python parse_eff.py --check-res     # resource names exist on disc
    python parse_eff.py --names         # emitter names
    python parse_eff.py --channels      # the 22 channels: facts + the ruled-out idea
"""
import sys, os, glob, struct, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FS = os.path.join(ROOT, "assets", "pack", "filesystem")
EFF_DIR = os.path.join(FS, "data", "eff")
TEX_DIR = os.path.join(FS, "data", "texture")
MDL_DIR = os.path.join(FS, "data", "model")

MAGIC = b"@EFF$"
MAT_SIZE, EMI_SIZE, CURVETAB_SIZE, KEY_SIZE = 312, 620, 176, 8
N_SLOTS = 22
# the header's section offsets, in order; +0x1c and +0x24 are zero everywhere
SEC_OFF = (0x14, 0x18, 0x20, 0x28, 0x2c, 0x30, 0x34, 0x38, 0x3c, 0x40, 0x44)


def _u32(d, o): return struct.unpack_from("<I", d, o)[0]


def _cstr(b):
    """Cut at the FIRST NUL: what follows is leftovers of previous names."""
    return b.split(b"\0")[0]


def header(d):
    assert d[:5] == MAGIC, f"unexpected magic {d[:5]!r}"
    return {"size": _u32(d, 8), "n_emitters": _u32(d, 0x0c),
            "n_materials": _u32(d, 0x10),
            "sections": [_u32(d, o) for o in SEC_OFF]}


def parse(d):
    h = header(d)
    A, B = h["n_emitters"], h["n_materials"]
    s = h["sections"]
    out = {"size": len(d), "header": h, "materials": [], "emitters": []}
    for i in range(B):
        o = s[0] + i * MAT_SIZE
        out["materials"].append({
            "offset": o,
            "color_map": _cstr(d[o:o + 128]).decode("latin1"),
            "alpha_map": _cstr(d[o + 128:o + 256]).decode("latin1"),
            "params": d[o + 256:o + MAT_SIZE]})
    for i in range(A):
        o = s[1] + i * EMI_SIZE
        try:
            name = _cstr(d[o:o + 64]).decode("shift-jis")
        except UnicodeDecodeError:
            name = _cstr(d[o:o + 64]).decode("latin1")
        curves = []
        ct = s[4] + i * CURVETAB_SIZE
        for k in range(N_SLOTS):
            cnt, ptr = struct.unpack_from("<2I", d, ct + k * 8)
            curves.append(
                [struct.unpack_from("<2f", d, ptr + j * KEY_SIZE)
                 for j in range(cnt)] if cnt else [])
        out["emitters"].append({
            "offset": o, "name": name, "curves": curves,
            "tab28": _u32(d, s[3] + i * 4), "tab30": _u32(d, s[5] + i * 4),
            "tab40": _u32(d, s[9] + i * 4),
            "params": d[o + 64:o + EMI_SIZE]})
    return out


def parse_file(path):
    with open(path, "rb") as f:
        return parse(f.read())


def _files(paths=None):
    return sorted(paths or glob.glob(os.path.join(EFF_DIR, "*.eff")))


# --------------------------------------------------------------------------
def check(paths=None):
    """The section equalities: this is what decides the layout is right."""
    files = _files(paths)
    st = collections.defaultdict(collections.Counter)
    for p in files:
        d = open(p, "rb").read()
        h = header(d)
        A, B, s = h["n_emitters"], h["n_materials"], h["sections"]
        n = len(d)
        o = s + [n]
        st["magic @EFF$"][d[:5] == MAGIC] += 1
        st["+0x08 (LE) == file size"][h["size"] == n] += 1
        st["+0x14 == 72"][s[0] == 72] += 1
        st["offsets monotonic"][all(a <= b for a, b in zip(o, o[1:]))] += 1
        st["+0x1c and +0x24 == 0"][_u32(d, 0x1c) == 0 and _u32(d, 0x24) == 0] += 1
        st["[+0x14,+0x18) == B*312"][o[1] - o[0] == B * MAT_SIZE] += 1
        st["[+0x18,+0x20) == A*620"][o[2] - o[1] == A * EMI_SIZE] += 1
        st["[+0x20,+0x28) empty"][o[3] - o[2] == 0] += 1
        st["[+0x28,+0x2c) == A*4"][o[4] - o[3] == A * 4] += 1
        st["[+0x2c,+0x30) == A*176"][o[5] - o[4] == A * CURVETAB_SIZE] += 1
        st["[+0x30,+0x34) == A*4"][o[6] - o[5] == A * 4] += 1
        st["[+0x34,+0x40) empty"][o[9] - o[6] == 0] += 1
        st["[+0x40,+0x44) == A*4"][o[10] - o[9] == A * 4] += 1
        st["tail is a multiple of 4"][(n - o[10]) % 4 == 0] += 1
        st["empty file (A=B=0)"][A == 0 and B == 0] += 1
    print(f"=== .eff structure over {len(files)} files ===")
    for k, v in st.items():
        tot = sum(v.values())
        ok = v.get(True, 0)
        flag = "" if ok == tot or k.startswith("empty file") else "   <-- WARNING"
        print(f"  {k:34s} {ok}/{tot}{flag}")


def check_curves(paths=None):
    """Pointers, tail tiling and the [0,1] domain."""
    files = _files(paths)
    st = collections.Counter()
    ncur = nkey = 0
    gaps = collections.Counter()
    kcount = collections.Counter()
    lo = hi = None
    for p in files:
        d = open(p, "rb").read()
        h = header(d)
        A, s = h["n_emitters"], h["sections"]
        if A == 0:
            continue
        tail0, tail1 = s[10], len(d)
        st["files"] += 1
        blocks, ok_ptr = [], True
        for i in range(A):
            ct = s[4] + i * CURVETAB_SIZE
            for k in range(N_SLOTS):
                cnt, ptr = struct.unpack_from("<2I", d, ct + k * 8)
                if not cnt:
                    continue
                ncur += 1
                nkey += cnt
                kcount[cnt] += 1
                if not (tail0 <= ptr and ptr + cnt * KEY_SIZE <= tail1):
                    ok_ptr = False
                    continue
                blocks.append((ptr, cnt * KEY_SIZE))
                ks = [struct.unpack_from("<2f", d, ptr + j * KEY_SIZE)
                      for j in range(cnt)]
                ts = [t for t, _ in ks]
                st["first key t==0"] += ts[0] == 0.0
                st["last key t==1"] += ts[-1] == 1.0
                st["times non-decreasing"] += all(a <= b for a, b in zip(ts, ts[1:]))
                st["times within [0,1]"] += all(0.0 <= t <= 1.0 for t in ts)
                for _, v in ks:
                    lo = v if lo is None else min(lo, v)
                    hi = v if hi is None else max(hi, v)
        st["pointers inside the tail"] += ok_ptr
        blocks.sort()
        covered = bytearray(tail1 - tail0)
        overlap = False
        for a, ln in blocks:
            for x in range(a - tail0, a - tail0 + ln):
                if covered[x]:
                    overlap = True
                covered[x] = 1
        st["no overlap between curves"] += not overlap
        rest = [d[tail0 + x] for x in range(len(covered)) if not covered[x]]
        gaps[len(rest)] += 1
        st["uncovered tail bytes are all zero"] += not any(rest)
        st["tail fully covered"] += not rest
    n = st["files"]
    print(f"=== .eff curves: {ncur} curves, {nkey} keys, over {n} files ===")
    for k in ("pointers inside the tail", "no overlap between curves",
              "uncovered tail bytes are all zero", "tail fully covered"):
        print(f"  {k:38s} {st[k]}/{n}")
    for k in ("first key t==0", "last key t==1", "times non-decreasing",
              "times within [0,1]"):
        print(f"  {k:38s} {st[k]}/{ncur}  ({100*st[k]/ncur:.4f}%)")
    print(f"  uncovered tail bytes: {dict(sorted(gaps.items())[:6])}")
    print(f"  keys per curve: {dict(sorted(kcount.items())[:6])} ... max {max(kcount)}")
    print(f"  values: from {lo} to {hi}")


def check_res(paths=None):
    """Do the texture/model names inside the materials exist on disc?"""
    names_ = collections.Counter()
    for p in _files(paths):
        for m in parse_file(p)["materials"]:
            for nm in (m["color_map"], m["alpha_map"]):
                if nm:
                    names_[nm] += 1
    miss = collections.Counter()
    for nm, c in names_.items():
        e = os.path.splitext(nm)[1]
        d = TEX_DIR if e == ".texture" else MDL_DIR if e == ".model" else None
        if d is None or not os.path.exists(os.path.join(d, nm)):
            miss[nm] = c
    ok = sum(names_.values()) - sum(miss.values())
    print("=== resources referenced by .eff materials ===")
    print(f"  {len(names_)} distinct names, {sum(names_.values())} references")
    print("  extensions:", dict(collections.Counter(
        os.path.splitext(k)[1] for k in names_)))
    print(f"  present on disc: {ok}/{sum(names_.values())}"
          f"  ({len(names_)-len(miss)}/{len(names_)} names)")
    print(f"  missing: {miss.most_common()}")
    print("    <- 'textuer' and the extensionless name are the author's typos;"
          " the Mb243_* live in the unexploded levels/eventpacks packs")


def names(paths=None):
    """Emitter names (Shift-JIS)."""
    nm = collections.Counter()
    dirty = tot = 0
    for p in _files(paths):
        d = open(p, "rb").read()
        h = header(d)
        for i in range(h["n_emitters"]):
            b = d[h["sections"][1] + i * EMI_SIZE:][:64]
            s = _cstr(b)
            tot += 1
            dirty += any(b[len(s):])
            try:
                nm[s.decode("shift-jis")] += 1
            except UnicodeDecodeError:
                nm[s.decode("latin1")] += 1
    print(f"=== emitter names: {len(nm)} distinct over {sum(nm.values())} ===")
    print(f"  records with dirty bytes after the NUL: {dirty}/{tot}"
          "   <- cut at the first NUL, do not strip zeros")
    for n, c in nm.most_common(20):
        print(f"   {n!r:24s} x{c}")


def channels(paths=None):
    """The 22 channels: facts, plus the test that RULED OUT pairing a channel
    with a static emitter parameter."""
    BORING = (0.0, 1.0, -1.0, 0.5, 255.0, 360.0)
    s = collections.defaultdict(lambda: collections.Counter())
    rng = {}
    hits = collections.defaultdict(collections.Counter)
    distinctive = collections.Counter()
    nomatch = collections.Counter()
    for p in _files(paths):
        d = open(p, "rb").read()
        h = header(d)
        for i in range(h["n_emitters"]):
            eo = h["sections"][1] + i * EMI_SIZE
            ct = h["sections"][4] + i * CURVETAB_SIZE
            statics = {}
            for o in range(64, EMI_SIZE - 3, 4):
                v = struct.unpack_from("<f", d, eo + o)[0]
                if v == v and abs(v) < 1e30:
                    statics[o] = v
            for k in range(N_SLOTS):
                cnt, ptr = struct.unpack_from("<2I", d, ct + k * 8)
                if not cnt:
                    continue
                vs = [struct.unpack_from("<f", d, ptr + j * KEY_SIZE + 4)[0]
                      for j in range(cnt)]
                c = s[k]
                c["n"] += 1
                c["ends at 0"] += vs[-1] == 0.0
                c["constant"] += len(set(vs)) == 1
                c["in [0,255]"] += all(0.0 <= v <= 255.0 for v in vs)
                c["in [0,1]"] += all(0.0 <= v <= 1.0 for v in vs)
                a, b = rng.get(k, (1e30, -1e30))
                rng[k] = (min(a, min(vs)), max(b, max(vs)))
                if vs[0] not in BORING:
                    distinctive[k] += 1
                    m = [o for o, sv in statics.items() if sv == vs[0]]
                    if not m:
                        nomatch[k] += 1
                    for o in m:
                        hits[k][o] += 1
    print("=== the 22 curve channels ===")
    print("ch  |   used | constant | ends at 0 | in [0,1] | in [0,255] |"
          "        min |       max")
    for k in range(N_SLOTS):
        c = s.get(k)
        if not c or not c["n"]:
            print(f" {k:2d} | never used")
            continue
        n = c["n"]
        lo, hi = rng[k]
        print(f" {k:2d} | {n:6d} | {100*c['constant']/n:7.1f}% |"
              f" {100*c['ends at 0']/n:8.1f}% | {100*c['in [0,1]']/n:7.1f}% |"
              f" {100*c['in [0,255]']/n:9.1f}% | {lo:10.4g} | {hi:9.4g}")
    print("\n--- RULED OUT: is curve(t=0) equal to a static emitter parameter?")
    print("  (distinctive values only: 0, +-1, 0.5, 255 and 360 match dozens"
          " of slots by chance)")
    print("  ch  | distinctive cases | NO match at all | best offset")
    for k in range(N_SLOTS):
        n = distinctive[k]
        if not n:
            continue
        best = hits[k].most_common(1)
        b = f"+0x{best[0][0]:03x} {100*best[0][1]/n:.1f}%" if best else "-"
        print(f"   {k:2d} | {n:17d} | {100*nomatch[k]/n:14.1f}% | {b}")
    print("  -> the curve's initial value is NOT duplicated in the static"
          " block: the curve replaces the parameter.")


def summary(path):
    m = parse_file(path)
    h = m["header"]
    print(f"=== {os.path.basename(path)} - {m['size']} bytes (little-endian) ===")
    print(f"  {h['n_emitters']} emitters, {h['n_materials']} materials")
    print("  sections:", " ".join(f"0x{v:x}" for v in h["sections"]))
    for i, mt in enumerate(m["materials"]):
        print(f"  material #{i} @0x{mt['offset']:x}"
              f"  colour={mt['color_map']!r}  alpha={mt['alpha_map']!r}")
    for i, e in enumerate(m["emitters"]):
        used = [(k, len(c)) for k, c in enumerate(e["curves"]) if c]
        print(f"  emitter #{i} @0x{e['offset']:x}  {e['name']!r}"
              f"  tab=({e['tab28']},{e['tab30']},{e['tab40']})"
              f"  {len(used)} animated channels")
        for k, n in used:
            c = e["curves"][k]
            vals = ", ".join(f"{t:.3f}:{v:g}" for t, v in c[:4])
            print(f"      channel {k:2d}  {n:2d} keys  {vals}"
                  + (" ..." if n > 4 else ""))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "--check":
        check()
    elif a[0] == "--check-curves":
        check_curves()
    elif a[0] == "--check-res":
        check_res()
    elif a[0] == "--names":
        names()
    elif a[0] == "--channels":
        channels()
    else:
        p = a[0] if os.path.exists(a[0]) else os.path.join(EFF_DIR, a[0])
        if not os.path.exists(p):
            sys.exit(f"{a[0]}: not found")
        summary(p)
