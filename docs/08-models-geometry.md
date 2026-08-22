# 08 — Models & geometry (`wii modl` / NW4R)

`.model` files are `chnkdata` containers with the subtag **`wii modl`**. The
subtag *does* discriminate the asset type: textures use `wii text`, models
`wii modl`, animations `wii anim` (see the note at the end of [04](04-textures-gx.md)).

Underneath, the format is built on **NW4R** — Nintendo Ware for Revolution, the
official Wii graphics SDK. The giveaway is the skeleton root, always named
`nw4r_root`.

Inventory on the disc: **5,306** `.model`, **4,409** `.motion`, **5,265**
`.material`, **4,454** `.lip`.

## Global header (version 3)

| Offset | Field |
|---|---|
| `0x0c` | subtag `wii modl` |
| `0x14` | version (3) |
| `0x18` | flags |
| `0x1c` | data size |
| `0x20`–`0x38` | AABB: min.xyz, max.xyz (float) |
| `0x40` | embedded material-name count |
| `0x60`… | array of material-name pointers (alphabetical = matIdx order) |

## Chunks are self-describing

Every chunk starts with the same 16-byte preamble:

```
<4CC magic> <u32 count> <u32 selfOffset> <u32 size> ...chunk-specific...
```

`selfOffset` equals the chunk's own file offset. That makes the format
**self-validating**: rather than trusting the pointer table, `parse_model.py`
scans for known magics and confirms `selfOffset`, which is robust against any
pointer we have mis-read.

| Magic | Contents |
|---|---|
| `strm` | one vertex-attribute stream (one per attribute *per mesh*) |
| `mesh` | a draw descriptor (`polygon0`, `polygon1`, …) |
| `subm` | a GX packet: matrix-memory slots + a pointer to its display list |
| `dlst` | the raw GX display-list bytes |
| `sdsc` | shape descriptor (GX vertex-descriptor / format info) |
| `node` | a skeleton bone — *and* the node that draws a mesh |
| `mtrx` | the skinning matrix palette (see [09](09-skinning.md)) |

### `strm` — vertex attribute streams

| Offset | Field |
|---|---|
| `0x10` | name offset |
| `0x14` | id |
| `0x18` | element count |
| `0x1c` | data offset |

Bytes per element `= (chunkEnd - dataOff) / count` identifies the attribute:

| B/elem | Attribute |
|---|---|
| 6 | POS — `s16 × 3`, quantised (the scale is per-mesh, see [09](09-skinning.md)) |
| 3 | NRM — `s8 × 3` |
| 4 | UV (`s16 × 2`) or CLR (`rgba8`) |

Some models name their streams `group__MATERIAL` (e.g. `cat__an008_body`),
which is a usable secondary route to the material. Others (`pc001`) leave them
unnamed — for those the node table in [09](09-skinning.md) is what resolves it.

### `mesh` — draw descriptor

| Offset | Field |
|---|---|
| `0x14` | matIdx |
| `0x18` | ptr → `sdsc` |
| `0x1c`…`0x48` | **attribute → stream table, 12 slots**: POS, NRM, CLR0, CLR1, TEX0…TEX7 (`-1` = absent) |
| `0x4c` | number of `subm` |
| `0x50` | ptr → array of `subm` offsets |

All **12** slots matter. `pc001`'s `mouth` and `teeth` also use **TEX1** (pointing
at the same stream as TEX0); reading only the first five slots shifts every
following offset and the vertex layout stops adding up — one of those meshes
still decoded, but with a wrong layout that happened to validate.

## The display list

`dlst` holds raw GX commands: an opcode, a `u16` vertex count, then
`count × stride` bytes.

| Opcode | Primitive |
|---|---|
| `0x98` | triangle strip |
| `0xa0` | triangle fan |
| `0x90` | quads |
| `0x00` | NOP |

### Vertex layout

Each vertex is a run of **indices**, not values:

```
[ matrix-index bytes ] [ POS ] [ NRM ] [ CLR ] [ TEX0 ] [ TEX1 ] …
```

