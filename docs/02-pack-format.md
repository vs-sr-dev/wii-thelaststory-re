# 02 — Pack format (`.pfs` / `.pkh` / `.pk`)

Every pack archive is a **triplet** of files sharing the same stem, e.g.
`filesystem.pfs`, `filesystem.pkh`, `filesystem.pk`.

| File | Role |
|---|---|
| `.pfs` | Name tree — directories and file names |
| `.pkh` | Index — hash → data location table |
| `.pk` | Data blob — the actual (usually compressed) file contents |

All multi-byte fields are **big-endian** (PowerPC).

## `.pfs` — name tree

Header: `[?, ?, numDirs, numFiles]`, followed by 24-byte directory entries, a
name-offset table, and a string table. This yields the human-readable path of
every file. It does **not** tell you where the data is — that comes from `.pkh`.

## `.pkh` — index

```
u32 count
count × { u32 hashPath, u32 offset, u32 uncSize, u32 compSize }   // 16 bytes each
```

Entries are **sorted by `hashPath`** (enabling binary search at runtime).
`compSize == 0` means the file is stored **uncompressed**; otherwise the blob at
`offset` in the `.pk` is LZ11-compressed with `uncSize` the decompressed length.

## `.pk` — data + LZ11

Compressed entries use **Nintendo LZ11**: a 4-byte header (`0x11` magic followed
by the 24-bit little-endian decompressed size), then the standard LZ11 token
stream. A standalone C decompressor is provided in `tools/lwextract.c`; a Python
implementation is in `tools/lwpack.py`.

## The path hash — cracked and confirmed

The single fact that unlocks the whole archive is the definition of `hashPath`.
It is **CRC-32/BZIP2**:

- polynomial `0x04C11DB7`
- init = xorout = `0xFFFFFFFF`
- **not** reflected (neither input nor output)

computed over the file path **lower-cased**, relative to the `.pfs` root, using
`/` as separator:

```python
hashPath = crc32_bzip2("boot/ai_table.csv".lower())
```

Verified 100% on 20 of the 21 packs. This was then **confirmed in the
disassembly**: function `FUN_800dc880` in `main.dol` is exactly this CRC, unrolled
to 8 iterations per byte (`crc = 0xffffffff; crc ^= *p << 24; … poly 0x4c11db7 …;
return crc ^ 0xffffffff`). The pack-open routine `FUN_8046fa18` strips a leading
`/` from the path before hashing. A precomputed CRC table also exists in the
`data4` section (around `0x807348a4`).

## ⚠️ The blob order is not the tree order

The order of blobs in the `.pk` does **not** follow the directory-tree order of
the `.pfs`. The name↔data mapping must **always** go through the hash. A naive
by-position mapping happens to produce correct names only by coincidence on small
packs and is scrambled everywhere else — which is why the game's plaintext text
initially looks "encrypted" when read positionally. It is not encrypted; the
index is simply hash-addressed.

See `tools/lwpack.py` and `tools/extract_all.py`.

## Packs inside packs: `levels/` and `eventpacks/`

Two of the three `pack/` archives unpack into **more packs** — 1313 under
`levels/` and 739 under `eventpacks/`, 2052 in all. Each nested one ships a
`.pkh` and a `.pk` but **no `.pfs`**: there is no name tree, so the archive knows
where each file sits and not what it is called.

That is why they sat unopened for several sessions, and why they kept being
listed as the likely home of every resource reference that could not be
resolved. They are not. `parse_nested_packs.py --verify` settles it two ways.

**The names are recoverable.** The path hash is CRC-32/BZIP2 (above), so a name
can be *proposed* instead of read: hash a candidate and check whether it is
present. Hashing all 47,204 paths from the top-level `filesystem.pfs`:

| Key form tried | Nested hashes it accounts for |
|---|---|
| **full path** | **19,703 — 100.0 %** |
| leading slash | 0 |
| basename | 2 |
| basename, no extension | 1 |

Every distinct hash in every nested pack is a path that already exists in
`filesystem`. Not most — all.

**The bytes are the same.** Across a 400-entry sample drawn from packs
throughout both trees, **400 of 400** decompress byte-identical to the
`filesystem` copy.

So the nested packs are a **per-level duplication of shared content**: 106,902
entries covering only 19,703 distinct files, an average of 5.4 copies each, laid
out so a level streams from one contiguous archive instead of seeking across the
global one. Ordinary practice for optical media — and it means there is nothing
new inside, and nothing there can explain a dangling reference.

The four textures `.eff` materials ask for and the disc does not contain
(`Mb243_fire`, `Mb243_hei`, `Mb243_wave`, `eff_swd01o`) are therefore simply
**absent**, like the two author typos in [17](17-eff-binary.md) — references to
assets deleted before release.

```
python parse_nested_packs.py            # inventory + type histogram
python parse_nested_packs.py --verify   # the two checks above
python parse_nested_packs.py --list ev0101
```
