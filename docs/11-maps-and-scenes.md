# 11 — Maps and scenes (`.map`, `.locator`, `.building`, `.chr`)

A level is not one file. It is a plain-text bill of materials pointing at
geometry, plus one binary file that places instances. Three of the four formats
are TSV and readable in a text editor; only `.locator` needed reversing.

```
.map  ──────> the scene's bill of materials
  ├─ MODEL        ──> .model directly   (the terrain is the *_base.model)
  ├─ LOCATORS     ──> .locator = instances with TRS
  │                     └─ asset ──> .building
  │                                    └─ .model
  ├─ COLLI_TREE   ──> .hocb   (collision tree — not covered here)
  └─ AREAFILE     ──> .area   (triggers/zones — not covered here)
```

## `.map` — the bill of materials

Plain TSV, `\r\n` line endings, `#` comments. 468 files. Key census across all
of them:

| Key | Rows | Meaning |
|---|---|---|
| `MODEL` | 1864 | static model `[+ flags]` |
| `LOCATORS` | 1604 | prop instance list → `.locator` |
| `GIMMICK_LOC` | 773 | same, for interactive gimmicks |
| `COLLI_TREE` | 481 | `.hocb` |
| `AREAFILE` | 431 | `.area` |

plus rendering keys that carry no geometry but describe the lighting:
`AMBIENT_COLOR`, `LIGHT`, `LIGHTSURROUND`, `FOG`, `SHADOW`, `REFLECT`, `BLOOM`,
`DOF`, `GODRAY`, `GAMMA`, `COLOR_MATRIX`, `CLEAR_COLOR`, `CAMERA_CLIP`.

Flags seen on `MODEL` rows: `HIDE_BIRDVIEW`, `REFRACT`/`FORCE_REFRACT`,
`REFLECT`/`FORCE_REFLECT`, `NO_SHADOW`.

**The terrain is the `MODEL` row ending in `_base.model`.** No separate
heightmap or terrain format exists — the ground is an ordinary model.

Three files write `CREAR_COLOR` instead of `CLEAR_COLOR`. That typo is in the
shipped data; treat it as an alias.

Rows to skip when building a solid scene: `*_occ.model` (occlusion-culling
mesh), anything flagged `HIDE_BIRDVIEW` (duplicates for the overhead camera),
and the backdrop — `*_sky*`, `*_far*`, `*_lightshaft*`. The skydome is vastly
larger than the playable area and swallows it whole if left in.

## `.locator` — prop instances

`chnkdata`, subtag `wii loct`. This is the only binary of the four.

```
+0x14  u32  version (always 3)
+0x18  u32  16
+0x1c  u32  data size
+0x20  ptr  -> name of the group's BAKE (lightmap) texture,
              e.g. 'dg001_01_01_bake01.texture'
+0x24  u32  nInstance
+0x28  u32  0
```

Instance array at `+0x2c`, **48-byte** records:

| Offset | Field |
|---|---|
| `0x00` | ptr → instance name, unique (`dg001_arch10_0009`) |
| `0x04` | `f32[3]` position |
| `0x10` | `f32[3]` rotation, in **degrees** |
| `0x1c` | `f32[3]` scale |
| `0x28` | `nParam` (always 1 in the files seen) |
| `0x2c` | ptr → array of 16-byte params |

Param, 16 bytes:

| Offset | Field |
|---|---|
| `0x00` | ptr → **asset name, no extension** (`dg001_arch10`) |
| `0x04` | `f32` u — the instance's tile in the lightmap atlas |
| `0x08` | `f32` v |
| `0x0c` | `f32` tile side (`0.11111` = 1/9 → a 9×9 atlas) |

Rotations are in degrees, not radians: the data contains exact `90.0` and `0.0`
values. `.motion` uses radians, so the two must not be fed through the same
path. Composition is otherwise the engine's usual `T · Rz·Ry·Rx · S`.

**The layout self-verifies by arithmetic.** On `dg001_01_01.locator`, n = 53:

```
end of instance array  = 0x2c + 53×0x30  = 0xa1c
first param pointer                       = 0xa1c   ✓
end of param array     = 0xa1c + 53×0x10 = 0xd6c
header +0x20                              = 0xd6c   ✓
```

Strings start immediately after. The file is fully accounted for — header,
instances, params, strings — with no unexplained bytes.

The instance-to-asset ratio is what an instancing system should look like: 53
instances over 13 distinct assets, every instance name unique (asset + serial).

