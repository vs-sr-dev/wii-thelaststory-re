# 14 — Collision (`.hocb`, `.hcb`) — the first real binary reverse of the group

Two twin formats sharing one header family: `.hocb` (351 files, magic `COH@`) and
`.hcb` (388 files, magic `BCH@`). The magic is the tag `@HOC` / `@HCB` stored
byte-swapped. A `.map` names its collision with a `COLLI_TREE` row; gimmicks name
theirs with `COLLISION_BEFORE`/`COLLISION_AFTER` (see
[12 — Gimmicks](12-gimmicks.md)).

This is **not** a `chnkdata` container, so the generic parser is no help.

## The one thing you must know first: offsets are self-relative

Every offset in the file is relative to **the position of the field holding it**,
not to the start of the file:

```
target = address_of_field + value
```

That is why the file is littered with words like `ffffff70` — they are *negative*
`s32`, pointers running backwards. Read as absolute offsets they are nonsense,
and that is the format's main trap. Everything else follows once you know this.

## Header

```
+0x00  char[4]  'COH@' / 'BCH@'
+0x04  u32      0x00010000     version
+0x08  u32      total file size            (exact on all 739 files)
+0x20  u32      nSections      \  table DESCRIPTOR, not a section
+0x24  u32      4 + n*16        >  the relation between the two is exact, 739/739
+0x28  u32      formatID       /   0x204 in .hocb, 0x209 in .hcb
+0x30  ...      table: nSections rows of 16 bytes
                (relativeOffset, size, type, flags)
```

`.hocb` always has exactly **3** sections; `.hcb` has between 5 and 88. In
`.hocb`:

| Type | Contents |
|---|---|
| `0x203` | collision **material** table, 32-byte entries |
| `0x200` | the **triangle array** |
| `0x003` | tail |

Three checks of the self-relative convention, each **351/351**
(`parse_hocb.py --check-offsets`):

- the tail's `target + size` lands **exactly** on the file size;
- the material table ends exactly where the triangle array begins;
- the triangle array size is an exact multiple of 72.

None of these works if you read the offsets as absolute.

## The triangle record — 72 bytes

```
+0x00  s32     self-relative pointer to a collision material
+0x04  u32     0
+0x08  f32[3]  v0   \
+0x14  f32[3]  v1    >  the three vertices, world coordinates, plain f32
+0x20  f32[3]  v2   /
+0x2c  f32[3]  face normal
+0x38  f32[3]  bounding-sphere centre
+0x44  f32     bounding-sphere radius
```

The vertices are **neither quantised nor indexed** — every triangle carries its
own three, in full. No vertex buffer, no index list. That costs 3× the space of
an indexed mesh and is exactly the trade you make when every query must read one
whole triangle with no indirection.

Most triangles in a file point at the same material: in `dg001_01.hocb`, 2226 of
2242 point at entry #0, 12 at #2 and 4 at #1.

## Why we believe we are reading it right

739 files, **413,385 non-degenerate triangles** (`--check`, `--check-map`).

**1. The normal is recomputable.** `normalize(cross(v1-v0, v2-v0))` matches on
413,379 — **99.9985 %**. All 6 misses are near-collinear slivers (area down to
1.8e-5; in one, the edge lengths are 14.979 + 15.161 = 30.141 exactly). There the
normal is numerically unstable, and in one case the engine itself wrote `(0,0,0)`.
Not a parsing problem.

**2. The sphere contains its own three vertices — 413,385 of 413,385, 100 %.**
This is the invariant that settles the `(centre, radius)` reading. A misread
field does not produce spheres that always enclose their own triangle.

**3. Which sphere: 99.91 % match a closed form exactly.** Either the midpoint of
the longest edge with half its length (82.97 %), or the centroid with the maximum
vertex distance (16.94 %). Only 0.09 % match neither.

