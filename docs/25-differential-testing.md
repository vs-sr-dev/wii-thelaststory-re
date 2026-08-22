# 25 — Differential testing against a running game

Every other document in this repository is validated by **internal and
cross-format consistency**: a claim about one file is checked against another
file, or against a count the format itself has to satisfy. That criterion is
strong, and it has caught real errors. But until this session it had never once
been checked against **the game actually running**.

This document is that check. Nothing here is a new file format. It is the
existing work put in front of an external witness.

## The witness

Dolphin can do two things that make it usable as ground truth:

1. **Dump textures** (`Graphics > Advanced > Dump Textures`). Every texture the
   game hands to the GPU is written out as a decoded PNG.
2. **Record a FIFO log** (`Tools > FIFO Player > Record`). One frame of the raw
   **GX command stream** the hardware received, plus the *contents of the game's
   memory* that the graphics processor read while producing that frame.

The second is the interesting one. A `.dff` file is not a screenshot; it is the
game's own draw calls and its own vertex data, captured mid-execution.

## Part 1 — Textures

`tools/dolphin_texdiff.py` matches dumps against the decoded assets. Results and
the two decoder errors it found are in [04](04-textures-gx.md); in short:

| sample | exact pixel matches |
|---|---|
| title screen, 18 textures | 4/18 before the fixes, **17/17** after (1 was not a disc asset) |
| in-game, 1,043 dumps | 290 exact, including **84 mipmap levels** |

The large in-game sample adds one fact the small one could not: **mip levels 1
and 2 match exactly**, which confirms that mips are packed immediately after
level 0, each rounded up to the format's block geometry. That was previously an
assumption.

It also produced a clean partition. 694 of the 1,043 dumps are I8, but the game
only ships **18** I8 textures. Those ~692 are intensity buffers the game builds
at run time (post-processing), not disc assets — the same category as the one
unmatched texture on the title screen.

## Part 2 — The FIFO log container

`tools/parse_dff.py`. Little-endian (it is a host file, not a Wii file); the GX
commands inside it are big-endian.

| Offset | Field |
|---|---|
| `0x00` | file id `0x0d01f1f0`, version 6 |
| `0x0c` | BP register block (256 entries) |
| `0x18` | CP register block (256 entries) |
| `0x24` | XF memory (4096 words), `0x30` XF registers (88) |
| `0x3c` | frame list offset, `0x44` frame count |
| `0x4c` | TMEM image (1 MB), `0x58` MEM1/MEM2 sizes |
| `0x60` | game id (`SLSP01`) |

Per frame: FIFO data offset/size, the GP address range, then a list of
**memory updates** — `(fifoPosition, address, dataOffset, dataSize, type)`.

Three arithmetic closures confirm the layout without any guessing:

- `fifoDataOffset + fifoDataSize == memoryUpdatesOffset`
- the memory-update record length is **measured**, not assumed: 24 bytes is the
  only stride in 16..32 for which every record has a known type, a
  non-decreasing FIFO position, and a blob inside the file
- the end of the last blob is the end of the file, exactly

Our capture: one frame, 555,010 bytes of GX commands and **3.64 MB of the
game's live RAM** — 794 vertex-stream blocks and 66 texture blocks.

## Part 3 — The bytes in RAM are the bytes on the disc

`tools/dff_match.py` compares the texture blocks with the extracted `.texture`
payloads. **54 of the 65 distinct blocks are byte-for-byte identical**, and the
assets they identify describe one coherent scene: `dg004_*` walls and floors,
`pc102_*`, `np_mouth`/`np_teeth`/`np_eye`, `ws002`/`ws024` weapons, `em303`,
`tutorial_*`.

> **Corrected while reading the BP registers.** This first said 56, because the
> matcher compared only `min(len(payload), len(block))` bytes. A 32 KB block
> whose first bytes happen to agree with a 128-byte texture — a black mask
> agrees with almost anything — was being "identified". Requiring the asset to
> be **at least as long as the region the GP actually read** drops two false
> matches and makes every surviving one exact in length as well as content. The
> witness that caught it is in Part 6: the same register that gives a texture's
> address declares its width, height and format independently.

