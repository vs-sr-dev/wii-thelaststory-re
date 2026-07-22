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
