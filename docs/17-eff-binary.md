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
+0x00  char[4]  '@EFF'
+0x04  u32      VERSION — 0x24 on every file   3158/3158
+0x08  u32      file size                      2210/2210
+0x0c  u32      A = number of EMITTERS
+0x10  u32      B = number of MATERIALS
+0x14  u32      72, always (start of data)     2210/2210
+0x18 … +0x44   section offsets, monotonic     2210/2210
                (+0x24 is zero in every file)
+0x1c  u32      C = count of a third record type — 0 in every file
```

> **Correction.** This was previously read as an 8-byte magic `'@EFF$\0\0\0'`.
> It is a **4-byte** magic and a **u32 version**: the `'$'` is `0x24`, the low
> byte of version 36 stored little-endian. The DOL's loader is what settles it —
> see [The loader in `main.dol`](#the-loader-in-maindol) below — and the reading
> holds on all 3158 `.eff` files on the disc.

Sections carry no size field — a section's length is the distance to the next
offset. The record sizes fall out of that, and they are exact on **every file**:

| Section | Size | Contents |
|---|---|---|
| `[+0x14, +0x18)` | **B × 312** | materials |
| `[+0x18, +0x20)` | **A × 620** | emitters |
| `[+0x20, +0x28)` | 0 | a **third record type**, 272 bytes — count `C` is 0 in every file, but the loader supports it |
| `[+0x28, +0x2c)` | A × 4 | one u32 per emitter — a **bitmask of which channel groups are keyed**, see [20](20-eff-channels.md) |
| `[+0x2c, +0x30)` | **A × 176** | curve tables, one per emitter |
| `[+0x30, +0x34)` | A × 4 | one u32 per emitter (always 1) |
| `[+0x34, +0x40)` | 0 | empty in every file |
| `[+0x40, +0x44)` | A × 4 | one u32 per emitter — a second mask, **which channel groups are inert**, see [20](20-eff-channels.md) |
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

### What the 22 channels are is *not* settled — *settled in [20](20-eff-channels.md)*

> **Session 10.** The channels are decoded: the grouping guessed below is real
> (and includes a pair, 10–11, missed here), the `A × 4` table at `+0x28` is the
> per-emitter **bitmask of which groups are keyed**, and the map holds on
> 77,733 / 77,733 checks against the shipped data. See
> [20 — The 22 `.eff` channels](20-eff-channels.md). The section below is kept
> because the ruled-out idea in it is still worth not repeating — and because
> [20](20-eff-channels.md) explains *why* it could never have worked.

They are clearly used at different rates and look grouped by component
(0–2, 3–5, 7–9, 12–14, 15–17, 19–21, with 6 and 18 standing alone). The tempting
move is to read each group as one XYZ curve — but **the key counts within a
group do not always agree**: 79 % for the first group, ~99 % for the others. So
each component is keyed independently and a group is not one vector curve.

#### An idea that looked right and was not

There was a data-driven route worth trying before falling back on the DOL. If a
channel animates a parameter, the curve's value at `t = 0` ought to equal the
corresponding **static** parameter inside the emitter's 620 bytes — pairing
channel to offset through a recomputable invariant, which is how most of this
project's results were reached.

The first count looked like a hit: some channels matched a static offset in over
90 % of cases. It was **entirely an artefact**. Those matches were on the values
`0.0` and `1.0`, which sit in dozens of static slots and therefore match by
chance; several unrelated offsets tied with identical counts, which is the tell.

Repeating the count **on distinctive values only** — excluding `0`, `±1`, `0.5`,
`255`, `360` — the signal vanishes:

| Channel | Distinctive cases | No match at all | Best offset |
|---|---|---|---|
| 0 | 3236 | **94.4 %** | +0x11c, 1.9 % |
| 1 | 1816 | 90.5 % | +0x24c, 4.1 % |
| 6 | 4844 | **99.9 %** | +0x1a0, 0.1 % |

So the hypothesis is falsified: the curve's initial value is **not** duplicated
in the static block. The curve *replaces* the parameter rather than shadowing
it. Which means this really is out of reach of data analysis and needs the DOL
or an on-screen comparison. Run `parse_eff.py --channels` to reproduce both the
artefact and its refutation.

#### What can be stated as fact

- **Channel 6 is the universal one.** Animated on 7,992 of 8,637 emitters
  (92 %), constant in only 0.7 % of cases, and **ending at exactly 0 on 94.4 %
  of its 7,992 curves** — a quantity that dies out at end of life. It stays
  within [0,255] on 99.6 % of curves and within [0,1] on 0.0 %, so it is on a
  0–255 scale rather than normalised.
- Channels 19–21 reach −360, −403, 720 and 848 — multiples of 360, so degrees.
  But they are used only 45 times, far too few to conclude anything.
- Channels 1 and 2 are constant in 51 % and 81 % of cases: multipliers left
  at 1.

Naming them beyond that would be guessing, so they are left unnamed.

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
python parse_eff.py --channels      # channel stats + the ruled-out pairing
```

