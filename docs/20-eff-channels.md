# 20 — The 22 `.eff` curve channels

[17 — `.eff` binary](17-eff-binary.md) proved the *shape* of the animated part
of an effect: each emitter carries a 176-byte table of **22 pairs**
`(key count, offset)`, and each key is `(float t, float value)` with `t` on the
particle's normalised life — first key at 0.0 and last at 1.0 on all 36,705
curves. What no amount of staring at the data produced was the **meaning** of
any single channel. A promising data-only attempt (does `curve(0)` equal the
matching static emitter parameter?) turned out to be an artifact of the values
0.0 and 1.0 and was withdrawn.

The channels are settled now, by reading the simulation code. That became
possible only after Ghidra learned the Gekko instruction set —
[19 — A Gekko SLEIGH for Ghidra](19-gekko-sleigh.md).

Tool: [`eff_channels.py`](../tools/eff_channels.py) (`--map`, `--proof`,
`--profile`, `--statics`).

## The evaluator

`FUN_8023329c`, 172 bytes, the only function in the binary that begins with
`mulli …, 0xb0` — which is how you index an array of 22×8-byte tables:

```c
float eval(float t, float base, int channel, int emitter, Eff *e, int mul)
{
    Curve *tab = e->curveTables + emitter * 0xb0;   // 0xb0 = 22 * 8
    n = tab[channel].count;
    p = tab[channel].keys;                          // (float t, float v)
    /* walk the keys for the bracket p[i].t <= t <= p[i+1].t */
    v = p[i].v + (t - p[i].t) / (p[i+1].t - p[i].t) * (p[i+1].v - p[i].v);
    return mul ? v * base : v + base;
}
```

Three things fall out of six lines:

- interpolation is **linear**, not Hermite — unlike `.motion`
  ([10 — animation](10-animation.md)), which does carry tangents;
- if no bracket matches, `v` stays 0.0, so a curve that does not cover `t`
  contributes nothing rather than holding its last value;
- the result is **combined with a base**, by addition or multiplication
  depending on a flag in the emitter record. The curve does not simply *become*
  the value.

## The `A*4` table at +0x28 is a bitmask

Session 8 filed the three `A*4` tables under "unknown". One of them is not:
every call to the evaluator is guarded by

```c
if (eff->tab28[emitterIndex] & BIT) { ...evaluate the curves... }
else                                { ...use a static field instead... }
```

so `tab28` is a **per-emitter bitmask of which channel groups are keyed**, and
the 22 channels are organised into **8 groups addressed by 9 bits**:

| bit | channels | drives | particle | static | rate |
|---|---|---|---|---|---|
| `0x001` | 12,13,14 | emitter displacement (x,y,z) | — | `0x0a4` | — |
| `0x002` | 15,16,17 | rotation, degrees | `0x0a4` | `0x0e0` | — |
| `0x004` | 0,1,2 | scale (x,y,z) | `0x0b0` | `0x11c` | `0x134` |
| `0x008` | 7,8,9 | world-space vector, unnamed | `0x098` | `0x158` | — |
| `0x010`/`0x020` | 3,4,5 + 6 | colour R,G,B + A | `0x0bc` | `0x194` | `0x1b4` |
| `0x040` | 18 | world-space scalar, unnamed | `0x0cc` | `0x1e4` | `0x1ec` |
| `0x080` | 19,20,21 | rotation with spin rate, degrees | `0x0d0` | `0x1f8` | `0x210` |
| `0x100` | 10,11 | pair, no static fallback | `0x0dc` | — | — |

*static* and *rate* are offsets into the 620-byte emitter record; *particle* is
the offset in the runtime particle struct the group is written to. When a bit is
clear the engine reads the static field, and in the per-frame path **integrates**
its companion rate: `p[field] += dt * emitter[rate]`. That is what a rate field
is for, and it is why some groups have one and others do not.

Colour takes two bits, tested by *population count*: one bit set means alpha
(channel 6) alone is keyed, both bits mean RGB is keyed as well. So RGB is never
animated without alpha — a constraint of the format, not a coincidence of the
data.

## The proof