- the matrix-index bytes come first: PNMTXIDX, then TEXnMTXIDX. In this game
  the observed run is 5 bytes with the pattern `p, p+30, p+30, p, p` (GX texture
  matrices are numbered from 30). Unskinned meshes have **none**.
- each attribute index is **u8 or u16** depending on its stream size, and the
  stride varies per mesh (3…48 observed).

Neither the widths nor the stride are stored anywhere we found, so
`export_obj.py` *solves* the layout: given the attributes present and their
different stream counts, the assignment where every index falls inside its own
stream is unique in practice. One caveat had to be added — a column is normally
required to show ≥2 distinct values to be believed, but a stream with **one**
element (a constant vertex colour) can only ever index 0. Without that
exception, `pc001`'s `earring`, `necklace` and `op_01_strap` failed to decode at
all.

## Skeleton

`node` chunks carry a local TRS and a parent index:

| Offset | Field |
|---|---|
| `0x14` | name hash |
| `0x1c` | parent index (`-1` = root) |
| `0x34` | scale (3 floats) |
| `0x40` | rotation (3 floats, Euler radians, **ZYX**) |
| `0x4c` | translation (3 floats) |

`L = T · Rz · Ry · Rx · S`, `world = world[parent] · L`. `skeleton.py` rebuilds
the tree and can dump it as OBJ line segments. Validated on `an008`:
hips → spine → neck → head with increasing Y, limbs descending, and a tail
extending to Z = −8.19 (the model is a cat). These are the matrices `.motion`
animates.

A hash table of `(index, hash)` sorted by hash, at the offset in the header,
gives name → bone lookup.

## Materials and lip-sync

`.material` and `.lip` are **plaintext**, and both are bridges to other asset
types.

`.material` is a TAB-indented INI. Each `Material` block names its shader and
its texture channels (`TexColor1`, `TexEmboss1`, `TexSpec1`, …), each with a
`name=xxx.tga`. That `.tga` stem is the real asset `xxx.texture`, hence
`textures_png/**/xxx.texture.png` — the mesh ↔ texture bridge.

`.lip` is a TSV: a header `<nFrames>\t<fps>` (fps = 30), then
`frame \t viseme \t weight` rows. Visemes are the Japanese vowels **A E I O U**
plus **SLT** (silent). The third column is the viseme's weight (0..1), *not* a
timestamp — time is `frame / fps`. The file is named after its audio stream
(`VO_EV0101_010.lip` ↔ `VO_EV0101_010.brstm`), which is the bridge to
[05](05-audio-brstm.md).

## Tools

```
python tools/parse_model.py    FILE.model [--json|--skeleton]
python tools/skeleton.py       FILE.model [--obj OUT.obj]
python tools/export_obj.py     FILE.model OUT.obj [--scale S] [--raw]
python tools/render_obj.py     OUT.obj OUT.png [--no-cull]
python tools/parse_material.py FILE.material [--json|--textures]
python tools/parse_lip.py      FILE.lip [--json|--csv]
```

`render_obj.py` is the only tool here that needs third-party packages
(`numpy`, `pillow`).

Assembling the geometry into a coherent model is the subject of
**[09 — Skinning](09-skinning.md)**.

## Confirmed against a running game

The vertex layout described above was reconstructed from the files alone. It
has since been checked against a FIFO log — one frame of the real GX command
stream — see [25](25-differential-testing.md). Three points are no longer
inferences:

- **175 of 175** array references confirmed: where a CP register says the
  position/normal/colour/texcoord array lives, and with what stride, is exactly
  the `dataOff` and bytes-per-element that `parse_model` reports from the file.
  No discordances.
- The `strm` classification by bytes-per-element is right: stride 6 is
  `POS(s16x3)`, 12 is `POS(f32x3)`, 3 is `NRM(s8x3)`, 4 is a texture coordinate
  or a colour.
- **The per-mesh quantisation K is a declared hardware field.** VAT A carries
  `pos_frac`; across the frame it takes the values 9-15 and 17, matching the
  range this document had to solve for.

One thing the log does *not* settle: the `strm` field at `+0x14` is not an
attribute type tag, so the 4-byte `UV/CLR` ambiguity stays ambiguous in the
file. It is resolved only by which CP array the display list points at.
