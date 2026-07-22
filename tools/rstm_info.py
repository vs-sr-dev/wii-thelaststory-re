#!/usr/bin/env python3
"""
rstm_info.py - Parser dell'header BRSTM/RSTM (Nintendo) di The Last Story.

Legge i campi audio direttamente dall'header (nessun subprocess): usato per
generare il manifest di tutti i 12.696 stream senza spawnare vgmstream 12k volte.

Layout RSTM (big-endian, BOM FE FF):
  0x00  'RSTM'
  0x04  BOM (FE FF)
  0x08  file_size (u32)
  0x10  HEAD chunk offset (u32), 0x14 HEAD size (u32)
  HEAD chunk @ head_off:
    +0x00 'HEAD' + size
    +0x08 tre reference (8 byte: marker u8=0x01, 3 pad, offset u32 rel. a +0x08)
    la prima reference -> block1 (stream info):
      +0x00 codec u8   (0=PCM8,1=PCM16,2=DSP-ADPCM)
      +0x01 loop_flag u8
      +0x02 channels u8
      +0x03 pad
      +0x04 sample_rate u16
      +0x08 loop_start  u32 (samples)
      +0x0C total_samples u32 (samples)
Verificato contro vgmstream-cli -m (32000Hz/loop 917504/tot 3080266).
"""
import struct

CODEC = {0: 'PCM8', 1: 'PCM16', 2: 'DSP-ADPCM'}

def read_info(path):
    with open(path, 'rb') as f:
        hdr = f.read(0x100)
    if hdr[:4] != b'RSTM':
        raise ValueError(f'non RSTM: {path}')
    head_off = struct.unpack_from('>I', hdr, 0x10)[0]
    # prima reference: offset a head_off+0x0C (marker@+0x08, offset@+0x0C)
    b1_rel = struct.unpack_from('>I', hdr, head_off + 0x0C)[0]
    b1 = head_off + 0x08 + b1_rel
    codec, loop, chans, _pad = hdr[b1], hdr[b1+1], hdr[b1+2], hdr[b1+3]
    sr = struct.unpack_from('>H', hdr, b1 + 0x04)[0]
    loop_start, total = struct.unpack_from('>II', hdr, b1 + 0x08)
    return {
        'codec': CODEC.get(codec, f'?{codec}'),
        'channels': chans,
        'sample_rate': sr,
        'loop': bool(loop),
        'loop_start': loop_start if loop else 0,
        'total_samples': total,
        'seconds': round(total / sr, 3) if sr else 0.0,
    }

if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        print(p, read_info(p))
