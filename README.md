# The Last Story (Wii) — Reverse Engineering Notes

Format documentation and tooling for the internal **"LastWorld"** engine of
**The Last Story** (Mistwalker / AQ Interactive / Feelplus, 2011), the Wii JRPG
directed by Hironobu Sakaguchi with music by Nobuo Uematsu.

This is a **didactic reverse-engineering** project: it documents the container,
text, texture and audio formats of the game and provides clean, dependency-light
tools to parse them. As far as I have been able to verify, **no public
reverse-engineering material existed for this title** — no format notes, no
extraction tools, no dialogue database. This repository aims to fill that gap.

> ### ⚠️ Disclaimer
> **No game asset is included in this repository.** It contains only original
> source code and documentation. The tools operate on files extracted from a
> disc that **you must legally own**. "The Last Story", its code and all its
> assets (text, voice, music, artwork) are the property of their respective
> rights holders. This work is published for **interoperability, preservation
> research and education**. Nothing here redistributes copyrighted content.

---

## Status

The asset container is fully reversed, the path-hash function was cracked and
confirmed against the disassembly, and the text / texture / audio pipelines are
documented with working extractors. Highlights:

| Area | Result |
|---|---|
| **Pack format** `.pfs/.pkh/.pk` | Reversed; LZ11 decompression; **path hash = CRC-32/BZIP2**, confirmed in `main.dol` |
| **Text & dialogue** | UTF-16BE plaintext; 6-language script structure (JP/EN/FR/DE/ES/IT) |
| **Textures** | GX container `chnkdata`; all formats (CMPR, IA4/8, RGB5A3, RGB565, I4/8, RGBA8) decoded |
| **Audio** | Standard Nintendo **BRSTM** (DSP-ADPCM); RSTM header decoded; engine sound registry (`rsid`) parsed |
| **Text ↔ Voice** | Dialogue `voiceID` maps 1:1 to stream filename → lines linked to their voice clip (98.7%) |
| **`main.dol`** | Loaded in Ghidra via a custom DOL loader; 14,530 functions; boot call-graph reconstructed |
| **Debug menu** | Present in retail but deliberately unlinked at the linker level (diagnosed) |

Full details are in [`docs/`](docs/).

## Documentation

| Doc | Topic |
|---|---|
| [01 — Disc structure](docs/01-disc-structure.md) | Partition layout, where the real assets live |
| [02 — Pack format](docs/02-pack-format.md) | `.pfs/.pkh/.pk`, LZ11, the CRC path-hash (cracked) |
| [03 — Text & dialogue](docs/03-text-dialogue.md) | UTF-16BE CSVs, the 6-language dialogue schema, internal codenames |
| [04 — Textures (GX)](docs/04-textures-gx.md) | `chnkdata` container, GX tiled formats, decoder |
| [05 — Audio (BRSTM)](docs/05-audio-brstm.md) | RSTM header, `rsid` registry, text↔voice linkage |
| [06 — Debug menu](docs/06-debug-menu.md) | The retail debug menu and why it can't boot |
| [07 — main.dol in Ghidra](docs/07-main-dol-ghidra.md) | DOL loader, boot call-graph, hash confirmation |

## Tools

Small, mostly zero-dependency Python (3.8+). See [`tools/`](tools/) and
[REPRODUCING.md](REPRODUCING.md) for how to run them against your own extraction.

| Tool | Purpose |
|---|---|
| `lwpack.py` | Pack (`.pfs/.pkh/.pk`) parser + LZ11 + CRC path-hash |
| `extract_all.py` | Rebuild manifests by hash and extract every pack |
| `lwextract.c` | Standalone LZ11 decompressor (C) |
| `gxtex.py`, `batch_tex.py` | GX texture decoder → PNG (all formats) |
| `rstm_info.py` | BRSTM/RSTM header parser (no subprocess) |
| `parse_rsid.py` | Engine sound registry (`LastWorld.rsid.csv`) parser |
| `build_audio_manifest.py` | Manifest of every stream (codec/rate/loop/duration) |
| `audio_decode.py` | Batch BRSTM → WAV/OGG (wraps vgmstream, parallel, resumable) |
| `build_dialogue_db.py` | Build the consolidated 6-language dialogue database |
| `link_voices.py` | Link each dialogue line to its voice clip |
| `build_dialogue_browser.py` | Generate a local text+voice HTML browser |
| `rso_parse.py`, `rso_reloc.py`, `elfhash_search.py` | RSO/`.sel` module parsing & symbol hashing |
| `ghidra_scripts/` | Java Ghidra scripts: DOL loader, reports, decompile |

## Repository layout

```
docs/            format documentation (start here)
tools/           parsers, decoders, extractors
REPRODUCING.md   how to reproduce every result from your own disc
LICENSE          MIT — covers the code/docs only
.gitignore       blocks every kind of game asset from ever being committed
```

## Reproducing

You need your own legal copy of the game. See **[REPRODUCING.md](REPRODUCING.md)**
for the full pipeline (extraction → packs → text/texture/audio).

## Acknowledgements

To the original developers at Mistwalker, AQ Interactive and Feelplus, and to
the Operation Rainfall campaign that helped bring the game west. This project is
a study of their engineering, made out of respect for it.

## License

Code and documentation: **MIT** (see [LICENSE](LICENSE)). No rights are granted
to any game asset.