Of the eleven that did not match at offset 0, one is a mipmap tail *inside*
`dg001_01_04b_bake01.texture` (found by substring search). The others sit
in a single address region, `0x1284`–`0x128b`, together with the run-time
geometry described below: a scratch heap, not disc data.

This proves the whole extraction chain — partition, `.pfs`/`.pkh`/`.pk`, LZ11,
the cracked hash — against a running game, without passing through any decoder
of ours.

## Part 4 — The GX command stream

`tools/fifo_decode.py` walks the command stream, tracking CP state.

**The criterion is closure.** Vertex size is computed from the CP registers; if
the reading of the vertex descriptor or of a VAT were wrong, the pointer would
desynchronise and land on an illegal opcode long before the end. It is not a
soft test — and it failed twice before it passed:

- the first run stopped at 86.9% because a normal that is indexed **with
  `NormalIndex3` set costs three indices, not one**;
- the second stopped at the same place, on a draw whose vertex size came out as
  zero. The cause: **GX has exactly one vertex descriptor**, registers `0x50`
  and `0x60`, shared by all eight VATs — only the *format* is per-VAT. Reading
  the descriptor as per-VAT works for as long as the game only uses VAT 0, and
  this frame contains exactly one draw that does not.

With both corrected: **555,010 / 555,010 bytes, 5,469 draw calls, 44,053
vertices, 100%.**

What the frame contains: 5,229 triangle strips, 188 triangle lists, 52 quads.
The skinned draws carry `PosMatIdx` plus `Tex4..7MatIdx` as *direct* bytes —
the matrix-palette indices — exactly the arrangement [09](09-skinning.md)
reconstructed from the files alone.

The VAT records also state the position quantisation directly: `pos_fmt = s16`
with `pos_frac` taking the values 9, 10, 11, 12, 13, 14, 15 and 17 across
meshes, alongside `f32` positions with no fraction. The **per-mesh K** that
[08](08-models-geometry.md) had to infer is a declared hardware field, and the
range matches.

## Part 5 — The closing test on geometry

`tools/fifo_model_xref.py`. Three sources that never talked to each other:

1. a CP register says *"the position array is at address A, stride S"*;
2. a RAM block from the log contains bytes that occur, identically, at offset
   `O` of one of our extracted `.model` files;
3. `parse_model`, reading only the file on disc, says there is a `strm` chunk at
   `dataOff == O` with that many bytes per element.

**Result: 175 array references attributed, 175 confirmed, 0 discordant.** Every
address that falls inside a resolved RAM block lands exactly on a `strm` chunk's
declared offset, with exactly the stride the hardware was told to use.

| GX attribute | stride | what `parse_model` calls it | n |
|---|---|---|---|
| Tex0 | 4 | `UV/CLR(4B)` | 45 |
| Normal | 3 | `NRM(s8x3)` | 36 |
| Tex1 | 4 | `UV/CLR(4B)` | 26 |
| Position | 12 | `POS(f32x3)` | 25 |
| Position | 6 | `POS(s16x3)` | 21 |
| Color0 | 4 | `UV/CLR(4B)` | 20 |
| Tex2 | 4 | `UV/CLR(4B)` | 2 |

604 of the 744 vertex blocks were located inside 21 model files, and a separate
closure holds on them: for each file, `address − offset` is a **constant** — the
address the game loaded it at — for **603 of 604** blocks.

The 140 unlocated blocks are not failures. They live in the `0x1289xxxx` scratch
region, and the same address reappears with growing sizes (57, 81, 84, 93
bytes): a buffer being appended to. That is geometry built at run time — UI,
text quads, particles — which by definition is not on the disc.

### A warning about attribution

The first version of this cross-check attributed an array address to a file by
extrapolating from the file's load base, and reported 50 discordances. All 50
were the heuristic's fault: file ranges overlap, and a load base measured from a
single short block is not a measurement at all. Attributing through **the RAM
block that actually contains the address** — file and offset both known exactly
— removed every one of them. The formats were never in question; the bridge was.

## What this does and does not establish

It establishes that, for the pipeline stages it touches, our reading is not
merely self-consistent but *matches what the hardware was actually given*: the
extracted bytes, the texture decode, the vertex array layout, the attribute
formats, the quantisation, the matrix-palette arrangement.

It does not touch TEV/material semantics, animation evaluation, or any game
logic. Those remain validated only internally.