What we could **not** pin down is what *chooses* between the two. It is not
"whichever is tighter" — sometimes the stored sphere is wider than the available
candidate — and redoing the arithmetic in `float32` makes the agreement *worse*
(86 % vs 92.5 %), so it is not a rounding artefact either. This is a derived
broad-phase acceleration field; knowing it is a bounding sphere is enough to use
it or regenerate it, and the honest statement is that the selection rule remains
open.

**4. Bounding box against the map.** A cross-check between this binary format and
an independent text one. Of 362 maps with a `COLLI_TREE` and readable terrain,
**3 match at 0.0 %** — identical XZ bounding box — and 155 fall within 10 % of the
map's extent:

```
0.0%  dg018_01.map   terrain  X[-324.0, 1350.0]  Z[-1269.7, 1130.0]
                     collision X[-324.0, 1350.0]  Z[-1269.7, 1130.0]
```

The rest are not errors. Collision routinely extends past the visible terrain —
invisible walls and out-of-bounds barriers; `dg012_05` has a containment box at
±5371.8 — and several maps share one collision file.

## The declared sections do not cover the file — the octree lives in the gap

Easy to miss: the three sections account for only part of the file. In
`dg001_01.hocb` the triangles end at `0x27760` and the tail starts at
`0x6d30c`, leaving **285,612 bytes — 64 % of the file — undeclared**. That gap
is the spatial subdivision tree the `.map`'s `COLLI_TREE` key is named after.

It is an **octree**, and it is decoded. One fixed 80-byte record serves both
internal nodes and leaves:

```
+0x00  u32       N = how many triangles this node holds (0 on internal nodes)
+0x04  f32[6]    the cell's AABB, min then max
+0x1c  s32[8]    the 8 child slots (self-relative, 0 = empty)
+0x3c  s32       pointer to the triangle list (0 when N == 0)
+0x40  char[16]  name = the node's path in the tree
```

Two things make this easy to get wrong:

- **A parent's pointer targets the `N` field, not the AABB.** The triangle list
  is a blob of `N` self-relative pointers placed immediately *before* the
  record, so the record proper begins where the blob ends. Aiming at the AABB
  puts every subsequent field off by four bytes, which looks almost right — the
  name still reads, shifted.
- **The root is the last record in the file**, at `tailStart - 80`. It is
  named `"0"`.

The 8 slots are positional, and the position *is* the octant: **bit 0 = X,
bit 1 = Y, bit 2 = Z**. A node's name is its path from the root
(`"0"` → `"00"` → `"003"` → `"0033"` → `"00332"`), and the final digit always
equals the slot index its parent keeps it in — so the name is redundant with the
structure, which is what makes it such a good check.

### Validated at 100 %

`parse_hocb.py --check-tree`, across all 351 files and **253,447 nodes**:

| Invariant | Result |
|---|---|
| edges vs nodes (253,447 nodes − 351 roots) | **253,096** exactly — no cycles, no orphans |
| child AABB contained in parent | 253,096 / 253,096 |
| child is the **exact octant** of the parent, split at the midpoint | 253,096 / 253,096 |
| child name = parent name + one digit | 253,096 / 253,096 |
| that digit == the slot index | 253,096 / 253,096 |
| triangle references intersecting their own cell | **1,314,561 / 1,314,561** |

The octant test is the decisive one: you do not hit an exact regular subdivision
by accident a quarter of a million times.

One thing worth stating because the first attempt got it backwards: a triangle
is filed under every cell it **intersects**, not the one that contains it. Large
floor triangles straddle many cells, and on average each triangle appears in
about **3.2** of them (1,314,561 references for 413,390 triangles). Testing for
containment instead fails on 92 % of references — which is a wrong test, not a
wrong parse.

Depths run from 1 to 12, peaking at 7.

## Collision materials

1781 entries across the 351 `.hocb` files, 32 bytes each, of which only three
words carry anything — `+0x0c` through `+0x1c` are zero in **every** entry:

```
+0x00  u32   SURFACE TYPE — an id into boot/colli_attr_table.csv
+0x04  u32   bitfield      (0, 0x200, 0x11e, 0x21e, 0x1e, 0x16, …)
+0x08  u32   ARGB colour
```

