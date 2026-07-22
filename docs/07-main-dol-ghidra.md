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

## Ghidra scripts

Under [`tools/ghidra_scripts/`](../tools/ghidra_scripts/):

| Script | Purpose |
|---|---|
| `DolLoad.java` | Load a `.dol`, rebuild sections, disassemble |
| `DolReport.java` | Dump functions + string xrefs |
| `DolDecomp.java` | Decompile given addresses to C |

These run under `analyzeHeadless`; see [REPRODUCING.md](../REPRODUCING.md).
