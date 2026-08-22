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
confirmed against the disassembly, and the text / texture / audio / geometry
pipelines are documented with working extractors. Highlights:

| Area | Result |
|---|---|
| **Pack format** `.pfs/.pkh/.pk` | Reversed; LZ11 decompression; **path hash = CRC-32/BZIP2**, confirmed in `main.dol` |
| **Text & dialogue** | UTF-16BE plaintext; 6-language script structure (JP/EN/FR/DE/ES/IT) |
| **Textures** | GX container `chnkdata`; all formats (CMPR, IA4/8, RGB5A3, RGB565, I4/8, RGBA8) decoded |
| **Audio** | **BRSTM** streams and the whole `lastworld.brsar` archive: 13,996 sound ids bound to audio, 2,756 internal waves, sequence bytecode and instrument banks |
| **Text ↔ Voice** | Dialogue `voiceID` resolved through the sound archive → **98.95%** of 7,717 voiced lines linked to their clip; the remaining 81 are proven to be cut content |
| **Models** `wii modl` | NW4R-based container reversed; GX display lists, vertex layout solver, skeleton, UVs, materials |
| **Skinning** | Matrix palette (1/2/3-bone tables), the hybrid bone-space/model-space convention, per-mesh POS quantisation, node→mesh binding — models assemble with **no dropped triangles** |
| **Animation** `wii anim` | `.motion` reversed: three track encodings, per-name bone binding, the two loop conventions, 30 fps measured |
| **Maps & scenes** | `.map` → `.locator` → `.building` → `.model` chain composed; a character **walks on a real map**, validated to ±1.6 cm of the floor |
| **Gimmicks** `.gmk` | The interaction system as data: `STATE`/`TRIGGER` machine and `MOTCMD` commands anchored to animation frames |
| **Areas** `.area` | Per-volume environment overrides (AABB proven twice); `SET_AREA` is visibility partitioning, not loading |
| **Collision** `.hocb`/`.hcb` | Both reversed: self-relative offsets, triangle records (72 B / 68 B), the **octree validated on 253,447 nodes**, a scene graph in `.hcb`, the **surface type** joined to the game's 33-row material table, and the `+0x04` word decoded as a **query exclusion mask** (collision layers) |
| **`main.dol` class names** | RTTI survived the symbol strip: **704 C++ class names with their vtables**, incl. 60+ named `AI::Script::*` behaviours |
| **Effects** `.efp`/`.effconfig`/`.eff` | Whole group decoded: XML sequencer (effects attach to the skeleton **by bone name**, verified against 4,691 models), area presets, and the particle binary — **little-endian**, with curves keyed over normalised lifetime (100 % on 36,705 curves). The engine's own **loader and its layout schemas** have since been located in `main.dol`, confirming the record sizes from code |
| **`main.dol`** | Loaded in Ghidra via a custom DOL loader; boot call-graph reconstructed. Ghidra's stock PowerPC has no Gekko paired-singles and saw only **44 %** of the text — installing a **Gekko SLEIGH** language took that to **97.6 %** and 15,955 functions, which is what unblocked the effect channels |
| **Effect curve channels** | All 22 identified and grouped, with the `A × 4` table at `+0x28` decoded as the **bitmask of which groups are keyed** — checked **77,733 / 77,733** against the shipped data |
| **Sound archive** `.brsar` | The last large container opened: 14,171 names in four patricia trees (**14,171/14,171** lookups), 13,996 sound ids bound to audio, 2,756 internal waves reached through group items, and a DSP-ADPCM decoder that reproduces the encoder's saved loop state **227/227** |
| **Sequences & banks** `RSEQ`/`RBNK` | The archive closed: sequence bytecode read against its own plain-text labels (**898/898** tracks decode to their terminator, **572/572** jumps land on a named track), and three instrument banks whose programs cover **exactly** their own waves |
| **Checked against the running game** | The first external validation: dumped textures caught **two decoder errors** (CMPR interpolation is 5/8-3/8, not thirds; I4/I8 put intensity in alpha), and a FIFO log decodes **555,010 / 555,010** bytes of GX commands with **175/175** array references matching `parse_model` |
| **Debug menu** | Present in retail but deliberately unlinked at the linker level (diagnosed) |

