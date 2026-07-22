# 06 — The retail debug menu (present but unreachable)

The disc ships a `config.ini` with developer-looking keys:

```
DebugMenuType   = Default
BootSequence    = DebugMenu
DrawErrorMessage = false
Neko            = false
```

and an RSO module `LastWorld_tools.rso` (loaded via `LastWorld.sel`) that exposes
an entire debug menu still present in the retail game:
`Tools_SoundTestExec`, `Tools_MessageTestExec`, `Tools_LipSyncTestExec`,
`Tools_StageSelectExec`, `Tools_BattleDebugExec`, `Tools_LevelEditorExec`,
`Tools_SpecialEventViewerStaffRollExec`, `Tools_SaveDataEditorExec`,
`CharaSelect`, … The original build path is visible:
`c:\programs\lw\trunk\lastworld\...`.

It is tempting to think `BootSequence = DebugMenu` boots it. It does not.

## What `main.dol` actually shows

- The **debug-menu parameter tree is compiled into retail and built at init**:
  `FUN_80186520` registers hundreds of tunable parameters (`Config` →
  `DrawSystemInfo`, `DebugCamera`, `DifficultyLevel`, `Player`, `SceneDebug`,
  `DrawCollision`, `DrawErrorMessage`, …) through a menu API (`FUN_8008937c` =
  node, `FUN_800874c8` = int, `FUN_80087994` = bool, `FUN_8008771c` = float,
  `FUN_800875f8` = colour).
- `config.ini` applies values to menu entries **by name**: `DrawErrorMessage` is
  both a config key and a menu entry.
- The `DebugMenu` strings in `main.dol` are the menu's **label/title** (next to
  `Config`), referenced via SDA (r2) — **not** a boot selector.
- The keys `BootSequence` / `Neko` **do not exist as strings, nor as CRC hashes,
  in ANY shipped binary** (not `main.dol`, not `LastWorld_tools.rso`, not any
  disc file) — they appear only inside `config.ini` itself. Boot sequences
  (including `FUN_8047a4c8`) are invoked **via vtable/pointers**, with no static
  xref.

**Conclusion:** `config.ini` is a **vestigial development config**. The code that
once consumed `BootSequence` / `Neko` was **compiled out** of the retail build
(25 Nov 2011). What survives is (a) the debug-menu parameter tree
(`FUN_80186520`, built at init) and (b) the `LastWorld_tools.rso` module with
`SequenceDebugMenu` / `Tools_DebugMenuExec` / `Tools_NekoRegisterGameHandlers`.

## Why it can't boot — a linker-level cut

Reversing the **RSO** format (`tools/rso_parse.py`) on `LastWorld_tools.rso` and
`LastWorld.sel`:

- The tools RSO is a shell of **thunks**: `Tools_DebugMenuExec` contains no logic
  and tail-calls the **import** `SetTask__17SequenceDebugMenu` (plus
  `SetSeqHolder__17SequenceDebugMenu`). So the real DebugMenu sequence lives **in
  `main.dol`**, not in the RSO.
- To link those imports, the RSO looks them up in `main.dol`'s export table =
  **`LastWorld.sel`** (itself an RSO). But the retail `.sel` exports **only 13
  symbols**: the 6 HomeButton functions (`HBMRso*`), libc (`OSReport`, `strlen`,
  `memcpy`, `__dl__FPv`, `OSGetStackPointer`) and `_SDA_BASE_` / `_SDA2_BASE_`.
  **No `SetTask__` debug symbol.**
- Verified via **ELF symbol hashing** (the hash function was derived and
  confirmed on the `.sel`'s known name→hash pairs): the hashes of
  `SetTask__17SequenceDebugMenu*`, `SetTask__9SoundTest*`, etc. **appear nowhere
  in `main.dol`** — there is no wider internal export table.

⇒ Even if the tools RSO were loaded, its debug entries would hit the
`_unresolved` stub ("*B called an unlinked function*", a string present in the
RSO). **The debug menu is not disabled by a flag: it is deliberately unlinked at
the linker level in the retail build.** That is why the community has never
activated it — it is not a `config.ini` toggle.

## To actually enable it

You would need to locate `SequenceDebugMenu::SetTask` inside `main.dol` **by code
analysis** (symbols are stripped; `FUN_80186520`, the menu builder, has no xref —
it is only reached externally), then either (a) patch the boot sequence to
instantiate it, or (b) rebuild `LastWorld.sel` to export the `SetTask__` symbols
and load the tools RSO. Groundwork tools: `tools/rso_parse.py`,
`tools/rso_reloc.py`, `tools/elfhash_search.py`.
