r"""The .eff loader inside main.dol -- and the schemas that declare its layout.

The `.eff` particle format is little-endian on a big-endian console, so
something has to byte-swap it at load. Finding that code turns out to hand over
the format's field layout, because the swapper is **schema-driven**: it does not
know about `.eff` at all, it walks a descriptor table.

--- HOW IT WAS FOUND -------------------------------------------------------
PowerPC has byte-reversing loads (`lwbrx`), so those were the obvious net.
There are exactly 32 in the whole DOL and all 32 sit in one routine -- which
turns out to be **MD5** (the F function, the sine table, the 7/12/17/22
rotations; MD5 is defined little-endian). A dead end, but a decisive one.

That left the software idiom, `rlwimi rT,rS,24,0,7` + `rlwimi rT,rS,24,16,23`.
191 of those, in 41 clusters, two of which land in the same address region as
the `atn::EffectManager` and `atn::LoadEffect` vtables recovered in
dol_classes.py -- which is what made them worth reading first.

--- THE SWAPPER: FUN_802371bc(void *data, const Entry *schema) --------------
Entry is 8 bytes:

    s16 op ; s16 count ; u32 nested

    op -1  end of schema
    op  0  skip `count` BYTES, untouched   <- this is how strings are marked
    op  1  swap `count` u16
    op  2  swap `count` u32                <- u32 and f32 alike
    op  3  swap `count` u64
    op  4  recurse into `nested`, `count` times

Because op 0 means "leave alone", the schema says exactly which byte ranges are
text and which are numbers. It is the format's own declaration of itself, in the
same spirit as the `.hcb` relocation table.

--- THE DRIVER: FUN_80239030 -----------------------------------------------
Sole caller. In order it:

  1. swaps the 64-byte header with the schema at 0x80783a18
  2. reads a VERSION at +0x04:  < 0x22 -> refuse to load and return 0
                                < 0x24 -> load, but log "old eff version!"
                               >= 0x24 -> two extra header words at +0x40/+0x44
  3. relocates the section offsets at +0x28..+0x3c by adding the base address
  4. walks `count` at +0x0c emitters of stride 0x26c  (620) -> schema 0x80783a80
  5. walks `count` at +0x10 materials of stride 0x138 (312) -> schema 0x80783b18
  6. walks `count` at +0x1c records of stride 0x110 (272)   -> schema 0x80783b60
  7. for each emitter, loops **22** times (`iVar7 < 0x16`) over 8-byte
     (count, offset) pairs inside a 0xb0 = 176-byte block, relocating each
     offset and swapping `count` 8-byte keys
  8. for each 272-byte record, the same with **13** channels in a 0x68 = 104-byte
     block

Steps 4, 5 and 7 confirm 620 / 312 / 22 / 8 from the code, independently of the
file-size arithmetic that established them in parse_eff.py.

--- WHAT THIS CORRECTED ----------------------------------------------------
The magic was read as the 8 bytes `'@EFF$\0\0\0'`. It is not. The header schema
skips **4** bytes and then swaps a u32, and the loader treats that u32 as the
version. So the magic is `'@EFF'` and the `'$'` is the low byte of version
**0x24** in little-endian. Checked on every `.eff` on the disc: 3158/3158 files
have magic `@EFF` and version `0x24` -- accepted by the loader, and new enough
to avoid the "old eff version!" path.

--- WHAT IT ADDED ----------------------------------------------------------
A **third record type**: 272 bytes, its own count at header +0x1c, its own
section at +0x20, and **13** animatable channels of its own. Its count is 0 in
all 3158 files. parse_eff.py had already found that section empty everywhere;
the loader says it is not padding but a supported structure this game never
shipped.

Usage:
    python dol_swap_schema.py             # decode the six .eff schemas
    python dol_swap_schema.py 0x80783a80  # decode a schema at any address
"""
import io
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOL = os.path.join(ROOT, "extract", "sys", "main.dol")

OPS = {-1: "END", 0: "skip bytes", 1: "swap u16", 2: "swap u32",
       3: "swap u64", 4: "recurse"}
WIDTH = {0: 1, 1: 2, 2: 4, 3: 8}

# The schemas FUN_80239030 passes, in the order it uses them.
EFF_SCHEMAS = [
    ("HEADER",                 0x80783A18),
    ("EMITTER (stride 620)",   0x80783A80),
    ("MATERIAL (stride 312)",  0x80783B18),
    ("THIRD TYPE (stride 272)", 0x80783B60),
    ("u32 table entry",        0x80783B90),
    ("CURVE KEY",              0x80783BA0),
]


class Dol:
    def __init__(self, path=DOL):
        self.d = open(path, "rb").read()
        u32 = lambda o: struct.unpack_from(">I", self.d, o)[0]
        self.secs = []
        for i in range(18):
            if i < 7:
                off, addr, size = u32(0x00 + i*4), u32(0x48 + i*4), u32(0x90 + i*4)
            else:
                j = i - 7
                off, addr, size = u32(0x1C + j*4), u32(0x64 + j*4), u32(0xAC + j*4)
            if size:
                self.secs.append((addr, off, size))

    def off(self, va):
        for addr, off, size in self.secs:
            if addr <= va < addr + size:
                return off + (va - addr)
        return None


def read_schema(dol, va, depth=0, seen=None):
    """-> (entries, totalBytes); entry = (offset, op, count, nested, sub, subSize)."""
    seen = set(seen or ())
    if va in seen or depth > 4:
        return [], 0
    seen.add(va)
    out, off = [], 0
    for i in range(4096):
        o = dol.off(va + i * 8)
        if o is None:
            break
        op, cnt = struct.unpack_from(">hh", dol.d, o)
        nested = struct.unpack_from(">I", dol.d, o + 4)[0]
        if op == -1:
            break
        if op == 4:
            sub, subsize = read_schema(dol, nested, depth + 1, seen)
            out.append((off, op, cnt, nested, sub, subsize))
            off += cnt * subsize
        else:
            out.append((off, op, cnt, None, None, 0))
            off += cnt * WIDTH.get(op, 0)
    return out, off


def show(dol, name, va):
    ents, total = read_schema(dol, va)
    print(f"\n=== {name}  @ {va:#010x}   describes {total} bytes ({total:#x}) ===")
    if not ents:
        print("  (nothing readable there)")
        return
    for off, op, cnt, nested, sub, subsize in ents:
        span = cnt * (subsize if op == 4 else WIDTH.get(op, 0))
        tail = f"  -> {nested:#010x}, {cnt} x {subsize} B" if op == 4 else ""
        note = "   <- text, left alone" if op == 0 else ""
        print(f"  +0x{off:03x}  {OPS.get(op, op):11s} x{cnt:<4d} = {span:5d} B{tail}{note}")
        for so, sop, scnt, *_ in (sub or []):
            print(f"             +0x{so:03x}  {OPS.get(sop, sop):11s} x{scnt}")


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    if not os.path.exists(DOL):
        sys.exit(f"need {DOL} -- see docs/07-main-dol-ghidra.md")
    dol = Dol()
    args = sys.argv[1:]
    if args:
        for a in args:
            show(dol, f"schema {a}", int(a, 0))
    else:
        for name, va in EFF_SCHEMAS:
            show(dol, name, va)


if __name__ == "__main__":
    main()
