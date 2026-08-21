# 22 — Who reads offset N of a struct?

Session 12 left one group of formats unfinished. The 22 `.eff` curve channels
were grouped and proved ([20](20-eff-channels.md)), but three of the groups had
structure and no name, and the note left for the next session said what to do
about it: the missing thing was not another pass over the data but the ability
to ask *which code reads a given field of a runtime struct*, and that was a
small amount of work on top of the register-file interpreter already written
for the indirect calls ([21](21-indirect-calls.md)).

This page is that tool, the two defects in the interpreter it exposed, and the
answer it produced.

## Why the question is hard to ask

Ghidra will list the readers of a global. It will not list the readers of a
struct member, because a struct member is not a thing the binary records:

```
lfs   f1, 0x98(r30)
```

There is no type here. The programmer knew `r30` was a particle; the machine
only knows it is a register. So "find the readers of `particle+0x98`" collapses
into "find every `0x98` in the binary", which in `main.dol` is thousands of
unrelated hits and no way to sort them.

But `vcall_scan.interpret()` already knows what `r30` is. It walks a function
keeping a symbolic value per GPR, and represents a memory read as
`('mem', base, offset)`. Hanging a callback on the loads therefore turns the
whole text into a table of

```
(function, base expression, offset, kind)
```

Grouping that by `(function, base)` gives the set of offsets one pointer was
used at, in one place. That is a **recovered struct usage** — the closest thing
to a type declaration the stripped binary still contains. `tools/field_xref.py`
is a hundred lines around that idea.

### The discriminator is co-access, not the offset

`0x98` on its own means nothing; any class can have a field there. A base that
is read at `0x98` **and** `0xbc` **and** `0xa4` is a particle, because nothing
else has that combination. `--fingerprint` ranks every `(function, base)` pair
by how many offsets of a stated set it touches.

One caveat worth stating, because it cost time: a constructor or a `memcpy`
sweeps a whole struct in a contiguous run and so satisfies *any* fingerprint by
brute force. Those bases dominate the ranking and mean nothing. `--max-offsets`
drops them — a base that touches six fields and stops is making a claim; a base
that touches 245 consecutive words is not.

### A free result: `r2` and `r13` are the float pool

CodeWarrior keeps float literals in the small data area, and this binary's
`r2 = 0x808885a0` and `r13 = 0x808856c0` are known
([07](07-main-dol-ghidra.md)). So a load off those registers is not an unknown
field at all — it is a *constant*, and the tool prints its value. `--consts`
dumps the pool ranked by how many functions use each value, which is a readable
summary of what a binary computes:

```
 3293  0.0
 2596  1.0
  899  0.10000000149011612
  588  0.5
  572  1.1920928955078125e-07     <- FLT_EPSILON
  484  1.5707963705062866         <- pi/2
  264  3.1415927410125732
  204  6.2831854820251465         <- 2*pi
  148  255.0
  107  0.01745329238474369        <- degrees to radians
```

That turned the standing question "where does the colour `/255` happen" from a
control-flow hunt into a lookup: `--const 0.003921569` returns 20 functions, and
exactly two of them are in the effect module.

## Two defects in the interpreter, both found by the tool finding nothing

Session 12 ended with a corollary: when the new scanner reports nothing, suspect
the model before the target. It applied twice more here, and both times the
symptom was identical — a large, obviously interesting function came back with
almost every base printed as `?`.

**1. Every argument but `this` died in the prologue.** `interpret()` dropped all
volatile registers at every `bl`, with one exception carved out for `r3` so the
receiver of a virtual call would survive. But CodeWarrior opens a large function
with `bl __save_gpr`, which touches only `r11` and the callee-saved bank:

```
8023193c  stwu  r1, -0x100(r1)
80231948  addi  r11, r1, 0xd0
80231964  bl    __save_gpr          <- r4..r10 wiped, in the model only
80231968  lfs   f3, 0x14(r5)        <- r5 is already '?'
```

