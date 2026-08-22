# 23 — `lastworld.brsar`: the sound archive

The last large container on the disc that had never been opened. One file,
85.8 MB, and everything the game can play that is not a `.brstm` sitting on the
filesystem lives inside it: 964 sound effects, 330 sequences, 3 instrument
banks, and the index that binds all 13,996 sound IDs to actual audio.

[05 — Audio (BRSTM)](05-audio-brstm.md) decoded the streams and built the
text↔voice loop from `LastWorld.rsid.csv`, the sound registry the disc ships in
the clear. What that registry never had was the *binding*: which file a name
plays, which player owns it, how loud, how it attenuates. The archive is that
binding, and the two agree on **13,996 of 13,996** names in entry order.

The DOL says what runtime this is, so it did not have to be guessed:
`nw4r::snd::SoundArchivePlayer`, `nw4r::snd::DvdSoundArchive::DvdFileStream`
and `SoundArchivePlayer::WsdCallback` survive in the RTTI recovered in
[18](18-dol-classes.md), alongside the game's own `atn::SoundManager` and
`GameSoundControl`.

Tool: [`tools/parse_brsar.py`](../tools/parse_brsar.py). Every count below is
from `--validate`, which runs 43 checks over the whole file, none sampled.

## The shape, and why the shape is a measurement

```
+0x00  'RSAR'  BOM 0xfeff  version 1.04
+0x08  u32     file size = 0x51dd940  == the actual length
+0x0c  u16     header length 0x40
+0x0e  u16     section count 3
+0x10  3 x (u32 offset, u32 size)
```

| Section | Offset | Size | Contents |
|---|---|---|---|
| `SYMB` | `0x40` | `0xc9500` | the string table and four name trees |
| `INFO` | `0xc9540` | `0x1e7de0` | six tables: sounds, banks, players, files, groups, footer |
| `FILE` | `0x2b1320` | `0x4f2c620` | the packed `RWSD`/`RSEQ`/`RBNK` blobs and their waves |

Nothing here was inferred from a single field. Three measurements pin the
layout, and each one is a coincidence the format does not have to produce:

* the **four SYMB trees are contiguous byte for byte** — each one ends exactly
  where the next begins — and their leaves sum to **13,996 + 5 + 167 + 3 =
  14,171**, which is exactly the number of strings. No orphan string, no
  invented leaf.
* **every INFO table ends exactly where its first entry begins.** The sound
  table holds 13,996 references of 8 bytes; `0xc957c + 13996×8 = 0xe4adc`, and
  `0xe4adc` is the address the first reference points at. That is what makes
  the entry stride a measurement instead of a guess.
* the **last group's wave block ends at `0x51dd940`**, the final byte of the
  file.

