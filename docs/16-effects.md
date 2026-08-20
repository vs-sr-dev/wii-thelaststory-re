# 16 — Effects: `.efp` (sequencer) and `.effconfig`

The effects group looked like one big untouched format — 3,158 files, the last
intact block on the disc. It is three formats, and two of them are plaintext:

| | Files | Format | Status |
|---|---|---|---|
| `.efp` | 1,264 | Shift-JIS XML | **decoded here** |
| `.effconfig` | 34 | one CSV line | **decoded here** |
| `.eff` | 2,210 | binary `@EFF$` | not yet |

This document covers the two text ones. They are the layers that connect
[gimmicks](12-gimmicks.md) and [areas](13-areas.md) to what the player actually
sees, so decoding them closes two dangling references rather than opening a new
subsystem.

## Before touching the binary: `.eff` is little-endian

Worth stating up front, because it inverts the habit this project has built over
eight sessions of big-endian PowerPC data.

The word at `+0x08` read **little-endian** is the file size, on **2210/2210**
files. Read big-endian it is garbage. The offsets in the header are also
**absolute**, not self-relative like the collision formats in
[14](14-collision.md) and [15](15-collision-hcb.md). The magic is `@EFF$` stored
in reading order — not byte-swapped the way `@HOC` ships as `COH@`.

## `.efp` — the sequencer

An `.efp` contains no effect. It says *when* to start a `.eff`, *where* to put
it, and *what to attach it to*.

```xml
<EffectSequencer version="1|2|1.0.4">
  <EffectLine num="N"/>
  <Effect file="X.eff" enable="0|1">
    <Frame start="" end=""/>
    <Pos x y z/> <Rot x y z/> <Scl val/> <Color a r g b/>
    <Parent type node obj flag release/>
    [<Throw flag speed><PointList num><Point x y z flag/>…</PointList></Throw>]
    [<Erase type frame/>]
  </Effect>
  [<Object path file><Pos/><Rot/><Motion file loop/></Object>]
</EffectSequencer>
```

That is the **complete** grammar: 15 tags, censused across all 1,264 files
(`parse_efp.py --check`), not a sample. `Throw`/`Erase` appear in 13 files and
`Object`/`Motion` in 6 — all of them version `1.0.4`, files left in the effect
editor's own dialect. One still carries the author's Windows path,
`..\..\<mojibake Shift-JIS>\`.

Every `<Effect file>` resolves: **2865/2865** named `.eff` files exist on disc.

### `Parent` is the interesting part

| `type` | Count | Meaning |
|---|---|---|
| 4 | 2487 | attach to a node — `node` filled in 2485 of them |
| 0 | 308 | world space — `node` usually empty |
| 1 | 44 | — |
| 3 | 26 | — |

`obj` is filled only 7 times and names a `.hdb`, an extension with **not one
file anywhere on the disc**: an editor reference left in the shipped data.

### The claim worth proving: `node` is a bone name

The names read like a rig — `body`, `spine1`, `hips`, `head`, `righthand`,
`rightforearm`, `nw4r_root`. That is a hypothesis, not a result, and it can be
checked against a completely unrelated format: the bone names inside the binary
NW4R `.model` skeletons ([08](08-models-geometry.md)). Two measurements
(`parse_efp.py --check-bones`):

**1. Narrow.** For every gimmick that declares both an `EFP` and a `MODEL`, the
`Parent node` names in that `.efp` must be bones of *that* model — no borrowing
from elsewhere. Over 288 `.efp` files: **811/833 = 97.4 %**.

**2. Global.** Every name used anywhere must be a bone of *some* model. Against
all 4,691 `.model` files, holding 13,202 distinct bone names:
**2,582/2,653 references = 97.3 %**, 566 of 591 distinct names.

The 71 leftovers are not misreads, and the two measurements disagree in an
informative way. The narrow misses are `shard52`, `splinter80_1`,
`hahen01_shard18` — *hahen* is 破片, fragment — debris nodes that live in the
model of the object's **other** state, which that gimmick row does not name. The
global misses are `eff_oar01..12`, `block_level01/02`, `polySurface505_DUP`,
`up_model22`: models that are not in `data/model/` at all, because the recursive
`levels`/`eventpacks` packs are still unexploded.

So the effect system attaches to the skeleton by **name**, exactly as `.motion`
binds its animation tracks ([10](10-animation.md)). Name-based binding is the
engine's consistent choice.

### `end=0` means "no end"

303 `<Frame>` elements have `start > end`. That reads as corruption until you
notice that **every single one of them has `end=0`** — and that there is no
`end<0` anywhere, and no case of `start > end` with a non-zero `end`.

```
end > 0   real interval        start <= end on 1509/1509 = 100%
end == 0  no declared end      1053 with start=0, 303 with start>0
```

The invariant is not something that holds by luck: if `end` were just another
frame number, `start > end` would sometimes occur with `end` non-zero too. It
never does.

### Two authoring bugs shipped on the disc

`gm001_000b.efp` **is not valid XML**. It contains `<Pos x="0" y="0" y="0"/>` —
`y` twice, in place of `z`, on both `<Pos>` and `<Rot>`. 1,263 of 1,264 files
parse under a strict parser; this one does not.

The tool repairs it (the duplicate becomes `z`) and flags the repair in
`["repaired"]` rather than skipping the file, because dropping it would silently
lose a real sequencer with four effects. A parser that quietly ignores
unparseable inputs will under-report and look correct while doing it.

Second, harmless: `ef_uc047.efp` declares `<EffectLine num="6">` but carries 5
`<Effect>` elements. The two agree on the other 1,263 files, so `num` genuinely
is the count — but do not use it to decide how many elements to read.

### A trap when counting references from `.gmk`

There is not one `EFP` key but **eleven**: `EFP` (309), `EFP_BEFORE`,
`EFP_WAIT`, `EFP_ROLL`, `EFP_CRUSH`, `EFP_SHOOT`, `EFP_GET`, `EFP_ARROW`,
`EFP_BURNOUT`, `EFP_ITEM` — plus `EFPLIGHT`, which names no file at all and is
four numbers. A single row can also carry several paths followed by empty
fields.

Matching only `EFP` and taking only the last argument yields 275 references.
The correct count is **341** — a fifth of them lost to a plausible-looking
shortcut.

## `.effconfig` — area presets

34 files, one CSV line each (one file has two). This is a zone's ambient-effect
preset, referenced from `.area` rows keyed `EFF_CONFIG` — 16 references, 14
distinct, none missing.

```
name , category , r , g , b , a , eff [, eff [, eff]]