**Entry #0 of every file is the default** — surface 0, flags `0`, colour
`0xff000000` — in 351 of 351 files.

### `+0x00` is the surface type, not a bitfield

It was read as a bitfield for one simple reason: its commonest values are `0x01`,
`0x02`, `0x08`, `0x10`. Those look like single bits. They are not — they are the
ordinals of the four commonest surfaces in the game, *brown earth*, *black soil*,
*grass* and *stone paving*, in a 33-row table the game ships in plain sight:

```
boot/colli_attr_table.csv      (Shift-JIS, 33 rows, ids 0..32)
  id, name,        ATR_EFF,       ATR_HUMAN_SE, ATR_CREATURE_SE, ATR_MACHINE_SE
  8,  grass,       ,              SE_ATTR008,   SE_ATTR021,      SE_ATTR008
  20, water,       ef_ca020.eff,  SE_ATTR020,   SE_ATTR020,      SE_ATTR020
```

Each row says what to spawn and what to play when something touches that
surface: one effect and three footstep sounds, split by who is walking —
human, creature, machine.

Small ordinals and bit masks are indistinguishable until you find the table they
index. What found it here was a **class name**: `ColliAttrManager`, recovered
from the DOL's surviving RTTI strings — see
[18 — DOL class names](18-dol-classes.md).

Four checks, all from `parse_colli_attr.py --check`:

| Check | Result |
|---|---|
| **Range** — ids outside 0..32 | **none**, over 413,390 triangles in 351 files; the maximum is *exactly* 32, the table's last row |
| **Shape** — is the distribution sensible? | 80.8 % id 0 "nothing" (the default), then 8.2 % stone paving across 177 files, then grass, earth, rock. "On leaves" appears in exactly one file |
| **Effects** — do the four `.eff` the table names exist? | all four, under `data/eff/`. Their names carry the id: `ef_ca020.eff` ↔ id 20 (water), `ef_ca032.eff` ↔ id 32. `ca` = collision attribute |
| **Localisation** — is water where water should be? | ids 20/21/28/29/32 appear in 1–23 files out of 351, not scattered. Muddy water is used in exactly one map |

The range check alone would prove little: `0` and `1` dominate almost every
field in every format, so "small values, in range" confirms nearly any guess.
What carries the argument is the maximum landing *exactly* on the table's last
id, together with the other three.

### `+0x04` is a query exclusion mask

**Answered in session 11, and it was not the kind of thing everyone assumed.**
The word does not describe the surface. It describes **who is allowed to see
it**: a collision query supplies a mask of categories to ignore, and a triangle
whose word intersects that mask is skipped. From `FUN_80059660`, the triangle
test inside the query:

```c
mat = *(Material **)(tri + 0x40);
if ((queryMask & mat->word04) == 0 &&                  // <-- +0x04
    (surfFilter < 0 || surfFilter == mat->word00) &&   // +0x00, <0 = any
    intersects(query, tri)) { ...record the hit... }
```

Collision layers, in other words. Full write-up and the cross-format check in
`colli_flags.py` (`--map`, `--vocab`); the reason this became readable at all is
[19 — A Gekko SLEIGH for Ghidra](19-gekko-sleigh.md).

That also explains why the three readings below all came back empty: they each
looked for a *property of the geometry*, and there is none to find. Nothing
about a triangle's orientation, colour or position can predict which categories
its author chose to hide it from.

Two by-products: `+0x00` is not only the surface type but doubles as a **query
filter** (ask for water specifically, or `< 0` for any), and the same function
independently re-derives the 68-byte `.hcb` stride, the material pointer at
`+0x40` and the surface id at `+0x00` — details it was never fitted to.

Still open: **what each bit is called** — and three routes to it have been tried
and closed, recorded here so the next attempt starts further along:

1. **There are no direct callers.** Each of the three query methods has exactly
   one reference: its own vtable slot.