Everywhere the format points at something it uses the same 8-byte tagged
pointer: byte 0 is the base the offset is relative to (always 1 here, meaning
the section's data base — `0x48` for SYMB, `0xc9548` for INFO), byte 1 is a
data-type tag, and the trailing u32 is the offset. Zero means null.

## SYMB — the names

A string table (`14,171` strings) and four patricia trees, one per kind. The
string table is ordered by kind, which is what lets `LastWorld.rsid.csv` line
up with it: players `0-4`, groups `5-171`, banks `172-174`, sounds
`175-14170`.

A tree node is 20 bytes: `u16 flags` (bit 0 = leaf), `u16 bit index`,
`u32 left`, `u32 right`, `s32 string id`, `s32 item id`. A branch tests bit `k`
of the name, where bit `k` is bit `7 - (k & 7)` of byte `k >> 3`, and a name
too short for the index takes the left branch.

The walk is implemented and run over every name in the archive:
**14,171 / 14,171** lookups land on the leaf that owns the name. This matters
more than it looks — the walk never *fails*, it just lands somewhere. Checking
that it lands on the right leaf for every single name is what proves the bit
convention rather than assuming it.

## INFO — six tables

Each table is `u32 count` followed by that many 8-byte references.

| Table | Count | Entry |
|---|---|---|
| sounds | 13,996 | 0x2c + a 0x0c per-type tail + a 0x0c 3D block = **0x44** |
| banks | 3 | 8 bytes: string id, file id |
| players | 5 | string id, playable sound count, heap size |
| files | 13,222 | sizes, an optional disc path, and a position list |
| groups | 168 | two blocks in `FILE`, and an item list |
| footer | — | not a table: `(64, 64, 5, 5, 8, 64, 64, 0)` |

### The sound entry, 0x44 bytes

```
+0x00  u32   string id
+0x04  u32   file id
+0x08  u32   player id
+0x0c  Ref   -> the 3D block, at +0x38 of this same entry
+0x14  u8    volume
+0x15  u8    player priority
+0x16  u8    sound type: 1 = SEQ, 2 = STRM, 3 = WAVE
+0x17  u8    remote filter
+0x18  Ref   -> the per-type tail, at +0x2c of this same entry
+0x20  u32   user param 1
+0x24  u32   user param 2
+0x28  u8    pan mode
+0x29  u8    pan curve
+0x2a  u8    actor player id
+0x2c  0x0c  the per-type tail
+0x38  0x0c  3D: u32 flags, u8 decay curve, u8 decay ratio, u8 doppler factor
```

The two references pointing back into the entry at `+0x2c` and `+0x38` are what
say the entry is a 0x2c head with two 0x0c tails, rather than one 0x44 struct.

The tail's *data-type tag byte* equals the sound type on **13,996 / 13,996**
entries — the record is self-describing, and that is free confirmation that the
tag byte means what it looks like.

| Type | Count | Tail |
|---|---|---|
| `STRM` | 12,702 | `u32 start position`, `u16 channel count`, `u16 track flag` |
| `WAVE` | 964 | `u32 subNo`, `u32 alloc track`, `u8 channel priority` |
| `SEQ` | 330 | `u32 data offset`, `u32 bank id`, `u32 alloc track` |

### Where the audio is — a split the format does not enforce

A file entry either carries a disc path or lives inside `FILE`. Nothing forbids
mixing. The data does not mix:

* **12,702 STRM sounds → 12,702 external `.brstm`**, without exception
* **964 WAVE + 330 SEQ sounds → all internal**, without exception
* every one of the 13,222 external paths ends in `.brstm`
* all 13,996 file ids are in range; all 13,996 player ids are in range

`pan_mode` is `1` on every STRM sound and `0` on every WAVE and SEQ sound —
13,996 / 13,996, a clean split along the same line as the storage.

A file entry names the group items that hold it, and a group item names the
file — the back-reference closes on **831 / 831** items, and the file's two
size fields equal the item's two size fields on **831 / 831**.

## FILE — groups, items, waves

A group has a data block and a wave block, contiguous (`data_offset +
data_size == wave_offset` on **168 / 168**), and an item list. There are 168
groups but only 167 names: **group 167 has string id `-1`**, and its wave block
is the one that ends at the last byte of the file.

The 831 items are not all the same kind:

| Item kind | Count | Waves |
|---|---|---|
| `RWSD` | 448 | 2,518 |
| `RSEQ` | 378 | 0 |
| `RBNK` | 5 | 238 |

### The trap: the waves belong to the item, not the group

A group's wave block starts with an `RWAR`, and it is tempting to read that one
`RWAR`'s wave table as the group's waves. It is not. Each *item* has its own
`RWAR` side by side in the block. Reading only the first finds **783** of the
**2,756** waves in the archive and loses the rest silently — the count looks
plausible, so nothing complains.

What catches it is asking a question the wrong count cannot answer: every
`RWSD` note holds an index into a wave table, and under the group reading only
843 of 2,651 of those indices are in range. Under the item reading it is
**2,651 / 2,651**.

### Name to sample, the whole chain

```
sound name
  -> string id -> sound entry
  -> file id   -> file entry
  -> positions -> (group, item)
  -> subNo     -> the item's RWSD wave-sound entry
  -> its note  -> a wave index into the item's own RWAR
  -> RWAV
```

The chain is not merely consistent, it is a bijection. There are 2,651 distinct
`(group, item, subNo)` triples, 2,651 sound placements, and 2,651 `RWSD`
entries — nothing collides and nothing is orphaned. And **all 2,518 waves in
`RWSD` items are reached by a name**, 100%.

The 238 unreached waves are **exactly** the `RBNK` ones: instrument samples a
sequence plays by note number, which no sound id ever names. That partition is
declared nowhere. It falls out at 2,518 / 238 with nothing left over. (238 is
placements, not distinct samples: the five `RBNK` items hold the three banks,
and `SEQBNK_MAP_TW001` is packed into three groups, so 184 distinct instrument
samples appear 238 times.)

## RWAV, and proving the decoder rather than trusting the ear

An `RWAV` is a 0x20 header, an `INFO` section and a `DATA` section. All 2,756
are DSP-ADPCM except one, which is PCM16. Sample rates run from 4 kHz to
48 kHz, with 16 kHz, 14 kHz, 22.05 kHz and 18 kHz the common ones.

Two things in the `INFO` block are easy to get wrong, and both were:

**`loopStart` and `loopEnd` are nibble addresses, not sample counts.** A frame
is 8 bytes = 16 nibbles: the first two are the header byte, the remaining 14
are one sample each. Read as samples, `loopEnd` asks for more bytes than the
wave contains — `SE_VRCOM_ARENA` would need 34,608 bytes of a 30,560-byte wave
— and the decoder runs off the end of the channel into the next one. Two
measurements settle it: `loopEnd / 2` bytes per channel fits inside the `RWAV`
on **2,755 / 2,755** waves, and the frame-header coefficient index, which can
only be 0-7, takes values 11-15 in 552 frames under the sample reading and
**never** under the nibble reading. The impossible values *were* the trailing
garbage.

**The ADPCM info block starts with `gain`.** Sixteen `s16` coefficients, then
`u16 gain`, then `u16 predictor/scale`, `s16 yn1`, `s16 yn2`, then the same
three again for the loop point. Omitting `gain` shifts everything after it by
one `u16`, and the resulting audio still sounds like audio — the error is
inaudible, which is exactly why it needs a check that is not the ear.

The format supplies that check, because the encoder left its own state behind:

| Check | Result |
|---|---|
| `ps` == the first frame's header byte | **2,965 / 2,965** channels |
| `loop_ps` == the header byte of the frame the loop starts in | **457 / 457** |
| decoding forward to the loop reproduces `(loop_yn2, loop_yn1)` | **227 / 227** |

The third is the strong one: the decoder has to agree with the encoder *sample
for sample*, on the exact 16-bit values, after running the full IIR from the
start of the wave. 230 more channels loop at sample 0 and have no history to
compare, and are excluded rather than counted as passes.

## Checked against things that are not the archive

**`LastWorld.rsid.csv`** — the registry the disc ships in the clear. Row *i*
names sound *i* on **13,996 / 13,996**, and the 175 rows after them are exactly
the 3 banks, 5 players and 167 named groups, each restarting its own
numbering. 13,996 + 175 = 14,171.

**The `.brstm` files themselves** — a different file, in a format decoded in
[05](05-audio-brstm.md). The STRM tail declares a channel count; the stream's
own header also declares one. They agree on **12,702 / 12,702**: mono where
mono, stereo where stereo, not one disagreement. And every one of the 12,678
paths in the archive exists on the disc.

## What the archive says that the names do not

The disc has **12,696** `.brstm` and the archive names **12,678**. The
asymmetry only runs one way — nothing is dangling, the filesystem simply has
extras. The 18 unnamed ones are `test1.brstm`, `test_23/25/26.brstm`,
`ev9002bgm.brstm` and `ev9002bgm_18k.brstm`, an 18 kHz variant
`bgm_town001_18k.brstm`, eight `se_vrtwn_*` town ambiences, `se_votwn_181.brstm`,
and two voice lines — `vo_pld004_0280.brstm` and
`vo_pld004_1441.brstm` — that no sound id names and no line of the dialogue
database matches. They shipped and cannot be reached.

**398 STRM sounds play a `.brstm` whose filename is not their name**:
`SYSTR_FANTOM` → `Fantom.brstm`, `SE_EVCOM_000_2` → `FlashBack01.brstm`. Any
mapping built by matching names would get those wrong.

**1,086 sounds named `SE_*` are routed to `PLAYER_VOICE`** — filing by filename
prefix, which is what `audio_decode.py` did, puts them under sound effects. The
authored names agree with the routing once you stop reading only the prefix:
the second token carries it (`SE_VOBT101_004`, `SE_VOTWN…`). Of the 1,093 `SE_*`
names with `VO` in token two, **1,071 (98.0%)** are on `PLAYER_VOICE`; of the
1,574 without it, **15 (0.95%)** are. Two independent sources — what a human
typed and where the runtime sends it — disagree on 37 of 2,667.

Five sound ids point at waves of **0 or 1 sample** (192-byte stubs):
`SE_EM202_005`, `SE_CGCS1_006`, `SE_DG022_004`, `SE_CGGR1_010`,
`SE_EV0510_004`. They are in the retail build.

## Using it

```
python tools/parse_brsar.py --summary
python tools/parse_brsar.py --validate                    # 43 checks, ~2 s
python tools/parse_brsar.py --csv    audio/brsar_sounds.csv
python tools/parse_brsar.py --groups audio/brsar_groups.csv
python tools/parse_brsar.py --extract audio/rwav          # 927 waves + index.csv
```

`--extract` writes the raw `.rwav` and a decoded `.wav` beside it, one per
distinct sound name (`--all-copies` writes every group placement instead), with
an `index.csv` giving the sound names, group, channels, rate, length and loop
point. Five of the 927 produce no `.wav`: those are the empty stubs.

## Still open

* `RSEQ` — 378 sequence items and 330 `SEQ` sounds are located and bounded, but
  the sequence bytecode itself is not read. The three `RBNK` banks and their
  238 instrument samples are the other half of that.
* The `RWSD` wave-sound entry is three references — parameters, track table,
  note table. Only the third is followed, far enough to reach the wave index;
  the pitch/pan block and the track table are read past.
* The 3D block's `flags` field takes four values across the archive — `0`
  (13,428), `15` (563), `1` (4), `9` (1) — and they are not characterised.
