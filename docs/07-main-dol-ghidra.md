# 07 — `main.dol` in Ghidra

The executable was analysed in **Ghidra 12.1.2** (headless). Two practical
obstacles shaped the approach:

1. The **DOL format has no native Ghidra loader**.
2. Ghidra 12 **removed Jython**, so scripting must be Java (or PyGhidra).

The loader is therefore a Java GhidraScript,
[`DolLoad.java`](../tools/ghidra_scripts/DolLoad.java), which reconstructs the
**7 text + 11 data sections** at the addresses in the DOL header (entry
`0x80004050`, language `PowerPC:BE:32:default`).

Result: **14,530 functions**, 11,810 strings. The build is stripped (no symbols),
but the path strings embedded for the pack loader give the anchors needed to
navigate.

## Reconstructed boot call-graph

```
FUN_8047a4c8  (init)
   └─ loads /config.ini            FUN_80187c44
   └─ registers pack loaders
        ├─ FUN_8046f014            the 3 archives in pack/
        └─ FUN_8046f2c4            the 18 archives in preload/
   └─ pack open                    FUN_8046fa18 / FUN_8046ef08
        └─ CRC path hash           FUN_800dc880   (see docs/02)
```

`FUN_800dc880` is the CRC-32/BZIP2 that hashes pack paths — the same function
that confirmed the cracked path-hash (see
[02 — Pack format](02-pack-format.md)).

## ⚠️ Ghidra sees less than half of this binary — *fixed, see [19](19-gekko-sleigh.md)*

> **Resolved in session 10.** Teaching Ghidra the Gekko instruction set raised
> text coverage from **44.1 % to 97.6 %** and dropped the paired-singles outside
> any function from 96.1 % to 0.7 %. The measurement below is kept because it is
> the *before* half of that comparison, and because it is the reason several
> earlier statistics in these docs are lower bounds. How to reproduce the fix:
> [19 — A Gekko SLEIGH for Ghidra](19-gekko-sleigh.md).

Ghidra 12 ships **no Gekko/Broadway processor language**. The Wii's CPU extends
PowerPC with **paired-single** instructions — two `f32` packed in one 64-bit
FPR — and stock `PowerPC:BE:32` does not know them. Where the disassembler meets
one it reports *bad instruction data* and stops, so the function containing it is
never created and the decompiler answers `halt_baddata()`.

The scale of that, from `dol_disasm.py --coverage`:

```
text bytes             : 7,501,824
covered by a Ghidra fn : 3,305,399  (44.1%)
NOT covered            : 4,196,425  (55.9%)

                           inside fns  outside fns
words                         826,376    1,049,080
paired-singles                  2,199       53,957
  density                    0.2661%      5.1433%

total paired-singles   : 56,156
  of them outside a fn : 96.1%   (uncovered text is only 55.9%)
  density ratio        : 19x
```

**96.1 % of the paired-single instructions lie outside any function Ghidra
found**, in territory that is only 55.9 % of the text — a 19× concentration in
exactly the blind spots. The correlation does not prove every hole has this
cause (some uncovered bytes are data-in-text, padding, or simply unreached), but
it is the dominant one.

Two consequences worth carrying:

- **`functions.txt` is a floor, not an inventory.** Any statistic computed
  against it is understated by roughly this much — including the vtable check in
  [18 — DOL class names](18-dol-classes.md), where 28.3 % of pointers matched a
  known function entry. That number is a lower bound for this reason.
- **The interesting code is the missing code.** Vector maths, particle
  simulation, animation blending and skinning are precisely what uses paired
  singles. The `.eff` *loader* was readable ([17](17-eff-binary.md)) because it
  only moves bytes; the particle *simulation* that would name the 22 curve
  channels is not.

`dol_disasm.py` is the workaround: a partial PowerPC disassembler that decodes
enough to follow data flow and **labels** paired-singles instead of dying on
them. Anything it does not recognise prints as `.word`, so nothing is silently
mis-decoded.

```
python dol_disasm.py --func 0x8022fbbc     # find the enclosing function, then list it
python dol_disasm.py 0x8022fac4 120
python dol_disasm.py --coverage
```

It is not a decompiler and not a complete disassembler. The proper fix was a
Gekko SLEIGH language for Ghidra — that is now done, and
[19 — A Gekko SLEIGH for Ghidra](19-gekko-sleigh.md) has the recipe. `dol_disasm.py`
remains useful for quick look-ups without opening a project, and `--coverage`
is still the measurement that tells you whether your Ghidra setup is the good
one: point it at a `functions.txt` and it prints the number.

## Ghidra scripts

Under [`tools/ghidra_scripts/`](../tools/ghidra_scripts/):

| Script | Purpose |
|---|---|
| `DolLoad.java` | Load a `.dol`, rebuild sections, disassemble |
| `DolReport.java` | Dump functions + string xrefs |
| `DolDecomp.java` | Decompile given addresses to C |
| `DolCallers.java` | List references to an address |

These run under `analyzeHeadless`; see [REPRODUCING.md](../REPRODUCING.md).
