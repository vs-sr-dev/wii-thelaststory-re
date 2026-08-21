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
| `0x008` | 7,8,9 | **velocity (x,y,z), world space** | `0x098` | `0x158` | — |
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


---

# Session 13 — group {7,8,9} is the particle's velocity

Found with `tools/field_xref.py`, the field-level cross reference described in
[22](22-field-xref.md). The tool separates the two structs that
`FUN_8023193c` juggles — `r5` is the particle, `r4` the 620-byte emitter record —
and shows `particle+0x98` being read eleven times and written seven, next to a
position. Reading the code at those addresses settles it.

## The integration

At `0x80231c8c`:

```
predicted_y = (dt * particle[0x9c] + particle[0x84]) - radius
```

A quantity multiplied by `dt` and added to a position is a velocity, and
`0x98/0x9c/0xa0` are the three channels of group `0x008`, in order. That alone
names the group. What follows names the seven fields around it.

## The physics block at the tail of the emitter record

The velocity is only interesting because of what the update does with it. Guarded
by a flag, and only when the group is *not* keyed:

| record | address | what the code does with it |
|---|---|---|
| `0x240` | `80232004` | gates the entire block |
| `0x244` | `80232048` | subtracted from `vy` each frame, × `dt` × global scale |
| `0x248` | `80232028` | subtracted from the predicted `y` before the floor test, added back after — a **radius** |
| `0x24c` | `8023208c` | on contact the velocity is multiplied by **minus** this |
| `0x250` | `80232198` | scales `vx` and `vz`, with a clamp that zeroes them if the scaling flipped their sign |
| `0x254` | `802322fc` | multiplies the accumulated rolling angle |
| `0x258` | `8023205c` | the plane the test is against |

Multiplying a velocity by a negated coefficient on contact is a **bounce**;
scaling the two horizontal components with a guard against reversing them is
**friction** — that clamp exists for no other reason. And at `0x80232304`:

```
particle[0x180] += emitter[0x254] * 2*pi * (|v_horizontal * dt| / (pi * 2 * radius))
```

The `2*pi` cancels: the angle grows as **distance ÷ radius**, about an axis
computed as the cross product of the horizontal velocity with `(0,-1,0)`, then
normalised and stored at `particle+0x184`. That is rolling, written the way
rolling is written. The constants are read straight out of the small-data pool
and are exactly `pi`, `2.0` and `2*pi` (`r2-0x54c4`, `r2-0x54c8`, `r2-0x5498`).

## The check: `eff_channels.py --physics`

Seven plausible-looking floats are not a result. The test is not that the values
are sensible — almost any float is sensible — but that they behave like the
fields of a dialog box whose checkbox is off. If that is what they are, then
with the flag clear nobody edited them and they should collapse onto a single
authoring default; with it set they should fan out. Nothing in the file format
produces that.

```
8,637 emitters

the enable flag is a flag: distinct u32 values at +0x240 -> {0: 8417, 1: 220}

   off field        distinct       min       max  default when off (share)      spread when on
---------------------------------------------------------------------------------------------
0x0244 gravity            24        -1         2  0.5       51.9%   0.3x68 0.2x25 0.1x17 0.5x17
0x0248 radius              7         0        20  0.5       99.2%   0.5x138 0.1x76 1x2 10x2
0x024c restitution        14         0       1.1  0.7       97.3%   0.3x96 0.7x40 0.1x29 0.2x21
0x0250 friction            6         0         1  0.1       99.0%   0.1x114 0.03x76 0x18 0.05x9
0x0254 roll gain          13         0        33  1         98.4%   1x91 0x45 3x26 0.2x17
0x0258 floor Y             7      -100        70  0         99.9%   0x212 70x4 -10x2 -8x1
```

The flag takes **exactly two values** across 8,637 emitters. Five of the six
fields sit on one value in 97–99.9 % of the emitters that have the flag clear,
and fan out when it is set. The defaults name the fields on their own: a
restitution of 0.7, a friction of 0.1, a radius of 0.5, a floor at 0, and a roll
gain of exactly **1.0** — the same argument that identified the scale group in
session 10, a multiplier whose default is the identity.

One prediction made here was **wrong and is worth recording**: that the physics
fields would be *zero* when the flag is clear. They are not — 8,364 of 8,417
carry a gravity value with physics switched off. The authoring tool writes its
defaults into every emitter regardless. Splitting by the flag instead of testing
for zero is what turned a failed prediction into a stronger result.

## Two supports from the data alone

Neither uses the DOL.

**The emitters that key the group.** Across the 33 emitter names used 25 times or
more, the group is keyed on 17.7 % of all emitters but on:

| name | reading | keyed |
|---|---|---|
| `火花` | sparks | 93.5 % (29/31) |
| `土煙` | kicked-up dust | 86.4 % (38/44) |
| `石` | stones | 85.1 % (40/47) |
| `煙` | smoke | 76.6 % (72/94) |

Sparks, flying stones and dust kicked off the ground are what a per-particle
velocity is for, and stones are what a bounce-and-roll block is for. The authors'
own naming agrees with the code.