A five-argument function loses four of its arguments before using one of them.
The fix generalises the `r3` exception: `volatile_writes()` measures which
volatile registers a small leaf function actually writes, and `interpret()`
preserves the rest across a call to it. In `FUN_8023193c` the unknown bases go
from **330 of 393 to 9**.

**2. The paired-single loads were not decoded at all.** `psq_l`/`psq_st` carry a
**12-bit** displacement — the top four bits are the GQR index and the `W` flag —
so they cannot be decoded with the usual 16-bit field, and they were simply
falling through every branch. They are also precisely the instructions the
effect, vector-maths and animation code is written in, which is the same
observation that motivated installing the Gekko language in the first place
([19](19-gekko-sleigh.md)). Leaving them out makes the interesting functions
look like they touch nothing.

### The fix pays for itself elsewhere

Both changes are in `interpret()`, so `vcall_scan.py` gets them too. Its own
published measurement moves:

| | session 12 | with the fix |
|---|---|---|
| functions given a class | 5,056 | **5,401** |
| indirect sites with a vtable shape | 4,390 | **5,218** |
| callee named via the object's class | 569 | **625** |
| resolved, total | 827 (12.7 %) | **883 (13.6 %)** |

The `+828` on vtable shapes is the argument-preservation fix: an object
expression that used to be `?` now resolves.

Part of the same defect was a plain ordering bug — the argument captured for a
call's return tag was read *after* the volatiles had already been cleared, so it
was always `?`. Call arguments print for real now.

## What it answered

Pointed at the effect module, the tool separates the two structs that had been
tangled together in the decompiler output. In `FUN_8023193c`, `r5` carries the
**particle** and `r4` the **620-byte emitter record** — and it says so by their
offset sets, not by a variable name a decompiler guessed:

```
--- base r5 ---                    --- base r4 ---
  +0x0098  lfs x11, stfs x7          +0x0240  lwz     @80232004
  +0x009c  lfs x6,  stfs x9          +0x0244  lfs     @80232048
  +0x00a0  lfs x10, stfs x7          +0x0248  lfs     @80232028
  +0x0084  lfs x5,  stfs x2          +0x024c  lfs x2  @8023208c
  +0x0180  lfs, stfs                 +0x0250  lfs x4  @80232198
  +0x018c  stfs                      +0x0254  lfs     @802322fc
                                     +0x0258  lfs     @8023205c
```

The left column is a vector being read and written many times next to a
position; the right column is seven fields at the tail of a record, each read
once. Reading the code at those addresses names the group:
`particle+0x98` is the particle's **velocity**, and the seven fields are a
gravity/bounce/friction/rolling block. That result, and the check that confirms
it against all 8,637 shipped emitters, is in
[20 — The 22 `.eff` channels](20-eff-channels.md).

## Usage

```
python field_xref.py --offset 0x98              # who touches +0x98
python field_xref.py --offset 0x98 --near       # ...and what else, same base
python field_xref.py --fingerprint 0x98,0xa4,0xbc --min 3 --max-offsets 70
python field_xref.py --fn 8023193c              # struct views of one function
python field_xref.py --const 0.003921569        # who loads a float constant
python field_xref.py --consts                   # the float pool itself
python field_xref.py --csv out.csv              # every access, machine readable
```

The whole text is 307,000 memory accesses over 15,955 functions and takes about
eight seconds to sweep, so every mode re-scans from scratch rather than caching.

## The limit, stated

The interpreter is straight-line and drops volatiles at joins, so a base that is
computed inside a loop from an index — the shape a draw loop over an array of
particles takes — still comes out `?`. That is why this page names one group and
not three: `particle+0xcc` and `particle+0xdc` are **written** by the update and
read by nothing this tool can see. Their consumer is either behind an
unresolvable base or outside the reach of a per-function sweep. Knowing *that*
is worth something too — it says the remaining two groups will not fall to
another pass of the same technique.
