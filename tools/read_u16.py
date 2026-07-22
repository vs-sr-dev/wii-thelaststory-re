"""Legge file .u16 (CSV UTF-16BE) e mostra le prime righe."""
import os
import sys

def read_u16(path):
    data = open(path, 'rb').read()
    enc = 'utf-16-be' if data[:2] == b'\xfe\xff' else 'utf-16-le'
    return data.decode(enc).lstrip('﻿')

base = os.path.join(os.environ.get('TLS_ROOT', '.'), r'assets\pack\filesystem\game_message')
out = open(os.path.join(os.environ.get('TLS_ROOT', '.'), r'tools\gm_sample.txt'), 'w', encoding='utf-8')
for lang in ('it', 'en', 'jp'):
    t = read_u16(base + '\\dg001_01_' + lang + '.u16')
    lines = t.split('\n')
    out.write(f'===== dg001_01_{lang}.u16 : {len(lines)} righe =====\n')
    for l in lines[:15]:
        out.write(l.rstrip('\r') + '\n')
    out.write('\n')
out.close()
print('scritto gm_sample.txt')