A `GIMMICK_LOC` entry may reference an **effect** rather than a model —
`be002_001` resolves to `be002_001.eff`, not a `.model`. That is not a missing
asset.

## `.building` — the prop and its LODs

Plain TSV. Carries no geometry; it is the recipe linking a `.locator` asset name
to actual models. 1753 files.

| Key | Rows | Fields |
|---|---|---|
| `MODEL` | 1749 | `<model> <material>` |
| `MODEL_LOD` | 201 | `<model> <material> <distance>` |
| `OCCLUSION` | 52 | `<model>` — do not draw |
| `FOLDER` | 47 | `<name>` |

```
MODEL       b_house02_2f02.model       b_house02_2f02.material
MODEL_LOD   b_house02_2f02_lod1.model  b_house02_2f02.material   300
MODEL_LOD   b_house02_2f02_lod2.model  b_house02_2f02.material   600
OCCLUSION   b_house02_2f02_occ.model
```

LOD distances are in world units — 300 and 600 are 30 m and 60 m at
1 u ≈ 10 cm.

## Map geometry is not stored like character geometry

Two differences, both of which break a decoder written for characters.

**Positions are `f32x3`, not quantised `s16x3`.** A `*_base.model` stream
reports `perElem = 12` and `POS(f32x3)`. There is no per-mesh `K` to solve and
no skeleton to apply — the coordinates are already final, in world space.
A decoder that hard-rejects `perElem != 6` returns zero vertices, silently.

**The streams are named**, and the names are the artists' romaji Japanese part
labels — `jimen` (地面, ground), `rouka` (廊下, corridor), `gareki_yama`
(瓦礫山, rubble heap), `hari` (梁, beam). Character models leave the field empty.

Terrain and locator instances share one world space, with no extra transform.
Cross-check on `dg001_01`, where the floor level matters most:

| | Terrain | Locator instances |
|---|---|---|
| X | −498.5 … 260.0 | −325.0 … 585.0 |
| **Y** | **−29.5** … 167.7 | **−28.1** … 104.5 |
| Z | −344.4 … 505.7 | −490.0 … 677.0 |

## Three rendering traps

**Winding.** Map floors are wound with the normal pointing **down**. Verified by
hand on a courtyard quad of `dg001_01`: `e1 × e2 = (0, −459.8, 0)`. Viewed from
above they are backfaces, so a renderer with backface culling drops every floor
in the level and characters appear to walk on nothing. Render map geometry
two-sided.

**Depth vs winding, in the renderer itself.** `render_obj.py` culled backfaces
with `n[2] < 0` — which places the viewer at **+z** — while its depth test kept
the *smaller* z, which places the viewer at **−z**. The two conventions
contradicted each other. Since `rot()` maps world **+Y to a positive view z**,
"higher up" counted as "farther away", and the ground won the depth test against
anything standing on it: a character on a floor was drawn *underneath* it.

It stayed invisible for three sessions because everything rendered until then
was a single closed object. With backface culling, a convex closed mesh has
exactly one front-facing triangle per pixel, so the depth test never decides
anything — the cat and the character models looked correct either way. The bug
only surfaces with **separate objects at different depths**, which is precisely
what putting a character on terrain creates. Fixed by initialising the z-buffer
to `-inf` and keeping the larger z.

Worth stating because it is the general shape of the trap: a renderer can be
self-inconsistent and still look right on every test case you have, until the
first case that actually exercises the inconsistency.

**Degenerate triangles.** The terrain decode leaves slivers — 201 of 4707
triangles on `dg001_01`'s terrain, 1668 of 71,491 on the full scene. They have
near-zero area but span tens of units. Beyond looking wrong, they poison any
ground query: a path-finder walking the mesh will happily follow a sliver
straight out over empty space. Filter by `longest_edge > 80` or
`4·area / longest_edge² < 0.02`. This is a **geometric** filter; the screen-space
edge-length cull in `render_obj.py` is a different thing and will erase real
terrain whenever the camera is close.

## Character definition — `.chr` / `.mchr`

Plain TSV. `.chr` defines a character; `.mchr` is a shared animation set.

```
MOTION   <file.motion>   <STATE>
```

States are `CH_` + 3 letters + 2 digits. The three that drive locomotion:

| State | Clip | Meaning |
|---|---|---|
| `CH_WTN00` | `na000_wtn00_00.motion` | idle (wait) |
| `CH_WKN00` | `na000_wkn00_00.motion` | walk |
| `CH_RNN00` | `na000_rnn00_00.motion` | run |

