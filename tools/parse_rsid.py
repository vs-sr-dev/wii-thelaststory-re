#!/usr/bin/env python3
"""
parse_rsid.py - Parser della tabella-registro sonora dell'engine di The Last Story.

LastWorld.rsid.csv (sound/) e' la tabella RSID: mappa il nome simbolico che il
codice usa per richiedere un suono (es. BGM_BATT101, VO_PLD001_0010) all'indice
numerico globale con cui l'engine lo indirizza.

Formato riga (CSV, 14171 righe):  NAME,idx1,idx2,flag,
  NAME  = nome simbolico (VO_/SE_/BGM_/STRM_/GROUP_/PLAYER_/SYSTR_/SEQBNK_/DEFAULT)
  idx1  = indice RSID globale (0..~14000, NON perfettamente sequenziale: le voci
          GROUP/PLAYER/SEQBNK hanno numerazione propria intercalata)
  idx2  = sotto-indice (indice dentro il player/sotto-tabella della categoria)
  flag  = '1' su 2114 voci, altrimenti vuoto -> marca (probabile) "streamed"
  [5a col vuota per la virgola finale]

Output: audio/rsid_table.csv con colonna is_stream (il NAME esiste come .brstm).
"""
import csv, os, sys, collections

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RSID   = os.path.join(ROOT, 'extract', 'files', 'sound', 'LastWorld.rsid.csv')
STREAM = os.path.join(ROOT, 'extract', 'files', 'sound', 'stream')
OUTDIR = os.path.join(ROOT, 'audio')

def category(name):
    return name.split('_', 1)[0] if '_' in name else name

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    stream = set(os.path.splitext(f)[0] for f in os.listdir(STREAM))

    rows = []
    with open(RSID, encoding='utf-8', newline='') as fh:
        for raw in fh:
            raw = raw.rstrip('\r\n')
            if not raw:
                continue
            p = raw.split(',')
            name = p[0]
            idx1 = p[1] if len(p) > 1 else ''
            idx2 = p[2] if len(p) > 2 else ''
            flag = p[3] if len(p) > 3 else ''
            rows.append((name, idx1, idx2, flag, category(name),
                         '1' if name in stream else '0'))

    out = os.path.join(OUTDIR, 'rsid_table.csv')
    with open(out, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['name', 'rsid_index', 'sub_index', 'stream_flag',
                    'category', 'is_stream_file'])
        w.writerows(rows)

    # riepilogo
    cat = collections.Counter(r[4] for r in rows)
    is_stream = sum(1 for r in rows if r[5] == '1')
    flagged = sum(1 for r in rows if r[3] == '1')
    print(f"righe rsid          : {len(rows)}")
    print(f"scritte in          : {out}")
    print(f"categorie           : {dict(cat.most_common())}")
    print(f"flag=1 (streamed?)  : {flagged}")
    print(f"NAME e' un .brstm   : {is_stream}  (gli altri vivono nel brsar/bank)")
    # correlazione flag<->is_stream_file
    both = sum(1 for r in rows if r[3] == '1' and r[5] == '1')
    print(f"flag=1 AND stream   : {both}  (flag=1 ma non-stream: {flagged-both})")

if __name__ == '__main__':
    main()
