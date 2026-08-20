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
| **Audio** | Standard Nintendo **BRSTM** (DSP-ADPCM); RSTM header decoded; engine sound registry (`rsid`) parsed |
| **Text ↔ Voice** | Dialogue `voiceID` maps 1:1 to stream filename → lines linked to their voice clip (98.7%) |
| **Models** `wii modl` | NW4R-based container reversed; GX display lists, vertex layout solver, skeleton, UVs, materials |
| **Skinning** | Matrix palette (1/2/3-bone tables), the hybrid bone-space/model-space convention, per-mesh POS quantisation, node→mesh binding — models assemble with **no dropped triangles** |
| **Animation** `wii anim` | `.motion` reversed: three track encodings, per-name bone binding, the two loop conventions, 30 fps measured |
| **Maps & scenes** | `.map` → `.locator` → `.building` → `.model` chain composed; a character **walks on a real map**, validated to ±1.6 cm of the floor |
| **Gimmicks** `.gmk` | The interaction system as data: `STATE`/`TRIGGER` machine and `MOTCMD` commands anchored to animation frames |
| **Areas** `.area` | Per-volume environment overrides (AABB proven twice); `SET_AREA` is visibility partitioning, not loading |
| **Collision** `.hocb`/`.hcb` | Both reversed: self-relative offsets, triangle records (72 B / 68 B), the **octree validated on 253,447 nodes**, a scene graph in `.hcb`, and the **surface type** joined to the game's 33-row material table |
| **`main.dol` class names** | RTTI survived the symbol strip: **704 C++ class names with their vtables**, incl. 60+ named `AI::Script::*` behaviours |
| **Effects** `.efp`/`.effconfig`/`.eff` | Whole group decoded: XML sequencer (effects attach to the skeleton **by bone name**, verified against 4,691 models), area presets, and the particle binary — **little-endian**, with curves keyed over normalised lifetime (100 % on 36,705 curves). The engine's own **loader and its layout schemas** have since been located in `main.dol`, confirming the record sizes from code |
| **`main.dol`** | Loaded in Ghidra via a custom DOL loader; 14,530 functions; boot call-graph reconstructed. **Caveat measured**: Ghidra's stock PowerPC has no Gekko paired-singles, so it sees only **44 %** of the text |
| **Debug menu** | Present in retail but deliberately unlinked at the linker level (diagnosed) |

Full details are in [`docs/`](docs/).

## What is *not* solved

Kept here deliberately, because a format note is only useful if it says where it
stops:

- **The `.hocb` material bitfield at `+0x04`.** Undecoded (max `0x40014`). Its
  neighbour at `+0x00` *is* solved — it is the surface type — so this one most
  likely carries per-volume behaviour instead. The `.hcb` "type" field remains
  demonstrably *not* a surface type.
- **The 22 `.eff` curve channels.** Curves are decoded, their keying is proven,
  and the engine's loader confirms there are exactly 22 — but which channel
  drives which visual parameter is still unknown. Pairing them with static
  emitter parameters was tested and **ruled out**; the loader declares field
  *widths*, not meanings. The answer is in the particle simulation, and that
  code is **paired-single Gekko** which Ghidra cannot disassemble — see the
  blind-spot section in [07](docs/07-main-dol-ghidra.md). A Gekko SLEIGH
  language for Ghidra is the unblocking step.
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

The natural next step for several of these is `main.dol` itself: the `.eff`
reader is the most promising target, since a little-endian format on a
big-endian machine must leave a visible byteswap or a distinct load path. The
DOL is now a far better place to look than it was, because it turns out to
still carry its **C++ class names** — see [18](docs/18-dol-classes.md).

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
| [14 — Collision](docs/14-collision.md) | `.hocb` binary, self-relative offsets, the 72-byte triangle record, the octree |
| [15 — Collision (`.hcb`)](docs/15-collision-hcb.md) | Gimmick collision: the 68-byte record, the scene graph, and the relocation table that proves the layout |
| [16 — Effects](docs/16-effects.md) | `.efp` XML sequencer, bone-name attachment proven against the skeletons, `.effconfig` area presets |
| [17 — `.eff` binary](docs/17-eff-binary.md) | The particle definition: little-endian, emitters and materials, curves keyed over normalised lifetime |
| [18 — DOL class names](docs/18-dol-classes.md) | RTTI survived the strip: 704 C++ class names and their vtables, recovering named functions |

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
| `walk_poc.py` | A character walking on a real map: ground raycast + driven root motion |
| `parse_gmk.py` | `.gmk` gimmicks: state machine, `MOTCMD` timeline, cross-references |
| `parse_area.py` | `.area` per-volume environment overrides and `SET_AREA` visibility |
| `parse_hocb.py` | `.hocb` map collision: triangle soup, octree, materials, ground query |
| `parse_hcb.py` | `.hcb` gimmick collision: 68-byte triangles, scene graph, relocation check |
| `parse_colli_attr.py` | Surface types: joins the `.hocb` material id to the game's own `colli_attr_table.csv` |
| `dol_classes.py` | Recovers C++ class names and vtables from `main.dol`'s surviving RTTI |
| `dol_swap_schema.py` | Decodes the endian-fixup schemas the `.eff` loader uses — the format's layout, declared by the binary |
| `dol_disasm.py` | Gekko-tolerant partial disassembler, plus `--coverage`: measures how much of the DOL Ghidra silently misses |
| `parse_efp.py` | `.efp` effect sequencer + `.effconfig` presets; bone-attachment cross-check |
| `parse_eff.py` | `.eff` particle binary: emitters, materials, lifetime-keyed curves |
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
