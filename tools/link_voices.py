#!/usr/bin/env python3
"""
link_voices.py - Chiude il loop TESTO <-> VOCE di The Last Story.

Il DB dialoghi (dialogue_db/*.tsv) ha una colonna 'voice' con il voiceID
(es. VO_PLD001_0010). Gli stream .brstm hanno esattamente quel nome.
Questo tool aggancia ogni battuta doppiata alla sua clip:

  - legge audio/manifest.csv (durata/sr/canali di ogni stream)
  - per ogni riga con voice valido, verifica l'esistenza dello stream e
    (se convertito) del .ogg in audio/vo/
  - produce dialogue_db/voiced_lines.tsv : catalogo unico di TUTTE le battute
    doppiate, con scene, personaggio, voiceID, ogg path, durata, testo 6 lingue.
  - stampa statistiche di copertura.

Prima assoluta pubblica: testo + voce affiancati per un gioco mai documentato.
"""
import os, csv, glob, sys

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB     = os.path.join(ROOT, 'dialogue_db')
AUDIO  = os.path.join(ROOT, 'audio')
STREAM = os.path.join(ROOT, 'extract', 'files', 'sound', 'stream')

def load_manifest():
    m = {}
    p = os.path.join(AUDIO, 'manifest.csv')
    if not os.path.exists(p):
        return m
    with open(p, encoding='utf-8', newline='') as fh:
        for row in csv.DictReader(fh):
            m[os.path.splitext(row['file'])[0]] = row
    return m

def is_real_voice(v):
    if not v: return False
    v = v.strip()
    if v in ('', 'TEMP'): return False
    return v.startswith(('VO_', 'SE_'))

def main():
    manifest = load_manifest()
    stream_set = set(os.path.splitext(f)[0] for f in os.listdir(STREAM))
    def ogg_rel(v):
        sub = 'vo' if v.startswith('VO_') else 'se' if v.startswith('SE_') else None
        if sub and os.path.exists(os.path.join(AUDIO, sub, v + '.ogg')):
            return f'audio/{sub}/{v}.ogg'
        return ''

    scenes = sorted(glob.glob(os.path.join(DB, 'dg*.tsv')) +
                    glob.glob(os.path.join(DB, 'tw*.tsv')) +
                    [os.path.join(DB, 'system.tsv')])

    out_rows = []
    n_lines = n_voiced = n_matched = n_ogg = 0
    missing = []
    for tsv in scenes:
        scene = os.path.splitext(os.path.basename(tsv))[0]
        with open(tsv, encoding='utf-8', newline='') as fh:
            for row in csv.DictReader(fh, delimiter='\t'):
                n_lines += 1
                v = (row.get('voice') or '').strip()
                if not is_real_voice(v):
                    continue
                n_voiced += 1
                has_stream = v in stream_set
                if has_stream: n_matched += 1
                else: missing.append((scene, v))
                ogg = ogg_rel(v)
                if ogg: n_ogg += 1
                info = manifest.get(v, {})
                out_rows.append({
                    'scene': scene,
                    'M': row.get('M',''),
                    'chara': row.get('chara',''),
                    'voice': v,
                    'ogg': ogg,
                    'has_stream': int(has_stream),
                    'seconds': info.get('seconds',''),
                    'sample_rate': info.get('sample_rate',''),
                    'channels': info.get('channels',''),
                    'jp': row.get('jp',''),
                    'en': row.get('en',''),
                    'fr': row.get('fr',''),
                    'de': row.get('de',''),
                    'es': row.get('es',''),
                    'it': row.get('it',''),
                })

    out = os.path.join(DB, 'voiced_lines.tsv')
    cols = ['scene','M','chara','voice','ogg','has_stream','seconds',
            'sample_rate','channels','jp','en','fr','de','es','it']
    with open(out, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter='\t')
        w.writeheader()
        w.writerows(out_rows)

    print(f"righe DB totali        : {n_lines}")
    print(f"battute doppiate (VO/SE): {n_voiced}")
    print(f"  con stream .brstm     : {n_matched}  ({100*n_matched/max(1,n_voiced):.1f}%)")
    print(f"  con .ogg convertito   : {n_ogg}")
    print(f"voiced_lines.tsv        : {out}  ({len(out_rows)} righe)")
    distinct_missing = sorted(set(v for _, v in missing))
    print(f"voiceID senza stream    : {len(distinct_missing)} distinti")
    if distinct_missing:
        print("  esempi:", distinct_missing[:12])

if __name__ == '__main__':
    main()
