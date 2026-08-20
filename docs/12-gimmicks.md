# 12 — Gimmicks (`.gmk`) and the first game scripting

A *gimmick* is an interactive object in the world: a crate, a door, a pillar
that collapses, a lamp you can snuff out. 578 files in `data/gimmick/`, all
plain TSV — one directive per line, `#` comments, tab-separated.

This is the first format in the game that is not an asset. `.gmk` describes
**behaviour**: a state machine, and a timeline of commands fired at specific
frames of an animation.

```
.gmk ─────> an interactive object
  ├─ MODEL / MODEL_BEFORE / MODEL_AFTER  ──> .model     the object's looks per state
  ├─ COLLISION_BEFORE / _AFTER           ──> .hcb       collision changes with state
  ├─ MOTION <file> <GM_ACTnn>            ──> .motion    one clip per state code
  ├─ STATE / TRIGGER                                    explicit state machine
  └─ MOTCMD <GM_ACTnn> <frame> <op> ...                 the timeline — scripting
```

## Paths are logical, not real

Paths inside a `.gmk` look like `/gimmick/gm001_014/gm001_014b.model`. No such
directory exists on the disc. That tree is the artists' source layout; the
packed filesystem is flat per type, so the file actually lives at
`data/model/gm001_014b.model`. **Resolve by basename into `data/<type>/`.**
The same convention holds for `.motion`, `.efp` and `.hcb`.

## Key census

578 files. Top directives:

| Key | Rows | Meaning |
|---|---|---|
| `MOTION` | 520 | clip `<file> <GM_ACTnn>` |
| `MODEL` | 500 | single-state look |
| `EFP` | 308 | attached effect |
| `MOTCMD` | 179 | **timeline command** |
| `COLLISION_BEFORE` | 176 | `<radius> <.hcb>` |
| `MODEL_AFTER` / `COLLISION_AFTER` | 118 | post-transition state |
| `MATALPHA` | 113 | material fade |
| `INIT_STATE` | 101 | starting state |
| `TARGET_COLLISION` | 68 | lock-on volume |
| `STATE` | 46 | state-machine node |
| `NODEVIS` | 34 | node visibility |
| `TRIGGER` | 31 | state-machine edge |

119 files use the simple `MODEL_BEFORE`/`MODEL_AFTER` pair; 17 use the explicit
`STATE`/`TRIGGER` machine; the rest are single-state props. The state code is
`GM_ACTnn` — the same shape as the characters' `CH_*` codes, and the key by
which the engine picks a clip.

## `MOTCMD` — commands on the animation timeline

```
MOTCMD <GM_ACTnn> <frame> <OPCODE> <arg1> <arg2> <arg3> <arg4> [arg5]
```

"At frame N of state S's animation, do X." `arg1` is the target, `arg2..4` a
local XYZ offset, `arg5` a scale or extra parameter.

| Opcode | Rows | Arguments |
|---|---|---|
| `EFP_PLAY` | 91 | `<file.efp> <x> <y> <z> <scale>` — one-shot effect |
| `CAM_SHAKE` | 49 | `<empty> <ampX> <ampY> <duration> <delay>` |
| `EXPLODE` | 18 | `<id> <x> <y> <z> <force> <node>` — detach a model node |
| `EFP_LOOP` | 18 | `<file.efp> <x> <y> <z> <scale>` — persistent effect |
| `SE_PLAY` | 3 | `<SE_xxx> <x> <y> <z> <scale>` — sound, id from the `rsid` registry |

Two directives outside `MOTCMD` live on the same timeline:

```
NODEVIS  <node> <frame>                    hide the node at frame N
MATALPHA <material> <frame> <length> <f>   fade the material out
```

A whole collapsing pillar reads straight off the file (`gm001_016.gmk`):

```
GM_ACT01  <- gm001_016b_01.motion   (300 frames)
    f   0  CAM_SHAKE  1.5 1.5 10 0
    f  30  CAM_SHAKE  1   1   10 0
    f  40  CAM_SHAKE  0.8 0.8 30 0
    f  60  CAM_SHAKE  1   1  100 0
    f  80  CAM_SHAKE  0.5 0.5 30 0
    f 120  CAM_SHAKE  0.5 0.5 50 0
    f 299  NODEVIS hahen02          (the debris disappears one frame before the end)
```

