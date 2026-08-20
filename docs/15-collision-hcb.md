# 15 — `.hcb`: the gimmick collision body

[14 — Collision](14-collision.md) cracked the header family shared by `.hocb` and
`.hcb` and then decoded `.hocb` in full. It left `.hcb` open with a guess
attached — "used by gimmicks with a radius parameter, which suggests primitive
volumes rather than a triangle soup". **The guess was wrong**, and the way it was
wrong is the most useful thing in this document, so it comes first.

388 files, magic `BCH@`. Every one is a gimmick's collision: the `.gmk` files
name them through `COLLISION_BEFORE` / `COLLISION_AFTER`, one per visual state of
the object (see [12 — Gimmicks](12-gimmicks.md)).

## The trap that kept this format closed

`.hocb`'s triangle record is 72 bytes. Session 7 checked whether any `.hcb`
section was a multiple of 72, found none, and concluded the triangles were not
there. They are:

**the `.hcb` triangle record is 68 bytes.** It is the same sixteen floats as
`.hocb` with the material pointer packed differently — `.hocb` puts the pointer
first and pads to a 8-byte boundary (4 + 4 + 64 = 72), `.hcb` puts it *last* and
skips the padding (64 + 4 = 68). Once you test divisibility by 68 instead, every
single one of the 553 candidate sections divides exactly, with no remainder, for
a total of 13,566 triangles.

The lesson generalises: a size test that fails is evidence about *that size*, not
about the contents. Both packings hold identical data, so the "is there a
triangle array here" question was never really about 72.

## The second trap: the type field is not a type

The section table's third word takes the values `0x205`…`0x208`. It is natural to
read them as `.hocb`'s `0x200`/`0x203` do — one value per kind of data. That
reading is false, and following it produces a parser that works on one file and
silently misreads the next:

| Type word | Rows | What is actually there |
|---|---|---|
| `0x205` | 553 | material table ×280, **node ×273** |
| `0x206` | 553 | triangle array ×553 |
| `0x207` | 1344 | mesh ×553, node ×683, **material table ×108** |
| `0x208` | 388 | root node ×388 |

Only two are exact: `0x206` is always a triangle array and `0x208` is always the
root node, one per file.

This is not a misparse of the table. The `(offset, size)` pair of every row is
verified independently — see the relocation check below — so the rows are being
read correctly and the type word genuinely varies for the same class of data.

What discriminates instead is **size**, plus position:

```
28 bytes            mesh descriptor
16 bytes            file tail (always the last row)
104 or 116 bytes    scene-graph node
multiple of 68      triangle array
multiple of 32      material table
```

File order is meaningful where the type word is not: the material table is the
first row in **388 of 388** files. Sort the rows by type and that stops being
true — in 67 files it lands third. Run `parse_hcb.py --kinds` for the full
tabulation.

## The relocation table — how any of this gets proved

Immediately after the section table, at `0x30 + 16*nSections`, sits a list of
self-relative `s32` values. Each one points at **a field in the file that is
itself a pointer**. Its length lives in the last table row, which is not a
section but the file's 16-byte tail:

```
tail row: (rel -> last 16 bytes, size 16, nRelocations, 4*(nRelocations+1))
```

The relation between those last two fields holds on 388/388.

This gives the strongest validation available on a binary format of this kind.
A proposed record layout implies a set of pointer field addresses. The file
declares its own set. If the layout is right the two sets must be **equal** — not
overlapping, equal.

```
python parse_hcb.py --check
  POINTERS == RELOCATIONS                388/388
```

They match exactly on every file. A single field placed wrongly — the material
pointer at the front instead of the back, a missed pointer in the node record —
breaks it immediately. In fact that is how the node's *second* pointer was found:
an early layout matched as a strict subset, short by exactly `nNodes + 2`
entries, which located the missing field at `+0x38` without any guessing.

## Structure