2. **Signature matching does not find the call sites.** The vptr is
   `classRecord + 0x08` (from the constructor `FUN_80057f28`, the only code
   reference to `0x807775c0`), so the query slots are at `+0x0c/+0x10/+0x14`
   and the mask is r7. Matching on `li r8,-1` yields 3 sites, all false — the
   `-1` belongs to a preceding `bl`. Matching on a stack hit-buffer yields 115,
   and **r7 is never written within 20 instructions of any of them**, so none is
   a six-argument call.
3. **Hunting hard-coded masks by bit vocabulary fails on small integers.**
   Immediates whose bits fall only inside the used set come back as `0x6`,
   `0x30`, `0x14`, `0x3e8` — 6, 48, 20, 1000. The same trap as
   [17](17-eff-binary.md): exclude the common values before counting.

The reason all three miss is structural: `ColliTree` objects are constructed
from dozens of sites across `0x803f…`–`0x8042…`, embedded in entity classes
rather than owned by a single manager. The queries are therefore scattered
through gameplay code. Naming the bits needs indirect-call resolution — which
objects hold a `ColliTree`, and what writes the field the mask comes from.

The three readings that were ruled out, kept so nobody repeats them
(`parse_hocb.py --materials`):

- **They are not a floor/wall classification.** That would be redundant: the
  normal is already in the triangle record. Correlating each bit with face
  orientation separates nothing — except two bits that never appear on an
  up-facing face: `+0x04` bit 8 (0.5 % up, over 99 files) and bit 18 (0.0 %,
  58 files). Those two are plausible "not walkable" markers, and they are the
  only orientation signal in the whole bitfield. *(In hindsight that signal is
  real but inverted: those are categories that only ever hide vertical
  surfaces — a mask, not a property.)*
- **The colour is not derived from the flags.** The commonest combination
  (`0/0`) appears with 65 different colours. It is a hand-picked per-material
  tint, and the alpha byte genuinely varies (`0x82`, `0x9d`) — a translucent
  debug overlay, not computed data.
- **Special-material triangle groups are not placed gimmicks.** In
  `dg001_01.hocb` the two non-default materials cover 4 and 12 triangles, and
  neither sits on any of the map's 18 `GIMMICK_LOC` positions. They are
  hand-authored volumes — the 12-triangle one is exactly a box (6 faces × 2).

The guess recorded here in the previous round — that these fields carry surface
semantics the geometry cannot express, "footstep sound, damage, camera
behaviour, climbability", and that pinning them down "needs either the DOL or a
ground-truth comparison" — turned out to be right on both counts, and it was the
DOL that delivered. It is `+0x00` that holds the semantics, though, not the
bitfield the sentence was written about. And the bitfield turned out not to hold
surface semantics at all: it holds the *audience*.

### One field or two? The `.hocb` / `.hcb` cross-check

The decompiled path is the `.hcb` one. The materials profiled above are `.hocb`.
Before carrying the reading across, `colli_flags.py --vocab` asks whether the
two formats are even speaking the same language:

```
.hocb   351 files,  1781 entries,  43 distinct values at +0x04
.hcb    388 files,   757 entries,  14 distinct values at +0x04

values used by both formats: 8
  they account for 84.7% of .hocb entries and 98.8% of .hcb entries
  shared: 0x0 0x10 0x12 0x16 0x11e 0x200 0x31e 0x20000
bit 0 is never set, in either format, across all 2,538 entries
```

Eight values, most of them multi-bit and arbitrary-looking (`0x11e`, `0x31e`),
covering the overwhelming majority of both populations. Two unrelated fields do
not agree like that. And bit 0 going unused in 2,538 independent entries says
the categories are numbered from 1 — a small fact, but one a wrong reading of
the field would have no reason to produce.

## `.hcb` — same header, different body

`.hcb` shares the header, the descriptor relation and the self-relative
convention (verified on all 388). Its body is a triangle array plus a scene
graph, and it is decoded in **[15 — `.hcb`](15-collision-hcb.md)**.

