# 04 — Textures (GX format)

Binary assets (textures, models, animations, lip-sync) use a common container
called **`chnkdata`**:

- magic `"chnkdata"`
- a subtag at `0x0c`, here `"wii text"`
- a header with format/dimensions
- payload starting at offset `0x40`

> **Correction.** An earlier revision of this document claimed the subtag was
> generic and identical across asset types. It is not: the subtag **does**
> discriminate the content. Textures are `wii text`, models `wii modl`
> ([08](08-models-geometry.md)), animations `wii anim`. The mistake came from
> only ever having looked at textures.

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
assets under their own subtags. The textures decoded here are applied to meshes
through the `.material` files — see [08](08-models-geometry.md) and
[09](09-skinning.md).