There is no octree here. `.hocb` needs one because a map has hundreds of
thousands of triangles; a gimmick has twelve. What `.hcb` has instead — and
`.hocb` does not — is a **scene graph**.

```
material table    1 per file, 32-byte entries (identical to .hocb)
triangle array    1 per mesh, 68-byte records
mesh descriptor   1 per array, 28 bytes
nodes             104- or 116-byte records forming a tree
root              1 per file: a node with everything zero but its child pointer
```

### Triangle record — 68 bytes

```
+0x00  f32[3]  v0    \
+0x0c  f32[3]  v1     >  model-space floats: not quantised, not indexed
+0x18  f32[3]  v2    /
+0x24  f32[3]  face normal
+0x30  f32[3]  bounding-sphere centre
+0x3c  f32     bounding-sphere radius
+0x40  s32     self-relative pointer to the material   <- at the END
```

Both of `.hocb`'s recomputable invariants hold here, and more cleanly
(`parse_hcb.py --check-tris`):

| Invariant | Result |
|---|---|
| normal == `normalize(cross(v1-v0, v2-v0))` | **13,562 / 13,562** non-degenerate — 100.0000 % |
| the sphere contains its own three vertices | **13,566 / 13,566** — 100 % |

Four records are degenerate (zero-area slivers) and are excluded from the normal
test, as in `.hocb`.

### Mesh descriptor — 28 bytes

```
+0x00  u32     1          (never anything else: 553/553)
+0x04  u32     triangle count
+0x08  s32     self-relative pointer to the array
+0x0c  f32[3]  bounding-sphere centre
+0x18  f32     radius
```

The declared array size equals `count * 68` on 553/553, and each mesh's sphere
contains every vertex of its own triangles on 553/553 — worst overshoot
`1.2e-5`, which is float noise.

### Node — 104 or 116 bytes

```
+0x00   u32     authoring index (0 = root; NOT a 0..n-1 numbering, see below)
+0x04   u32     always 0
+0x08   u32     0 or 1
+0x0c   s32     -> mesh descriptor, or 0
+0x10   f32[3]  translation
+0x1c   f32[4]  rotation, Euler angles in RADIANS (fourth value always 0)
+0x2c   f32[3]  scale
+0x38   s32     -> first child, 0 if leaf
+0x3c   s32     -> next sibling, 0 if last
+0x40   char[]  NUL-terminated name
end-12  f32[3]  an authored point (see below)
```

The record size is constant *within* a file — 317 files use 116, 71 use 104 —
and only the name field length changes. That is why the trailing three floats
must be read from `end - 12` rather than a fixed offset.

That it really is a tree is checked rather than assumed. Walking child and
sibling pointers from the root reaches **every** node in the file on 388/388,
with `edges == nodes - 1` on 388/388 — so no cycles and no orphans. The root is
the node at the highest address and carries index 0 on 388/388.

**791 of the 1344 nodes carry no geometry.** They are transform and grouping
nodes. Rotation is essentially unused: only 2 nodes in the entire set have a
non-zero one, and the value that pinned the encoding as radians is a clean
`-1.5707964` — exactly −π/2.

The index at `+0x00` is not a per-file numbering (it is only 0..n-1 in 102 of 388
files); it reaches 111 in a file holding 8 nodes. It is the object's index in the
*author's* scene. The names confirm that reading — they are DCC names left in the
shipped data:

```
Sphere01   pCube2      Maya / Max default object names
hasira01   hasira04    hasira = 柱, pillar
hako                   箱, box
ita01                  板, board
c8  g20  o11  s8       working names
gm001_008_hcb          the one node the artist tagged for collision export
```

Many files export the artist's whole hierarchy and hang the collision off a
single node — the one suffixed `_hcb` or `_c`. `gm001_008a.hcb` has 38 nodes and
exactly one mesh.