`hahen` (破片, "shard") is a real node in the twin `.model`, and its children
are literally named `shard37 … shard57`.

## Why we believe `<frame>` is a frame

Three tests, weakest first. `parse_gmk.py --check` and `--xref` reproduce them.

**1. Containment (weak on its own).** All 179 `MOTCMD` frames fall inside the
duration of their *own* state's clip, no exceptions. But the highest
frame/duration ratio is only 0.47 — every command sits in the first half — so
any small integer would pass this test too. Not sufficient.

**2. Saturation (strong).** `NODEVIS` and `MATALPHA` use the same scale and
*saturate* it: 299/300, 250/251, 150/151, 240/250. The fade ends exactly on the
animation's last frame. An arbitrary number does not do that. 32/34 `NODEVIS`
and 108/113 `MATALPHA` land inside the duration.

**3. Cross-format name agreement (strong).** The names these directives cite
must exist in a completely different format. 18/18 `EXPLODE` node names, 32/34
`NODEVIS` nodes and 108/113 `MATALPHA` materials match the twin `.model` /
`.material`. All seven misses are explained, and none is a parsing error:

- `em205_cloth`, `em205_leg` (in `gm001_101`/`102`) — the material belongs to
  the **enemy's** `.material`, not to the gimmick's model. Confirmed present in
  `em205_00_bs00.material`. `MATALPHA` addresses materials **by name across the
  whole loaded scene**: the same file also fades `ai_dg005_*` and `og_dg005_*`,
  which are map geometry. That is a courtyard-crumbles set piece dissolving
  scenery, an enemy statue and its own debris in one go.
- `delete` vs the real node `delete0` — a one-character near-miss.
- `h_gm001_108b_mat3` — a dead reference; only `mat1/2/4/5` exist.

Incidentally, `.material` turns out to be plain text too — an INI-like
`Name=`/`Shader=`/`TexColor1` block list.

## `STATE` / `TRIGGER` — the state machine

```
STATE   <id> <GM_ACTnn | file.hocb> <f> <loop> <f> [<f> <MODE> ...]
TRIGGER <from> <to> <type> <p1> [<p2>]
```

`loop` is 1 for a cycling clip, 0 for play-once. Modes seen: `NOMOTION` (a
state with no animation — a pure timer), `ATTENTION`, `DRAWOFF`, and
`TRANS`/`TRANSINV` followed by four numbers that look like fade thresholds.

**`TRIGGER` type 1 is a timeout in frames.** In 12 of the 16 measurable cases
`p1` is *exactly* the duration of the source state's clip — i.e. "advance when
the animation ends". The rest are longer waits on a looping state. `p2` is 0 in
every "end of clip" case and non-zero only on long timers, which suggests a
random jitter, but with a sample of 2 that stays a guess. Types 2–6 are not
timeouts (`p1` is always well below the clip duration) and are still undecoded.

`gm034_100` is an NPC standing around, and the machine reads plainly:

```
MODEL   an009_00.model
STATE 1 GM_ACT01 ... NOMOTION      TRIGGER 1 2 1 300 60   stand still ~10 s (±2 s?)
STATE 2 GM_ACT01 ... loop=0        TRIGGER 2 1 1  13  0   play a 13-frame fidget,
                                                          then back to standing
```

## Tools

```
python parse_gmk.py FILE.gmk        # structured dump + timeline
python parse_gmk.py --census        # key census over all files
python parse_gmk.py --check         # validate MOTCMD frames against .motion
python parse_gmk.py --xref          # validate names against .model / .material
python parse_gmk.py --check-trigger # validate type-1 TRIGGER against clip length
```

## What is still open

- `TRIGGER` types 2–6: the actual conditions (proximity? damage? player input?).
  Type 3 appears with a second parameter of 0.5/0.7, which smells like a
  probability.
- `EXPLODE`'s first argument (2003, 2005, 2032…) and `EXPLODE_PARAM` — an index
  into some debris/physics table not yet located.
- `TRANS`/`TRANSINV`'s four numbers.
- `PATH_POINT` (38 rows) — XZ polylines, presumably moving-platform routes.
