# 21 — Resolving the indirect calls

The game is C++ with virtual dispatch, and by session 11 that had become the
thing standing in front of everything else. Three separate attempts to find who
calls `atn::ColliTree`'s query methods had failed
([14 — Collision](14-collision.md)), and they failed for a reason no better
pattern was going to fix: at a virtual call site the callee's address is never
written down.

```
lwz   r12, 0(rObj)      load the vptr out of the object
lwz   r12, 0xc(r12)     pick a slot
mtctr r12
bctrl                   nothing here names the callee
```

Searching the bytes cannot answer "who calls this method". But two things *are*
present at the site — the **slot number** and an **expression for the object** —
and both can be recovered by reading the register file instead of the bytes.
That is `tools/vcall_scan.py`.

## Reading the register file

`interpret()` walks a function's instructions in address order carrying a
symbolic value per GPR, so when it reaches `bctrl` it knows what `mtctr` was
fed. Values are small expressions rather than numbers:

| value | meaning | printed |
|---|---|---|
| `('c', 0x807775c0)` | a constant | `0x807775c0` |
| `('in', 3)` | whatever r3 held on entry, i.e. `this` | `r3` |
| `('add', e, off)` | `e + off` | `r3+0x1c` |
| `('mem', e, off)` | `*(e + off)` | `[r3+0x1c]` |
| `('ret', addr)` | the value a call returned | `ret(80695ea0)` |

A virtual call is then a *shape*: CTR fed by `('mem', ('mem', E, N), slot)`,
with the object at `E + N`. The arguments in r3–r10 fall out of the same pass,
which is what makes the *values* passed to a virtual method readable.

Three details decide whether this finds anything at all:

- **N is not always 0.** For a sub-object the compiler folds the `addi` into the
  vptr load, so `lwz r12,0x14b0(r28)` loads the vptr of the object at
  `r28+0x14b0`. Requiring the load to be at offset 0 silently drops those sites.
- **The object is often a return value.** `bl getTree; lwz r12,0(r3)` is a call
  on whatever a getter handed back, so `bl` has to make r3 a `ret(target)`
  rather than unknown.
- **But most "return values" in this binary are not returns at all.** With that
  modelling in place, `ret(...)` was the root of 1,004 shaped sites — and the
  four most common targets were `0x80695e9c`–`0x80695eac`, which are entry
  points *inside* CodeWarrior's `__save_gpr` prologue helper. It touches only
  r11 and r14–r31, so r3 goes straight through it. Treating a call as
  transparent when the callee provably never writes r3 (1,584 functions
  qualify) drops the `ret(...)` roots from 1,004 to **180** — 82 % of them were
  an artefact of the assumption, not data.
- **CodeWarrior spills `this` to the stack** in any function of size. A one-slot
  stack memory — remember what `stw rX,d(r1)` wrote, hand it back on
  `lwz rY,d(r1)` — is needed, and it also removes fake shapes rooted at r1.

Inlining real getters on top of that — read a short function up to its first
`blr`, substitute its return expression into `ret(F, x)` — was written and
measured at **zero** additional call sites resolved, so it is not in the tool.
The 180 survivors return from functions too large to read this way.

The sweep is straight-line, not along the CFG: unsound at joins, deliberately,
because this is a lead generator whose hits get checked. To keep it honest where
that is cheap, the volatile registers are dropped at every join and after every
call, so only what a callee-saved register carries — the `mr r31, r3` that holds
`this` — survives a block boundary. Each site records how many boundaries were
crossed before it, so the clean ones can be preferred.

## Giving the objects a type

A call site says `[r3+0x1c]`, not `ColliTree`. The link is the store a
constructor makes, and [18 — class names](18-dol-classes.md) already supplies
the other half: the vtable pointer an object carries is `class record + 8`, and
method *k* lives at `vptr + 8 + 4k`. So a slot offset converts to a method index
by `(slot − 8) / 4`, and a stored constant that equals some `record + 8`
identifies both the class and the offset it sits at.

