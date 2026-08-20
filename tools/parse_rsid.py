#!/usr/bin/env python3
"""
parse_rsid.py - Parser for the sound registry table of The Last Story's engine.

LastWorld.rsid.csv (sound/) is the RSID table: it maps the symbolic name the code
uses to request a sound (e.g. BGM_BATT101, VO_PLD001_0010) to the global numeric
index the engine addresses it by.

Row format (CSV, 14171 rows):  NAME,idx1,idx2,flag,
  NAME  = symbolic name (VO_/SE_/BGM_/STRM_/GROUP_/PLAYER_/SYSTR_/SEQBNK_/DEFAULT)
  idx1  = global RSID index (0..~14000, NOT perfectly sequential: GROUP/PLAYER/
          SEQBNK entries have their own numbering interleaved)
  idx2  = sub-index (index inside the category's player/sub-table)
  flag  = '1' on 2114 entries, empty otherwise -> (probably) marks "streamed"
  [5th column empty, from the trailing comma]

Output: audio/rsid_table.csv with an is_stream column (the NAME exists as a .brstm).
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

    # summary
    cat = collections.Counter(r[4] for r in rows)
    is_stream = sum(1 for r in rows if r[5] == '1')
    flagged = sum(1 for r in rows if r[3] == '1')
    print(f"rsid rows           : {len(rows)}")
    print(f"written to          : {out}")
    print(f"categories          : {dict(cat.most_common())}")
    print(f"flag=1 (streamed?)  : {flagged}")
    print(f"NAME is a .brstm    : {is_stream}  (the rest live in the brsar/bank)")
    # correlation flag <-> is_stream_file
    both = sum(1 for r in rows if r[3] == '1' and r[5] == '1')
    print(f"flag=1 AND stream   : {both}  (flag=1 but not a stream: {flagged-both})")

if __name__ == '__main__':
    main()
