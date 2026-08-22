# 24 — `RSEQ` and `RBNK`: the sequences and the instrument banks

[23 — The sound archive](23-brsar.md) opened `lastworld.brsar` and left two of
its three item kinds located but unread: **378 `RSEQ` items** (326 distinct
sequences, played by 330 `SEQ` sounds) and **5 `RBNK` items** (3 distinct
banks, 184 instrument samples). This reads both, and closes the archive: after
it, every one of the 2,756 waves inside the file is reached by something that
names it.

Tool: still [`tools/parse_brsar.py`](../tools/parse_brsar.py). `--validate` now
runs **52 checks**, none sampled; `--seq` writes every sequence out as text and
`--banks` writes the programs as CSV.

## The labels are why this format opens

An `RSEQ` has two sections, `DATA` and `LABL`, on **326 / 326** files. `DATA`
is a `u32` offset followed by the bytecode. `LABL` is a count, that many
offsets, and at each one a `u32` byte offset into the bytecode, a `u32` length,
and **the label's name in plain ASCII**.

There are 1,870 of them over the 326 distinct sequences, and they are not
decoration:

```
SMF_C4_16_006_Begin      +0x00
SMF_C4_16_006_Start      +0x03
SMF_C4_16_006_Track_0    +0x0a
SMF_C4_16_006_Track_1    +0x1b
SMF_C4_16_006_End        +0x25
```

Three things fall out immediately. The `SMF_` prefix says the sequences were
converted from **Standard MIDI Files** — 324 of the 326 carry it. Two are not:
`town_zawa` (ざわ, a town murmur, packed into three groups) and `jihibiki_goo`
(地響き, an earth rumble) are hand-written, carry a single label each, and are
the only sequences in the archive that were not run through the converter.

And, more useful than either: **a label offset is a claim about the bytecode
that can be checked**. Everything below is checked that way.

## What a sound points at

A `SEQ` sound's per-type tail is `u32 entry offset`, `u32 bank id`,
`u32 allocated tracks`. The entry offset is a **label offset on 382 / 382**
sound placements, and the bank id indexes the bank table on **330 / 330**
sounds. Where it lands is itself informative: 296 placements enter at `_Start`,
82 at an offset where `_Begin` and `_Start` coincide, and 4 at the name of a
hand-written sequence. The 82 are the single-track sequences — with one track
there is no `alloctrack` to emit, so `_Begin` has nothing before `_Start` and
the two labels sit on the same byte.

## The bytecode, established against the labels

Commands below `0x80` are notes; `0x80` and up are commands. The argument
widths were not taken on faith — a wrong width desynchronises the decode, so
"every track reaches its terminator" is a real test and it is the one that
holds the table together.

Four opcodes are pinned by the labels alone:

| Byte | Meaning | How it is known |
|---|---|---|
| `0xFF` | `fin` | the byte at the `_End` label, **324 / 324** |
| `0xFE` | `alloctrack`, `u16` mask | the mask equals the exact set of `Track_N` indices, **259 / 259** |
| `0x88` | `opentrack`, `u8` track + `u24` offset | the offset is a `Track_N` label **and** the track byte is that label's number, **572 / 572** |
| `0xB0` | one byte, invariably `96` | the first command at every `_Start`, **324 / 324** |

`0x88` deserves a note, because two readings of the bytes both worked. After
`B0 60` the stream is `88 01 00 00 1b`. Reading `0xB0` as a one-byte command
gives `opentrack track 1 → +0x1b`; reading it as a three-byte one (opcode,
`u8`, `s16`) instead gives a variable assignment and then a note — and both
land on the next label. What separates them is that only the first reading
*claims* something: that an arbitrary `u24` is a named label offset and the
byte before it is that label's index. That claim is true 572 times out of 572.
The other reading explains none of it.

`0xB0`'s argument is `96` in every sequence and never anything else. Given
the labels say the source was a Standard MIDI File, where 96 ticks per quarter
note is the classic resolution, a timebase is the natural reading — but that
is an inference from the name of the source format, not a measurement, so the
tool prints it as `op_b0`.

### `0xA0` is a prefix, and it is six bytes

Six sites in three files use `0xA0`, and all six randomise the same command,
`0xC4`:

```
a0 c4 ff 81 00 7f      ->  random on 0xC4 in [-127, +127]
a0 c4 ff ce 00 1e      ->  random on 0xC4 in [-50, +30]
a0 c4 ff 9c 00 32      ->  random on 0xC4 in [-100, +50]
```

Again two readings fit — with or without the command's own argument byte
between the opcode and the bounds. The bounds settle it. `0xC4`'s parameter is
one signed byte, so its bounds have to lie in `[-128, 127]`; under the six-byte
reading **all 12 bounds do**, and under the seven-byte reading they come out as
−32512 and +32572. A randomiser cannot have bounds outside the domain of the
thing it randomises.

### Named from the operand distributions

| Byte | Name | The evidence |
|---|---|---|
| `0x00`–`0x7F` | note: key, `u8` velocity, varint length | keys 27–88, velocities 1–127 |
| `0x80` | `wait`, varint | 7,993 uses, 441 distinct delta times, mode 1 |
| `0x81` | `prg`, varint | **1,112 / 1,112** are below the program count of the bank their sound names — see below |
| `0xC0` | `pan` | mode **64** (649 of 1,517), range 0–127: dead centre |
| `0xC1` | `volume` | mode **127** (644 of 1,178), range 0–127: full |
| `0xC7` | `notewait` | 896 uses — **exactly one per track** — and always `0` |
| `0xE1` | `tempo`, `u16` | 150 (311×), 100, 170, 200, 30, 45: beats per minute |
| `0xC4` | *bend* | 155 distinct byte values clustered at both ends (0, 250, 244, 228 = 0, −6, −12, −28), concentrated in 74 tracks — a signed, zero-centred parameter under automation, and the only thing `0xA0` ever randomises. "Pitch" is the obvious reading and is not proven here |

