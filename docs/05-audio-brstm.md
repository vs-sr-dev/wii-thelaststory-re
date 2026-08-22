# 05 — Audio (BRSTM) & the text↔voice loop

The `12,696 .brstm` files in `files/sound/stream/` are **standard Nintendo
BRSTM** streams: magic `RSTM`, BOM `FE FF`, codec `02` = 4-bit **DSP-ADPCM**.
There is no custom variant here — any BRSTM tool decodes them.

## RSTM header (decoded)

Metadata can be read directly from the header without spawning a decoder — this
is how the full manifest of all 12,696 streams is built cheaply
(`tools/rstm_info.py`):

```
0x00  'RSTM'
0x04  BOM (FE FF)
0x08  file size (u32)
0x10  HEAD chunk offset (u32)     -> head_off
HEAD @ head_off:
  +0x00 'HEAD' + size
  +0x08 three references (8 bytes each: marker u8=0x01, 3 pad, offset u32
        relative to head_off+0x08)
  first reference -> block1 (stream info):
     +0x00 codec  u8   (0=PCM8, 1=PCM16, 2=DSP-ADPCM)
     +0x01 loop   u8
     +0x02 chans  u8
     +0x03 pad
     +0x04 sample_rate   u16
     +0x08 loop_start    u32 (samples)
     +0x0C total_samples u32 (samples)
```

Every field was verified against `vgmstream-cli -m` (e.g. a battle track reads
32000 Hz / loop_start 917504 / total 3080266 — exact match).

## Inventory

Total: **17h48m of audio, ~1.4 GB**.

| Macro | Files | Duration | Notes |
|---|---|---|---|
| `VO_` voices | 10,960 | 8h51m | mono 22050 Hz, no loop — the voice acting |
| `SE_` sfx / voice-sfx | 1,363 | 1h55m | battle/town shouts |
| `BGM_` music | 74 | 2h39m | stereo 32000 Hz, **with loop points** |
| `ev*` event streams | 299 | 4h23m | cutscene audio |

`tools/build_audio_manifest.py` emits a CSV with codec/rate/channels/loop/
duration for every stream.

## The engine sound registry — `LastWorld.rsid.csv`

`files/sound/LastWorld.rsid.csv` is the engine's **sound registry**: 14,171 rows
of `NAME,rsid_index,sub_index,flag` mapping the symbolic name the code requests
(e.g. `BGM_BATT101`, `VO_PLD001_0010`) to the global numeric ID the engine
addresses it by. Categories: VO 10,963 · SE 2,667 · STRM 285 · GROUP 167 · BGM
78 · PLAYER/SYSTR/SEQBNK.

A useful finding: bare names such as `BGM_FILD012`, `BGM_JNGL001`, `SE_EVCOM_*`
are **not** streams — they live in `lastworld.brsar` (the sequenced/sample bank),
whereas all `VO_` entries are streamed. (The `flag` column is set on 2,114 rows
but correlates only weakly with streaming; its exact meaning is unconfirmed.)
Parser: `tools/parse_rsid.py`.

## Closing the text↔voice loop

The dialogue `voiceID` (e.g. `VO_PLD001_0010`) is **literally** the `.brstm`
filename, so linking text to voice needs no extra table:
`tools/link_voices.py` walks the dialogue database and attaches each spoken line
to its clip. Result: **7,717 voiced lines, 98.7% resolved** to a stream (the ~64
misses are `SE_VOTWN_*` / `SE_VOBT_*` voice-sfx that live in the `brsar`).

## Decoding to WAV/OGG

`tools/audio_decode.py` wraps [vgmstream](https://vgmstream.org/) — parallel,
resumable, and able to pipe `vgmstream -p | ffmpeg` straight to OGG Vorbis with
no intermediate WAV:

```
python tools/audio_decode.py --cat VO  --fmt ogg      # voices
python tools/audio_decode.py --cat BGM --fmt wav      # music, single clean pass
python tools/audio_decode.py --cat all --fmt ogg -j 12
```

Looped BGM/EV are rendered as a single clean pass (`-i`); the loop points remain
in the manifest for anyone reconstructing seamless playback.

`tools/build_dialogue_browser.py` then generates a **local, standalone HTML
browser** that shows each line with its 6-language text and an inline play button
for the voice clip — a text+voice reading of the whole script, built from your
own extraction.

---

**Update (23).** The `.brsar` has since been opened — see
[23 — The sound archive](23-brsar.md). It supersedes name matching as the way
to find a sound's audio: 398 sounds play a `.brstm` that is not named after
them, and 1,086 sounds named `SE_*` are routed to `PLAYER_VOICE` rather than
the sound-effect player. It also closes the 104 dialogue lines this document
could not hook: 23 were matchable (21 differed only in letter case), and the
remaining 81 reference voiceIDs that do not exist in the archive at all.