The map above is a claim about code. Turned around, it is a falsifiable claim
about **data**: the bit must be set exactly when those channels carry keys.
Nothing in the container enforces that — a file with the bit clear and keys
present would parse fine.

```
$ python eff_channels.py --proof

prediction                                              holds   fails
-----------------------------------------------------------------------
bit 0x001 <-> channels (12, 13, 14)                     8,637       0
bit 0x002 <-> channels (15, 16, 17)                     8,637       0
bit 0x004 <-> channels (0, 1, 2)                        8,637       0
bit 0x008 <-> channels (7, 8, 9)                        8,637       0
bit 0x040 <-> channels (18,)                            8,637       0
bit 0x080 <-> channels (19, 20, 21)                     8,637       0
bit 0x100 <-> channels (10, 11)                         8,637       0
bits 4|5 popcount ==2 <-> rgb (ch 3,4,5) keyed          8,637       0
bits 4|5 popcount >=1 <-> alpha (ch 6) keyed            8,637       0
-----------------------------------------------------------------------
TOTAL                                                  77,733       0

emitters with a bit outside 0x1ff set: 0 (the mask uses exactly 9 bits)
```

**77,733 / 77,733**, and no emitter ever sets a bit outside the nine. The
grouping shows up in the data independently too: the channel co-occurrence
matrix (`--profile`) is block-diagonal on exactly these groups, at 100 %.

## Two medians that name two groups

The static fallback must live on the same scale as the curve it replaces, so the
statics are a second, independent reading of what a group means — and they come
from the data, not from the code (`--statics`, over 8,637 emitters):

| field | median | reading |
|---|---|---|
| ch6 static (`0x1a0`) | **255.0** | an alpha, on 0–255 |
| ch3/4/5 statics (`0x194`) | 205 / 180 / 200 | RGB on the same scale |
| ch0/1/2 statics (`0x11c`) | **1.0 / 1.0 / 1.0** | scale factors, default identity |
| ch15/16/17 statics (`0x0e0`) | 0.0, range ±180…360 | degrees, default none |
| ch19/20/21 statics (`0x1f8`) | 0.0, range ±180…294 | degrees, default none |
| ch12/13/14 statics (`0x0a4`) | 0.0, range ±1000…1800 | world units, default none |

A default alpha of exactly 255 and a default scale of exactly 1 are what those
two things *are*. Neither is forced by the format, and neither was visible
before the code said which field belonged to which channel.

The displacement group has a third, structural confirmation. In the
emitter-level function `FUN_802301ec` channels 12,13,14 are evaluated **twice**,
at `t` and at 0, and the **difference** is taken, rotated by the emitter's
matrix, scaled, and added to the translation column of that matrix. A quantity
that is only meaningful as a delta from its own value at birth, and that ends up
in a matrix's translation, is a displacement.

## What this corrects

Session 8 concluded that a curve **replaces** its static parameter, after the
`curve(0) == static` test failed. That is right, and now it has a mechanism: the
bitmask *selects* between them, so the two are alternatives and are never both
in play — which is exactly why no correlation between them could ever be found.
The failed test was not measuring a weak signal; it was measuring something that
does not exist.

Also corrected: `tab28` is no longer "one of three unknown `A*4` tables".

## Still open

- **Channels 7,8,9 and 18.** Both are world-space (multiplied by the same global
  scale as the size group) and both integrate a rate when unkeyed. Their
  statics are small and centred on 0. Position offset, velocity, and trail
  length all remain plausible; the particle fields they feed (`0x098`, `0x0cc`)
  need chasing into the draw path to settle it.
- **Channels 10,11.** A pair with no static fallback — when the bit is clear
  both are simply 0. UV scroll is the obvious guess and is not yet evidence.
- **The colour normalisation point.** Colour is authored on 0–255, but the
  runtime clamps the particle's colour to `[0,1]` (unless emitter flag
  `0x4c & 2` is set) after combining the curve with a per-particle base at
  `0xf0`. Where the ÷255 happens is not yet pinned down; the group's identity
  does not depend on it.
- **The two rotation groups** (15,16,17 and 19,20,21) are both angles in
  degrees; which is the billboard and which the texture is not established.