The player's file lists no clips of its own — it delegates:

```
pc001_bs00_00.chr:
    MODEL        pc001_a00.model   pc001_a00.material
    MOTION_SET   /database/chara/motion/na000_00.chr
```

with one catch: the real file is `na000_00.**mchr**` in that directory, and the
engine resolves the extension. The `na000_00.chr` under `data/character/` exists
but is **0 bytes**. Following the literal path finds nothing. Resolved properly,
the set yields 367 states.

This is the same shared-library pattern seen from the animation side
(§ [10](10-animation.md)): `.motion` binds curves to bones **by name**, so one
set of clips drives every humanoid rig.

Other keys across the 1597 `.chr` files: `MODEL_LOD`, `OPTION_PARTS`,
`NODE_EDIT`, `BOUND_CENTER_NODE`, `EDIT_DATABASE`, `SCALE`, `PBONE`,
`PROTECTOR`, `EFP`, `COLLISION`, `EQUIP`, and `COLLI_RADIUS` (3 = 30 cm).

## Putting it together

`build_scene.py` walks the whole chain and merges a level into one OBJ. Each
asset's geometry is decoded **once** and reused for all its instances.

```
python build_scene.py dg001_01.map out.obj                 # full scene
python build_scene.py dg001_01.map out.obj --terrain-only  # just the ground
```

`dg001_01` (a ruined castle) resolves to 5 direct models plus **551 instances**
from 12 locator files: 74,215 triangles, 75 of 76 materials textured. Rendered
from overhead it reads as a floor plan — rectangular rooms, corridors, a
colonnaded hall with evenly spaced pillars, doorways. Even spacing is the useful
signal: an error in the instance rotation or in the TRS composition order
scatters the pillars, so a tidy colonnade is evidence the transform is right.

## Walking on it

`walk_poc.py` puts a character on a real map and moves it. Three decisions, each
taken from measured data rather than tuned by eye:

1. **The engine drives translation** — locomotion clips are in place
   (§ [10](10-animation.md)).
2. **Speed comes from the stance plateau** — 0.1808 u/frame for the walk, so
   the feet do not skate.
3. **The loop period is tested per file**, not assumed from `frameCount`.

Ground support is a downward raycast against the scene mesh. That is enough for
"a character moving over a map"; the `.hocb` collision tree is a separate
problem and is not needed here.

The check that it works is numeric, not visual: over a full walk cycle the
character's lowest vertex stays between **4.839 and 5.051** against a floor at
**Y = 5.000** — within ±1.6 cm at 1 u ≈ 10 cm, with no offset applied. The
model's origin *is* its ground contact point.

### The state machine

`--plan` plays a sequence of states, each bringing its own clip, period and
speed — all read from the data, none copied between states:

| State | Clip | Period | Speed |
|---|---|---|---|
| `CH_WTN00` | `na000_wtn00_00` | 60 | 0 u/s — standing still |
| `CH_WKN00` | `na000_wkn00_00` | 54 | 5.42 u/s (0.54 m/s) |
| `CH_RNN00` | `na000_rnn00_00` | 24 | 21.2 u/s (2.12 m/s) |

Phase restarts at 0 on each switch. A real engine would cross-fade the clips;
this does not, and it is the one place the PoC visibly reads as "not from the
game".

### Two things the camera needs

**A follow camera must keep the span constant.** What makes framing wobble is
recomputing the span per frame, not the centre moving. Fix the span and let the
centre track the character and the result is stable.

**Cut the ceiling.** At a 30–50° camera angle, upper floors and roofs land
between the camera and the character and hide them completely. This is the same
problem the game solves with `HIDE_BIRDVIEW`, and the minimal fix is the same
idea: do not draw faces above the character's head, with the threshold moving
with them.

Note also that the automatic path finder is a heuristic. Weighting run length by
the minimum terrain density along the route stops it choosing the empty fringes
at the map edge, but it can still land somewhere the camera cannot see into.
Pass an explicit start when the framing matters.

```
python walk_poc.py                                    # walk on dg001_01
python walk_poc.py --state run --props                # run, full scene
python walk_poc.py --plan "idle:16,walk:48,run:32"    # the state machine
python walk_poc.py --x -258.5 --z -60 --dir 270       # explicit start
python walk_poc.py --fixed-cam                        # fixed instead of follow
```
