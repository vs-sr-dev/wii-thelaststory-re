"""Batch: istogramma formati (modo 'hist') o conversione completa (.texture -> PNG)."""
import sys
import os, struct, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gxtex

u32 = lambda d, o: struct.unpack('>I', d[o:o+4])[0]
FMT_NAME = {0:'I4',1:'I8',2:'IA4',3:'IA8',4:'RGB565',5:'RGB5A3',6:'RGBA8',
            8:'C4',9:'C8',0xA:'C14X2',0xE:'CMPR'}

ASSETS = os.path.join(os.environ.get('TLS_ROOT', '.'), r'assets')
OUT = os.path.join(os.environ.get('TLS_ROOT', '.'), r'textures_png')

def all_textures():
    for root, dirs, fs in os.walk(ASSETS):
        for f in fs:
            if f.endswith('.texture'):
                yield os.path.join(root, f)

def hist():
    import collections
    c = collections.Counter(); nonchnk = 0; total = 0
    for p in all_textures():
        total += 1
        head = open(p, 'rb').read(0x28)
        if head[:8] != b'chnkdata':
            nonchnk += 1; continue
        c[u32(head, 0x20)] += 1
    print(f'texture totali: {total}, non-chnkdata: {nonchnk}')
    for fmt, n in c.most_common():
        print(f'  fmt {fmt:2d} {FMT_NAME.get(fmt,"?"):8s}: {n}')

def convert_all(limit=None):
    ok = err = skip = 0
    for i, p in enumerate(all_textures()):
        if limit and i >= limit:
            break
        d = open(p, 'rb').read()
        if d[:8] != b'chnkdata':
            skip += 1; continue
        fmt = u32(d, 0x20); w = u32(d, 0x24); h = u32(d, 0x28); doff = u32(d, 0x34)
        if fmt not in gxtex.BLOCK or w == 0 or h == 0 or w > 4096 or h > 4096:
            skip += 1; continue
        rel = os.path.relpath(p, ASSETS)
        outp = os.path.join(OUT, rel + '.png')
        os.makedirs(os.path.dirname(outp), exist_ok=True)
        try:
            rgba = gxtex.decode(fmt, w, h, d[doff:])
            gxtex.save_png(outp, w, h, rgba)
            ok += 1
        except Exception as e:
            err += 1
            if err <= 10:
                print('ERR', rel, e)
        if ok and ok % 500 == 0:
            print(f'  ... {ok} convertite', flush=True)
    print(f'FATTO: ok={ok} skip={skip} err={err}')

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'hist'
    if mode == 'hist':
        hist()
    else:
        convert_all(int(sys.argv[2]) if len(sys.argv) > 2 else None)
