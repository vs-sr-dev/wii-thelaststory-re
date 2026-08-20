#!/usr/bin/env python3
"""
audio_decode.py - Batch converter for The Last Story's BRSTM streams.

Wraps vgmstream-cli. Decodes Nintendo DSP-ADPCM -> WAV, and optionally re-encodes
to OGG Vorbis (web-friendly) through ffmpeg over a pipe (no temporary WAV hits the
disk). Parallel and resumable (skips outputs that already exist).

Usage:
  python tools/audio_decode.py --cat VO --fmt ogg            # every voice clip -> audio/vo/*.ogg
  python tools/audio_decode.py --cat BGM --fmt wav           # music -> WAV (loop ignored, single pass)
  python tools/audio_decode.py --cat all --fmt ogg -j 12
  python tools/audio_decode.py --list VO_PLD001_0010 ...     # specific files

Categories: VO, SE, BGM, EV, all.  Formats: ogg (default), wav.
Looping BGM/EV are rendered as one clean pass (-i) [loop_start lives in the manifest].
"""
import os, sys, argparse, subprocess, concurrent.futures as cf

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAM = os.path.join(ROOT, 'extract', 'files', 'sound', 'stream')
OUTBASE= os.path.join(ROOT, 'audio')
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
    """src .brstm -> dst (.ogg through the pipe, or .wav directly). Returns (dst, ok, err)."""
    tmp = dst + '.part'
    try:
        if fmt == 'wav':
            r = subprocess.run([VGM, '-i', '-o', tmp, src],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if r.returncode != 0:
                return (dst, False, r.stderr.decode('utf-8','replace')[:200])
        else:  # ogg over the vgmstream(-p) | ffmpeg pipe
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
    ap.add_argument('-q', '--quality', default='1', help='OGG Vorbis quality (-q:a), default 1')
    ap.add_argument('--list', nargs='*', help='convert specific files (names without extension)')
    ap.add_argument('--limit', type=int, default=0, help='max files (for a quick test)')
    args = ap.parse_args()

    # VGM may be an explicit path or a command on PATH: only validate the first case
    if (os.sep in VGM or (os.altsep and os.altsep in VGM)) and not os.path.exists(VGM):
        sys.exit(f'vgmstream-cli not found: {VGM}\nset VGMSTREAM_CLI or put it on your PATH')

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

    print(f"category={args.cat if not args.list else 'manual'} fmt={args.fmt} "
          f"total={len(names)} todo={len(todo)} already_there={len(names)-len(todo)} "
          f"jobs={args.jobs} -> {outdir}")
    if not todo:
        print("nothing to convert."); return

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
        print(f"ERRORS ({len(errors)}):")
        for d, e in errors[:15]:
            print(f"  {os.path.basename(d)}: {e}")
    print(f"DONE: ok={ok} err={err}")

if __name__ == '__main__':
    main()
