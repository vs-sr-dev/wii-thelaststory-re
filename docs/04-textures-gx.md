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
above, with zero external dependencies.

> **Correction.** An earlier revision of this document said the decoder had been
> "validated visually, CMPR / IA8 / RGBA8 / IA4 alpha all correct". Visual
> validation was not enough: it passed two decode errors that a real run caught
> immediately (see below). The images looked right because both errors are
> small, uniform, and in the one channel the eye is worst at judging.

Batch conversion:

```
python tools/batch_tex.py all
```

produces PNGs. The same `chnkdata` container wraps `.model` / `.motion` / `.lip`
assets under their own subtags. The textures decoded here are applied to meshes
through the `.material` files — see [08](08-models-geometry.md) and
[09](09-skinning.md).

## Validation against a real run

Every other claim in this project is validated by internal and cross-format
consistency. This decoder is the first piece checked against **the game actually
running**: textures dumped by Dolphin (`Graphics > Advanced > Dump Textures`,
with `SafeTextureCacheColorSamples = 0` so hashes cover the whole texture) are
compared pixel-for-pixel with what `gxtex.py` produces from the extracted disc
assets. `tools/dolphin_texdiff.py` does the comparison: it indexes the dumps by
`(width, height, format)`, decodes every asset with a matching signature, and
reports exact equality or a pixel/max-delta count.

The first sample was the title screen: 18 textures. Their identification is
self-confirming — the matched assets are `strapA_en` / `strapB_en` (the boot
warning screens), `ui_logo_thelaststory`, `ui_shine`, `font_05_01_s`. A wrong
match would have landed on an unrelated texture, not on the title logo.

**4 of 18 matched exactly.** The other 14 were all and only the CMPR ones, and
all of them had a maximum per-channel delta of **11**. That number is a
signature, not a statistic:

    255 x |1/3 - 3/8| = 10.6

### Correction 1 — CMPR interpolation is 5/8 and 3/8, not 2/3 and 1/3

DXT1 defines the two interpolated colours of a 4-colour block as `(2*c0+c1)/3`
and `(c0+2*c1)/3`. The GX texture unit does **not** compute those: it
approximates the thirds with eighths.

```python
cols.append(((5*r0+3*r1) >> 3, ...))   # instead of (2*r0+r1)//3
cols.append(((3*r0+5*r1) >> 3, ...))   # instead of (r0+2*r1)//3
```

This affects **9,685 of the 10,206 textures** in the game. With the fix, all 14
CMPR dumps became byte-identical.

A second, smaller point in the same branch: in the 3-colour (punch-through)
mode, the fourth entry is transparent but **not black** — it keeps the average
of the two endpoints with alpha 0. Writing `(0,0,0,0)` there is invisible on
its own, but wrong under any filtering that averages neighbouring texels.

### Correction 2 — I4/I8 expand intensity into alpha

The one I8 dump showed an alpha channel *exactly equal* to its luminance
channel, in every one of its 65,536 pixels. GX replicates intensity across all
four channels for the I formats; the decoder was writing `alpha = 255`. Only 61
textures use I4 or I8, but they are masks, where the alpha channel is the entire
point of the file.

### The one texture that is not on the disc

After both fixes, 17 of 18 matched byte-for-byte and one did not: a 256x256 I8
gradient. It was the *only* 256x256 I8 candidate in the whole asset set, so the
pairing had been forced by the signature rather than chosen — worth checking
before calling it a decoder failure.

Re-encoding the dump back into I8 tiled byte order and searching for its
gradient block across the entire extraction — **70,897 files, 7.04 GB** — found
zero occurrences. The image is a linear ramp with an exact step of -15 (255/17).
It is drawn by the CPU at run time and never existed as a file. The result is
therefore **17 of 17** on disc-sourced textures, plus a measured negative.

### Why this matters beyond textures

The two errors above are the kind that internal consistency cannot see: both
decoders were self-consistent, both produced images that looked correct, and
neither could be contradicted by any other file in the game. Only an external
witness could separate "our reading is plausible" from "our reading is what the
hardware does".
