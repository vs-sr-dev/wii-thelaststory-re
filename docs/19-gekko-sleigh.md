# 19 — A Gekko SLEIGH for Ghidra: 44 % → 98 % of the binary

For nine sessions the same wall kept appearing. Three separate results —
the collision material bitfield, the identity of the 22 `.eff` curve channels,
the emitter float parameters — all ended with "this cannot be settled from the
data, it needs the DOL", and the DOL could not be read where it mattered.

[07 — main.dol in Ghidra](07-main-dol-ghidra.md) measured why: Ghidra's stock
`PowerPC:BE:32` does not know the Wii CPU's **paired-single** instructions, so
the disassembler stops at the first one and never creates the function around
it. Ghidra saw **44.1 %** of the text, and **96.1 %** of the paired-single
instructions sat outside any function it had found — a 19× concentration in
exactly the blind spots. The interesting code *is* the missing code: vector
maths, skinning, animation blending, particle simulation.

The fix is a processor language. This is the whole recipe.

## The recipe

A community SLEIGH definition for Gekko/Broadway exists —
[`aldelaro5/ghidra-gekko-broadway-lang`](https://github.com/aldelaro5/ghidra-gekko-broadway-lang)
(later folded into
[`Cuyler36/Ghidra-GameCube-Loader`](https://github.com/Cuyler36/Ghidra-GameCube-Loader)).
It adds the `ps_*` arithmetic, the quantised loads and stores `psq_l`/`psq_st`
with their GQR scale/type registers, and `dcbz_l`. It is written against an
older Ghidra, but it is a self-contained fork of the PowerPC spec: the only
thing it borrows from the host installation is a handful of `.sinc` includes.

```bash
git clone --depth 1 https://github.com/aldelaro5/ghidra-gekko-broadway-lang

# stage it next to the stock PowerPC .sinc files it includes, and compile
cp ghidra-gekko-broadway-lang/data/languages/* build/
cp $GHIDRA/Ghidra/Processors/PowerPC/data/languages/*.sinc build/   # no overwrite
$GHIDRA/support/sleigh build/ppc_gekko_broadway.slaspec

# install: six files, all new, nothing in the stock language is touched
cp build/ppc_gekko_broadway.{sla,slaspec,ldefs,pspec,cspec} \
   build/ppc_instructions_gekko_broadway.sinc \
   $GHIDRA/Ghidra/Processors/PowerPC/data/languages/
```

On Ghidra 12.1.2 this compiles clean — only NOP-constructor and
unreferenced-table warnings, all inherited from the stock PowerPC spec. Ghidra
ships its own SLEIGH compiler (`support/sleigh`), so no external toolchain is
needed. The new language id is **`PowerPC:BE:32:Gekko_Broadway`**.

Then re-import, using the same DOL loader script as before:

```bash
analyzeHeadless <proj> TLS -import main.dol \
  -processor PowerPC:BE:32:Gekko_Broadway \
  -loader BinaryLoader \
  -scriptPath tools/ghidra_scripts -preScript DolLoad.java <path/main.dol>
```

Import the DOL under a **different program name** than the stock-PowerPC one.
Keeping both in the project is what makes the before/after comparison below
possible, and it costs nothing.

## The verification

The point of a measurement is that it can come out badly. `--coverage` reads a
`functions.txt` exported from Ghidra and compares it against the DOL's own
section table, so it is not Ghidra grading its own homework:

```bash
python dol_disasm.py --coverage                        # stock PowerPC
python dol_disasm.py --coverage ghidra_out_gekko/functions.txt   # Gekko
```

| | stock `PowerPC:BE:32` | `PowerPC:BE:32:Gekko_Broadway` |
|---|---|---|
| functions found | 14,530 | **15,955** |
| text covered by a function | 3,305,399 B — **44.1 %** | 7,318,360 B — **97.6 %** |
| paired-singles outside any function | 53,957 — **96.1 %** | 385 — **0.7 %** |

The second row is the result; the third is the one that says *why*, and it is
the sharper test. If the language had merely made Ghidra braver about creating
functions, coverage would have risen while paired-singles stayed stranded.
Instead the stranded ones essentially vanish, which is what a correct
instruction decoding predicts and a lucky heuristic does not.

The residual 2.4 % is unremarkable: data-in-text, padding, and code no
call-graph walk reaches.

## What it unblocked immediately

`0x8022fac4` — the one function in the binary with `mulli …, 620`, i.e. the one
indexing the `.eff` emitter array — used to decompile to 247 bytes of
`halt_baddata()`. It now decompiles to 32 KB of C, and the calls it makes are
legible on sight: `FUN_805f89f0` is a 3×4 matrix concatenation, `FUN_805f90d0`
builds a matrix. From there the curve evaluator was two greps away, and the
22 channels fell: [20 — The 22 `.eff` channels](20-eff-channels.md).

Worth knowing when reading the output: paired-single loads and stores appear as
`__psq_l0/__psq_st0` intrinsics with a `GQR` argument rather than as plain float
accesses, so a `Vec3` copy reads as three pairs of intrinsic calls. The
decompiler also emits many "Removing unreachable block" warnings inside these
functions — that is the quantisation branches being folded away, not a decoding
problem.

## The lesson, which is not about Ghidra

The blind spot had been *measured* in session 9 and correctly diagnosed, and the
next three targets were still queued as "read more assembly by hand". They were
all downstream of one tooling defect. When several independent lines of work
stall at the same place, the thing to fix is the place, not the lines — and here
the fix was a `git clone` and one compile against a tool that was already
installed.
