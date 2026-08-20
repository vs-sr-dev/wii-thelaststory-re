# 13 — Areas (`.area`) — per-volume environment and visibility

A level is not lit as one thing. `.area` cuts it into zones: inside each box the
lighting, fog, weather and colour grading are different, and a set of assets is
tagged as belonging to that zone. 293 files in `data/area/`, plain TSV,
**block-structured**.

A `.map` names its area file with an `AREAFILE` row (see
[11 — Maps & scenes](11-maps-and-scenes.md)).

```
AREA <name> <minX> <minY> <minZ> <maxX> <maxY> <maxZ>
AREA_BOX <6 floats>          extra volumes belonging to the SAME block
<environment overrides>      LIGHT, FOG, SHADOW, GODRAY, RAIN, ...
SET_AREA <asset>             which assets belong to this zone
```

A block runs from one `AREA` row to the next. Blank lines mean nothing.
293 files hold **448 zones, 89 `AREA_BOX`, 676 `SET_AREA`**.

## The AABB field order is proven

Two independent checks, both in `parse_area.py --check-box`.

**1. `RAINDROPS` repeats the box.** The row ends with `BOX <6 floats>`. In **214
blocks those six numbers are byte-identical to the block's own `AREA` AABB** —
same values, same order. That settles `minXYZ` then `maxXYZ` with no
interpretation needed. In 47 blocks the box is all zeros (unset); in 68 it is a
volume of its own, so the rain box is an independent volume that merely
*defaults* to the area's. It is **not** constrained to sit inside the area (30
inside, 38 not), so don't assume containment.

**2. `COVERAGEMAP` is the XZ projection.** The row carries
`<minX> <minZ> <maxX> <maxZ>` plus a `.texture`. In **325 of 433 blocks it is
exactly the XZ union of `AREA` and its `AREA_BOX`es** — which proves the field
order *and* that `AREA_BOX` rows belong to the block above them (33 of those 325
only match once the boxes are included). The remaining 108 don't match: the
coverage map is a hand-painted texture, and there it covers more (63) or
something else entirely (45). A very strong correlation, not a law — enough for
the purpose, and stated as such.

Worked example, `dg001_01.area` block 2:

```
AREA      dg001_01_02_area01  -154.26 … 117.84   x   53.44 … 495.73  (z)
AREA_BOX  -296.14 … 24.45  x  -144.16 …  58.73
AREA_BOX    18.48 … 188.22 x   -18.47 …  82.13
COVERAGEMAP -296.1383  -144.1634  188.215  495.7271
            ^ minX from box 1   ^ maxX from box 2   ^ maxZ from AREA
```

## Environment overrides — and what the engine won't let you localise

Comparing the key sets of `.area` and `.map` splits cleanly in three:

| Where | Keys | Reading |
|---|---|---|
| **Both** | `LIGHT`, `LIGHTSURROUND`, `AMBIENT_COLOR`, `FOG`, `SHADOW`, `REFLECT`, `GODRAY`, `COLOR_MATRIX` | the `.map` sets a scene default, the `.area` overrides it per volume |
| **Area only** | `RAIN`, `RAINDROPS`, `HAZE`, `CLOUDMAP`, `COVERAGEMAP`, `EFF_CONFIG` | local phenomena — weather has no scene-wide default |
| **Map only** | `BLOOM`, `DOF`, `GAMMA`, `CLEAR_COLOR`, `CAMERA_CLIP` | post-processing and camera stay global to the frame |

That third row is an architectural statement, not a data quirk: post-process and
camera clip are properties of the frame, so the engine offers no per-volume
form of them. Per-key counts inside each group are near-identical
(`FOG` 349/326, `LIGHT` 400/317, `BLOOM` 0/326), which supports the split.

## `SET_AREA` — partitioning, not loading

`SET_AREA` takes exactly one argument, an asset name, and belongs to the block
above it. The obvious guess is that it loads extra content per zone. **It
mostly doesn't** — `parse_area.py --check-setarea`:

| | Count |
|---|---|
| already listed by the `.map` that loaded this area | **626** |
| listed by a *different* `.map` | 18 |
| listed by no map at all | 30 |
| file does not exist on disc | 2 |

So 626 of 676 references (92.6 %) point at assets the map already loads. That
makes `SET_AREA` a **visibility / streaming partition**: it says which zone owns
each piece, so the engine can decide what to draw or keep resident as the player
moves between volumes.

The 50 exceptions are worth knowing:

- **18 cross-map references** — some `.area` files are shared between maps.
  `title06_area.area` names `dg014_03_03` assets; `dg054_01_area.area` names
  `dg048_*`. The asset is real and some other map loads it.
- **30 in no map**, almost all the camp menu UI: `status_board.locator`,
  `save_load_board.locator`, `map_board.locator`, `weapon_board.locator`,
  `shop_board.locator`, `ui_menu_ground.model`. For those, `SET_AREA` genuinely
  *is* the only thing that pulls them in — `UI_camp_area.area` is the menu
  screen's scene description.
- **2 dead references**: `dg035_10_base_b.locator`, `dg040_13_bluelight.model`.

Beware a near-miss when cross-referencing by hand: `dg005_01_01b.locator` and
`dg005_01_01_b.locator` are **both real, different files**. The underscore
matters.

## Tools

```
python parse_area.py FILE.area       # structured dump
python parse_area.py --census        # key census
python parse_area.py --check-box     # validate the AABB field order
python parse_area.py --check-setarea # SET_AREA: in the map? on disc?
```

## What is still open

- The argument grammar of the individual overrides. Several are self-describing
  (`GODRAY ON COLOR r g b POS x y z MODE POSITION SIZE w h`,
  `HAZE ... SCALE ... SCROLL ... POS ... SIZE ... FADE ...`), so they can be
  parsed keyword-wise, but the units and the exact effect are untested.
- `EFF_CONFIG` (16 rows) → `.effconfig` files, not opened yet.
- `MODEL_MAT_COLOR` (2 rows).
- Whether an `AREA` with an all-zero AABB (`UI_camp_area`) means "no volume,
  always active" — consistent with it being a menu screen, but unverified.
