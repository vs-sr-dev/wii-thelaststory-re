"""Ricava la funzione hash usata da .sel/.rso e cerca simboli debug in main.dol."""
import os
import struct

# coppie note (nome, hash) dagli export del .sel e dell'RSO
known = [
    ('OSReport', 0x088c73d4), ('strlen', 0x07ab92be), ('memcpy', 0x073c3a79),
    ('_SDA_BASE_', 0x0730202f), ('_SDA2_BASE_', 0x08521fef),
    ('OSGetStackPointer', 0x00a25f12), ('__dl__FPv', 0x0b255e26),
    ('Tools_DebugMenuExec', 0x0b864de3), ('Tools_SoundTestExec', 0x0fa6be03),
    ('MyRsoFunc__Fv', 0x00a2f046),
]

def elf_hash(s):
    h = 0
    for c in s.encode('ascii'):
        h = (h << 4) + c
        g = h & 0xf0000000
        if g:
            h ^= g >> 24
        h &= ~g & 0xffffffff
    return h & 0xffffffff

def elf_hash_masked(s):
    # variante con mask 0x0fffffff (i valori noti sono < 0x10000000)
    return elf_hash(s) & 0x0fffffff

ok = all(elf_hash_masked(n) == h for n, h in known)
print('ELF hash (masked 0x0fffffff) combacia con i noti:', ok)
if not ok:
    for n, h in known:
        print(f'  {n:24s} atteso={h:#010x} calc={elf_hash_masked(n):#010x}')

# se combacia, hasha i simboli debug-target e cercali in main.dol
d = open(os.path.join(os.environ.get('TLS_ROOT', '.'), r'extract\sys\main.dol'), 'rb').read()
words_un = set()
for i in range(len(d)-3):
    words_un.add(struct.unpack('>I', d[i:i+4])[0])

targets = [
    'SetTask__17SequenceDebugMenuFPQ23atn4Task',
    'SetSeqHolder__17SequenceDebugMenuFQ217SequenceDebugMenu5LevelPQ23atn14SequenceHolderPCc',
    'SetTask__9SoundTestFPQ23atn4Task',
    'SetTask__11BattleDebugFPQ23atn4Task',
    'instance___11CharaSelect',
]
print('\nricerca hash target in main.dol:')
for t in targets:
    h = elf_hash_masked(t)
    loc = 'TROVATO' if h in words_un else 'assente'
    print(f'  {h:#010x}  {loc}  {t}')
