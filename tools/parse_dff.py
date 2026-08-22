"""Parser for Dolphin's FIFO log (.dff): the GX command stream the emulator
actually saw during a real run, plus the contents of the memory the game had
in RAM at that moment.

It is the EXTERNAL WITNESS for geometry, the way dumped textures are for the
image decoder.

The container is little-endian (it is a host file, not a Wii file); the GX
commands inside `fifo` are big-endian.

Usage:  python tools/parse_dff.py fifo.dff
"""
import struct, sys, collections

u8 = lambda d, o: d[o]
u16 = lambda d, o: struct.unpack_from('<H', d, o)[0]
u32 = lambda d, o: struct.unpack_from('<I', d, o)[0]
u64 = lambda d, o: struct.unpack_from('<Q', d, o)[0]


def header(d):
    h = dict(
        file_id=u32(d, 0x00), version=u32(d, 0x04), min_loader=u32(d, 0x08),
        bp_off=u64(d, 0x0c), bp_size=u32(d, 0x14),
        cp_off=u64(d, 0x18), cp_size=u32(d, 0x20),
        xf_off=u64(d, 0x24), xf_size=u32(d, 0x2c),
        xfreg_off=u64(d, 0x30), xfreg_size=u32(d, 0x38),
        frames_off=u64(d, 0x3c), frame_count=u32(d, 0x44),
        frame_size=u32(d, 0x48),
        tex_off=u64(d, 0x4c), tex_size=u32(d, 0x54),
        mem1=u32(d, 0x58), mem2=u32(d, 0x5c),
        game_id=d[0x60:0x66].decode('ascii', 'replace'))
    return h


def frames(d, h):
    out = []
    for i in range(h['frame_count']):
        o = h['frames_off'] + i * h['frame_size']
        out.append(dict(
            fifo_off=u64(d, o + 0x00), fifo_size=u32(d, o + 0x08),
            fifo_start=u32(d, o + 0x0c), fifo_end=u32(d, o + 0x10),
            mem_off=u64(d, o + 0x14), mem_count=u32(d, o + 0x1c)))
    return out


MEM_TYPE = {1: 'TEXTURE_MAP', 2: 'XF_DATA', 4: 'VERTEX_STREAM', 8: 'TMEM'}


def mem_updates(d, fr, stride=21):
    """Each record: fifoPosition u32, address u32, dataOffset u64,
    dataSize u32, type u8."""
    out = []
    for i in range(fr['mem_count']):
        o = fr['mem_off'] + i * stride
        out.append(dict(fifo_pos=u32(d, o), addr=u32(d, o + 4),
                        data_off=u64(d, o + 8), size=u32(d, o + 16),
                        type=u8(d, o + 20)))
    return out


def check_stride(d, fr):
    """Find the record length by MEASURING it: the right one is the only
    stride for which every record has a known type, a non-decreasing FIFO
    position, and a blob that lies inside the file."""
    ok = []
    for stride in range(16, 33):
        try:
            u = mem_updates(d, fr, stride)
        except struct.error:
            continue
        if not u:
            continue
        good = (all(x['type'] in MEM_TYPE for x in u)
                and all(u[i]['fifo_pos'] <= u[i + 1]['fifo_pos']
                        for i in range(len(u) - 1))
                and all(0 < x['size'] <= 0x400000 for x in u)
                and all(x['data_off'] + x['size'] <= len(d) for x in u))
        if good:
            ok.append(stride)
    return ok


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'fifo.dff'
    d = open(path, 'rb').read()
    h = header(d)
    print(f'{path}: {len(d)} bytes')
    print(f'  file_id  0x{h["file_id"]:08x}  version {h["version"]}  '
          f'min_loader {h["min_loader"]}  game {h["game_id"]}')
    print(f'  BP  @0x{h["bp_off"]:x} x{h["bp_size"]}   '
          f'CP  @0x{h["cp_off"]:x} x{h["cp_size"]}')
    print(f'  XF  @0x{h["xf_off"]:x} x{h["xf_size"]}   '
          f'XFregs @0x{h["xfreg_off"]:x} x{h["xfreg_size"]}')
    print(f'  TMEM @0x{h["tex_off"]:x} x0x{h["tex_size"]:x}   '
          f'MEM1 0x{h["mem1"]:x}  MEM2 0x{h["mem2"]:x}')
    print(f'  {h["frame_count"]} frame(s), record of {h["frame_size"]} bytes '
          f'@0x{h["frames_off"]:x}')

    F = frames(d, h)
    for i, fr in enumerate(F):
        print(f'\n  frame {i}: fifo @0x{fr["fifo_off"]:x} x0x{fr["fifo_size"]:x}'
              f'  (GP range 0x{fr["fifo_start"]:08x}-0x{fr["fifo_end"]:08x})')
        print(f'            {fr["mem_count"]} memory updates '
              f'@0x{fr["mem_off"]:x}')
        # arithmetic closures: they are the proof the layout is read right
        print(f'            fifo_off+fifo_size == mem_off ? '
              f'{fr["fifo_off"] + fr["fifo_size"] == fr["mem_off"]}')
        strides = check_stride(d, fr)
        print(f'            measured record length: {strides}')
        if not strides:
            continue
        U = mem_updates(d, fr, strides[0])
        t = collections.Counter(MEM_TYPE.get(x['type'], x['type']) for x in U)
        print(f'            types: {dict(t)}')
        tot = sum(x['size'] for x in U)
        print(f'            {tot} bytes of RAM ({tot/1e6:.2f} MB)')
        lo = min(x['data_off'] for x in U)
        hi = max(x['data_off'] + x['size'] for x in U)
        print(f'            blobs 0x{lo:x}..0x{hi:x}; end of file 0x{len(d):x} '
              f'-> matches: {hi == len(d)}')
        ar = sorted(set((x["addr"] >> 24) for x in U))
        print(f'            address regions (top byte): {[hex(a) for a in ar]}')


if __name__ == '__main__':
    main()
