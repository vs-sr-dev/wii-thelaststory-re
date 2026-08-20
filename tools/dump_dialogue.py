"""Readable dump of a dialogue file (game_message) in IT, EN and JP."""
import os
import sys, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lwpack import parse_pfs, parse_pkh, path_hash, lz11_decompress

stem = os.path.join(os.environ.get('TLS_ROOT', '.'), 'extract', 'files', 'pack', 'filesystem')
files = parse_pfs(stem + '.pfs')
entries = parse_pkh(stem + '.pkh')
by_hash = {e[0]: e for e in entries}
pk = open(stem + '.pk', 'rb').read()

def get_text(path):
    h, off, unc, comp = by_hash[path_hash(path)]
    blob = pk[off:off + (comp if comp else unc)]
    d = lz11_decompress(blob) if comp else blob
    return d.decode('utf-16-be').lstrip('﻿')

out = io.open(os.path.join(os.environ.get('TLS_ROOT', '.'), 'tools', 'dialogue_sample.txt'), 'w', encoding='utf-8')
for name in ['game_message/dg001_01_it.u16', 'game_message/dg001_01_en.u16',
             'game_message/dg001_01_jp.u16']:
    t = get_text(name)
    rows = t.replace('\r\n', '\n').split('\n')
    out.write(f'===== {name} : {len(rows)} rows =====\n')
    for r in rows[:25]:
        out.write(r + '\n')
    out.write('\n')
out.close()
print('wrote dialogue_sample.txt')
