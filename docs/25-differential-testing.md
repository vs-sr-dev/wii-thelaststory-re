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
payloads. **56 of the 65 distinct blocks are byte-for-byte identical**, and the
assets they identify describe one coherent scene: `dg004_*` walls and floors,
`pc102_*`, `np_mouth`/`np_teeth`/`np_eye`, `ws002`/`ws024` weapons, `em303`,
`tutorial_*`.

Of the nine that did not match at offset 0, one is a mipmap tail *inside*
`dg001_01_04b_bake01.texture` (found by substring search). The other eight sit
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
