# 01 — Disc structure

The disc analysed is the European release, **SLSP01**, PAL Multi-5
(En/Fr/De/Es/It), dual-layer (~8.1 GiB), IOS56, System Menu 4.3E. Internal build
**2350**, timestamped `Nov 25 2011 14:46:33`.

The game data lives in the `DATA` partition, whose filesystem root (`files/`)
holds **12,999 files**. Main categories:

| Path | Contents | Notes |
|---|---|---|
| `sys/main.dol` | PowerPC executable | ~8.1 MB, RVL_SDK + CodeWarrior |
| `files/pack/` | 3 mega-archives | `filesystem` (~47k files), `levels`, `eventpacks` |
| `files/preload/` | 18 preload archives | `boot`, `title00`–`title08`, `change_dg`, … |
| `files/sound/` | 12,696 `.brstm` + `lastworld.brsar` (82 MB) | standard Wii streaming audio |
| `files/movie/` | 68 `.thp` (~1.98 GB) | Nintendo THP video |
| `files/data/shader/` | 76 `.shader` | plaintext |

## Key point: the real assets are inside the packs

The disc filesystem is mostly a thin outer layer. The actual game content —
models, textures, animations, dialogue, tables — is stored **inside the pack
archives** (`.pfs` / `.pkh` / `.pk`), not as loose files on the disc. To get at
anything meaningful you first have to reverse the pack format and, crucially, its
path-hash function (see [02 — Pack format](02-pack-format.md)).

`levels.pk` and `eventpacks.pk` additionally contain **nested** `.pk`/`.pkh`
pairs (recursive packs), still to be fully exploded.

## Getting the filesystem out

Extraction of the `DATA` partition is done with **wit** (Wiimms ISO Tools):

```
wit extract <game>.iso <out_dir> --psel data
```

This yields the `files/`, `sys/`, and disc-metadata layout described above. From
there the tooling in this repo operates on the extracted tree.