water,BE,0.75,0.75,0.75,1,be001_023,be001_024,be001_021
yuge,BE,0.7,0.5,0.5,1,be003_013
hikari,BE,1,0.93,0.7,1,be002_003
```

The names continue the romanised Japanese taxonomy used across the disc:
`water`, `yuge` (湯気, steam), `yuge_big`, `blue_fire`, `smoke`, `wave`,
`funsui_water` (噴水, fountain), and `hikari` (光, light) — which alone accounts
for 20 of the 35 rows, all of them in the `tw03_*` town maps.

The category is `BE` on 33 rows and `MAGIC_CIRCLE` on 2. The trailing tokens are
`.eff` basenames without the extension, and all of them exist — except the
literal `DEFAULT` on the two `MAGIC_CIRCLE` rows, which is a keyword rather than
a filename.

## The reference graph

```
.gmk  --EFP*-->  .efp  --file-->  .eff        341 / 2865 refs, 0 missing
.area --EFF_CONFIG--> .effconfig --> .eff      16 refs, 0 missing
```

955 of the 1,264 `.efp` are never named by a gimmick: those are the `be*`
(battle) and `ef_*` (ambient) effects, driven from elsewhere. 351 of the 2,210
`.eff` are never named by a sequencer.

## Tools

```
python parse_efp.py FILE.efp        # summary of one sequencer
python parse_efp.py --check         # grammar + invariants over every file
python parse_efp.py --check-bones   # Parent node vs .model bone names
python parse_efp.py --config        # the .effconfig files
python parse_efp.py --xref          # gmk -> efp -> eff, area -> effconfig
```

## What is still open

- `.eff` itself — the actual particle/effect definition. Binary, little-endian,
  absolute offsets, `+0x08` = file size, `+0x14` = 72 constant, two counters at
  `+0x0c`/`+0x10`, section offsets at `+0x18`/`+0x20`/`+0x28`. It carries
  **plaintext texture names** (`ef_kem06o_c.texture`) in fixed-length slots, so
  it links straight into the texture pipeline from [04](04-textures-gx.md).
- `Parent` types 1 and 3, and the `flag` / `release` fields.
- What `Throw` and its `PointList` drive — only 13 files use them.