### A measured negative

The `strm` chunk's field at `+0x14` is **not** an attribute type tag. Using the
175 confirmed rows as ground truth, its values are large, multiples of 16, and
collide across attributes. It is an id internal to the file. The
`UV/CLR(4B)` ambiguity in `parse_model` — 4 bytes per element is either a
`s16x2` texture coordinate or an `RGBA8` colour — is not resolved by that field.

## Reproducing

```
# 1. enable dumping, boot, play a few minutes, then Tools > FIFO Player > Record
python tools/dolphin_texdiff.py "<Dolphin>/Dump/Textures/SLSP01"
python tools/parse_dff.py fifo.dff
python tools/dff_match.py fifo.dff
python tools/fifo_decode.py fifo.dff
python tools/fifo_model_xref.py fifo.dff
```

## Part 6 — The BP registers: what was bound, and what the material does not say

The command stream also carries **7,491 BP register writes** — the pixel-side
state. `tools/fifo_tev.py` replays the stream keeping that state, so every draw
can be asked what it had bound.

### Texture bindings, confirmed twice

`TX_SETIMAGE3` holds a texture's address (value `<< 5`). `TX_SETIMAGE0` — a
*different* register — declares its width, height and format. So each binding
can be checked two ways at once: the address says *which* asset, and the
dimensions say whether that answer is consistent.

**59 bindings resolved, 59 confirmed, 0 discordant.** Every address that falls
inside a recognised RAM block belongs to a `.texture` whose `chnkdata` header
carries exactly the width, height and format the register declares.

Two false readings had to be removed first, and both were mine:

- **Stale units.** Reporting a binding for every unit that has an address and a
  format reads leftovers: the game only rewrites the registers of the unit it is
  about to use. The units a draw *actually* uses are the ones its active TEV
  stages name, in `RAS1_TREF` (`0x28`–`0x2f`), whose per-stage enable bit says
  whether the stage samples a texture at all. Filtering by that cut the
  bindings-in-use from 43,752 to 16,663.
- **The prefix match** described above, which the register dimensions exposed.

### The material does not name everything the engine binds

`tools/fifo_material_xref.py` puts three sources together: the CP registers say
which `.model` a draw's vertices come from, the BP registers say which
`.texture` is bound, and the `.material` with the same stem — read from the disc
alone — says what *should* be used. CP and BP are different subsystems that do
not talk to each other, and neither has seen the material.

Of the textures bound while drawing a model, **36 are named by its material and
19 are not**. The 19 are not noise; they are four engine behaviours:

| Bound but unnamed | What it is |
|---|---|
| `dg004_01_01*_bake01` | the area's baked lightmap, substituted into the material's `bake_tex` slot |
| `specular`, `lightsurround` | engine-global channels, bound for any lit model |
| `dg004_01_01_coverage01` | an area coverage map bound for *moving* objects — the character and both weapons |
| `dg036_water03` on `dg004_Puddle01` | a shared water texture, from a different dungeon's set |

**`bake_tex` is a placeholder, and the engine fills it per instance.** The claim
is exact:

- 6 models in this frame have `bake_tex` in their material;
- all **6 of 6** bind exactly one `*_bake01` texture and nothing else beyond the
  globals;
- and no model *without* `bake_tex` binds a bake texture at all.

The substituted bake differs per prop — `dg004_01_01_bake01`,
`…b_bake01`, `…c_bake01` — which is what a per-instance lightmap tile looks
like; `.locator` carries exactly such a field ([11](11-maps-and-scenes.md)).
The map geometry itself does *not* use the placeholder: `dg004_01_01_base`
names `dg004_01_01_base_bake01` outright. That asymmetry is the point — props
are instanced across areas and cannot name a bake, map geometry belongs to one
area and can.

A reader of the files alone would conclude that `bake_tex` is a missing texture.

### One more attribution trap

Draws that use **direct** vertices — the UI, text quads, particles — read no
array at all, so the CP base register still holds the previous model's value.
Attributing them by that register made a character appear to be drawing the
interface fonts. Requiring `Position` to be *indexed* before attributing a draw
removed 13 spurious texture associations. It is the same failure as the stale
texture units, and as the load-base attribution in Part 5: **three times in one
session, the wrong answer came from reading state that was merely left over.**
