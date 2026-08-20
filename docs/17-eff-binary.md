# 17 — `.eff`: the particle effect binary

[16 — Effects](16-effects.md) decoded the two text formats of the effects group
and left the binary one open. This is it: 2,210 files, magic `@EFF$`, holding
the actual definition — particle emitters, materials, and animation curves.

## Read this first: it is little-endian

Every binary format in this project so far has been big-endian, which is what a
PowerPC console wants. This one is not, and finding that out by accident costs
an hour.

The word at `+0x08` read **little-endian** is the file size, on **2210/2210**
files. Read big-endian it is noise. The offsets are also **absolute**, not
self-relative like the collision formats in [14](14-collision.md) and
[15](15-collision-hcb.md) — the other habit worth unlearning here.

It is consistent: the magic is `@EFF$` in reading order, *not* byte-swapped the
way `@HOC` ships as `COH@`. Together with the Windows author path found inside
a `.efp` in [16](16-effects.md), the picture is an effect editor running on a PC
whose output was shipped as-is.

## Header and sections — 72 bytes

```
+0x00  char[8]  '@EFF$\0\0\0'
+0x08  u32      file size                      2210/2210
+0x0c  u32      A = number of EMITTERS
+0x10  u32      B = number of MATERIALS
+0x14  u32      72, always (start of data)     2210/2210
+0x18 … +0x44   section offsets, monotonic     2210/2210
                (+0x1c and +0x24 are zero in every file)
```

Sections carry no size field — a section's length is the distance to the next
offset. The record sizes fall out of that, and they are exact on **every file**:

| Section | Size | Contents |
|---|---|---|
| `[+0x14, +0x18)` | **B × 312** | materials |
| `[+0x18, +0x20)` | **A × 620** | emitters |
| `[+0x20, +0x28)` | 0 | empty in every file |
| `[+0x28, +0x2c)` | A × 4 | one u32 per emitter |
| `[+0x2c, +0x30)` | **A × 176** | curve tables, one per emitter |
| `[+0x30, +0x34)` | A × 4 | one u32 per emitter (always 1) |
| `[+0x34, +0x40)` | 0 | empty in every file |
| `[+0x40, +0x44)` | A × 4 | one u32 per emitter |
| `[+0x44, EOF)` | — | tail: the curve key data |

These are what establish that `A` and `B` are counters and that the records are
312, 620, 176 and 4 bytes wide. None was guessed from one file — each holds on
2210/2210 (`parse_eff.py --check`). Six files are empty: `A = B = 0`, 72 bytes
total, every offset equal to the file size.

## Material — 312 bytes

```
+0x000  char[128]  COLOUR texture name   (…_c.texture)
+0x080  char[128]  ALPHA texture name    (…_a.texture)
+0x100  56 bytes   parameters (u32 + f32)
```

128 + 128 + 56 = exactly 312. The two slots follow the `_c` / `_a` suffix
convention already established from the texture pipeline
([04](04-textures-gx.md)), which is a nice independent confirmation of the split.
Some slots hold a `.model` instead of a texture: effects can use meshes, not
only billboards.

**Cross-check** (`--check-res`): the names have to be real files. 727 distinct
names across 8,250 references, and **721 exist on disc** under `data/texture/`
or `data/model/`.

The six that do not are worth listing, because none is a parsing failure:

- `ef_waa04n_a.textuer` — the author typed the extension wrong;
- `ef_hkr21n_c` — no extension at all;
- `Mb243_hei`, `Mb243_fire`, `Mb243_wave`, `eff_swd01o` — models and textures
  that live in the recursive `levels`/`eventpacks` packs, still unexploded.

## Emitter — 620 bytes

```
+0x000  char[64]   NAME, NUL-terminated, Shift-JIS
+0x040  …          parameters: lifetime, count, gravity, sizes,
                   RGBA as floats in 0..255, rotation in degrees, …
```

The names are hand-authored and mostly Japanese, and they read like an artist's
layer list: `煙` (smoke, 94 times), `土煙` (dust cloud), `軌跡` (trail),
`フラッシュ` (flash), `クロモヤ` (black haze), `石` (stone), `埃` (dust) and
`埃_加算` (dust, additive) — mixed with romaji shorthand like `line00`, `tub00`,
`smk`. 2,570 distinct names across 8,637 emitters.

