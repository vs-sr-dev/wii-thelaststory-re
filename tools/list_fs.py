"""Listing and statistics for the contents of the filesystem/levels/eventpacks packs."""
import os
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lwpack import parse_pfs, parse_pkh

FILES = os.path.join(os.environ.get('TLS_ROOT', '.'), 'extract', 'files')
for name in ('filesystem', 'levels', 'eventpacks'):
    stem = os.path.join(FILES, 'pack', name)
    files = parse_pfs(stem + '.pfs')
    entries = parse_pkh(stem + '.pkh')
    print(f'== {name}: {len(files)} names, {len(entries)} pkh entries, match={len(files)==len(entries)}')
    exts = collections.Counter(f.rsplit('.', 1)[-1] if '.' in f.rsplit('/',1)[-1] else '(none)' for f in files)
    print('   ext:', dict(exts.most_common(15)))
    dirs = collections.Counter(f.split('/')[0] for f in files)
    print('   top dir:', dict(dirs.most_common(15)))

# look for text/language files inside filesystem
files = parse_pfs(os.path.join(FILES, 'pack', 'filesystem') + '.pfs')
pats = ['_en', '_fr', '_de', '_es', '_it', '_jp', 'text', 'msg', 'message', 'font']
hits = [f for f in files if any(p in f.lower() for p in pats)]
print(f'\n{len(hits)} "language" files in filesystem:')
for h in hits[:80]:
    print('  ', h)
if len(hits) > 80:
    print(f'   ... (+{len(hits)-80})')
