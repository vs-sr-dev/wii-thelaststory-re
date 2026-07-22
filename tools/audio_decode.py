#!/usr/bin/env python3
"""
audio_decode.py - Convertitore batch degli stream BRSTM di The Last Story.

Wrappa vgmstream-cli. Decodifica DSP-ADPCM (Nintendo) -> WAV, e opzionalmente
ri-codifica in OGG Vorbis (web-friendly) tramite ffmpeg via pipe (nessun WAV
temporaneo su disco). Parallelo, resumable (salta gli output gia' presenti).

Uso:
  python tools/audio_decode.py --cat VO --fmt ogg            # tutte le voci -> audio/vo/*.ogg
  python tools/audio_decode.py --cat BGM --fmt wav           # musica -> WAV (loop ignorato, 1 passata)
  python tools/audio_decode.py --cat all --fmt ogg -j 12
  python tools/audio_decode.py --list VO_PLD001_0010 ...     # file specifici

Categorie: VO, SE, BGM, EV, all.  Formati: ogg (default), wav.
BGM/EV con loop -> resi in una singola passata pulita (-i) [il loop_start e' nel manifest].
"""
import os, sys, argparse, subprocess, concurrent.futures as cf

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAM = os.path.join(ROOT, 'extract', 'files', 'sound', 'stream')
OUTBASE= os.path.join(ROOT, 'audio')
# vgmstream sta nello scratchpad di sessione; override via env VGMSTREAM_CLI
# Path to vgmstream-cli: set the VGMSTREAM_CLI env var, else it must be on PATH.
VGM = os.environ.get('VGMSTREAM_CLI', 'vgmstream-cli')
FFMPEG = 'ffmpeg'

SUBDIR = {'VO': 'vo', 'SE': 'se', 'BGM': 'bgm', 'EV': 'ev'}

def macro(name):
    for p in ('VO_', 'SE_', 'BGM_'):
        if name.startswith(p):
            return p.rstrip('_')
    return 'EV'

def pick(cat):
    files = sorted(f for f in os.listdir(STREAM) if f.lower().endswith('.brstm'))
    if cat == 'all':
        return files
    return [f for f in files if macro(f) == cat]

def convert(src, dst, fmt, quality):
    """src .brstm -> dst (.ogg via pipe, o .wav diretto). Ritorna (dst, ok, err)."""
    tmp = dst + '.part'
    try:
        if fmt == 'wav':
            r = subprocess.run([VGM, '-i', '-o', tmp, src],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if r.returncode != 0:
                return (dst, False, r.stderr.decode('utf-8','replace')[:200])
        else:  # ogg via pipe vgmstream(-p) | ffmpeg
            p1 = subprocess.Popen([VGM, '-i', '-p', src],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p2 = subprocess.Popen([FFMPEG, '-y', '-loglevel', 'error', '-i', '-',
                                   '-c:a', 'libvorbis', '-q:a', str(quality), '-f', 'ogg', tmp],
                                  stdin=p1.stdout, stderr=subprocess.PIPE)
            p1.stdout.close()
            _, err = p2.communicate()
            p1.wait()
            if p2.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                return (dst, False, err.decode('utf-8','replace')[:200])
        os.replace(tmp, dst)
        return (dst, True, None)
    except Exception as e:
        return (dst, False, str(e)[:200])
    finally:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except OSError: pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cat', default='VO', choices=['VO','SE','BGM','EV','all'])
    ap.add_argument('--fmt', default='ogg', choices=['ogg','wav'])
    ap.add_argument('-j', '--jobs', type=int, default=10)
    ap.add_argument('-q', '--quality', default='1', help='qualita OGG Vorbis (-q:a), def 1')
    ap.add_argument('--list', nargs='*', help='converti file specifici (nomi senza estensione)')
    ap.add_argument('--limit', type=int, default=0, help='max file (per test)')
    args = ap.parse_args()

    # VGM puo' essere un path esplicito o un comando su PATH: valida solo il primo caso
    if (os.sep in VGM or (os.altsep and os.altsep in VGM)) and not os.path.exists(VGM):
        sys.exit(f'vgmstream-cli non trovato: {VGM}\nimposta VGMSTREAM_CLI o mettilo nel PATH')

    if args.list:
        names = [n if n.endswith('.brstm') else n+'.brstm' for n in args.list]
        outdir = os.path.join(OUTBASE, '_manual')
    else:
        names = pick(args.cat)
        outdir = os.path.join(OUTBASE, SUBDIR.get(args.cat, 'all'))
    if args.limit:
        names = names[:args.limit]
    os.makedirs(outdir, exist_ok=True)
    ext = '.' + args.fmt

    todo = []
    for f in names:
        dst = os.path.join(outdir, os.path.splitext(f)[0] + ext)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            continue
        todo.append((os.path.join(STREAM, f), dst))

    print(f"categoria={args.cat if not args.list else 'manual'} fmt={args.fmt} "
          f"totali={len(names)} da_fare={len(todo)} gia_presenti={len(names)-len(todo)} "
          f"jobs={args.jobs} -> {outdir}")
    if not todo:
        print("niente da convertire."); return

    ok = err = 0; errors = []
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(convert, s, d, args.fmt, args.quality) for s, d in todo]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            dst, good, e = fut.result()
            if good: ok += 1
            else:
                err += 1; errors.append((dst, e))
            if i % 250 == 0 or i == len(todo):
                sys.stdout.write(f"\r  {i}/{len(todo)}  ok={ok} err={err}")
                sys.stdout.flush()
    print()
    if errors:
        print(f"ERRORI ({len(errors)}):")
        for d, e in errors[:15]:
            print(f"  {os.path.basename(d)}: {e}")
    print(f"FATTO: ok={ok} err={err}")

if __name__ == '__main__':
    main()
