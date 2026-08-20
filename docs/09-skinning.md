# 09 — Skinning and mesh assembly

Decoding the display list ([08](08-models-geometry.md)) gives correct triangles
in the wrong places. Rendered as-is, a model comes out as a cloud of spikes with
its parts scattered. This document covers what it takes to assemble it, which
turned out to hinge on a single conceptual point rather than on any missing
field.

## The `mtrx` chunk: one palette, three tables

`mtrx` is not a pair of arrays. It is **one palette**, split into three
fixed-record tables — one per number of influencing bones.

| Offset | Field |
|---|---|
| `0x10` | `total` — matrices in the palette (matIdx `0 … total-1`) |
| `0x14` / `0x18` | `nA` / ptr → table A: `nA × 8 B` — `(matIdx, bone)` — **1 bone** |
| `0x1c` / `0x20` | `nB` / ptr → table B: `nB × 20 B` — `(matIdx, b0,w0, b1,w1)` — **2 bones** |
| `0x24` / `0x28` | `nC` / ptr → table C: `nC × 28 B` — `(matIdx, b0,w0 … b2,w2)` — **3 bones** |

Record size is `4 + n·8`, except for the 1-bone case where the weight is
implicitly 1.0 and is not stored (8 bytes, not 12). **Padding to 16 bytes sits
at the end of each table, not inside the records** — reading table C at a
32-byte stride slides the records and silently corrupts entries.

Integrity checks that all pass: `nA + nB + nC == total`, matIdx values run
sequentially across the tables, and every weight set sums to exactly 1.0.

```
an008:   90 = 19 +  71 + 0
pc001:  346 = 56 + 285 + 5      matIdx 341 = mouth_L ×0.5
                                           + mouth_down ×0.3 + chin ×0.2
```

Note the zero. **Table C is empty on `an008`.** Working from that model alone,
the third table is invisible, and the matIdx values it would have held simply
look like holes in the palette. Those holes are real geometry: on `pc001` they
are 47 triangles around the mouth, jacket and skin.

## From a vertex to its bones

`subm` is a GX packet:

| Offset | Field |
|---|---|
| `0x10`…`0x34` | `matrixList[10]` (`0xffffffff` = empty slot) |
| `0x38` | ptr → `dlst` |

Ten slots, because GX matrix memory holds ten position matrices. The chain is:

```
vertex byte0 (PNMTXIDX) / 3  →  slot 0..9
subm.matrixList[slot]        →  matIdx
palette[matIdx]              →  1, 2 or 3 bones with weights
```

Confirmed by consistency: every observed byte0 is a multiple of 3 and always
lands on an occupied `matrixList` slot. Unskinned meshes have no PNMTXIDX byte
at all and their `matrixList` is entirely `-1`.

## The hybrid NW4R convention

This is the part that matters, and it is not a field — it is a convention.

**The tables describe different *spaces*, not different encodings.**

| Palette entry | Where the vertex lives | How to place it |
|---|---|---|
| table A (1 bone, rigid) | **bone space** | `world[bone] · (raw / K)` |
| tables B / C (blended) | **already bind model space** | `raw / K` |

The reason is what the hardware is handed at runtime. For a blended vertex the
loaded matrix is `Σ wᵢ · (W_bone,ᵢ · W_bind,ᵢ⁻¹)`, which at bind pose is the
**identity** — so the stored data must already be in model space. Rigid
vertices get `W_bone` directly, so theirs must be bone-local.

Applying the blend to every vertex — or to none — tears the mesh at every bone
boundary. Those are the spikes. Measured on `an008` as
`median(longest edge of cross-bone triangles) / median(same-bone)`:

| Hypothesis | ratio | p95 / same |
|---|---|---|
| everything is model space | 4.37 | 12.77 |
| everything is bone-local | 7.35 | 13.39 |
| **hybrid, as above** | **1.28** | **2.52** |

