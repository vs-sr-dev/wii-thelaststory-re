#!/usr/bin/env python3
"""
build_audio_manifest.py - Manifest di tutti gli stream .brstm (audio/manifest.csv).

Legge l'header RSTM di ogni file (via rstm_info) e produce una tabella con
categoria, codec, canali, sample rate, loop, durata. Nessun subprocess.
"""
import os, csv, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rstm_info import read_info

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAM = os.path.join(ROOT, 'extract', 'files', 'sound', 'stream')
OUTDIR = os.path.join(ROOT, 'audio')

def macro(name):
    for p in ('VO_', 'SE_', 'BGM_'):
        if name.startswith(p):
            return p.rstrip('_')
    return 'EV/other'

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    files = sorted(f for f in os.listdir(STREAM) if f.lower().endswith('.brstm'))
    out = os.path.join(OUTDIR, 'manifest.csv')
    n_err = 0
    stats = {}   # macro -> [count, seconds, bytes]
    with open(out, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['file', 'macro', 'codec', 'channels', 'sample_rate',
                    'loop', 'loop_start', 'total_samples', 'seconds', 'bytes'])
        for f in files:
            path = os.path.join(STREAM, f)
            try:
                info = read_info(path)
            except Exception as e:
                n_err += 1
                sys.stderr.write(f'ERR {f}: {e}\n')
                continue
            m = macro(f)
            sz = os.path.getsize(path)
            w.writerow([f, m, info['codec'], info['channels'], info['sample_rate'],
                        int(info['loop']), info['loop_start'], info['total_samples'],
                        info['seconds'], sz])
            s = stats.setdefault(m, [0, 0.0, 0])
            s[0] += 1; s[1] += info['seconds']; s[2] += sz

    print(f"file processati : {len(files)-n_err}  (errori: {n_err})")
    print(f"manifest        : {out}")
    print(f"{'macro':10} {'n':>6} {'durata':>12} {'MB':>8}")
    tot = [0, 0.0, 0]
    for m, (n, sec, b) in sorted(stats.items()):
        h = int(sec // 3600); mm = int((sec % 3600)//60); ss = int(sec % 60)
        print(f"{m:10} {n:6} {h:3}h{mm:02}m{ss:02}s {b/1048576:8.1f}")
        tot[0]+=n; tot[1]+=sec; tot[2]+=b
    h=int(tot[1]//3600); mm=int((tot[1]%3600)//60); ss=int(tot[1]%60)
    print(f"{'TOTALE':10} {tot[0]:6} {h:3}h{mm:02}m{ss:02}s {tot[2]/1048576:8.1f}")

if __name__ == '__main__':
    main()