Two claims that stood here until session 8 turned out to be wrong, and are worth
leaving on the record:

- *"none is a multiple of 72, so the triangles are not there."* The `.hcb`
  triangle record is **68** bytes — the same sixteen floats with the material
  pointer moved to the end and the padding word dropped. All 553 candidate
  sections divide by 68 exactly.
- *"used by gimmicks with a radius parameter, which suggests primitive volumes."*
  The leading float of `COLLISION_BEFORE` is not a radius (it is `0.0` in 108 of
  141 cases), and there are no primitives — all 553 meshes are triangles.

## Walking on it

The session-6 movement PoC stood the character on the *rendering* mesh. With the
octree in place it can stand on the real collision instead —
`walk_poc.py --collision`, backed by `parse_hocb.Collision`, which descends the
tree and tests only the cells above the query point (~10 triangles instead of
2242 on `dg001_01`).

Comparing the two surfaces at 4000 random points on `dg001_01`
(`parse_hocb.py --check-ground`) — matching every rendering surface against the
nearest collision surface, because both are layered:

```
median difference 0.000    90th percentile 5.0
within 0.01 units: 63.5%      within 5 units: 89.2%
```

The median is an exact match. The residual is real and expected: collision has
floors the graphics never draw (1030 sample points had collision but no visible
surface) and skips decorative geometry you cannot stand on.

One trap when reusing the PoC's `Ground` helper: pass `filter_slivers=False`.
That filter exists to discard artefacts of the *rendering* strip decode;
collision is authored geometry with no such artefacts, and the filter throws
away 635 of 2242 triangles — the large floors, which are exactly the ones you
walk on. With it off, the path finder finds 200 units of clear run on
`dg001_01` instead of 40.

## Tools

```
python parse_hocb.py FILE               # summary: sections, triangles, bbox
python parse_hocb.py --check            # normals + spheres over every file
python parse_hocb.py --check-offsets    # the self-relative convention
python parse_hocb.py --check-map        # collision bbox vs map terrain bbox
python parse_hocb.py --materials        # material entries: what the flags are NOT
python parse_hocb.py --check-tree       # the octree invariants
python parse_hocb.py FILE --obj OUT.obj # export the soup as a mesh

python colli_flags.py --map      # the exclusion mask, with the decompiled test
python colli_flags.py --vocab    # .hocb vs .hcb: one field or two?
python colli_flags.py --profile  # per bit: what does its geometry look like?
python colli_flags.py --bits     # the bits that are pinned down, with evidence
python colli_flags.py --ladder   # bits 1,2,3,4,8 as one near-nested ladder
python colli_flags.py --birdview # bit 9 is bird view, and the DOL names it
```

## Asking the geometry instead — `colli_flags.py --profile`

With the code route measured out (see below), the remaining evidence is the data.
Session 7 asked "can the geometry predict the flag" and got nothing — correctly,
because the overwhelming majority of walls carry flag 0. **The converse is a
different measurement, and it is not symmetric: given the flag, what does the
geometry look like?** That one is strongly non-random. Against a baseline of
413,390 world triangles that are 17.2 % up-facing and 73.8 % vertical:

