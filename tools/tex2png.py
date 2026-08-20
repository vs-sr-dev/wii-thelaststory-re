"""Decodes .texture (chnkdata) -> PNG (mip 0 only)."""
import sys
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gxtex

u32 = lambda d, o: struct.unpack('>I', d[o:o+4])[0]

def load(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'chnkdata', d[:8]
    fmt = u32(d, 0x20); w = u32(d, 0x24); h = u32(d, 0x28)
    doff = u32(d, 0x34)
    return fmt, w, h, d[doff:]

def convert(path, out):
    fmt, w, h, data = load(path)
    rgba = gxtex.decode(fmt, w, h, data)
    gxtex.save_png(out, w, h, rgba)
    return fmt, w, h

if __name__ == '__main__':
    A = os.path.join(os.environ.get('TLS_ROOT', '.'),
                     'assets', 'pack', 'filesystem', 'data', 'texture')
    OUT = os.path.join(os.environ.get('TLS_ROOT', '.'), 'tools', 'tex_out')
    os.makedirs(OUT, exist_ok=True)
    picks = ['action_base.texture', 'ai_dg003_barrel01_01.texture',
             'ai_dg003_apples01_01.texture', 'ai_dg002_casket01_01.texture',
             'ai_dg003_chair01_01.texture', 'ai_dg003_bed01_01.texture']
    for name in picks:
        p = os.path.join(A, name)
        if not os.path.exists(p):
            print('missing', name); continue
        try:
            fmt, w, h = convert(p, os.path.join(OUT, name + '.png'))
            print(f'OK {name}: fmt={fmt} {w}x{h}')
        except Exception as e:
            print(f'ERR {name}: {e}')
