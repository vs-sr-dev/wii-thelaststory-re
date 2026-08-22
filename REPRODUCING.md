# Reproducing the results

Every result in this repository can be regenerated **from your own legal copy of
the game**. No game data is distributed here; you supply the disc.

## Prerequisites

- **Python 3.8+** (the tools are mostly standard-library only)
- **[wit](https://wit.wiimm.de/)** (Wiimms ISO Tools) — to extract the disc
- **[vgmstream-cli](https://vgmstream.org/)** — only for audio decoding
- **ffmpeg** — only for OGG output in `audio_decode.py`
- **[Ghidra](https://ghidra-sre.org/) 12.x** — only for the `main.dol` analysis
- **numpy** and **pillow** — only for `render_obj.py` (the model preview)
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

## 6. Models and geometry

```
# structure of a model, and its bone tree
python tools/parse_model.py assets/.../model/an008_00.model
python tools/parse_model.py assets/.../model/an008_00.model --skeleton

# skinning palette + the POS quantisation resolved for each mesh
python tools/skinning.py assets/.../model/an008_00.model

# export to OBJ + MTL, assembled in model space and textured
python tools/export_obj.py assets/.../model/an008_00.model an008.obj

# optional visual check (needs numpy + pillow)
python tools/render_obj.py an008.obj an008.png --no-cull
```

`export_obj.py` resolves textures against `textures_png/`, so run step 4 first
if you want a textured result. Add `--raw` to skip the assembly step and see
the quantised positions untouched. See [docs/08](docs/08-models-geometry.md) and
[docs/09](docs/09-skinning.md).

The plaintext bridges can be read on their own:

```
python tools/parse_material.py assets/.../material/an008_00.material --textures
python tools/parse_lip.py      assets/.../lip/VO_EV0101_010.lip --csv
```

## 7. Analyse `main.dol` in Ghidra

Load `main.dol` with the Java loader script, then run the reports:

```
analyzeHeadless <proj_dir> LastWorld -import extract/sys/main.dol \
  -postScript DolLoad.java -postScript DolReport.java \
  -scriptPath tools/ghidra_scripts
```

See [docs/07](docs/07-main-dol-ghidra.md).

**Do the Gekko step first — it is worth more than everything else here.**
Without a Gekko processor language Ghidra decodes 44 % of this binary; with one,
97.6 %. Install it, re-import with `-processor PowerPC:BE:32:Gekko_Broadway`,
and check the result with

```
python tools/dol_disasm.py --coverage <your_ghidra_out>/functions.txt
```

The recipe and the before/after numbers are in
[docs/19](docs/19-gekko-sleigh.md).

---

**Note on outputs.** The generated tables and media (`assets/`, `audio/`,
`textures_png/`, dialogue DB, manifests) contain copyrighted game content and are
**excluded by `.gitignore`** — they are yours to generate locally, not to
redistribute.

## 10. Differential testing against Dolphin

The only step that needs the game *running*. See
[docs/25](docs/25-differential-testing.md).

1. In Dolphin, enable `Graphics > Advanced > Dump Textures`, and set
   `SafeTextureCacheColorSamples = 0` in `GFX.ini` so hashes cover the whole
   texture. Boot the game and play for a few minutes.
2. For the geometry test, stop in a scene and use
   `Tools > FIFO Player > Record`, 1 frame, then Save as `fifo.dff`.

```
set TLS_DUMP=<Dolphin user dir>/Dump/Textures/SLSP01
python tools/dolphin_texdiff.py
python tools/parse_dff.py fifo.dff
python tools/dff_match.py fifo.dff
python tools/fifo_decode.py fifo.dff
python tools/fifo_model_xref.py fifo.dff
```

`fifo_decode.py` is the load-bearing one: it must report 100% of the stream
decoded. Anything less means the vertex descriptor or a VAT is being read
wrongly.