The trailing three floats are zero in 1174 of 1344 nodes. Where they are not,
they look like a centre — 51 of them equal the mesh's bounding-sphere centre to
the bit — but they are **not derived from the geometry**: in 70 cases they match
neither the sphere centre, nor the bbox centre, nor the node translation, and two
different files carry byte-identical values. It is an authored point, most likely
an interaction pivot. `parse_hcb.py --pivot`.

### Materials

The same 32-byte entries as `.hocb`, same layout, `+0x0c`…`+0x1c` zero in all 757
entries. Entry #0 of every file is the default (flags `0/0`, colour
`0xff000000`) in 388 of 388 files — the same invariant that holds on `.hocb`.
Files carry one to three entries.

The flag semantics remain undecoded, and [14](14-collision.md) already records
the three readings that were ruled out. **That is not a data-analysis problem any
more**: it needs the DOL or an in-game observation. Do not re-run it here.

## Cross-format check: `.hcb` against `.model`

The tests above are all internal. This one is not: every gimmick that declares
both `MODEL_*` and `COLLISION_*` gives a pair of files in two unrelated binary
formats that should describe the same object. Comparing the `.hcb` triangle bbox
against the AABB in the `.model` header (`parse_hcb.py --check-model`):

| Result | Pairs |
|---|---|
| boxes overlap | **141 / 141** |
| agree within 2 % | 48 |
| within 10 % | 32 |
| within 30 % | 9 |
| beyond 30 % | 52 |

Several agree *exactly*, float for float:

```
gm001_011a   hcb   (-5, 0, -5) .. (5, 60, 5)
             model (-5, 0, -5) .. (5, 60, 5)
gm001_074a   hcb   (-35, 0, -4.5) .. (35, 140, 4.5)
             model (-35, 0, -4.5) .. (35, 140, 4.5)
```

The 52 outliers were checked rather than written off, and none is a parsing
failure:

- the `.model` AABB is inflated by a far-away vertex — `gm001_095b` reaches
  y = −1905, `gm001_054b` reaches z = −699;
- or the two states genuinely differ, which is the whole point of
  before/after. `gm001_037b`'s collision is a flattened slab (y from 0 to 0.65)
  while its model stands 80 units tall: it is the object *after it falls over*.

## A negative result worth keeping

The premise this format was opened on — `COLLISION_BEFORE 5.0 <file>.hcb`, so the
leading float is a radius and the file holds primitives — is **false on both
halves**.

The float is `0.0` in 108 of 141 cases, and where it is not, its ratio to the
file's actual bounding radius ranges from 0.08 to 2.62 (median 0.73). There is no
relation. Whatever that parameter is, it is not the shape's size.

And there are no primitives. All 553 meshes are triangles, including the node
literally named `Sphere01` — which is a *tessellated* sphere sitting under a
transform with scale 10, not a sphere primitive with radius 10.

## Tools

```
python parse_hcb.py FILE              # summary + scene graph
python parse_hcb.py --check           # structure: relocations, tree, meshes
python parse_hcb.py --check-tris      # triangle normals and spheres
python parse_hcb.py --check-model     # .hcb bbox vs the gimmick's .model AABB
python parse_hcb.py --kinds           # evidence that the type field is not a type
python parse_hcb.py --pivot           # the three trailing floats
python parse_hcb.py FILE --obj OUT.obj
```

## What is still open

- The material flags — shared with `.hocb`, and needing the DOL, not more data
  analysis.
- What the leading float of `COLLISION_BEFORE` / `COLLISION_AFTER` actually is.
- Why the type word varies for identical data. The rows are read correctly and
  the counts are stable per file (`0x205` appears once per mesh, `0x207` once per
  node plus one), so it carries *something* — but it is not the class of the
  section, and nothing depends on it.
- The 16-byte tail record, of which only the pointer at `+0x0c` is understood.

With this, the collision family is complete: `.hocb` in [14](14-collision.md),
`.hcb` here.