### Characterised and deliberately not named

`0xB0` (always 96), `0xC5` (76 uses, 15 distinct), `0xCA`, `0xD0`, `0xD9`
(4 uses, always 18), `0xD5` (2,797 uses, 0–127), `0xD4` (237 uses, always 0),
`0xFC` and `0xFD` (no arguments).

`0xD4` and `0xFC` look like a loop-start / loop-end pair, and the tempting move
is to name them. The data says no: per track their counts come out (3,2),
(2,1), (3,1), (1,2) and (1,0) as often as (1,1), and 5 of the 103 tracks that
use either have an `0xFC` with no open `0xD4` before it. A pair that does not
pair is not a pair, so both keep their numbers.

**Every track decodes cleanly to its terminator: 898 / 898.**

## `RBNK` — the instrument banks

One `DATA` section: a count, that many 8-byte references — one per program
number — and then the records. The table ends exactly where the first record
begins in all three banks (`0x124` for 36 programs, `0x3dc` for 123, `0xc4`
for 24), which is what fixes the record stride at **48 bytes**.

The reference's type byte says how to read the target: `0` is a null program
(one exists), `1` is a direct record, `2` splits by key range, `3` by index
(unused here). A key-range split is a count, that many upper key bounds,
aligned to four, then that many further references:

```
03 2f 3b 7f | ref -> +0x290 | ref -> +0x2c0 | ref -> +0x2f0
   keys ≤47      ≤59            ≤127
```

A direct record is 48 bytes of which **only the first 20 are ever used** —
bytes `0x14`–`0x2f` are zero on **180 / 180** records:

```
+0x00  u32  wave index
+0x04  u8   attack, decay, sustain, release
+0x08  u32  0
+0x0c  u8   original key (0x3c = 60), volume (0x7f), pan (0x40 = centre), 0
+0x10  f32  tune (1.0)
```

| Bank | Programs | Records | Waves |
|---|---|---|---|
| `SEQBNK_SYS` | 123 direct | 123 | 123 |
| `SEQBNK_ATTR` | 35 direct + 1 null | 35 | 34 |
| `SEQBNK_MAP_TW001` | 22 direct + 2 key-range | 27 | 27 |

**Each bank's programs cover exactly its own set of waves — 3 / 3 banks**, no
index out of range and no wave left unreferenced. `SEQBNK_MAP_TW001` is the
sharpest: 24 programs would not cover 27 waves, and it is precisely the two
key-range splits, expanding to five records, that make 22 + 5 = 27.

## The two halves have to agree, and they do

The sequences and the banks are separate structures reached by different
paths. A `prg` command selects a program; the sound entry selects the bank.
Nothing in either file constrains the other — and yet **every one of the 1,112
`prg` commands reachable through a `SEQ` sound is below the program count of
the bank that sound names**.

With that, the archive is closed: of its 2,756 waves, 2,518 are reached by
sound name through `RWSD` ([23](23-brsar.md)) and the remaining 184 distinct
samples are reached as instruments through the three banks (185 records over
184 waves — two programs in `SEQBNK_ATTR` share one).

## The `main.dol` route, and why it was abandoned

The obvious way to get the opcode table is to read the interpreter. The player
is definitely linked: `nw4r::snd::SoundArchivePlayer::SeqNoteOnCallback`,
`SeqSound` and `SeqTrack` all survive in the DOL's RTTI strings. But two cheap
anchors both came back empty, and the negative is worth recording so the next
attempt does not repeat them:

* **There is no opcode jump table.** No `bctr` in the binary is preceded by a
  bound check of 0x4f, 0x50, 0x7e, 0x7f or 0x80, and no table of function
  pointers with 80 or 128 entries lands inside the `nw4r::snd` address range.
* **No function is a comparison cascade over the opcodes either.** Across the
  whole binary, the function comparing the most sequence opcode values as
  immediates manages three, and inside `nw4r::snd` the best is one.

One promising-looking 73-entry dispatch table at `0x80797488` turned out to be
a game-side event dispatcher: it is indexed by a field at `+36` of an object,
bounded at 72, and each of its handlers logs a line number before calling out.
Not audio.

So the opcode table here rests on the data, which — given 898 clean decodes,
572 label-confirmed jumps and 1,112 bank-confirmed program numbers — it can.

## Using it

```
python tools/parse_brsar.py --validate                     # 52 checks
python tools/parse_brsar.py --seq   audio/sequences.txt    # 326 sequences, readable
python tools/parse_brsar.py --banks audio/brsar_banks.csv  # 186 program rows
```

## Still open

* `0xB0`, `0xC5`, `0xCA`, `0xD0`, `0xD4`, `0xD5`, `0xD9`, `0xFC`, `0xFD` are
  sized and counted but not named. `0xD5` is the interesting one: 2,797 uses,
  the whole 0–127 range, and no distinguishing shape.
* Nothing here renders a sequence to audio. The pieces now exist — programs,
  envelopes, base key, tune, and the waves — but the note-to-pitch mapping and
  the envelope's time base are not measured.
* The sequence interpreter in `main.dol` is still unlocated; see above for the
  two anchors that do **not** find it.
