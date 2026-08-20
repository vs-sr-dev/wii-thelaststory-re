r"""The nested packs inside levels/ and eventpacks/ -- and why they hold nothing new.

`pack/levels.pk` and `pack/eventpacks.pk` unpack into **more packs**: 1313 and
739 of them. Each nested pack ships a `.pkh` (hash -> location) and a `.pk`
(data) but **no `.pfs`**, so there is no name tree. The archive knows where every
file is and not what any of them is called, which is why this project left them
alone for several sessions and kept listing them as the likely home of the
resource references that could not be found.

They are not. This closes that question.

--- THE CONTENT ------------------------------------------------------------
The data needs no names to come out: the `.pkh` gives offset and size and the
compression is the same LZ11. All **106,902** entries across the 2052 nested
packs decompress cleanly. But there are only **19,703 distinct hashes** among
them -- an average of 5.4 copies of each file.

--- THE NAMES --------------------------------------------------------------
The path hash is CRC-32/BZIP2 and was cracked in [02](../docs/02-pack-format.md),
so names can be *proposed* rather than read: hash a candidate path and see if it
is present. Hashing all 47,204 paths from the top-level `filesystem.pfs` gives:

    full path        19,703   100.0 % of the nested hashes
    leading slash         0
    basename              2
    basename, no ext      1

**Every distinct hash in every nested pack is a path that already exists in
`filesystem`.** Not most of them -- all of them.

And the bytes match too: on a 400-entry sample drawn across the nested packs,
**400 of 400** decompress to output byte-identical to the `filesystem` copy.

So the nested packs are a **per-level duplication of shared content**, laid out
for locality so a level loads from one contiguous archive instead of seeking
across the global one. Standard practice for optical media, and it means:

  * there is nothing new inside them;
  * they cannot explain any dangling reference;
  * naming them is free -- the hash index over `filesystem.pfs` resolves 100 %.

--- WHAT THAT LEAVES ------------------------------------------------------
The four texture names that `.eff` materials ask for and the disc does not have
(`Mb243_fire`, `Mb243_hei`, `Mb243_wave`, `eff_swd01o`) are simply **absent**,
like the two author typos already recorded in
[17](../docs/17-eff-binary.md). References to assets that were deleted before
release, not references into a pack nobody had opened.

Usage:
    python parse_nested_packs.py             # inventory + type histogram
    python parse_nested_packs.py --verify    # the two checks above
    python parse_nested_packs.py --list dg001_01
"""
import collections
import glob
import io
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lwpack import parse_pfs, parse_pkh, path_hash, lz11_decompress

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets", "pack")
PACK = os.path.join(ROOT, "extract", "files", "pack")

MAGIC = {
    b"@EFF": ".eff particle binary",
    b"COH@": ".hocb map collision",
    b"BCH@": ".hcb gimmick collision",
    b"RSTM": ".brstm audio stream",
    b"\xfe\xff": "UTF-16BE text (.u16)",
    b"<?xm": "XML (.efp)",
}


def nested_packs():
    """-> [(label, pkhPath, pkPath)] for every second-level pack."""
    out = []
    for sub in ("levels", "eventpacks"):
        d = os.path.join(ASSETS, sub, sub)
        for ph in sorted(glob.glob(os.path.join(d, "*.pkh"))):
            pk = ph[:-4] + ".pk"
            if os.path.exists(pk):
                out.append((f"{sub}/{os.path.basename(ph)[:-4]}", ph, pk))
    return out


def name_index():
    """-> {pathHash: path} built from the top-level filesystem name tree."""
    paths = parse_pfs(os.path.join(PACK, "filesystem.pfs"))
    return {path_hash(p): p for p in paths}, paths


def entry_bytes(blob, off, unc, comp):
    raw = blob[off:off + (comp if comp else unc)]
    return lz11_decompress(raw) if comp else raw


