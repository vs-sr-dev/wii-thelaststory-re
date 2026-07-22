# 03 — Text & dialogue

**All in-game text is UTF-16 big-endian plaintext** (BOM `FE FF`), with no
encryption. Non-`.u16` CSV tables are Shift-JIS. (If text ever appears
"encrypted", it is a symptom of mapping names to data by position instead of by
the pack hash — see [02 — Pack format](02-pack-format.md).)

## Dialogue files

Dialogue lives inside the `filesystem` pack, under
`game_message/dg###_##_<lang>.u16` — one CSV per scene per language, with
`lang ∈ {jp, en, fr, de, es, it}` (the 5 PAL languages plus the original
Japanese). Columns (headers are in Japanese):

| Column (JP) | Meaning |
|---|---|
| 削除 | delete flag |
| キャラ | character (speaker) |
| M番号 | message number |
| モデル番号 | model number |
| data | — |
| キャラID | character ID |
| **ボイスID** | **voice ID** (links to the audio stream) |
| 表示wait / 表示時間 | display wait / duration |
| メッセージ原文 | original (JP) message text |
| 1行/2行/3行/4行 | per-line character counts |
| 発生条件 | trigger condition |
| 備考 | notes |

Localised files show the speaker as **internal JP codename / localised name**,
and the codenames frequently differ from the final English names:

| Internal (JP) | Localised | | Internal (JP) | Localised |
|---|---|---|---|---|
| エルザ (Elza) | **Zael** | | ジャッカル (Jackal) | **Lowell** |
| クォーク (Quark) | **Dagran** | | マナミア (Manamia) | **Mirania** |
| カナン (Kanan) | **Calista** | | ロッタ (Rotta) | **Horace** |
| セイレン (Seiren) | **Syrenne** | | タシャ (Tasha) | **Therius** |
| ユーリス (Yuris) | **Yurick** | | ウル (Uru) | **Uril** |

## Parsing notes

- `\n` inside a field is an **in-game line break**; real CR/LF are the CSV row
  separators. Use a proper CSV parser, not a newline split.
- Rows may include developer debug-jump entries (e.g. "jump to before the
  barracks?") interleaved with real lines.
- Other text tables live under `boot/`: `common_text_<lang>.u16`,
  `*_text_<lang>.u16` (equip/item/skill/sp), `map_id_table`, `maplink_name`,
  `shop_name_table`, `tutorial_table`. `chara_id_table_jp.u16` is large
  (~383 KB). `cp932_unicode.tbl` is a Shift-JIS → Unicode conversion table.

## The `ボイスID` bridge

The `voiceID` (e.g. `VO_PLD001_0010`) is the hook that links a written line to
its recorded voice clip — it is *literally* the filename of the corresponding
audio stream. See [05 — Audio](05-audio-brstm.md) for how the text↔voice loop is
closed.

Tools: `tools/build_dialogue_db.py` (consolidated 6-language database),
`tools/link_voices.py` (line → voice clip).
