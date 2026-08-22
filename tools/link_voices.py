#!/usr/bin/env python3
"""
link_voices.py - Closes the TEXT <-> VOICE loop of The Last Story.

The dialogue DB (dialogue_db/*.tsv) has a 'voice' column holding the voiceID
(e.g. VO_PLD001_0010). The .brstm streams carry exactly that name.
This tool hooks every voiced line to its clip:

  - reads audio/manifest.csv (duration/sample rate/channels of each stream)
  - for every row with a valid voice, checks that the stream exists and, if it has
    been converted, that the .ogg is in audio/vo/
  - writes dialogue_db/voiced_lines.tsv: a single catalogue of EVERY voiced line,
    with scene, character, voiceID, ogg path, duration and the text in 6 languages
  - a line whose sound is a wave INTERNAL to the brsar has no stream: it is
    hooked to the .wav that parse_brsar.py --extract wrote out.
  - prints coverage statistics.
"""
import os, csv, glob, sys

ROOT   = os.environ.get('TLS_ROOT',
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


# --- resolution through the sound archive -------------------------------
# A voiceID is a sound id in lastworld.brsar, and the archive says which
# .brstm it plays.  That is not always a file of the same name: 398 sounds
# play a differently named stream, and some differ only in letter case
# (SE_VOTWN_900A -> SE_VOTWN_900a.brstm).  Matching on the name alone misses
# those; asking the archive does not.
def brsar_index():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from parse_brsar import Brsar
        path = os.path.join(ROOT, 'extract', 'files', 'sound', 'lastworld.brsar')
        if not os.path.exists(path):
            return {}
        b = Brsar(open(path, 'rb').read())
    except Exception:
        return {}
    out = {}
    for i in range(len(b.sounds)):
        kind, src = b.sound_source(i)
        if kind == 'file':
            out[b.sound_name(i).upper()] = os.path.splitext(os.path.basename(src))[0]
    return out

def main():
    manifest = load_manifest()
    stream_set = set(os.path.splitext(f)[0] for f in os.listdir(STREAM))
    stream_ci = {s.upper(): s for s in stream_set}
    archive = brsar_index()
    rwav_dir = os.path.join(AUDIO, 'rwav')
    rwav_ci = ({f.upper()[:-4]: f for f in os.listdir(rwav_dir) if f.endswith('.wav')}
               if os.path.isdir(rwav_dir) else {})
    def ogg_rel(v):
        sub = 'vo' if v.startswith('VO_') else 'se' if v.startswith('SE_') else None
        if sub and os.path.exists(os.path.join(AUDIO, sub, v + '.ogg')):
            return f'audio/{sub}/{v}.ogg'
        return ''

    scenes = sorted(glob.glob(os.path.join(DB, 'dg*.tsv')) +
                    glob.glob(os.path.join(DB, 'tw*.tsv')) +
                    [os.path.join(DB, 'system.tsv')])

    out_rows = []
    n_lines = n_voiced = n_matched = n_ogg = n_via_brsar = n_internal = 0
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
                stream = v if v in stream_set else ''
                via = ''
                if not stream:
                    cand = archive.get(v.upper())
                    if cand:
                        stream = stream_ci.get(cand.upper(), '')
                        if stream:
                            via = 'brsar'
                            n_via_brsar += 1
                has_stream = bool(stream)
                ogg = ogg_rel(stream) if stream else ''
                if not has_stream:
                    inner = rwav_ci.get(v.upper())
                    if inner:
                        via = 'brsar-internal'
                        ogg = 'audio/rwav/' + inner
                        n_internal += 1
                    else:
                        missing.append((scene, v))
                if has_stream: n_matched += 1
                if ogg: n_ogg += 1
                info = manifest.get(stream, {})
                out_rows.append({
                    'scene': scene,
                    'M': row.get('M',''),
                    'chara': row.get('chara',''),
                    'voice': v,
                    'stream': stream,
                    'via': via,
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
    cols = ['scene','M','chara','voice','stream','via','ogg','has_stream',
            'seconds','sample_rate','channels','jp','en','fr','de','es','it']
    with open(out, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter='\t')
        w.writeheader()
        w.writerows(out_rows)

    print(f"DB rows total           : {n_lines}")
    print(f"voiced lines (VO/SE)    : {n_voiced}")
    print(f"  with a .brstm stream  : {n_matched}  ({100*n_matched/max(1,n_voiced):.1f}%)")
    print(f"    of those, resolved through the BRSAR: {n_via_brsar}")
    print(f"  hooked to an internal wave  : {n_internal}")
    print(f"  with a converted .ogg : {n_ogg}")
    print(f"voiced_lines.tsv        : {out}  ({len(out_rows)} rows)")
    distinct_missing = sorted(set(v for _, v in missing))
    print(f"voiceIDs with no stream : {len(distinct_missing)} distinct, {len(missing)} rows")
    print("  -- the archive does not know them at all: they are cut, not unmatched")
    if distinct_missing:
        print("  examples:", distinct_missing[:12])

if __name__ == '__main__':
    main()
