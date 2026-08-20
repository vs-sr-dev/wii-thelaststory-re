"""Extracts every pack (or a subset) using lwextract.exe.

Usage: python extract_all.py [stem ...]
       with no arguments: all 21 packs.
"""
import os
import sys, os, subprocess, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lwpack import parse_pfs, parse_pkh, path_hash

ROOT = os.environ.get('TLS_ROOT', '.')
FILES = os.path.join(ROOT, 'extract', 'files')
OUT = os.path.join(ROOT, 'assets')
EXE = os.path.join(ROOT, 'tools', 'lwextract.exe')
SCRATCH = os.path.join(ROOT, 'tools', '_manifests')
os.makedirs(SCRATCH, exist_ok=True)

stems = []
for sub in ('pack', 'preload'):
    d = os.path.join(FILES, sub)
    for f in sorted(os.listdir(d)):
        if f.endswith('.pfs'):
            stems.append((sub, f[:-4]))

want = sys.argv[1:]
if want:
    stems = [(s, n) for s, n in stems if n in want]

grand_ok = True
for sub, name in stems:
    stem = os.path.join(FILES, sub, name)
    files = parse_pfs(stem + '.pfs')
    entries = parse_pkh(stem + '.pkh')
    by_hash = {e[0]: e for e in entries}
    man = os.path.join(SCRATCH, f'{sub}_{name}.txt')
    skipped = 0
    with open(man, 'w', encoding='ascii') as f:
        for path in files:
            e = by_hash.get(path_hash(path))
            if e is None:            # name with non-ASCII bytes (placeholder '?')
                skipped += 1
                continue
            h, off, unc, comp = e
            f.write(f'{off}|{comp}|{unc}|{path}\n')
    if skipped:
        print(f'   (skipped {skipped} non-ASCII names)')
    outdir = os.path.join(OUT, sub, name)
    os.makedirs(outdir, exist_ok=True)
    print(f'== {sub}/{name}: {len(files) - skipped} files ==', flush=True)
    r = subprocess.run([EXE, stem + '.pk', man, outdir], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.stderr:
        print('STDERR:', r.stderr[:2000])
    if r.returncode != 0:
        grand_ok = False

print('DONE', 'OK' if grand_ok else 'WITH ERRORS')