Full details are in [`docs/`](docs/).

## What is *not* solved

Kept here deliberately, because a format note is only useful if it says where it
stops:

- ~~**The `.hocb` material bitfield at `+0x04`.**~~ — **answered.** It is a
  **query exclusion mask** (collision layers): a query passes a mask of
  categories to ignore and any triangle whose word intersects it is skipped. It
  never described the surface, which is why three data-side readings of it came
  back empty. `+0x00` also turns out to double as a query filter. See
  [14](docs/14-collision.md). **Still open: what each bit is called** — the
  masks are constants at indirect (vtable) call sites.
- **The `.hcb` "type" field** remains demonstrably *not* a surface type, and
  still unexplained.
- ~~**The 22 `.eff` curve channels.**~~ — **answered.** A Gekko SLEIGH language
  ([19](docs/19-gekko-sleigh.md)) made the particle simulation readable, and the
  channels resolve into 8 groups selected by a 9-bit mask — colour RGBA, scale,
  two rotations, emitter displacement, and three groups still unnamed. Verified
  **77,733 / 77,733** against the data. See [20](docs/20-eff-channels.md).
- ~~**What channels 7–9 actually drive.**~~ — **answered: the particle's
  velocity.** A field-level cross reference ([22](docs/22-field-xref.md)) found
  the readers of `particle+0x98`, and the update integrates the position by it,
  then applies gravity, a floor test, a bounce, friction and a rolling angle
  `s/r` — seven fields at the tail of the emitter record whose authoring
  defaults name them (restitution 0.7, friction 0.1, roll gain exactly 1.0).
  Backed from the data alone by the emitters that key it (`火花` sparks, `石`
  stones, `土煙` dust, ~5× the base rate) and by which component decays.
  See [20](docs/20-eff-channels.md).
- **What channels 18 and 10–11 drive.** Still open, and now known to be out of
  reach of the same technique: both are written by the update and read by
  nothing whose base can be resolved.
- ~~**Where the effect colour is divided by 255.**~~ — **answered: nowhere.**
  The engine holds colour as a float and multiplies by 255 with `fctiwz` when it
  writes the vertex, in the effect module's draw function (found by asking which
  functions write the GX FIFO). The only two uses of 1/255 in that module are an
  invisible-particle threshold. See [20](docs/20-eff-channels.md).
- **`.gmk` `TRIGGER` types 2–6** and the `PATH_POINT` opcode: seen, counted, not
  interpreted.
- **The `.hocb` `0x003` tail.** Present in every file, parsed as bytes, unread.
- ~~**`levels/` and `eventpacks/`**~~ — **answered.** The 2052 nested packs hold
  no `.pfs`, but their names are recoverable by hashing: **100 %** of their
  19,703 distinct hashes are paths that already exist in `filesystem`, and a
  400-entry sample is **100 %** byte-identical to it. They are per-level
  duplication for streaming locality, so they cannot explain any dangling
  reference — those assets are simply absent from the disc. See
  [02](docs/02-pack-format.md).

