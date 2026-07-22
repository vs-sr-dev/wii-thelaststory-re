# 04 — Textures (GX format)

Binary assets (textures, models, animations, lip-sync) use a common container
called **`chnkdata`**:

- magic `"chnkdata"`
- a generic tag `"wii text"` — the **same for every asset type**, so it does
  *not* discriminate the content type
- a header with format/dimensions
- payload starting at offset `0x40`

## Texture header fields

| Offset | Field |
|---|---|
| `0x20` | GX texture format |
| `0x24` | width |
| `0x28` | height |
| `0x2c` | mipmap count |
| `0x34` | data offset |

## Formats seen

Across **10,206 textures** (100% `chnkdata`), the GX format distribution is:

| Format | Count | | Format | Count |
|---|---|---|---|---|
| CMPR (DXT1-like) | 9,685 | | I4 | 43 |
| IA4 | 227 | | RGBA8 | 34 |
| RGB5A3 | 92 | | I8 | 18 |
| IA8 | 59 | | RGB565 | 48 |

No palettised (CI) formats were encountered.

## Decoding

GX textures are stored in **tiled blocks** (the classic Flipper/Hollywood
layout), not linearly. Block sizes and tiling differ per format (e.g. CMPR uses
8×8 blocks of 2×2 sub-tiles; RGBA8 uses 4×4 blocks split into AR/GB planes).
`tools/gxtex.py` implements the de-tiling and pixel decode for **all** formats
above, with zero external dependencies, and was validated visually (CMPR / IA8 /
RGBA8 / IA4 alpha all correct).

Batch conversion:

```
python tools/batch_tex.py all
```

produces PNGs. The same `chnkdata` container wraps `.model` / `.motion` / `.lip`
assets, whose formats are the subject of future work; the textures decoded here
are applied to those meshes through the `.material` files.
