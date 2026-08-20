"""Builds a consolidated dialogue DB for The Last Story.

For every game_message/dg###_## scene it aligns the 6 languages (jp/en/fr/de/es/it)
by message number (M番号) and writes:
  - dialogue_db/<scene>.tsv  (one row per line, one column per language)
  - dialogue_db/_index.tsv   (scene list + counts)
Uses proper CSV parsing (lines can contain newlines and commas).
"""
import os
import sys, os, csv, io, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lwpack import parse_pfs, parse_pkh, path_hash, lz11_decompress

ROOT = os.environ.get('TLS_ROOT', '.')
stem = os.path.join(ROOT, 'extract', 'files', 'pack', 'filesystem')
OUT = os.path.join(ROOT, 'dialogue_db')
os.makedirs(OUT, exist_ok=True)
LANGS = ['jp', 'en', 'fr', 'de', 'es', 'it']

files = parse_pfs(stem + '.pfs')
entries = parse_pkh(stem + '.pkh')
by_hash = {e[0]: e for e in entries}
pk = open(stem + '.pk', 'rb').read()

def get_text(path):
    e = by_hash.get(path_hash(path))
    if e is None:
        return None
    h, off, unc, comp = e
    blob = pk[off:off + (comp if comp else unc)]
    d = lz11_decompress(blob) if comp else blob
    return d.decode('utf-16-be').lstrip('﻿')

def parse_scene_lang(text):
    """Return dict {M番号: {'chara':..., 'voice':..., 'text':...}} from the CSV."""
    rows = list(csv.reader(io.StringIO(text)))
    out = {}
    for r in rows:
        if len(r) < 10:
            continue
        mnum = r[2].strip()
        if not mnum.isdigit():
            continue
        # col 4 = the text shown in-game (localised); col 9 = the original JP (reference)
        text = r[4].replace('\n', '\\n').replace('\r', '').strip()
        out[mnum] = {'chara': r[1].strip(), 'voice': r[6].strip(),
                     'text': text,
                     'cond': r[14].strip() if len(r) > 14 else ''}
    return out

# list the scenes (dg###_## prefixes)
scenes = sorted(set(f[len('game_message/'):].rsplit('_', 1)[0]
                    for f in files
                    if f.startswith('game_message/') and f.endswith('.u16')))

index_rows = []
total_lines = 0
for scene in scenes:
    per_lang = {}
    for lang in LANGS:
        t = get_text(f'game_message/{scene}_{lang}.u16')
        if t is not None:
            per_lang[lang] = parse_scene_lang(t)
    if 'jp' not in per_lang and 'en' not in per_lang:
        continue
    # sorted union of the message numbers
    mnums = sorted({m for d in per_lang.values() for m in d},
                   key=lambda x: int(x))
    out_path = os.path.join(OUT, scene + '.tsv')
    with io.open(out_path, 'w', encoding='utf-8', newline='') as fo:
        w = csv.writer(fo, delimiter='\t')
        w.writerow(['M', 'chara', 'voice', 'cond'] + LANGS)
        for m in mnums:
            base = next((per_lang[l][m] for l in LANGS if m in per_lang.get(l, {})), {})
            texts = [per_lang.get(l, {}).get(m, {}).get('text', '') for l in LANGS]
            w.writerow([m, base.get('chara', ''), base.get('voice', ''),
                        base.get('cond', '')] + texts)
    total_lines += len(mnums)
    index_rows.append((scene, len(mnums), ''.join(l[0] for l in LANGS if l in per_lang)))

with io.open(os.path.join(OUT, '_index.tsv'), 'w', encoding='utf-8', newline='') as fo:
    w = csv.writer(fo, delimiter='\t')
    w.writerow(['scene', 'lines', 'langs'])
    for row in index_rows:
        w.writerow(row)

print(f'{len(index_rows)} scenes, {total_lines} lines total -> {OUT}')
print('sample scenes:', [r[0] for r in index_rows[:8]])