| bit | tris | files | up | vertical | median area | per file | surface id 0 |
|---|---|---|---|---|---|---|---|
| 1 | 24458 | 182 | 5.5 % | 91.6 % | 620 | 62 | 58.9 % |
| 2 | 20986 | 183 | 6.0 % | 92.1 % | 793 | 60 | 70.6 % |
| 3 | 17965 | 145 | 4.7 % | 93.2 % | 922 | 72 | 67.5 % |
| 4 | 25664 | 190 | 5.8 % | 91.6 % | 571 | 72 | 62.1 % |
| 5 | 570 | 38 | 27.4 % | 72.6 % | 442 | 6 | 67.4 % |
| 6 | 642 | 41 | 24.3 % | 75.7 % | 409 | 6 | 71.0 % |
| 7 | 2016 | 33 | 8.5 % | 87.7 % | 1005 | 12 | 77.4 % |
| 8 | 10620 | 99 | 0.5 % | 99.0 % | 1094 | 58 | 68.6 % |
| 9 | 48806 | 153 | 16.8 % | 80.2 % | 165 | 194 | 79.3 % |
| 11 | 126 | 22 | 34.9 % | 65.1 % | 144 | 4 | 65.1 % |
| 16 | 3794 | 28 | 4.3 % | 95.7 % | 1192 | 4 | **4.4 %** |
| 17 | 192 | 2 | 16.7 % | 66.7 % | 48 | 96 | 50.0 % |
| 18 | 428 | 58 | **0.0 %** | **100.0 %** | 145 | 6 | **100.0 %** |

Three groups, and each is a fingerprint rather than a name:

- **1, 2, 3, 4, 8, 16, 18 sit on walls**, 91.6–100 % vertical. Bit 18 is the
  sharpest of them: 100 % vertical, 100 % surface-id-0, tiny (median area 145
  against 2,148 overall), about six per map across 58 maps — the profile of a
  hand-placed invisible blocker rather than of anything the artist modelled.
- **Bit 16 inverts the pattern that holds everywhere else.** Only 4.4 % of its
  triangles have surface id 0, where every other bit runs 50–100 %. It marks
  *authored* surfaces — material, footstep sound and all — that some query has to
  skip anyway; the other bits mostly mark geometry that was never a surface.
- **5, 6 and 11 are volumes, not surfaces.** Median areas 10–20× the overall
  mean, 4–6 triangles per file, and bits 5 and 6 carry the *same* surface-id
  histogram down to the individual counts (`0x1b`×106, `0x14`×50, `0x8`×30), so
  they are two bits on one set of triangles. Bit 11 runs 4 to 12 per file, and
  12 triangles is a box.

### Four bits, pinned down — `colli_flags.py --bits`

Following the fingerprints into the surface-attribute table
([`parse_colli_attr.py`](../tools/parse_colli_attr.py), 33 named surfaces)
settles four of them. Read them the right way round: the word is an *exclusion*
mask, so a bit names the category a querying system asks to **skip**.

**Bit 11 — water.** 34.9 % of its triangles carry a water-family surface id
against a 0.26 % base rate: a lift of **134×**, and every non-zero id it carries
is 27, *water surface*. The shape is a water **body**, not a plane — a `y+` top
face at id 27 with the containing walls at id 0:

```
tw02_02_02.hocb   {y+: 4, z+: 2, x-: 2, z-: 2}   surface ids {27: 4, 0: 6}
tw02_04_02.hocb   {y+: 2,        x-: 8, z-: 2}   surface ids {27: 2, 0: 10}
```

Bits **5 and 6** ride the same triangles for the larger bodies, at 105× and 93×
lift, and always together. "Bit 11 is water" means *a query that sets bit 11 is
one that must not see water* — which is what walking along a river bank needs,
and exactly what an "am I standing in water" test must not do.

**Bit 16 — terrain too steep to stand on.** Same material, flagged against not:

| surface | bit 16 | tris | median slope | walkable (<40°) | steep (>70°) |
|---|---|---|---|---|---|
| rock | set | 2178 | 90.0° | **0.0 %** | **100.0 %** |
| rock | clear | 4808 | 90.0° | 20.3 % | 79.7 % |
| grass | set | 1224 | 90.0° | **0.0 %** | **100.0 %** |
| grass | clear | 6135 | 25.8° | 53.7 % | 36.8 % |
| earth 2 | set | 176 | 19.5° | 61.4 % | 37.5 % |
| earth 2 | clear | 1536 | 90.0° | 22.2 % | 77.5 % |

Flagged rock and grass are over 70° **without a single exception in 3,402
triangles**, where the same materials unflagged are 20 % and 54 % walkable. The
implication runs one way only — flagged implies steep, steep does not imply
flagged — so this is an authoring decision, not a slope test the exporter ran.
The 176 *earth 2* triangles go the other way and are left standing as the
counter-example: 5 % of the bit's traffic, unexplained.

