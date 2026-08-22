r"""The sound archive: `lastworld.brsar`, read from the bytes up.

This is the last large asset container on the disc that had never been opened.
It is 85.8 MB, one file, and everything the game can play that is not a
`.brstm` sitting on the filesystem lives inside it.

The layout is recovered here the way the other formats were: by adjacency and
by counting, not by assuming.  Three measurements carry the whole parse, and
each one is checked against something the format does not have to satisfy:

  * the four SYMB name trees are **contiguous byte for byte**, and their
    leaves sum to exactly the number of strings in the string table
    (13996 + 5 + 167 + 3 = 14171).  No orphan string, no invented leaf.
  * every INFO table ends exactly where its first entry begins, so the entry
    stride is a measurement and not a guess -- and a sound entry's own two
    references land on `+0x2c` and `+0x38` of itself, which is what says the
    entry is 0x2c of head plus two 0x0c tails.
  * the last group's wave block ends at `0x51dd940`, the final byte of the
    file.

The archive is also the missing half of the audio work.  `audio/rsid_table.csv`
came from `LastWorld.rsid.csv`, which ships in the clear on the disc; what that
registry never had was the binding from a sound name to actual audio.  The
BRSAR is that binding, and the two agree on 13996 of 13996 names in entry
order.

  python tools/parse_brsar.py --summary
  python tools/parse_brsar.py --validate
  python tools/parse_brsar.py --csv audio/brsar_sounds.csv
  python tools/parse_brsar.py --groups audio/brsar_groups.csv
  python tools/parse_brsar.py --extract audio/rwav
"""
import argparse
import collections
import csv
import os
import struct
import sys