## K — the POS quantisation

POS is `s16`; `K` is its scale. It is a power of two and it **varies per mesh**
(`an008` body 2048, `an008` collar 8192, `pc001` meshes from 1024 to 65536).
This is the same unknown that used to make accessories float away from the
model — the "wrong scale" and "wrong assembly" problems are one problem.

K does not have to be guessed. Changing K changes the ratio between `R·raw/K`
and the bone translation `T`, so triangles that **cross** a bone change blow up
for every wrong K, while same-bone triangles are unaffected (rigid transform)
and serve as the ruler. Minimise

```
median(longest edge, cross-bone triangles) / median(same-bone)
```

The minimum is sharp — on `an008`, **1.28 at K = 2048** against 3.71 at 1024
and 6.32 at 4096.

## The node → mesh table

`node` chunks do more than hold bones. Nodes that draw geometry carry:

| Offset | Field |
|---|---|
| `0x70` | how many meshes this node draws (0 = none) |
| `0x74` | ptr → array of **12-byte** records: `matIdx`, `meshIdx`, `0` |

Verified bijective: `an008` (`cat` → mesh0, `op_01_collar` → mesh1 + mesh2) and
`pc001` (31 records for 31 meshes). The node names are the part names —
`armer`, `hair`, `boots`, `earring`, `op_01_strap`.

This closes the material question for models whose streams are unnamed. `matIdx`
indexes the model's embedded material-name table, and the names come out
coherent (`armer` → `pc001_armor`, `hair` → `pc001_hair`). No runtime-built
global material registry is involved — the mapping is in the file.

## The per-part AABB, and placing rigid props

Nodes that draw meshes also carry, at **`node +0x58`**, six floats: a
**model-space AABB for that part**. Bone nodes have zeros there.

This is a verification oracle. For rigid parts it matches the assembled bbox to
three decimals; for deformable ones (cape, hair) it is wider, because it is the
envelope over the animation rather than the bind pose.

It also solves the last placement problem. Unskinned meshes are bone-local, but
nothing says *which* bone, and the part node that draws them sits at the origin.
Since the node's AABB is ground truth, the `(bone, K)` pair whose result lands
on it is determined by the data. On `pc001` the recovered bones are
anatomically right:

| Mesh | Bone |
|---|---|
| `bag1`, `bag2`, `belt`, `buckle1` | `waist` |
| `buckle2` | `spine` |
| `earring`, `eye_kage` | `head` |
| `hand_l_obj` | `leftforearm` |
| `necklace` | `spine1` |

## Result

`an008` (a cat, 32 bones) and `pc001` (the protagonist, 102 bones, 31 meshes)
both assemble with **no triangles dropped** and no mesh outside the model AABB.
`pc001` is 6,658 vertices / 9,874 triangles, 17 of 24 materials textured (the
remaining 7 are texture lookups that find no PNG, not parsing failures).

```
python tools/export_obj.py FILE.model OUT.obj
python tools/render_obj.py OUT.obj OUT.png --no-cull
python tools/skinning.py   FILE.model          # palette + resolved K per mesh
```

`export_obj.py --raw` skips the assembly and writes the quantised positions
untouched — useful only to see what the step actually fixes. `render_obj.py`
culls over-long triangles by default to keep a broken mesh legible; `--no-cull`
turns that off, which is the honest check.

**Known non-issue.** `pc001`'s `op_03_tuka` (sword hilt and strap) stays
detached. The file declares its AABB as `[-2.2, -2.38, -0.71] … [10.28, 0.97,
0.33]` — 12.5 units long and at negative Y, i.e. a rest pose below the
character. It is a prop the game attaches at runtime, not a decoding failure.

## What this gives `.motion`

Everything `wii anim` needs is now in place: the bone hierarchy and world bind
matrices ([08](08-models-geometry.md)), the three-table matrix palette, and the
space convention that says which vertices a bone matrix may be applied to.