## The loader in `main.dol`

Everything above was derived from the files. The engine's own loader has since
been located, and it agrees — which is worth having, because until now the
record sizes rested on file-size arithmetic alone.

### Finding it

`.eff` is little-endian on a big-endian console, so *something* must byte-swap
it. PowerPC has byte-reversing loads, so `lwbrx` was the obvious net: there are
exactly **32 in the whole DOL, and all 32 sit in one routine** — which turns out
to be **MD5** (the F function, the sine table, the 7/12/17/22 rotations; MD5 is
defined little-endian). A dead end, but a quick and decisive one.

That leaves the software idiom, `rlwimi rT,rS,24,0,7` paired with
`rlwimi rT,rS,24,16,23`. 191 of those in 41 clusters — and two clusters sit in
the same address region as the `atn::EffectManager` and `atn::LoadEffect`
vtables recovered in [18 — DOL class names](18-dol-classes.md), which is what
made them worth reading first.

### It is schema-driven

`FUN_802371bc(void *data, const Entry *schema)` knows nothing about `.eff`. It
walks a descriptor of 8-byte entries:

```
s16 op ; s16 count ; u32 nested

op -1  end            op  2  swap `count` u32 (and f32)
op  0  skip `count` BYTES, untouched      op  3  swap `count` u64
op  1  swap `count` u16                   op  4  recurse into `nested`, `count` times
```

Because `op 0` means "leave alone", **the schema states which byte ranges are
text and which are numbers** — the format declaring its own layout, in the same
spirit as the `.hcb` relocation table in [15](15-collision-hcb.md).
`dol_swap_schema.py` decodes them:

| Schema | Describes |
|---|---|
| `0x80783a18` header | 64 B: 4 skipped (the magic), then u32s |
| `0x80783a80` emitter | **620 B**: 64 skipped (the name), then all u32 |
| `0x80783b18` material | **312 B**: 256 skipped (two 128-byte names), then 14 u32 |
| `0x80783b60` third type | 268 B in a 272 B stride |
| `0x80783ba0` curve key | **8 B**: 2 u32 |

The emitter's 64-byte skip and the material's 256 are the two name fields this
project had already inferred; the material's remaining 14 u32 are exactly the
56 bytes of parameters recorded above. The sizes 620, 312 and 8 now rest on the
code as well as on the arithmetic.

### The driver: `FUN_80239030`

The sole caller, and the `.eff` load path end to end:

1. swap the 64-byte header;
2. read the **version** at `+0x04` — below `0x22` it refuses and returns 0;
   below `0x24` it loads but logs `"old eff version!"`; at `0x24` or above two
   further header words at `+0x40`/`+0x44` exist and the curve tables are used
   in place rather than copied;
3. relocate the section offsets at `+0x28`…`+0x3c` by adding the load address;
4. walk `A` emitters, stride `0x26c` = **620**;
5. walk `B` materials, stride `0x138` = **312**;
6. walk `C` records of stride `0x110` = **272** — the type nothing ships;
7. per emitter, loop **22 times** (`iVar7 < 0x16`) over 8-byte `(count, offset)`
   pairs in a `0xb0` = **176**-byte block, relocating each offset and swapping
   `count` keys of 8 bytes;
8. per 272-byte record, the same with **13** channels in a `0x68` = 104-byte
   block.

Step 7 is the confirmation that matters most here: **22 channels of 8-byte keys
is what the engine does**, not an inference from `22 × 8 = 176`.

### What it did not give

The schema declares *widths*, not *meanings*. Every emitter field past the name
is `u32`, so the swapper cannot distinguish a float from a count, and it says
nothing about which channel is size or colour. Naming the 22 still needs either
the code that consumes them during simulation, or an on-screen comparison.

## What is still open

- The meaning of the individual floats in the emitter's 620 bytes and the
  material's 56. They are readable and their **widths are now confirmed**; they
  are not named.
- Which of the 22 channels is position, size, colour, rotation. The
  static-parameter pairing is ruled out (above) and the loader does not say —
  the next target is the simulation code that reads the curve block.
- ~~The three `A × 4` tables.~~ Two of the three are settled: `+0x28` is the
  keyed-group mask ([20](20-eff-channels.md)) and `+0x40` the inert-group mask,
  proved 38,105/38,105 in the same page. The one at `+0x30` is **1 in all 8,637
  records** and is read by no code in `main.dol` — still unexplained, but it
  carries no information either.
- The 272-byte third record type and its 13 channels: supported by the loader,
  used by nothing on this disc.

With this the effects group is complete: `.efp` and `.effconfig` in
[16](16-effects.md), `.eff` here.
