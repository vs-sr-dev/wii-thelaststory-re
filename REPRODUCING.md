# Reproducing the results

Every result in this repository can be regenerated **from your own legal copy of
the game**. No game data is distributed here; you supply the disc.

## Prerequisites

- **Python 3.8+** (the tools are mostly standard-library only)
- **[wit](https://wit.wiimm.de/)** (Wiimms ISO Tools) — to extract the disc
- **[vgmstream-cli](https://vgmstream.org/)** — only for audio decoding
- **ffmpeg** — only for OGG output in `audio_decode.py`
- **[Ghidra](https://ghidra-sre.org/) 12.x** — only for the `main.dol` analysis
- A C compiler (e.g. gcc/mingw) — only if you want the faster `lwextract.c`

Assumed layout (paths in the tools are relative to a project root that contains
the extraction; adjust as needed):

```
<root>/
  extract/            wit output (files/, sys/, …)
  Wii-TheLastStory/   this repo (tools/, docs/)
```

## 1. Extract the disc

```
wit extract "The Last Story.iso" extract --psel data
```

You should get `extract/files/`, `extract/sys/main.dol`, etc.
See [docs/01](docs/01-disc-structure.md).

## 2. Unpack the archives

```
python tools/extract_all.py
```

Rebuilds each pack's manifest **by hash** and extracts all packs to `assets/`.
The hash is CRC-32/BZIP2 over the lower-cased path — see
[docs/02](docs/02-pack-format.md). For a single pack or ad-hoc inspection use
`tools/lwpack.py`. To decompress a raw LZ11 blob in C, build `lwextract.c`.

## 3. Build the dialogue database

```
python tools/build_dialogue_db.py
```

Produces the consolidated 6-language dialogue tables. See
[docs/03](docs/03-text-dialogue.md).

## 4. Decode textures

```
python tools/batch_tex.py all
```

GX → PNG for all formats. See [docs/04](docs/04-textures-gx.md).

## 5. Audio

```
# manifest of every stream (no external tools needed)
python tools/build_audio_manifest.py

# engine sound registry
python tools/parse_rsid.py

# decode to OGG (needs vgmstream-cli on PATH, or set VGMSTREAM_CLI)
python tools/audio_decode.py --cat VO  --fmt ogg
python tools/audio_decode.py --cat all --fmt ogg -j 12

# link each dialogue line to its voice clip, then build the HTML browser
python tools/link_voices.py
python tools/build_dialogue_browser.py
```

`audio_decode.py` finds vgmstream via the `VGMSTREAM_CLI` environment variable,
falling back to `vgmstream-cli` on `PATH`. See [docs/05](docs/05-audio-brstm.md).

## 6. Analyse `main.dol` in Ghidra

Load `main.dol` with the Java loader script, then run the reports:

```
analyzeHeadless <proj_dir> LastWorld -import extract/sys/main.dol \
  -postScript DolLoad.java -postScript DolReport.java \
  -scriptPath tools/ghidra_scripts
```

See [docs/07](docs/07-main-dol-ghidra.md).

---

**Note on outputs.** The generated tables and media (`assets/`, `audio/`,
`textures_png/`, dialogue DB, manifests) contain copyrighted game content and are
**excluded by `.gitignore`** — they are yours to generate locally, not to
redistribute.