```
python vcall_scan.py --vptr Colli
  80057fac in FUN_80057f28    r3+0x000 = atn::ColliTree      <- this IS the constructor
  80057fcc in FUN_80057f28    r3+0x3c+0x000 = atn::LoadColliObject   <- a member at +0x3c
```

**Read the last store, not the first.** A constructor writes the base class's
vtable first and its own last, so taking the first hit types every class as its
own base — `atn::ColliTree`'s constructor reads as `atn::ColliSphere`.

That gives, over the whole text: 1,026 vtable stores in 703 functions covering
553 classes, and from them a **member layout** per class (`--layout`).
`gmk::FragileObject` holds two `atn::ColliTree`s, at +0x4c4 and +0x54c.
Constructors too small to be emitted separately show up inline; the ones that
are real functions are caught instead by `--xref`, which lists direct callers
with their arguments:

```
python vcall_scan.py --xref 0x80057f28
  803f47e0 in FUN_803f47a0    r3=r3+0x4c4      <- gmk::FragileObject::ctor
```

## What it resolves

```
functions given a class     : 5056 of 15955
indirect call sites         : 6505
  with a vtable shape       : 4390
  callee read out of a fixed pointer table : 258
  callee named via the object's class      : 569
  resolved, total           : 827   (12.7 % of all indirect calls)
```

Of the 569 named by class, 567 are calls on `this`, and the handful that are not
come from typed globals and members. That ratio is the honest summary of where
this technique's reach ends.

The two kinds of resolution are not equally strong and are reported apart.

**Exact (258).** `CTR = *(fixed address + slot)` is not a vtable at all but a
plain function-pointer table in a data section, so the callee is simply there to
be read. Checked against Ghidra's function list, **99.6 %** of those targets are
exact function entry points, against a 0.85 % base rate — this class of answer
needs no trusting. (They come from only 15 distinct tables: a handful of hot
dispatchers, called from everywhere.) Tables that live in BSS are filled at run
time and read back as a non-text word; those are reported unresolved rather than
guessed at.

**By class (588).** The object was typed, so the callee is that class's method
*k*. Note what this names: the **statically declared** method. If the object is
really of a derived class, dispatch goes to its override, and the honest reading
of the output is "this call enters `X::v12`'s slot", not "this call runs the
code at that address".

### Typing the containers

The obvious way to widen this is to type what the pointers point at, and there
is a clean rule for it: a constructor returns `this`, so a store of
`bl Y::ctor`'s return value into `this+OFF` says that field holds a Y. Applied
across the binary it yields **four** single-type pointer members and one
polymorphic one — far less than the 1,011 call sites on `[r3+K]` that wanted it,
because members are almost always assigned from a loader or factory rather than
from an inline `new`.

The interesting part is the one that is polymorphic, and it is the reason field
types are collected as **sets**:

```
python vcall_scan.py --fields
-- POLYMORPHIC --
  <character class> +0x0f80
      chr::ControlAppearCoffin   chr::ControlAppearEnd   chr::ControlAppearSkelton
      chr::ControlDamageLastOne  chr::ControlDropDownQuadruped
      chr::ControlGuarded        chr::ControlMountleQuadruped
      chr::ControlOneMotionTarget chr::ControlPushedAvoid chr::ControlShoot  …
```

That field is the character's **current control state**, and the state machine
is implemented as a polymorphic object swapped into one pointer. A
first-writer-wins rule would have named it after whichever `chr::Control*` came
first and then resolved a hundred call sites confidently and wrongly. Even a
single-type field is not trusted unless it was observed twice: the same state
pointer shows up under two different owner names, and in one of them only one
assignment is visible. Requiring two agreeing observations costs eight
resolutions and removes that entire class of wrong answer.

Propagation of `this` through direct calls runs to a fixpoint but drops every
function that two different classes reach — **96 of them**. Those are functions
a first-writer-wins rule would have silently mis-named.

Function-to-class comes from three sources, kept apart in `--names`:

| evidence | functions |
|---|---|
| the function is in a class's vtable | 4,301 |
| the function stores that class's vtable at `this+0` (a constructor) | 310 |
| a method of X calls it with `r3` unchanged (one round of propagation) | 536 |

One round only. Each extra round multiplies the chance of carrying a wrong name
along, and there is no measurement here that would catch it.