def identify(blob):
    if len(blob) < 4:
        return f"tiny ({len(blob)} B)"
    if blob.startswith(b"chnkdata"):
        sub = blob[8:16].split(b"\x00")[0].decode("ascii", "replace")
        return f"chnkdata: {sub or '?'}"
    for m, nm in MAGIC.items():
        if blob.startswith(m):
            return nm
    if all(32 <= b < 127 or b in (9, 10, 13) for b in blob[:64]):
        return "text"
    return f"unknown {blob[:4].hex()}"


def inventory():
    idx, _ = name_index()
    packs = nested_packs()
    kinds = collections.Counter()
    hashes = set()
    total = 0
    named = 0
    for label, ph, pk in packs:
        try:
            ents = parse_pkh(ph)
        except Exception:
            continue
        blob = open(pk, "rb").read()
        for h, off, unc, comp in ents:
            total += 1
            hashes.add(h)
            if h in idx:
                named += 1
            try:
                kinds[identify(entry_bytes(blob, off, unc, comp))] += 1
            except Exception:
                kinds["LZ11 failed"] += 1

    print(f"nested packs      : {len(packs)}")
    print(f"entries           : {total:,}")
    print(f"distinct hashes   : {len(hashes):,}"
          f"   ({total/max(1,len(hashes)):.1f} copies of each on average)")
    print(f"resolved to a name: {named:,}  ({named/max(1,total):.1%})\n")
    print("contents by type:")
    for k, v in kinds.most_common(15):
        print(f"  {v:7,}  {k}")


def verify():
    idx, paths = name_index()
    packs = nested_packs()
    hashes = set()
    for label, ph, pk in packs:
        try:
            for h, *_ in parse_pkh(ph):
                hashes.add(h)
        except Exception:
            pass
    print(f"distinct nested hashes : {len(hashes):,}")
    print(f"known filesystem paths : {len(paths):,}\n")

    forms = {
        "full path": lambda p: p,
        "leading slash": lambda p: "/" + p,
        "basename": lambda p: p.rsplit("/", 1)[-1],
        "basename, no ext": lambda p: p.rsplit("/", 1)[-1].rsplit(".", 1)[0],
    }
    print("CHECK 1 -- which key form do the nested packs hash?")
    for label, fn in forms.items():
        n = sum(1 for p in paths if path_hash(fn(p)) in hashes)
        print(f"  {label:18s} {n:7,}   {n/max(1,len(hashes)):6.1%} of nested hashes")

    print("\nCHECK 2 -- are the bytes the same as the filesystem copy?")
    fs_ent = {e[0]: e for e in parse_pkh(os.path.join(PACK, "filesystem.pkh"))}
    fs_blob = open(os.path.join(PACK, "filesystem.pk"), "rb").read()
    random.seed(7)
    sample = []
    for label, ph, pk in packs:
        try:
            ents = parse_pkh(ph)
        except Exception:
            continue
        if ents:
            sample.append((pk, random.choice(ents)))
    random.shuffle(sample)
    same = diff = bad = 0
    for pk, (h, off, unc, comp) in sample[:400]:
        if h not in fs_ent:
            bad += 1
            continue
        try:
            a = entry_bytes(open(pk, "rb").read(), off, unc, comp)
            _, foff, func, fcomp = fs_ent[h]
            b = entry_bytes(fs_blob, foff, func, fcomp)
        except Exception:
            bad += 1
            continue
        same += 1 if a == b else 0
        diff += 0 if a == b else 1
    n = same + diff + bad
    print(f"  sampled {n} entries: {same} identical, {diff} different, {bad} unresolved")
    print(f"  -> {same/max(1,n):.1%} byte-identical")


def listing(stem):
    idx, _ = name_index()
    for label, ph, pk in nested_packs():
        if not label.endswith("/" + stem):
            continue
        ents = parse_pkh(ph)
        print(f"{label}: {len(ents)} entries")
        for h, off, unc, comp in ents:
            print(f"  {h:08x}  {unc:8d} B  {idx.get(h, '<unresolved>')}")
        return
    print(f"no nested pack named {stem}")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    a = sys.argv[1:]
    if not a:
        inventory()
    elif a[0] == "--verify":
        verify()
    elif a[0] == "--list" and len(a) > 1:
        listing(a[1])
    else:
        print(__doc__)
