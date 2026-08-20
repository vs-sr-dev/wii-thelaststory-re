# 10 — Animation (`.motion`)

A `.motion` is a `chnkdata` container with subtag `wii anim`. It holds curves,
nothing else: no skeleton, no mesh, no root motion. Verified on 601 files and
32,237 `anmn` chunks sampled across the whole disc, with zero structural errors.

## Header and per-bone chunks

```
chunk `anim` @0x10
    +0x20  f32  frameCount     number of frames (see "How long is a clip" below)
    +0x24  u32  nAnmn
    +0x28  u32  ptr -> array of `anmn` chunk offsets
```

Each `anmn` chunk is **one bone's curves**:

| Offset | Field |
|---|---|
| `0x04` | `count` — always 3 (the X/Y/Z of a TRS group) |
| `0x10` | ptr → bone name |
| `0x14` | `nameHash` — matches `node+0x14` in the `.model` |
| `0x18` | `mask` — which TRS groups are animated |
| `0x1c` | `0xdeadbeef` marker |
| `0x20` | `popcount(mask) × count` records of 12 bytes |

Track record (12 bytes):

| Offset | Field |
|---|---|
| `0x00` | `channel` — 0-2 scale, 3-5 rotation, 6-8 translation |
| `0x02` | `fmt` — 0 constant, 1 keyframe, 4 dense |
| `0x04` | `nFrame` |
| `0x06` | `frac` — fractional bits (value = `s16 / 2^frac`) |
| `0x08` | `dataOff` — absolute offset of the track data |

`mask`: bit0 = translation, bit1 = rotation, bit2 = scale. Confirmed by exact
count over the sample: masks containing bit1 (2, 3, 6, 7) total 32,225 tracks,
exactly the number of tracks on channels 3/4/5; same for the other two bits. A
group absent from the mask means that bone keeps its `.model` bind-pose TRS.

**The bone is identified by name and hash, not by index.** On `an008` all 96
names and all 96 hashes match the `.model`'s `node` chunks. This is why one
animation library serves every humanoid: see `na000_*`, referenced by every
human character (§ [11](11-maps-and-scenes.md)).

## The three track formats

| `fmt` | Layout |
|---|---|
| 0 constant | 4 bytes: one `f32`, not quantised (`frac` = 0) |
| 1 keyframe | `nFrame × 6 B`: `(u16 frame, s16 value, s16 tangent)`, padded to 4 |
| 4 dense | `nFrame × s16`, one sample per frame, nothing to interpolate |

Format 0 is unambiguous to identify: the 64 constant-scale tracks all hold
`0x3f800000`, exactly 1.0.

Format 1 interpolates with a **Hermite cubic**. The tangent is
`d(value)/d(frame)` in the same quantised units, positive while the curve rises
and negative while it falls.

For formats 1 and 4 the real value is `s16 / 2^frac`. Rotations are in
**radians** — unlike `.locator` instance rotations, which are in degrees
(§ [11](11-maps-and-scenes.md)).

## Animated channels replace the bind pose, they do not add to it

Verified on `an008`: `hips.posY` is 3.0810 at bind and 3.0103 animated — the
pelvis dropping as the character walks — while `hips.rotY` stays −1.5708 against
−1.5711. If the channels were additive those numbers would not land on the bind
values. Groups absent from the bone's mask stay at bind.

## How long is a clip, and does it loop

Two separate questions, and the second one has **two answers** in this game.

`frameCount` is the **number of frames**, indices `0 … N-1`. Measured, not
assumed: `nFrame(dense) == frameCount` on 63,448 of 63,449 dense tracks, and the
last keyframe index equals `frameCount - 1` on 162,573 of 162,604 keyframe
tracks.

Whether the last frame **duplicates** the first is a per-file authoring choice.
The test is cheap — compare the wrap jump against the typical per-frame step:

```
wrap = |v(N-1) - v(0)|              distance jumped when returning to the start
step = median |v(i+1) - v(i)|       distance covered in an ordinary frame
r    = wrap / step
```

The distribution is sharply **bimodal** — over a 416-file sample, 120 files sit
at `r < 0.02` and 36 at `r ≈ 0.5–2.5`, with only 8 anywhere in between. (The
remaining 252 are one-shot clips, `r > 2.5`: attacks, gestures, reactions.)

| `r` | Meaning | True period |
|---|---|---|
| ≈ 0 | last frame repeats the first | `N - 1` — drop it when looping |
| ≈ 1 | the wrap is an ordinary step | `N` — keep every frame |

Both conventions encode the **same** underlying period, which is the check that
proves the reading:

| File | `frameCount` | `r` | Period |
|---|---|---|---|
| `na000_wkn00_00` | 54 | 1.35 | **54** |
| `na000_wkn00_01` | 55 | 0.00 | **54** |
| `na000_rnn00_00` | 24 | 0.81 | **24** |
| `na000_rnn00_02` | 25 | 0.00 | **24** |
| `an008_wtn00_00` | 60 | 0.81 | **60** |
| `na000_wtn00_00` | 61 | 0.00 | **60** |

Applying either rule globally corrupts half the library: assume `N-1` everywhere
and the `r ≈ 1` clips lose a real frame; assume `N` everywhere and the `r ≈ 0`
clips stutter on a repeated frame. `loop_closure.py` performs the test per file.

## The frame rate is 30

Not assumed — two independent measurements agree.

**Declared.** `.lip` files carry the rate in their header's second field, and it
reads `30.000000` on all 300 files sampled. (§ [08](08-models-geometry.md))

**Physical, and scale-free.** The run cycle `na000_rnn00_00` is 24 frames for
two steps. At 30 fps that is 0.8 s per cycle = **150 steps/min**, which is
ordinary running cadence (real runners sit at 150–180). At 60 fps it would be
300 steps/min, which no human gait reaches. This argument needs no assumption
about world scale, so it stands on its own.

A third check falls out of it: the run's stride is 18.0 units against a
character height of 17.79 units, a ratio of **1.01**, and human running stride
is very close to 1.0× height. That also fixes the world scale at **1 unit ≈
10 cm**, consistent with `MODEL_LOD` switch distances of 300 and 600 units
(30 m and 60 m) and a `CAMERA_CLIP` far plane of 5000 (500 m).

## Locomotion clips carry no root motion

Every locomotion clip animates **in place**. In `na000_wkn00_00` the bones
`nw4r_root` and `reference` sit at exactly `(0,0,0)` for all 54 frames; `hips`
drifts 0.037 units against an excursion of 0.46, which is noise. The same holds
for the run. **Translation is the engine's job, not the clip's.**

The clip does, however, tell you how fast to translate. While a foot is planted
it is stationary on the ground, so in an in-place clip it slides backwards at
exactly the travel speed. The plateau is clean and both feet agree:

| Clip | Period | Stance slide | Distance/cycle | Speed @30 fps | Cadence |
|---|---|---|---|---|---|
| `na000_wkn00_00` | 54 | −0.1808 u/f | 9.8 u | 5.42 u/s (0.54 m/s) | 67 steps/min |
| `na000_wkn00_01` | 54 | −0.3257 u/f | 17.6 u | 9.77 u/s (0.98 m/s) | 67 steps/min |
| `na000_rnn00_00` | 24 | −0.7505 u/f | 18.0 u | 22.51 u/s (2.25 m/s) | 150 steps/min |
| `na000_rnn00_02` | 24 | −0.8002 u/f | 19.2 u | 24.01 u/s (2.40 m/s) | 150 steps/min |

Drive the root at that rate and the feet stay planted; pick a speed by eye and
they skate. `gait.py` measures it, `walk_poc.py` consumes it.

Note the two walk variants share a period but differ 1.8× in speed — the game
has a slow walk and a normal walk on the same cadence, distinguished by stride.

## A trap: the Euler channels are in gimbal lock

`hips.rotY` is a constant ≈ −π/2 in the walk clip, which is exactly the
degenerate configuration for a `Rz·Ry·Rx` decomposition. In it, `rotX` and
`rotZ` become redundant, and the stored curves swing wildly (`rotZ` runs
0.785 → 0.10 → 1.57 within one cycle) while `rotX ≈ −rotZ` cancels them and the
actual orientation stays nearly constant.

Any analysis that compares raw Euler channels — loop closure, drift, symmetry —
will read those swings as real motion and conclude nonsense. **Work in world
space**: compose the skeleton and compare bone positions. Every measurement in
this document does.

## Tools

| Tool | What it does |
|---|---|
| `motion.py` | Parser, curve evaluation, world matrices, skinning matrices |
| `loop_closure.py` | Per-file loop convention test (the `r` above) |
| `gait.py` | Root drift and implied step speed, in world space |
| `gait_period.py` | Period by left/right leg cross-correlation |
| `render_anim.py` | Animated skinned render, GIF or frame strip |

```
python motion.py FILE.motion --bone hips     # dump one bone's curves
python motion.py FILE.motion --pose 12       # every bone's TRS at frame 12
python loop_closure.py "na000_wkn00_*"       # loop convention
python gait.py MODEL.model MOTION.motion --speed
```

Animated skinning uses the two rules of the hybrid NW4R convention from
§ [09](09-skinning.md): a rigid vertex is `W_anim[bone] @ (raw/K)`, a blended
vertex is `Σ w · W_anim[b] · W_bind[b]⁻¹`. At bind pose the second reduces to
the identity, so frame 0 of a still clip must equal the static export — a
useful self-check.
