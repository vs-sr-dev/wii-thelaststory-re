# 18 — `main.dol` still knows its own class names

The retail `main.dol` has no symbol table. Every one of its 14,530 functions
comes out of Ghidra as `FUN_8023c0c0`, and the earlier notes in this project
recorded it as "stripped, no symbols".

That is true of the *symbol table* and false of the binary. It was built with
**RTTI left enabled**, so the C++ type-name strings survive — and each name sits
immediately in front of that class's **vtable**.

```
80783c18: 8074300c  ──▶ "atn::EffectManager"
80783c1c: 80783bf8      back pointer (just past the previous record's methods)
80783c20: 80783c58      next record
80783c24: 00000000
80783c28: 8023c080  ─┐
8023c2c:  8023c0c0   │
   …                 ├── 9 virtual methods
80783c48: 8023fd90  ─┘
```

So `FUN_8023c080` is not anonymous: it is `atn::EffectManager`'s first virtual
method. **704 records** carry **13,069 code pointers** between them.

## Why these are really vtables

The failure mode is obvious — a string pointer followed by words that merely
look like addresses. Two independent tests answer it (`dol_classes.py --proof`).

**1. Against Ghidra's own function list.** 28.3 % of the pointers are exact
function *entry* points, against 0.59 % for the same number of randomly chosen
4-aligned text words — a **37× lift**. The 28 % is a floor rather than the true
rate: Ghidra defines functions over only **44 % of this DOL's text**, because its
stock PowerPC language cannot disassemble the Wii's paired-single instructions
(measured in [07 — main.dol in Ghidra](07-main-dol-ghidra.md)). A correct pointer
into one of those regions counts here as a miss.

**2. Against the instruction stream, needing no symbols at all.** What is the
first instruction at the target?

| First instruction | vtable pointers | random text words |
|---|---:|---:|
| `stwu r1,-N(r1)` — real prologue | 28.59 % | 0.41 % |
| `li r3, N` … — one-line virtual | 25.50 % | 1.12 % |
| `blr` — empty virtual | 8.39 % | 0.93 % |
| `lwz` first — getter | 10.06 % | 6.73 % |
| anything else | 27.46 % | 90.43 % |

**62.5 % land on a prologue or a recognisable stub, against 2.8 % by chance.**
The bulge in the middle rows is itself the argument: a vtable is largely trivial
overrides that return a constant or do nothing, and random code is not.

## What is in there

Past the `std::` and `boost::` template instantiations, the engine names its own
subsystems — including several this project had only ever seen from the outside:

| Class | Bearing on this project |
|---|---|
| `ColliAttrManager` | the name that led to `boot/colli_attr_table.csv` and the collision **surface types** — see [14 — Collision](14-collision.md) |
| `atn::EffectManager`, `SkillEffectManager`, `atn::LoadEffect` | the effect runtime; [16](16-effects.md), [17](17-eff-binary.md) |
| `CharaManager<PlayerTask>`, `CharaManager<EnemyTask>`, `CharaManager<NpcTask>` | one template, three instantiations — the character system |
| `ChaseManager`, `ChaserNpc`, `CrowdManager`, `CrowdSimulation` | pursuit and crowd behaviour |
| `Event::ActionCameraEffect`, `Event::ActionEffectPlay`, `Event::EffectData` | the event/cutscene action set |
| `AI::Script::AI_*` | **60-odd AI behaviours, named after what they do** |

The AI names are the most immediately readable thing in the whole binary,
because whoever wrote them was describing behaviour, not types:

```
AI::Script::AI_fr_follow_player        AI::Script::AI_em_sword_attack01
AI::Script::AI_np_wait_reaction        AI::Script::AI_em_archer_attack02
AI::Script::AI_fr_runaway              AI::Script::AI_magic_cure01
AI::Script::AI_fr_warppointescape      AI::Script::AI_sword_leaderguard01
AI::Script::AI_jackal01                AI::Script::AI_quark01
```

`fr_` is a friend/party member, `em_` an enemy, `np_` an NPC — and `AI_jackal01`
and `AI_quark01` are named for *Jackal* and *Quark*, the Japanese codenames of
Lowell and Dagran (see [03 — Text & dialogue](03-text-dialogue.md)). The
internal naming is consistent right across text, audio and code.

## Limits

Record detection is a **heuristic**: a data word pointing at a printable string,
followed by at least two text pointers. It over-collects. Strings such as `END`,
`rightfrontarm2` or `tt009` are state and bone names that happen to precede
pointer runs, not classes. Filter on `::`, or read the name, before trusting an
individual record.

The `+0x08` field does chain to the next record, but only within one blob — it
is not a global list, so it cannot be used to enumerate every class. Walking it
from `atn::EffectManager` reaches three records and stops.

Nothing here recovers *method names* or argument types. What it recovers is
which class a function belongs to and its slot number, which is normally enough
to work out the rest by reading the function.

## Tools

```
python dol_classes.py --engine     # class records, minus std:: / boost:: noise
python dol_classes.py Effect       # filter by substring
python dol_classes.py --proof      # the two tests above
python dol_classes.py --csv out.csv
```

Needs `extract/sys/main.dol`; `--proof`'s first test also wants
`ghidra_out/functions.txt` from [07 — main.dol in Ghidra](07-main-dol-ghidra.md),
and skips it if absent.