**Bit 18 — invisible wall.** 223 panels across 58 maps at **1.92 triangles per
plane**, i.e. quads. All at surface id 0, none facing up, 95.8 % standing
directly on walkable floor, and the height histogram is a standard part:

```
height  5:1   7:3   8:6   10:114   11:90   14:6   23:3
```

204 of 223 are 10 or 11 units tall. A material-less quad of standard height,
hand-placed on the floor, that some systems must ignore: there is no other thing
that is.

### Bit 9 is scoped to the map, not to the surface — and the `_bird` twin says so

Bit 9 is the bulk of the traffic, 48,806 triangles, and it behaves unlike the
rest: it is used **alone** on 87.6 % of them, and where it appears at all it
covers a median 59.9 % of the file (p75 94.1 %). That is a property of the map,
not of a surface.

Every map ships a second collision file with a `_bird` suffix, and the two
disagree about bit 9 sharply:

| | mean bit-9 coverage |
|---|---|
| plain `.hocb` (246 files) | 34.5 % |
| `_bird.hocb` (105 files) | **2.2 %** |

Triangle for triangle across every bird/plain pair, a bit-9 triangle survives
into the bird collision **4.6 %** of the time against **29.0 %** for everything
else — a 6.3× difference over 84,033 triangles. And 59 of the 63 maps where bit
9 covers more than 90 % of the collision are towns (`tw*`), which are exactly the
maps full of small ground-level clutter.

So bit 9 marks ground-level detail that the `_bird` collision drops. And the
system it belongs to is named in `main.dol`: `_bird.` is a literal string there,
and its neighbours settle it.

```
0x8074e230  touch control chant birdView chase chaseRear fix fixRotY
            Default Hide Shoot Crouch Control Chant BirdView WallUp Chase …
0x807387f0  DrawColliWire DrawColliAttrColor DrawBirdViewColli DrawCharaColli
            DrawCharaArea DrawDamageSphere DrawMap DrawMapBounds DrawChara …
0x80756ba0  HIDE_BIRDVIEW HIDE_BIRDVIEW_Y LMAP REFLECT REFRACT NO_SHADOW
            SHADOW_RECEIVER NO_CLOUD_MAP PROJECTED_SHADOW …
0x807385a0  ExpImmediately LevelCap AlwaysBirdview CircleComboType …
```

**Bird view is a camera mode** — one of eight — it has its own collision set
with its own debug renderer (`DrawBirdViewColli`, sitting among the other
collision debug toggles), and it has a per-instance **render** flag,
`HIDE_BIRDVIEW`, in the same list as `NO_SHADOW` and `REFLECT`. The maps use
that flag 344 times across 132 files, always on a `*_hide.locator` set — and
`build_scene.py` had been skipping it for sessions without knowing what it was.

### The corroboration that first said the opposite

Bit 9 (collision) and `HIDE_BIRDVIEW` (rendering) should be two faces of one
decision, so they should co-occur. Over all 233 maps that have both a `.map` and
a plain `.hocb`, the correlation is **negative**: r = −0.31, maps that hide
objects in bird view use *less* bit 9.

That is Simpson's paradox, and the confound is the map family:

| family | maps | uses `HIDE_BIRDVIEW` | mean bit-9 coverage |
|---|---|---|---|
| `dg` (dungeons) | 144 | 41.7 % | 7.9 % |
| `tw` (towns) | 89 | **0.0 %** | **76.1 %** |

Towns never use the render flag and are soaked in the collision bit; dungeons do
the reverse. Hold the family fixed and the sign flips back — within dungeons,
**56.7 %** of the maps that use `HIDE_BIRDVIEW` also use bit 9, against **29.8 %**
of those that do not (rank test AUC 0.642, permutation *p* = 0.001, n = 144).