ROOT = os.environ.get('TLS_ROOT',
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT = os.path.join(ROOT, 'extract', 'files', 'sound', 'lastworld.brsar')

SOUND_TYPE = {1: 'SEQ', 2: 'STRM', 3: 'WAVE'}
WAVE_FORMAT = {0: 'PCM8', 1: 'PCM16', 2: 'ADPCM'}


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

class Blob(object):
    def __init__(self, data):
        self.d = data

    def u8(self, o):
        return self.d[o]

    def u16(self, o):
        return struct.unpack_from('>H', self.d, o)[0]

    def u32(self, o):
        return struct.unpack_from('>I', self.d, o)[0]

    def s16(self, o):
        return struct.unpack_from('>h', self.d, o)[0]

    def s32(self, o):
        return struct.unpack_from('>i', self.d, o)[0]

    def cstr(self, o):
        end = self.d.index(b'\x00', o)
        return self.d[o:end].decode('ascii', 'replace')


class Ref(object):
    """The 8-byte tagged pointer the format uses everywhere.

    Byte 0 is the base the offset is relative to (1 = the section's data base,
    the only value this archive ever uses), byte 1 is a data-type tag, and the
    trailing u32 is the offset.  A zero offset means null.
    """
    __slots__ = ('base_type', 'data_type', 'offset')

    def __init__(self, base_type, data_type, offset):
        self.base_type = base_type
        self.data_type = data_type
        self.offset = offset

    def __repr__(self):
        return 'Ref(%d,%d,%#x)' % (self.base_type, self.data_type, self.offset)


def read_ref(b, a):
    return Ref(b.u8(a), b.u8(a + 1), b.u32(a + 4))


# --------------------------------------------------------------------------
# INFO records
# --------------------------------------------------------------------------

class SoundInfo(object):
    """0x2c of head, then the per-type tail at +0x2c and the 3D block at +0x38."""

    def __init__(self, b, a):
        self.addr = a
        self.string_id = b.u32(a + 0x00)
        self.file_id = b.u32(a + 0x04)
        self.player_id = b.u32(a + 0x08)
        self.param3d_ref = read_ref(b, a + 0x0c)
        self.volume = b.u8(a + 0x14)
        self.player_priority = b.u8(a + 0x15)
        self.sound_type = b.u8(a + 0x16)
        self.remote_filter = b.u8(a + 0x17)
        self.ext_ref = read_ref(b, a + 0x18)
        self.user_param1 = b.u32(a + 0x20)
        self.user_param2 = b.u32(a + 0x24)
        self.pan_mode = b.u8(a + 0x28)
        self.pan_curve = b.u8(a + 0x29)
        self.actor_player_id = b.u8(a + 0x2a)

    @property
    def type_name(self):
        return SOUND_TYPE.get(self.sound_type, '?%d' % self.sound_type)


class Sound3DParam(object):
    def __init__(self, b, a):
        self.flags = b.u32(a + 0x00)
        self.decay_curve = b.u8(a + 0x04)
        self.decay_ratio = b.u8(a + 0x05)
        self.doppler_factor = b.u8(a + 0x06)


class FileInfo(object):
    def __init__(self, b, base, a):
        self.addr = a
        self.file_size = b.u32(a + 0x00)
        self.wave_data_size = b.u32(a + 0x04)
        self.entry_number = b.s32(a + 0x08)
        self.path_ref = read_ref(b, a + 0x0c)
        self.pos_ref = read_ref(b, a + 0x14)
        self.external_path = (b.cstr(base + self.path_ref.offset)
                              if self.path_ref.offset else None)
        self.positions = []
        if self.pos_ref.offset:
            t = base + self.pos_ref.offset
            for i in range(b.u32(t)):
                e = base + b.u32(t + 4 + i * 8 + 4)
                self.positions.append((b.u32(e), b.u32(e + 4)))  # (group, item)


class GroupItem(object):
    """24 bytes: which file, and where its two halves sit inside the group."""

    def __init__(self, b, a):
        self.file_id = b.u32(a + 0x00)
        self.data_offset = b.u32(a + 0x04)
        self.data_size = b.u32(a + 0x08)
        self.wave_offset = b.u32(a + 0x0c)
        self.wave_size = b.u32(a + 0x10)
        self.reserved = b.u32(a + 0x14)


class GroupInfo(object):
    def __init__(self, b, base, a):
        self.addr = a
        self.string_id = b.s32(a + 0x00)
        self.entry_number = b.s32(a + 0x04)
        self.path_ref = read_ref(b, a + 0x08)
        self.data_offset = b.u32(a + 0x10)
        self.data_size = b.u32(a + 0x14)
        self.wave_offset = b.u32(a + 0x18)
        self.wave_size = b.u32(a + 0x1c)
        self.item_ref = read_ref(b, a + 0x20)
        self.items = []
        if self.item_ref.offset:
            t = base + self.item_ref.offset
            for i in range(b.u32(t)):
                self.items.append(GroupItem(b, base + b.u32(t + 4 + i * 8 + 4)))


class BankInfo(object):
    def __init__(self, b, a):
        self.string_id = b.s32(a + 0x00)
        self.file_id = b.u32(a + 0x04)


class PlayerInfo(object):
    def __init__(self, b, a):
        self.string_id = b.s32(a + 0x00)
        self.playable_sound_count = b.u8(a + 0x04)
        self.heap_size = b.u32(a + 0x08)


# --------------------------------------------------------------------------
# the archive
# --------------------------------------------------------------------------

class Brsar(Blob):
    def __init__(self, data):
        Blob.__init__(self, data)
        if self.d[:4] != b'RSAR':
            raise ValueError('not an RSAR file')
        self.bom = self.u16(0x04)
        self.version = self.u16(0x06)
        self.declared_size = self.u32(0x08)
        self.header_len = self.u16(0x0c)
        self.section_count = self.u16(0x0e)
        self.sections = []
        for i in range(self.section_count):
            o = 0x10 + i * 8
            off, size = self.u32(o), self.u32(o + 4)
            self.sections.append((self.d[off:off + 4], off, size))

        self.symb_off = self.sections[0][1]
        self.info_off = self.sections[1][1]
        self.file_off = self.sections[2][1]
        self._read_symb()
        self._read_info()

    # -- SYMB ------------------------------------------------------------
    def _read_symb(self):
        b = self.symb_off + 8            # every SYMB offset is relative to here
        self.symb_base = b
        self.strtab = b + self.u32(b)
        self.string_count = self.u32(self.strtab)
        self.tree_addr = [b + self.u32(b + 4 + i * 4) for i in range(4)]
        self.tree_names = ['sound', 'player', 'group', 'bank']

    def string(self, i):
        if i is None or i < 0 or i >= self.string_count:
            return None
        return self.cstr(self.symb_base + self.u32(self.strtab + 4 + i * 4))

    def tree(self, which):
        """(root index, [(is_leaf, bit, left, right, string id, item id)])."""
        a = self.tree_addr[which]
        root, n = self.u32(a), self.u32(a + 4)
        nodes = []
        for i in range(n):
            o = a + 8 + i * 0x14
            nodes.append((self.u16(o) & 1, self.u16(o + 2), self.u32(o + 4),
                          self.u32(o + 8), self.s32(o + 12), self.s32(o + 16)))
        return root, nodes

    def tree_lookup(self, which, name, nodes=None, root=None):
        """Walk the patricia tree the way the runtime does, and return the id.

        A branch node stores a bit index into the name: bit `k` is bit
        `7 - (k & 7)` of byte `k >> 3`, and a name too short for the index
        takes the left branch.  The leaf is only a hit if its string is the
        one we asked for -- the walk alone never fails, it just lands wrong.
        """
        if nodes is None:
            root, nodes = self.tree(which)
        raw = name.encode('ascii', 'replace')
        cur = root
        steps = 0
        while cur < len(nodes) and not nodes[cur][0]:
            steps += 1
            if steps > len(nodes):
                return None                       # cycle: malformed tree
            bit = nodes[cur][1]
            byte, mask = bit >> 3, 1 << (7 - (bit & 7))
            go_right = byte < len(raw) and (raw[byte] & mask)
            cur = nodes[cur][3] if go_right else nodes[cur][2]
        if cur >= len(nodes):
            return None
        leaf = nodes[cur]
        return leaf[5] if self.string(leaf[4]) == name else None

    # -- INFO ------------------------------------------------------------
    def _read_info(self):
        b = self.info_off + 8            # every INFO offset is relative to here
        self.info_base = b
        refs = [read_ref(self, b + i * 8) for i in range(6)]
        self.info_refs = refs

        def table(ref):
            a = b + ref.offset
            n = self.u32(a)
            return [b + self.u32(a + 4 + i * 8 + 4) for i in range(n)], a

        sa, self.sound_tab_addr = table(refs[0])
        ba, self.bank_tab_addr = table(refs[1])
        pa, self.player_tab_addr = table(refs[2])
        fa, self.file_tab_addr = table(refs[3])
        ga, self.group_tab_addr = table(refs[4])

        self.sounds = [SoundInfo(self, a) for a in sa]
        self.banks = [BankInfo(self, a) for a in ba]
        self.players = [PlayerInfo(self, a) for a in pa]
        self.files = [FileInfo(self, b, a) for a in fa]
        self.groups = [GroupInfo(self, b, a) for a in ga]
        self.sound_addrs = sa
        self.group_addrs = ga

        f = b + refs[5].offset
        self.footer = tuple(self.u16(f + i * 2) for i in range(8))

    # -- convenience -----------------------------------------------------
    def sound_name(self, i):
        return self.string(self.sounds[i].string_id)

    def group_name(self, i):
        s = self.groups[i].string_id
        return self.string(s) if s >= 0 else None

    def sound_3d(self, i):
        s = self.sounds[i]
        return (Sound3DParam(self, self.info_base + s.param3d_ref.offset)
                if s.param3d_ref.offset else None)

    def sub_no(self, i):
        """A WAVE sound's index into the RWSD of the item it lives in."""
        s = self.sounds[i]
        return self.u32(self.info_base + s.ext_ref.offset) if s.ext_ref.offset else None

    def wave_of_sound(self, i):
        """Resolve a WAVE sound to the actual RWAVs it plays.

        A sound is packed into every group that needs it, so this returns one
        placement per group: (group index, item index, wave index, address).
        """
        s = self.sounds[i]
        if s.sound_type != 3:
            return []
        sub = self.sub_no(i)
        out = []
        for gi, k in self.files[s.file_id].positions:
            g = self.groups[gi]
            it = g.items[k]
            ents = read_rwsd(self, g.data_offset + it.data_offset)
            if sub is None or sub >= len(ents) or not ents[sub]:
                continue
            wi = ents[sub][0]
            waves = item_rwavs(self, g, it)
            if 0 <= wi < len(waves):
                out.append((gi, k, wi, waves[wi][0]))
        return out

    def wave_owners(self):
        """(group, item, wave index) -> the sound names that play it."""
        m = collections.defaultdict(list)
        for i, s in enumerate(self.sounds):
            if s.sound_type != 3:
                continue
            for gi, k, wi, _ in self.wave_of_sound(i):
                m[(gi, k, wi)].append(self.sound_name(i))
        return m

    def sound_source(self, i):
        """Where the audio actually is: a disc path, or a place in a group."""
        s = self.sounds[i]
        if s.file_id >= len(self.files):
            return ('none', '')
        f = self.files[s.file_id]
        if f.external_path:
            return ('file', f.external_path)
        if f.positions:
            g, k = f.positions[0]
            return ('group', '%s#%d' % (self.group_name(g) or '<unnamed>', k))
        return ('none', '')


# --------------------------------------------------------------------------
# RWAR / RWAV
# --------------------------------------------------------------------------

class Rwav(object):
    """One wave inside an RWAR, with its per-channel ADPCM state."""

    def __init__(self, b, a):
        self.addr = a
        if b.d[a:a + 4] != b'RWAV':
            raise ValueError('not RWAV at %#x' % a)
        self.size = b.u32(a + 0x08)
        nsec = b.u16(a + 0x0e)
        secs = [(b.u32(a + 0x10 + i * 8), b.u32(a + 0x14 + i * 8)) for i in range(nsec)]
        self.info_off, self.info_size = secs[0]
        self.data_off, self.data_size = secs[1]
        v = a + self.info_off + 8        # INFO body: the offsets below are off here
        self.info_body = v
        self.format = b.u8(v + 0x00)
        self.loop = b.u8(v + 0x01)
        self.channels = b.u8(v + 0x02)
        self.sample_rate = (b.u8(v + 0x03) << 16) | b.u16(v + 0x04)
        self.loop_start = b.u32(v + 0x08)
        self.loop_end = b.u32(v + 0x0c)
        chtab = v + b.u32(v + 0x10)
        self.data_location = b.u32(v + 0x14)
        self.chan = []
        for c in range(self.channels):
            ci = v + b.u32(chtab + c * 4)
            data_off = b.u32(ci + 0x00)
            adpcm_off = b.u32(ci + 0x04)
            coef = None
            gain = ps = yn1 = yn2 = lps = lyn1 = lyn2 = 0
            if adpcm_off:
                # 16 coefficients, then gain, then the two decode contexts.
                # Forgetting `gain` shifts everything below by one u16 and the
                # error is invisible in the audio -- what catches it is that
                # `ps` must equal the first frame's header byte, and
                # `loop_ps` the header byte of the frame the loop starts in.
                p = v + adpcm_off
                coef = [b.s16(p + i * 2) for i in range(16)]
                gain = b.u16(p + 0x20)
                ps = b.u16(p + 0x22)
                yn1 = b.s16(p + 0x24)
                yn2 = b.s16(p + 0x26)
                lps = b.u16(p + 0x28)
                lyn1 = b.s16(p + 0x2a)
                lyn2 = b.s16(p + 0x2c)
            self.chan.append(dict(data_off=data_off, coef=coef, gain=gain, ps=ps,
                                  yn1=yn1, yn2=yn2, loop_ps=lps, loop_yn1=lyn1,
                                  loop_yn2=lyn2))

    # `loop_start` and `loop_end` are **nibble addresses**, not sample counts:
    # a frame is 16 nibbles, of which the first two are the header byte and the
    # remaining 14 are one sample each.  Reading them as samples asks for more
    # bytes than the wave has, runs off the end of the channel, and produces
    # impossible coefficient indices in the trailing garbage.
    @staticmethod
    def nibble_to_sample(n):
        return (n // 16) * 14 + max(0, (n % 16) - 2)

    @property
    def sample_count(self):
        return self.nibble_to_sample(self.loop_end)

    @property
    def loop_start_sample(self):
        return self.nibble_to_sample(self.loop_start)

    def channel_bytes(self, b, c):
        start = self.addr + self.data_off + 8 + self.chan[c]['data_off']
        return b.d[start:start + self.loop_end // 2]


def decode_dsp(raw, coef, yn1, yn2, nsamples):
    """Nintendo DSP-ADPCM -> 16-bit PCM.  One 8-byte frame is 14 samples."""
    out = []
    hist1, hist2 = yn1, yn2
    p = 0
    while len(out) < nsamples and p < len(raw):
        head = raw[p]
        p += 1
        scale = 1 << (head & 0x0f)
        idx = (head >> 4) & 0x07
        c1, c2 = coef[idx * 2], coef[idx * 2 + 1]
        for i in range(14):
            if len(out) >= nsamples or p + (i >> 1) >= len(raw):
                break
            byte = raw[p + (i >> 1)]
            nib = (byte >> 4) if (i & 1) == 0 else (byte & 0x0f)
            if nib >= 8:
                nib -= 16
            s = (((nib * scale) << 11) + 1024 + c1 * hist1 + c2 * hist2) >> 11
            s = -32768 if s < -32768 else (32767 if s > 32767 else s)
            out.append(s)
            hist2, hist1 = hist1, s
        p += 7
    return out


def write_wav(path, channels, rate):
    """channels: a list of 16-bit sample lists."""
    n = min(len(c) for c in channels)
    nch = len(channels)
    frames = bytearray()
    for i in range(n):
        for c in channels:
            frames += struct.pack('<h', c[i])
    with open(path, 'wb') as fh:
        fh.write(b'RIFF' + struct.pack('<I', 36 + len(frames)) + b'WAVE')
        fh.write(b'fmt ' + struct.pack('<IHHIIHH', 16, 1, nch, rate,
                                       rate * nch * 2, nch * 2, 16))
        fh.write(b'data' + struct.pack('<I', len(frames)) + bytes(frames))


def item_rwavs(b, g, it):
    """Every RWAV owned by one group item, through that item's own RWAR TABL.

    The waves belong to the *item*, not to the group: a group with several
    items has several RWARs side by side in its wave block.  Reading only the
    one at the group's wave offset finds 783 of the 2518 waves in the archive
    and silently loses the rest.
    """
    if it.wave_size == 0:
        return []
    w = g.wave_offset + it.wave_offset
    if b.d[w:w + 4] != b'RWAR':
        return []
    nsec = b.u16(w + 0x0e)
    secs = [(b.u32(w + 0x10 + i * 8), b.u32(w + 0x14 + i * 8)) for i in range(nsec)]
    tabl = w + secs[0][0]
    data = w + secs[1][0]
    out = []
    for i in range(b.u32(tabl + 8)):
        e = tabl + 12 + i * 12
        out.append((data + b.u32(e + 4), b.u32(e + 8)))
    return out


def group_rwavs(b, g):
    """Every RWAV in a group, across all of its items."""
    out = []
    for it in g.items:
        out.extend(item_rwavs(b, g, it))
    return out


def item_kind(b, g, it):
    """RWSD (waves), RSEQ (a sequence) or RBNK (an instrument bank)."""
    return b.d[g.data_offset + it.data_offset:g.data_offset + it.data_offset + 4]


def read_rwsd(b, addr):
    """An RWSD's wave-sound entries, each reduced to the wave indices it plays.

    An entry is three references -- parameters, track table, note table -- and
    the note carries the index into the item's RWAR.  Every entry in this
    archive holds exactly one note.
    """
    if b.d[addr:addr + 4] != b'RWSD':
        return []
    data = addr + b.u32(addr + 0x10)
    if b.d[data:data + 4] != b'DATA':
        return []
    body = data + 8

    def reflist(a):
        return [body + b.u32(a + 4 + i * 8 + 4) for i in range(b.u32(a))]

    out = []
    for e in reflist(body):
        notes = [b.s32(n) for n in reflist(body + b.u32(e + 0x14))]
        out.append(notes)
    return out


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------

def cmd_summary(b):
    print('RSAR  version %d.%02d  bom %#06x' % (b.version >> 8, b.version & 0xff, b.bom))
    print('declared size %#x   actual %#x   %s'
          % (b.declared_size, len(b.d),
             'match' if b.declared_size == len(b.d) else 'MISMATCH'))
    print('sections:')
    for tag, off, size in b.sections:
        print('  %-4s off %#010x size %#010x  end %#010x'
              % (tag.decode('ascii', 'replace'), off, size, off + size))
    print()
    print('SYMB  strings %d   base %#x' % (b.string_count, b.symb_base))
    total = 0
    for i, nm in enumerate(b.tree_names):
        root, nodes = b.tree(i)
        leaves = sum(1 for n in nodes if n[0])
        total += leaves
        print('  tree %-6s @%#09x  nodes %6d  leaves %5d  root %d'
              % (nm, b.tree_addr[i], len(nodes), leaves, root))
    print('  leaves total %d  vs strings %d  -> %s'
          % (total, b.string_count, 'EXACT' if total == b.string_count else 'MISMATCH'))
    print()
    print('INFO  base %#x' % b.info_base)
    print('  sounds  %6d' % len(b.sounds))
    print('  banks   %6d' % len(b.banks))
    print('  players %6d' % len(b.players))
    print('  files   %6d' % len(b.files))
    print('  groups  %6d' % len(b.groups))
    print('  footer  %s' % (b.footer,))
    print()
    print('sound types: %s' % dict(collections.Counter(s.type_name for s in b.sounds)))
    ext = sum(1 for f in b.files if f.external_path)
    print('files: %d external (a disc path), %d internal (inside FILE)'
          % (ext, len(b.files) - ext))
    print('players: %s' % ', '.join(
        '%s(%d voices, heap %#x)' % (b.string(p.string_id), p.playable_sound_count,
                                     p.heap_size) for p in b.players))
    print('banks: %s' % ', '.join('%s(file %d)' % (b.string(k.string_id), k.file_id)
                                  for k in b.banks))
    unnamed = [i for i in range(len(b.groups)) if b.groups[i].string_id < 0]
    print('groups: %d, unnamed %s' % (len(b.groups), unnamed))
    kinds = collections.Counter()
    nwave = 0
    for g in b.groups:
        for it in g.items:
            kinds[item_kind(b, g, it).decode('ascii', 'replace')] += 1
            nwave += len(item_rwavs(b, g, it))
    print('group items: %d  %s' % (sum(len(g.items) for g in b.groups), dict(kinds)))
    print('RWAV waves inside the FILE section: %d' % nwave)


def check(name, ok, total, detail=''):
    flag = 'PASS' if ok == total else 'FAIL'
    print('  [%s] %-56s %6d / %-6d %s' % (flag, name, ok, total, detail))
    return ok == total


def cmd_validate(b):
    allok = True
    print('=== structural ===')
    ok = 0
    for i, (tag, off, size) in enumerate(b.sections):
        nxt = b.sections[i + 1][1] if i + 1 < len(b.sections) else len(b.d)
        if off + size <= nxt:
            ok += 1
    allok &= check('sections do not overrun the next one', ok, len(b.sections))

    ends = []
    for i in range(4):
        _, nodes = b.tree(i)
        ends.append(b.tree_addr[i] + 8 + len(nodes) * 0x14)
    ok = sum(1 for i in range(3) if ends[i] == b.tree_addr[i + 1])
    allok &= check('SYMB trees are contiguous byte for byte', ok, 3)

    counts = [len(b.sounds), len(b.players), len(b.groups), len(b.banks)]
    trees = [b.tree(i) for i in range(4)]
    for i, nm in enumerate(b.tree_names):
        _, nodes = trees[i]
        leaves = [n for n in nodes if n[0]]
        ids = [n[5] for n in leaves]
        good = sum(1 for v in ids if 0 <= v < counts[i])
        allok &= check('tree %-6s leaf ids index its own table' % nm, good, len(leaves))
        allok &= check('tree %-6s leaf ids are unique' % nm, len(set(ids)), len(ids))

    print('=== name trees (the walk the runtime does) ===')
    for i, nm in enumerate(b.tree_names):
        root, nodes = trees[i]
        leaves = [n for n in nodes if n[0]]
        ok = 0
        for n in leaves:
            s = b.string(n[4])
            if s is not None and b.tree_lookup(i, s, nodes, root) == n[5]:
                ok += 1
        allok &= check('tree %-6s: lookup(name) == leaf id' % nm, ok, len(leaves))

    print('=== cross references ===')
    ok = sum(1 for s in b.sounds if 0 <= s.file_id < len(b.files))
    allok &= check('sound.file_id indexes the file table', ok, len(b.sounds))
    ok = sum(1 for s in b.sounds if 0 <= s.player_id < len(b.players))
    allok &= check('sound.player_id indexes the player table', ok, len(b.sounds))
    ok = sum(1 for s in b.sounds if b.string(s.string_id) is not None)
    allok &= check('sound.string_id resolves to a name', ok, len(b.sounds))
    ok = sum(1 for s in b.sounds if s.sound_type in SOUND_TYPE)
    allok &= check('sound.sound_type is one of SEQ/STRM/WAVE', ok, len(b.sounds))

    # the type/storage split -- nothing in the format enforces this
    pairs = collections.Counter()
    for s in b.sounds:
        f = b.files[s.file_id]
        pairs[(s.type_name, 'external' if f.external_path else 'internal')] += 1
    strm = sum(v for k, v in pairs.items() if k[0] == 'STRM')
    allok &= check('every STRM sound points at a disc .brstm',
                   pairs[('STRM', 'external')], strm)
    other = sum(v for k, v in pairs.items() if k[0] in ('WAVE', 'SEQ'))
    allok &= check('every WAVE/SEQ sound points inside the archive',
                   pairs[('WAVE', 'internal')] + pairs[('SEQ', 'internal')], other)
    ok = sum(1 for f in b.files
             if not f.external_path or f.external_path.endswith('.brstm'))
    allok &= check('every external path is a .brstm', ok, len(b.files))

    print('=== group geometry ===')
    ok = sum(1 for g in b.groups
             if b.file_off <= g.data_offset
             and g.data_offset + g.data_size <= len(b.d)
             and g.wave_offset + g.wave_size <= len(b.d))
    allok &= check('group data and wave blocks are inside the file', ok, len(b.groups))
    ok = sum(1 for g in b.groups if g.data_offset + g.data_size == g.wave_offset)
    allok &= check("a group's wave block follows its data block", ok, len(b.groups))
    ok = sum(1 for g in b.groups if b.d[g.data_offset:g.data_offset + 4] == b'RWSD')
    allok &= check('group data block starts with RWSD', ok, len(b.groups))
    last = max(b.groups, key=lambda g: g.wave_offset + g.wave_size)
    allok &= check('the last group ends at the last byte of the file',
                   1 if last.wave_offset + last.wave_size == len(b.d) else 0, 1,
                   '%#x' % (last.wave_offset + last.wave_size))

    nitem = sum(len(g.items) for g in b.groups)
    fits = back = sizes = 0
    for gi, g in enumerate(b.groups):
        for k, it in enumerate(g.items):
            if (it.file_id < len(b.files)
                    and it.data_offset + it.data_size <= g.data_size
                    and it.wave_offset + it.wave_size <= g.wave_size):
                fits += 1
            if it.file_id < len(b.files):
                f = b.files[it.file_id]
                if (gi, k) in f.positions:
                    back += 1
                if f.file_size == it.data_size and f.wave_data_size == it.wave_size:
                    sizes += 1
    allok &= check('group items fit inside their group', fits, nitem)
    allok &= check('file.positions points back at the group item', back, nitem)
    allok &= check('file sizes equal the group item sizes', sizes, nitem)

    print('=== items, waves, and the path from a name to a sample ===')
    kinds = collections.Counter()
    tot = okm = okfit = 0
    fmts = collections.Counter()
    rates = collections.Counter()
    notes = notes_ok = 0
    reached = set()
    for gi, g in enumerate(b.groups):
        for k, it in enumerate(g.items):
            kinds[item_kind(b, g, it).decode('ascii', 'replace')] += 1
            waves = item_rwavs(b, g, it)
            for addr, size in waves:
                tot += 1
                if b.d[addr:addr + 4] != b'RWAV':
                    continue
                okm += 1
                w = Rwav(b, addr)
                fmts[WAVE_FORMAT.get(w.format, w.format)] += 1
                rates[w.sample_rate] += 1
                if (w.size <= size
                        and addr + w.size <= g.wave_offset + it.wave_offset + it.wave_size):
                    okfit += 1
            for ents in read_rwsd(b, g.data_offset + it.data_offset):
                for wi in ents:
                    notes += 1
                    if 0 <= wi < len(waves):
                        notes_ok += 1
    print('  item kinds: %s' % dict(kinds))
    allok &= check('every TABL slot holds an RWAV', okm, tot)
    allok &= check('every RWAV fits its slot and its item', okfit, tot)
    allok &= check('every RWSD note indexes its own item\'s RWAR', notes_ok, notes)
    print('  wave formats: %s' % dict(fmts))
    print('  sample rates: %s' % dict(sorted(rates.items())))

    # the whole chain: sound name -> file -> group item -> RWSD subNo -> wave
    owners = b.wave_owners()
    uses = sum(len(b.files[s.file_id].positions)
               for s in b.sounds if s.sound_type == 3)
    placed = sum(len(b.wave_of_sound(i))
                 for i, s in enumerate(b.sounds) if s.sound_type == 3)
    allok &= check('every WAVE sound resolves in every group it is packed in',
                   placed, uses)
    allok &= check('the (group,item,subNo) triples collide with nothing',
                   len(set((gi, k, b.sub_no(i))
                           for i, s in enumerate(b.sounds) if s.sound_type == 3
                           for gi, k in b.files[s.file_id].positions)), uses)
    # Waves split cleanly by who owns them: an RWSD wave is addressed by a
    # sound name, an RBNK wave is an instrument sample a sequence plays by
    # note number and no name ever points at it.  The split is not declared
    # anywhere -- it falls out at 2518 / 238 with nothing left over.
    in_rwsd = sum(len(item_rwavs(b, g, it)) for g in b.groups for it in g.items
                  if item_kind(b, g, it) == b'RWSD')
    in_rbnk = sum(len(item_rwavs(b, g, it)) for g in b.groups for it in g.items
                  if item_kind(b, g, it) == b'RBNK')
    allok &= check('every RWAV in an RWSD item is reached by a sound name',
                   len(owners), in_rwsd)
    allok &= check('the unreached waves are exactly the RBNK ones',
                   tot - len(owners), in_rbnk, '(instrument samples)')

    print("=== against LastWorld.rsid.csv (the disc's own registry) ===")
    rsid = os.path.join(os.path.dirname(DEFAULT), 'LastWorld.rsid.csv')
    if os.path.exists(rsid):
        rows = [l.rstrip('\n').split(',')
                for l in open(rsid, encoding='utf-8') if l.strip()]
        ok = sum(1 for i in range(min(len(rows), len(b.sounds)))
                 if rows[i][0] == b.sound_name(i))
        allok &= check('rsid row i names sound i', ok, len(b.sounds))
        tail = len(rows) - len(b.sounds)
        named_groups = sum(1 for g in b.groups if g.string_id >= 0)
        expect = len(b.banks) + len(b.players) + named_groups
        allok &= check('rsid tail = banks + players + named groups',
                       1 if tail == expect else 0, 1, '%d vs %d' % (tail, expect))
    else:
        print('  (LastWorld.rsid.csv not found, skipped)')

    # The encoder left its own state behind, so the decoder can be checked
    # against it sample for sample rather than by ear: the predictor/scale
    # byte it recorded must be the first frame header, and decoding forward to
    # the loop point must reproduce the two history samples it saved there.
    print('=== the ADPCM decoder, against the state the encoder saved ===')
    nch = ok_ps = 0
    nloop = ok_lps = 0
    nhist = ok_hist = trivial = 0
    for g in b.groups:
        for it in g.items:
            for addr, _ in item_rwavs(b, g, it):
                w = Rwav(b, addr)
                if w.format != 2:
                    continue
                for c in range(w.channels):
                    ch = w.chan[c]
                    raw = w.channel_bytes(b, c)
                    if not raw:
                        continue
                    nch += 1
                    if raw[0] == ch['ps']:
                        ok_ps += 1
                    if not w.loop:
                        continue
                    nloop += 1
                    fo = (w.loop_start // 16) * 8
                    if fo < len(raw) and raw[fo] == ch['loop_ps']:
                        ok_lps += 1
                    lo = w.loop_start_sample
                    if lo < 2:
                        trivial += 1        # loops at the top: no history to hold
                        continue
                    nhist += 1
                    s = decode_dsp(raw, ch['coef'], ch['yn1'], ch['yn2'], lo)
                    if s[-1] == ch['loop_yn1'] and s[-2] == ch['loop_yn2']:
                        ok_hist += 1
    allok &= check('ps == the first frame header byte', ok_ps, nch)
    allok &= check('loop_ps == the header of the frame the loop starts in',
                   ok_lps, nloop)
    allok &= check('decoding to the loop reproduces (loop_yn2, loop_yn1)',
                   ok_hist, nhist, '(%d more loop at sample 0)' % trivial)

    # Independent of the archive entirely: the STRM tail declares how many
    # channels the stream has, and the .brstm on the filesystem is a different
    # file in a different format that also says so.
    print('=== against the .brstm files on the disc ===')
    stream_dir = os.path.join(os.path.dirname(DEFAULT), 'stream')
    manifest = os.path.join(ROOT, 'audio', 'manifest.csv')
    if os.path.exists(manifest):
        man = {r['file'].lower(): r for r in
               csv.DictReader(open(manifest, encoding='utf-8'))}
        seen = agree = 0
        for i, s in enumerate(b.sounds):
            if s.sound_type != 2:
                continue
            f = b.files[s.file_id]
            m = man.get(os.path.basename(f.external_path or '').lower())
            if not m:
                continue
            seen += 1
            if b.u16(b.info_base + s.ext_ref.offset + 4) == int(m['channels']):
                agree += 1
        allok &= check('declared channel count == the real .brstm header',
                       agree, seen)
    else:
        print('  (audio/manifest.csv not found, skipped)')
    if os.path.isdir(stream_dir):
        named = set(os.path.basename(f.external_path).lower()
                    for f in b.files if f.external_path)
        disc = set(x.lower() for x in os.listdir(stream_dir)
                   if x.lower().endswith('.brstm'))
        allok &= check('every name in the archive exists on the disc',
                       len(named & disc), len(named))
        orphan = sorted(disc - named)
        print('  [note] %d .brstm on the disc that no sound id names: %s%s'
              % (len(orphan), ', '.join(orphan[:6]),
                 ' ...' if len(orphan) > 6 else ''))
    else:
        print('  (stream/ not found, skipped)')

    print()
    print('ALL CHECKS PASSED' if allok else 'SOME CHECKS FAILED')
    return 0 if allok else 1


def cmd_csv(b, path):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['index', 'name', 'type', 'player', 'file_id', 'source_kind',
                    'source', 'volume', 'priority', 'pan_mode', 'pan_curve',
                    'actor_player', 'remote_filter', 'user1', 'user2',
                    'flags3d', 'decay_curve', 'decay_ratio', 'doppler'])
        for i, s in enumerate(b.sounds):
            kind, src = b.sound_source(i)
            p = b.sound_3d(i)
            w.writerow([i, b.sound_name(i), s.type_name,
                        b.string(b.players[s.player_id].string_id)
                        if s.player_id < len(b.players) else '',
                        s.file_id, kind, src, s.volume, s.player_priority,
                        s.pan_mode, s.pan_curve, s.actor_player_id, s.remote_filter,
                        s.user_param1, s.user_param2,
                        p.flags if p else '', p.decay_curve if p else '',
                        p.decay_ratio if p else '', p.doppler_factor if p else ''])
    print('wrote %s (%d sounds)' % (path, len(b.sounds)))


def cmd_groups(b, path):
    used = collections.Counter()
    for s in b.sounds:
        for g, _ in b.files[s.file_id].positions:
            used[g] += 1
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['index', 'name', 'data_offset', 'data_size', 'wave_offset',
                    'wave_size', 'items', 'waves', 'sounds_using'])
        for i, g in enumerate(b.groups):
            w.writerow([i, b.group_name(i) or '', '%#x' % g.data_offset, g.data_size,
                        '%#x' % g.wave_offset, g.wave_size, len(g.items),
                        len(group_rwavs(b, g)), used[i]])
    print('wrote %s (%d groups)' % (path, len(b.groups)))


def cmd_extract(b, outdir, decode=True, limit=None, unique=True):
    """Write the internal waves: the raw RWAV, and the decoded WAV beside it.

    The same SFX is packed into every group that needs it, so by default one
    copy per distinct sound name is written; `--all-copies` writes every
    placement, named by group.
    """
    os.makedirs(outdir, exist_ok=True)
    owners = b.wave_owners()
    written = 0
    seen = set()
    failed = []
    index = []
    for (gi, k, wi), names in sorted(owners.items()):
        if limit is not None and written >= limit:
            break
        gname = b.group_name(gi) or 'GROUP_%03d' % gi
        label = names[0] if len(names) == 1 else '%s+%d' % (names[0], len(names) - 1)
        if unique:
            if label in seen:
                continue
            base = label
        else:
            base = '%s__%s_%d_%d' % (label, gname, k, wi)
        seen.add(label)
        base = ''.join(c if c.isalnum() or c in '_+-' else '_' for c in base)
        g = b.groups[gi]
        addr = item_rwavs(b, g, g.items[k])[wi][0]
        try:
            w = Rwav(b, addr)
            with open(os.path.join(outdir, base + '.rwav'), 'wb') as fh:
                fh.write(b.d[addr:addr + w.size])
            wav = ''
            if decode and w.format == 2:
                chans = [decode_dsp(w.channel_bytes(b, c), w.chan[c]['coef'],
                                    w.chan[c]['yn1'], w.chan[c]['yn2'],
                                    w.sample_count)
                         for c in range(w.channels)]
                if chans and min(len(x) for x in chans) > 0:
                    wav = base + '.wav'
                    write_wav(os.path.join(outdir, wav), chans, w.sample_rate)
            index.append([base, ';'.join(names), gname, k, wi, w.channels,
                          w.sample_rate, w.sample_count,
                          round(w.sample_count / float(w.sample_rate), 4),
                          w.loop, w.loop_start_sample, wav])
            written += 1
        except Exception as e:                      # keep going, report at the end
            failed.append((base, str(e)[:80]))
    with open(os.path.join(outdir, 'index.csv'), 'w', newline='',
              encoding='utf-8') as fh:
        cw = csv.writer(fh)
        cw.writerow(['file', 'sound_names', 'group', 'item', 'wave_index',
                     'channels', 'sample_rate', 'samples', 'seconds', 'loop',
                     'loop_start', 'wav'])
        cw.writerows(index)
    print('extracted %d waves into %s (index.csv written)' % (written, outdir))
    if failed:
        print('failed: %d' % len(failed))
        for f in failed[:10]:
            print('  %s: %s' % f)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('brsar', nargs='?', default=DEFAULT)
    ap.add_argument('--summary', action='store_true')
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--csv')
    ap.add_argument('--groups')
    ap.add_argument('--extract')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--no-decode', action='store_true')
    ap.add_argument('--all-copies', action='store_true',
                    help='write every group placement, not one per sound name')
    a = ap.parse_args()

    b = Brsar(open(a.brsar, 'rb').read())
    rc = 0
    if a.summary or not (a.validate or a.csv or a.groups or a.extract):
        cmd_summary(b)
    if a.validate:
        rc = cmd_validate(b)
    if a.csv:
        cmd_csv(b, a.csv)
    if a.groups:
        cmd_groups(b, a.groups)
    if a.extract:
        cmd_extract(b, a.extract, decode=not a.no_decode, limit=a.limit,
                    unique=not a.all_copies)
    return rc


if __name__ == '__main__':
    sys.exit(main())
