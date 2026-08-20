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
```

## What is still open

- The material flags — the surface semantics (attempted; see above for the three
  readings that were ruled out).
- The `0x003` tail section (24 bytes).
- What selects between the two bounding-sphere formulas.