The two mechanisms are alternatives applied by different level teams, not the
same switch, which is why the aggregate misleads. Worth keeping as a warning:
the first number this project computed for that pair had the wrong sign, and
only splitting by an obvious covariate showed it.

### The wall bits are one near-nested ladder, not five categories

Over bits 1, 2, 3, 4 and 8 only **13** distinct values occur in 413,390
triangles, and five nested ones — `0x10` ⊂ `0x12` ⊂ `0x16` ⊂ `0x1e` ⊂ `0x11e` —
cover **96.3 %** of them:

| mask | bits | tris | files | median area | panel height | up-facing |
|---|---|---|---|---|---|---|
| `0x010` | 4 | 916 | 29 | 35.7 | 7.00 | 19.4 % |
| `0x012` | 1, 4 | 3880 | 3 | 61.3 | 13.04 | 3.0 % |
| `0x016` | 1, 2, 4 | 1836 | 38 | 48.5 | 10.00 | 14.8 % |
| `0x01e` | 1, 2, 3, 4 | 3372 | 36 | 721.7 | 120.00 | 9.3 % |
| `0x11e` | 1, 2, 3, 4, 8 | 6286 | 49 | 1114.8 | 100.00 | 0.3 % |

In nesting order the heights read 7.00, 13.04, 10.00, 120.00, 100.00. That is
**not** monotone — two adjacent rungs invert — but it is not flat either: there
is an order-of-magnitude **step** between the third rung and the fourth. The low
three are character-scale blockers of 7 to 13 units, the same scale as the
bit-18 invisible walls; the top two are full-height walls with 15–20× the
triangle area and, at `0x11e`, 0.3 % up-facing, i.e. pure vertical.

The ladder therefore separates two regimes cleanly and orders badly within a
regime — what one expects if the bits are categories that authors applied in a
near-nested way, rather than a level number. Two caveats belong on the page: the
field is not a chain in general (554 incomparable pairs across all 42 distinct
masks), and `0x12`'s 3,880 triangles come from only **three** files and are 98 %
sand, so that rung is one location rather than a category.

### One anchor from the code, after all

The three `ef_col##n.hcb` files are not scenery. `FUN_80256384` reads
`database/chara/special/` keys — `NormalAttackID`, `ComboWaitTime`, `ChantPoint`,
`HighJumpAttackID` — and loads `ef_col02n.hcb` into **two heap-allocated
`atn::ColliTree`s**: they are the hit volumes of a character special attack.
Their materials carry `0x298` and `0x29c` (bits 3, 4, 7, 9 and 2, 3, 4, 7, 9),
values that *no world collision file ever uses*, with surface id 0 throughout.
So at least part of the mask separates combat volumes from scenery — which also
fits the reading that a bit names **the system that must ignore the triangle**,
rather than a property of the triangle.

## What is still open

- The names of the remaining exclusion-mask bits. **11, 16 and 18 are settled**
  above, 5 and 6 travel with 11, **9 is bird view** — the overhead camera mode,
  named from the DOL and corroborated against the `HIDE_BIRDVIEW` render flag —
  and
  **1, 2, 3, 4, 8** are shown to be one near-nested ladder over two size
  regimes rather than five independent categories. Genuinely untouched: **7**
  (2,016 triangles, 21× water lift, so water-adjacent) and **17**, which occurs
  in exactly two dungeon maps at 96 triangles each, half surface id 0 and half
  sand — and the two occurrences are *not* the same object (0 triangles in
  common after translation) although both span exactly 199.2 units in x.
- Three grep-shaped routes to the *code* were ruled out here, and a fourth — an
  abstract interpreter over every indirect call site — ruled out a whole region
  of the search space; see [21 — Resolving the indirect
  calls](21-indirect-calls.md). The bits above were settled from the data
  instead.
- The material flags — the surface semantics (attempted; see above for the three
  readings that were ruled out).
- The `0x003` tail section (24 bytes).
- What selects between the two bounding-sphere formulas.