The natural next step for several of these is `main.dol` itself, which is now a
far better place to look than it was: it still carries its **C++ class names**
([18](docs/18-dol-classes.md)), and with a Gekko processor language installed
Ghidra reads **97.6 %** of its code instead of 44 %
([19](docs/19-gekko-sleigh.md)). Its C++ *indirect* calls are now readable too:
an abstract interpreter recovers the object and the slot at each virtual call
site, which gives thousands of its functions a class and a member layout for the
classes that own one ([21](docs/21-indirect-calls.md)). The same interpreter now
also answers *who reads offset N of a struct* — the question a decompiler cannot
ask, because a struct member is not something the binary records
([22](docs/22-field-xref.md)).

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
| [08 — Models & geometry](docs/08-models-geometry.md) | `wii modl` chunks, GX display lists, vertex layout, skeleton, `.material`/`.lip` |
| [09 — Skinning](docs/09-skinning.md) | Matrix palette, bone-space vs model-space, POS quantisation, node→mesh binding |
| [10 — Animation](docs/10-animation.md) | `wii anim` curves, Hermite tracks, the two loop conventions, 30 fps, in-place locomotion |
| [11 — Maps & scenes](docs/11-maps-and-scenes.md) | `.map`/`.locator`/`.building`/`.chr`, f32 map geometry, instancing, walking on a map |
| [12 — Gimmicks](docs/12-gimmicks.md) | `.gmk` interactive objects, the `STATE`/`TRIGGER` machine, `MOTCMD` animation-timeline scripting |
| [13 — Areas](docs/13-areas.md) | `.area` per-volume environment overrides, the proven AABB layout, `SET_AREA` visibility partitioning |
| [14 — Collision](docs/14-collision.md) | `.hocb` binary, self-relative offsets, the 72-byte triangle record, the octree, and the exclusion-mask bits for water, unstandable terrain and invisible walls |
| [15 — Collision (`.hcb`)](docs/15-collision-hcb.md) | Gimmick collision: the 68-byte record, the scene graph, and the relocation table that proves the layout |
| [16 — Effects](docs/16-effects.md) | `.efp` XML sequencer, bone-name attachment proven against the skeletons, `.effconfig` area presets |
| [17 — `.eff` binary](docs/17-eff-binary.md) | The particle definition: little-endian, emitters and materials, curves keyed over normalised lifetime |
| [18 — DOL class names](docs/18-dol-classes.md) | RTTI survived the strip: 704 C++ class names and their vtables, recovering named functions |
| [19 — A Gekko SLEIGH for Ghidra](docs/19-gekko-sleigh.md) | Teaching Ghidra the Wii's paired-single instructions: 44 % → 97.6 % of the text, with the before/after measurement |
| [20 — The 22 `.eff` channels](docs/20-eff-channels.md) | The curve evaluator, the group bitmask at `+0x28`, and the 77,733/77,733 check that proves the map |
| [21 — Resolving the indirect calls](docs/21-indirect-calls.md) | Reading the register file instead of grepping bytes: virtual call sites, recovered object layouts, 5,401 functions given a class |
| [22 — Who reads offset N of a struct?](docs/22-field-xref.md) | The field-level cross reference: recovered struct usages, the small-data float pool, and the two interpreter defects it exposed |
| [23 — The sound archive](docs/23-brsar.md) | `lastworld.brsar`: name trees, the six INFO tables, the chain from a sound id to a sample, and a DSP decoder proved against the encoder's own loop state |
| [24 — Sequences and banks](docs/24-rseq-rbnk.md) | `RSEQ` and `RBNK`: plain-text labels that prove the bytecode, the opcode table derived from 898 clean decodes, and the instrument banks that reach the last 184 waves |
| [25 — Differential testing](docs/25-differential-testing.md) | The first check against the game actually running: dumped textures, a FIFO log, and the CP registers cross-referenced with `parse_model` |

## Tools

Small, mostly zero-dependency Python (3.8+). See [`tools/`](tools/) and
[REPRODUCING.md](REPRODUCING.md) for how to run them against your own extraction.