**Which component is vertical.** Over the shipped curves, channels 7 and 9 end at
exactly 0 in **87.3 %** and **76.7 %** of cases; channel 8 does so in **12.0 %**.
Two components that reliably decay to nothing and one that does not is what
friction acting on the horizontal plane looks like — and it puts the vertical
axis at channel 8, i.e. `particle+0x9c`, which is the component the code
subtracts gravity from and tests against the floor. The data and the code pick
the same axis without being told.


# The third `A x 4` table: which groups are inert

Session 8 recorded three `A x 4` tables and explained none of them. Session 10
named the first (`+0x28`, the keyed-group mask). This is the third, at file
header **`+0x40`**, and it is read in exactly one place: `FUN_8023193c`, wrapped
*around* the `tab28` test.

```
if (tab40 == NULL || (tab40[e] & bit) != bit) {     <- if set, skip everything
    if (tab28[e] & bit28)  evaluate the curve
    else                   integrate the rate
}
```

A note on reading the runtime object: the loader keeps the header from `+0x10`
onward, so the code's `eff+0x18` is file header `+0x28` and `eff+0x30` is file
header `+0x40`. Two independently known tables fix that shift — `eff+0x1c` is
the curve-table pointer the evaluator uses, which is header `+0x2c`.

`tab40` numbers the groups its own way, and the difference is informative:

| tab40 bit | tab28 | group | read by the DOL? |
|---|---|---|---|
| `0x01` | `0x001` | 12,13,14 emitter displacement | **never** |
| `0x02` | `0x002` | 15,16,17 rotation | yes |
| `0x04` | `0x004` | 0,1,2 scale | yes |
| `0x08` | `0x008` | 7,8,9 velocity | yes |
| `0x10` | `0x010`\|`0x020` | 3,4,5,6 colour | yes |
| `0x20` | `0x040` | 18 | yes |
| `0x40` | `0x080` | 19,20,21 spin | yes |

Colour costs `tab28` two bits and costs this table one. Channels 10,11 get no
bit **at all** — and they are the one group with neither a static nor a rate, so
there is no per-frame work to skip. The table has a bit exactly where there is
something to skip.

Six of the seven pairings fall out of the data on their own: for each `tab40`
bit there is exactly one `tab28` bit it never co-occurs with, and it is the
partner above. The colour pairing comes from the code, which reads `tab28` and
takes the popcount of bits 4 and 5 immediately inside the guard.

## What the bit means, and the check that decides it

Two readings fit the code equally well — "freeze this group at its birth value"
or "this group has no per-frame work at all". They differ in something
checkable: only the second requires the group's **rate** field to be zero, and
nothing in the file format ties this table to those floats.

```
 tab40 group                        set  also keyed   rate==0  (both clear) rate==0  in DOL
--------------------------------------------------------------------------------------------
   0x1 12,13,14 displacement      8,376           0         -                     -  NO
   0x2 15,16,17 rotation          6,500           0         -                     -  yes
   0x4 0,1,2 scale                3,209           0    100.0%                 10.1%  yes
   0x8 7,8,9 velocity             6,001           0         -                     -  yes
  0x10 3,4,5,6 colour               641           0    100.0%                 25.0%  yes
  0x20 18                         6,104           0    100.0%                  3.2%  yes
  0x40 19,20,21 spin              7,274           0    100.0%                 68.4%  yes
--------------------------------------------------------------------------------------------
 TOTAL                           38,105           0    100.0%

emitters setting a tab40 bit outside 0x7f: 0 of 8,637
```

**38,105 set bits and not one co-occurs with its `tab28` partner.** Where the
group has a rate, that rate is **0.0 in 100 % of the 17,228 cases** the bit is
set, against 3–68 % when both masks are clear. No emitter sets a bit outside the
seven. So `tab40` is not a freeze flag: it is a **work-skipping mask**, written
by the authoring tool exactly when a group's per-frame update would have been a
no-op, and every group therefore has three states — keyed, rate-driven, inert.

And bit `0x01` is written by the tool on 8,376 of 8,637 emitters and read by
**no code in `main.dol`**. That is the same shape as the third record type the
loader supports and the game never uses ([17](17-eff-binary.md)): the exporter
is more general than this engine.

## Still open

- **Channel 18** (`particle+0x0cc`) and **channels 10,11** (`particle+0x0dc`).
  Both are **written** by the update and read by nothing `field_xref` can
  resolve, so the answer is not another sweep of the same kind — see the limit
  stated at the end of [22](22-field-xref.md). What is known: 18 is a world-scaled
  scalar that integrates rate `0x1ec` and is then damped by `0x1f0` (median 1.0);
  10 and 11 are a pair with no static, 97 % and 91 % of their key values inside
  `[-1,1]`. The one name enriched on the 10/11 group above threshold, in the
  whole vocabulary, is `軌跡` — *trail* — at 35.7 % against a 12.7 % base. That is
  a lead, not evidence.
- **`tab30`, the table at header `+0x30`.** Value 1 in all 8,637 records and
  read by no code in `main.dol`. It carries no information, so there is nothing
  to recover; recorded here so nobody spends a session on it.
- **The colour normalisation point.** Narrowed: `--const 0.003921569` finds the
  20 functions in `main.dol` that load 1/255, and exactly two are in the effect
  module (`FUN_80228ca0`, `FUN_8023193c`). Not yet pinned to an instruction.
- **The two rotation groups** (15,16,17 and 19,20,21) are both angles in
  degrees; which is the billboard and which the texture is not established.