## What it says about the collision mask — a measured negative

The bits of the collision exclusion mask still have no names, but the shape of
the question has changed, and that is worth recording precisely so the next
attempt does not start from scratch.

- Each of `atn::ColliTree`'s three query implementations appears **exactly once
  in the whole binary**, in the vtable. There is no direct call to any of them,
  and none to the octree walker beneath them either.
- All five collider classes (`ColliSphere`, `ColliBox`, `ColliCapsule`,
  `ColliObject`, `ColliTree`) put their query at the *same* slot 1, and no other
  class among the 704 has a query in its vtable. So a call is a query only if
  the object is a collider.
- Sweeping **every** `bctrl` in the DOL produced **no** call at slot 1 on an
  object typed as a collider, and none anywhere passing a constant mask with
  `surfFilter = -1`. The 183 KB of text Ghidra leaves without functions was
  swept separately: 107 indirect sites, 15 of them at slots 1–3, none of them a
  collider call either.
- The `ColliTree`s that do exist belong to `gmk::` classes
  (`FragileObject`, `HealPoint`, `Trap`, `PigeonManager`, `RotaryRoom`,
  `PlayEffect`, plus one class whose constructor at `0x803f1c38` RTTI does not
  name), and **none of those classes ever calls a method on its own tree**. Whoever queries them reaches them from somewhere else.

Two candidate explanations survive, and they are cheap to tell apart. Either the
object arrives out of a container or from a call this cannot see through — 180
shaped sites are still rooted at `ret(...)`, and 983 have a CTR shape that is not
a vtable load at all — or the receiver is one of the 2,545 sites rooted at `r3`
whose enclosing class is not among the 5,147 that have one. The layout table
covers only the classes that own an object with a vtable; widening it, most
plausibly by typing the containers, is the next instrument.

One thing this did close: the code is **not** somewhere else. The disc carries a
single RSO, `LastWorld_tools.rso`, so gameplay is all in `main.dol`.

## A correction to the 28 %

[18 — class names](18-dol-classes.md) reported that 28.3 % of vtable pointers
are exact Ghidra function entry points and called that a floor, understated
because Ghidra could then only see 44 % of the text. With the Gekko language
installed it sees 97.6 % and the number is **28.4 %** — unchanged. The
explanation was wrong.

Splitting the pointers by what the target looks like says what is really going
on:

| target's first instruction | count | is a Ghidra entry point |
|---|---|---|
| `stwu r1,-N(r1)` — a real prologue | 3,737 | **98.5 %** |
| `li r3` / `blr` — one-line virtuals | 4,428 | 0.1 % |
| anything else | 4,904 | 0.6 % |

Ghidra creates functions from *direct calls*. A trivial override that only ever
appears in a vtable is never directly called, so it never becomes a function.
That is what 71 % of the slots are: a third of them one-line stubs, the rest
code Ghidra never turned into a function either. Among the targets that do look
like real functions the hit rate is 98.5 %, which is a far stronger statement
than the 28 % ever was.

The lesson is the size of the correction rather than its direction: a plausible
cause had been attached to a number without checking that removing the cause
moved it. It cost minutes to test and the answer was "not at all".

## Usage

```
python vcall_scan.py --vptr [name]        constructors and members: class @ this+off
python vcall_scan.py --layout [name]      the recovered member layout
python vcall_scan.py --fields             pointer members, polymorphic ones first
python vcall_scan.py --vcalls             every virtual call site, by slot
python vcall_scan.py --slot 0xc --args 7,8   sites at a slot with given args known
python vcall_scan.py --xref 0x80057f28    direct callers, with their arguments
python vcall_scan.py --at 0x803f1c38      every call one function makes
python vcall_scan.py --resolve            name the callees, with the counts above
python vcall_scan.py --names out.csv      function -> class, with the evidence
python vcall_scan.py --csv out.csv        every indirect site, machine readable
```

Needs `ghidra_out_gekko/functions.txt` — see
[19 — Teaching Ghidra Gekko](19-gekko-sleigh.md). Pass `--funcs <path>` to use
another export.