| Tool | Purpose |
|---|---|
| `lwpack.py` | Pack (`.pfs/.pkh/.pk`) parser + LZ11 + CRC path-hash |
| `extract_all.py` | Rebuild manifests by hash and extract every pack |
| `parse_nested_packs.py` | The 2052 nameless packs inside `levels/`/`eventpacks/`: names them by hash, proves they are duplicates |
| `lwextract.c` | Standalone LZ11 decompressor (C) |
| `gxtex.py`, `batch_tex.py` | GX texture decoder → PNG (all formats) |
| `rstm_info.py` | BRSTM/RSTM header parser (no subprocess) |
| `parse_rsid.py` | Engine sound registry (`LastWorld.rsid.csv`) parser |
| `build_audio_manifest.py` | Manifest of every stream (codec/rate/loop/duration) |
| `audio_decode.py` | Batch BRSTM → WAV/OGG (wraps vgmstream, parallel, resumable) |
| `build_dialogue_db.py` | Build the consolidated 6-language dialogue database |
| `link_voices.py` | Link each dialogue line to its voice clip |
| `build_dialogue_browser.py` | Generate a local text+voice HTML browser |
| `parse_model.py` | `.model` (`wii modl`) structural parser; `--skeleton` for the bone tree |
| `skeleton.py` | Rebuilds world bind matrices from the node TRS; can dump the skeleton as OBJ |
| `skinning.py` | Matrix palette, node→mesh table, per-part AABB, POS quantisation solver |
| `export_obj.py` | `.model` → OBJ + MTL, assembled in model space and textured |
| `render_obj.py` | Tiny software renderer for the exported OBJ (needs `numpy`, `pillow`) |
| `parse_material.py` | `.material` parser — the mesh ↔ texture bridge |
| `parse_lip.py` | `.lip` lip-sync parser — the mesh ↔ audio bridge |
| `motion.py` | `.motion` (`wii anim`) parser, curve evaluation, world & skinning matrices |
| `loop_closure.py` | Per-file loop convention test (does the last frame repeat the first?) |
| `gait.py`, `gait_period.py` | Root drift, implied step speed, cycle period — all in world space |
| `render_anim.py` | Animated skinned render → GIF or frame strip |
| `parse_map.py` | `.map` scene bill of materials |
| `parse_locator.py` | `.locator` (`wii loct`) prop instances: name, TRS, lightmap tile |
| `parse_building.py` | `.building` prop recipe (model + material + LODs) |
| `parse_chr.py` | `.chr`/`.mchr` character definition and animation state machine |
| `build_scene.py` | Compose a whole map (terrain + instanced props) into one OBJ |
| `dolphin_texdiff.py` | Dumped textures from a real run vs our decoder, pixel for pixel (incl. mip levels) |
| `parse_dff.py` | Dolphin FIFO log container: registers, frames, memory updates |
| `dff_match.py` | The log's RAM blocks vs the extracted textures — byte identity, disc to running game |
| `dff_vertex_match.py` | The log's vertex blocks vs the `.model` files; measures each file's load address |
| `fifo_decode.py` | Decode the GX command stream; the criterion is landing exactly at the end |
| `fifo_model_xref.py` | CP array registers vs `parse_model`'s `strm` chunks: offset and stride, from three independent sources |
| `walk_poc.py` | A character walking on a real map: ground raycast + driven root motion |
| `parse_gmk.py` | `.gmk` gimmicks: state machine, `MOTCMD` timeline, cross-references |
| `parse_area.py` | `.area` per-volume environment overrides and `SET_AREA` visibility |
| `parse_hocb.py` | `.hocb` map collision: triangle soup, octree, materials, ground query |
| `parse_hcb.py` | `.hcb` gimmick collision: 68-byte triangles, scene graph, relocation check |
| `parse_colli_attr.py` | Surface types: joins the `.hocb` material id to the game's own `colli_attr_table.csv` |
| `colli_flags.py` | The material word at `+0x04` as a query exclusion mask, read from the DOL; `--vocab` cross-checks `.hocb` against `.hcb` |
| `dol_classes.py` | Recovers C++ class names and vtables from `main.dol`'s surviving RTTI |
| `dol_swap_schema.py` | Decodes the endian-fixup schemas the `.eff` loader uses — the format's layout, declared by the binary |
| `dol_disasm.py` | Gekko-tolerant partial disassembler, plus `--coverage`: measures how much of the DOL Ghidra silently misses |
| `parse_efp.py` | `.efp` effect sequencer + `.effconfig` presets; bone-attachment cross-check |
| `parse_eff.py` | `.eff` particle binary: emitters, materials, lifetime-keyed curves |
| `eff_channels.py` | What the 22 curve channels drive, read out of `main.dol`; `--proof` re-runs the 77,733-check against the data, `--physics` the bounce/friction/roll block |
| `eff_channels.py --tab40` | The third `A × 4` table: which channel groups are inert, 38,105/38,105 |
| `field_xref.py` | Who reads offset N of a struct: recovered struct usages over the whole text, plus the small-data float pool (`--consts`) |
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
