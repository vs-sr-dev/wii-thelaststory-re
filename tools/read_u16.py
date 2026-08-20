"""Reads .u16 files (UTF-16BE CSV) and shows the first rows."""
import os
import sys

def read_u16(path):
    data = open(path, 'rb').read()
    enc = 'utf-16-be' if data[:2] == b'\xfe\xff' else 'utf-16-le'
    return data.decode(enc).lstrip('﻿')

base = os.path.join(os.environ.get('TLS_ROOT', '.'),
                    'assets', 'pack', 'filesystem', 'game_message')
out = open(os.path.join(os.environ.get('TLS_ROOT', '.'), 'tools', 'gm_sample.txt'),
           'w', encoding='utf-8')
for lang in ('it', 'en', 'jp'):
    t = read_u16(os.path.join(base, f'dg001_01_{lang}.u16'))
    lines = t.split('\n')
    out.write(f'===== dg001_01_{lang}.u16 : {len(lines)} rows =====\n')
    for l in lines[:15]:
        out.write(l.rstrip('\r') + '\n')
    out.write('\n')
out.close()
print('wrote gm_sample.txt')