**One trap when reading the name.** In 3,553 of the 8,637 records the bytes
*after* the NUL terminator are not zero. They are the tail of a longer name
written earlier into the same buffer and never cleared:

```
波門_大 \0 E \x83 C \0 \0 \0 …
```

Cut at the first NUL. Stripping zeros, or decoding all 64 bytes, produces dirty
names — and the tool that does it will look like it is working.

## Curves — the part that can be proven

Each emitter owns a 176-byte record holding **22 pairs of (keyCount, offset)**,
one per animatable channel: 22 × 8 = exactly 176. The offset points into the
tail, where each key is **8 bytes = (f32 t, f32 value)**.

That reading is confirmed five independent ways, over 36,705 curves and 105,557
keys (`parse_eff.py --check-curves`):

| Check | Result |
|---|---|
| every pointer inside the tail, `offset + count*8` not overrunning | **2204/2204 files** |
| key blocks never overlap | **2204/2204** |
| every tail byte the curves do *not* cover is zero | **2204/2204** |
| first key has `t = 0.0` | **36,705 / 36,705 — 100 %** |
| last key has `t = 1.0` | **36,705 / 36,705 — 100 %** |

The third one is the structural argument: the curves tile the tail, and what
they leave over is padding — 4 to a few dozen zero bytes, always a multiple of
4. Nothing is ever covered twice and nothing non-zero is ever missed.

The last two are the semantic argument, and they say what the time axis *is*.
The domain is not frames — it is the particle's **normalised lifetime, [0,1]**,
the standard particle-system convention. A misread field does not produce 36,705
curves that all begin at exactly 0.0 and all end at exactly 1.0.

62 % of curves have just two keys, start and end; the largest has 78. Time is
non-decreasing on 36,659 of 36,705 (99.87 %) — the 46 exceptions are tiny
inversions between adjacent keys (`0.37224` then `0.36909`), authoring noise
rather than a parse error.

### What the 22 channels are is *not* settled

They are clearly used at different rates and look grouped by component
(0–2, 3–5, 7–9, 12–14, 15–17, 19–21, with 6 and 18 standing alone). The tempting
move is to read each group as one XYZ curve — but **the key counts within a
group do not always agree**: 79 % for the first group, ~99 % for the others. So
each component is keyed independently and a group is not one vector curve.

Which channel drives what would need the DOL or an on-screen comparison. It is
not a data-analysis problem, and it is not guessed here.

## Reading a real file

```
$ python parse_eff.py be004_001.eff
=== be004_001.eff - 2496 bytes (little-endian) ===
  2 emitters, 2 materials
  material #0  colour='ef_kem06o_c.texture'  alpha='ef_kem05o_a.texture'
  material #1  colour='ef_kem05o_c.texture'  alpha='ef_kem05o_a.texture'
  emitter #0  '埃'       5 animated channels
      channel  0   2 keys  0.000:5.95, 1.000:12.2
      channel  6   3 keys  0.000:1.59375, 0.500:51.7969, 1.000:0
      channel 18   2 keys  0.000:16, 1.000:6.9
  emitter #1  '埃_加算'   5 animated channels
```

Dust that grows from 5.95 to 12.2 over its life, with channel 6 rising and then
falling to zero — and a second additive pass over the same two textures.

## Tools

```
python parse_eff.py FILE.eff        # summary: materials, emitters, curves
python parse_eff.py --check         # the six section equalities
python parse_eff.py --check-curves  # tiling and the [0,1] domain
python parse_eff.py --check-res     # resource names exist on disc
python parse_eff.py --names         # emitter names
```

## What is still open

- The meaning of the individual floats in the emitter's 620 bytes and the
  material's 56. They are readable; they are not named.
- Which of the 22 channels is position, size, colour, rotation.
- The three `A × 4` tables. The one at `+0x30` is **1 in all 8,637 records**;
  the others carry 68 and 76 distinct values.

With this the effects group is complete: `.efp` and `.effconfig` in
[16](16-effects.md), `.eff` here.
