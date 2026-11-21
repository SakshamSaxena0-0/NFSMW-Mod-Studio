import struct

M32 = 0xFFFFFFFF


def _mix(a, b, c):
    a = (a - b - c) & M32; a ^= c >> 13
    b = (b - c - a) & M32; b ^= (a << 8) & M32
    c = (c - a - b) & M32; c ^= b >> 13
    a = (a - b - c) & M32; a ^= c >> 12
    b = (b - c - a) & M32; b ^= (a << 16) & M32
    c = (c - a - b) & M32; c ^= b >> 5
    a = (a - b - c) & M32; a ^= c >> 3
    b = (b - c - a) & M32; b ^= (a << 10) & M32
    c = (c - a - b) & M32; c ^= b >> 15
    return a, b, c


def h32(s, init=0xABCDEF00):
    k = s.encode('latin1') if isinstance(s, str) else bytes(s)
    a = b = 0x9E3779B9; c = init; i = 0; n = len(k)
    while n - i >= 12:
        x, y, z = struct.unpack_from('<3I', k, i)
        a, b, c = _mix((a + x) & M32, (b + y) & M32, (c + z) & M32); i += 12
    t = k[i:] + b'\0' * 12
    x, y, z = struct.unpack_from('<3I', t, 0)
    c = (c + len(k)) & M32
    a, b, c = _mix((a + x) & M32, (b + y) & M32, (c + (z << 8)) & M32)
    return c


EXPORT_CLASS, EXPORT_COLLECTION = 0x5E970CBC, 0x8E112EB7


class FormatError(Exception):
    pass


class AttribDB:
    def __init__(self, data):
        self.d = bytes(data)
        d = self.d
        if d[:4] != b'VPAK':
            raise FormatError('not an attributes.bin (no VPAK header)')
        bin_size, vlt_size, self.B, self.V = struct.unpack_from('<4I', d, 0x14)
        if not (0 < self.B < self.V <= len(d)):
            raise FormatError('bad VPAK header')
        self.bin_chunks = self._chunks(self.B, self.B + bin_size)
        self.vlt_chunks = self._chunks(self.V, self.V + vlt_size)
        for need in ('ExpN', 'PtrN'):
            if need not in self.vlt_chunks:
                raise FormatError('missing %s chunk' % need)
        self.names = {}
        if 'StrE' in self.bin_chunks:
            o, sz = self.bin_chunks['StrE']
            for s in d[o + 8:o + sz].split(b'\0'):
                if s:
                    self.names[h32(s)] = s.decode('latin1')
        o, sz = self.vlt_chunks['PtrN']
        self.ptr_start, self.ptr_end = o + 8, o + sz
        self.fix = {}
        for p in range(self.ptr_start, self.ptr_end - 11, 12):
            off, typ, fl, val = struct.unpack_from('<IHHI', d, p)
            if typ == 3:
                self.fix[off] = val
        o, sz = self.vlt_chunks['ExpN']
        n = struct.unpack_from('<I', d, o + 8)[0]
        if 12 + 20 * n > sz:
            raise FormatError('bad export table')
        self.classes, self.colls = {}, {}
        for i in range(n):
            key, typ, _, _, off = struct.unpack_from('<5I', d, o + 12 + 20 * i)
            if typ == EXPORT_CLASS:
                self.classes[key] = off
            elif typ == EXPORT_COLLECTION:
                k, c = struct.unpack_from('<2I', d, self.V + off)
                self.colls[(c, k)] = off
        if not self.classes or not self.colls:
            raise FormatError('no classes or collections found')
        self._defs = {}

    def _chunks(self, start, end):
        out, o = {}, start
        while o + 8 <= end:
            cid, sz = struct.unpack_from('<4sI', self.d, o)
            if sz < 8:
                break
            out.setdefault(cid[::-1].decode('latin1'), (o, sz))
            o += sz
        return out

    def name(self, key):
        return self.names.get(key, '%08x' % key)

    def classdefs(self, cls):
        if cls not in self._defs:
            coff = self.classes[cls]
            ndef = struct.unpack_from('<I', self.d, self.V + coff + 8)[0]
            dp = self.fix[coff + 12]
            defs = {}
            for i in range(ndef):
                key, typ, off, size, cnt, fl, al = struct.unpack_from('<IIHHHBB', self.d, self.B + dp + 16 * i)
                defs[key] = (typ, off, size, cnt, fl)
            self._defs[cls] = defs
        return self._defs[cls]

    def has(self, cls, key):
        return (cls, key) in self.colls

    def coll(self, cls, key):
        off = self.colls[(cls, key)]
        key, c, parent, _, _, ne, nt = struct.unpack_from('<7I', self.d, self.V + off)
        nt &= 0xFFFF
        types = struct.unpack_from('<%dI' % nt, self.d, self.V + off + 32)
        eo = off + 32 + 4 * nt
        ents = {}
        for i in range(ne):
            ek, val, ti, ef, _ = struct.unpack_from('<IIHBB', self.d, self.V + eo + 12 * i)
            ents[ek] = dict(value=val, type=types[ti] if ti < nt else 0, flags=ef,
                            addr=self.V + eo + 12 * i + 4, ptr=self.fix.get(eo + 12 * i + 4))
        return dict(key=key, cls=c, parent=parent, off=off, layout=self.fix.get(off + 28), entries=ents)

    def collections_of(self, cls):
        return [k for (c, k) in self.colls if c == cls]

    def refs(self, entry):
        if entry is None or entry['ptr'] is None:
            return []
        a = self.B + entry['ptr']
        n = struct.unpack_from('<HH', self.d, a)[1]
        if n > 64:
            return []
        return [struct.unpack_from('<2I', self.d, a + 8 + 12 * i)[1] for i in range(n)]

    def ref_slots(self, entry):
        a = self.B + entry['ptr']
        n = struct.unpack_from('<HH', self.d, a)[1]
        return [a + 12 + 12 * i for i in range(n)]

    def field_addrs(self, cls, key, field):
        defs = self.classdefs(cls)
        if field not in defs or not self.has(cls, key):
            return None
        typ, off, size, cnt, fl = defs[field]
        lay = self.coll(cls, key)['layout']
        if lay is None:
            return None
        a = self.B + lay + off
        if fl & 1:
            n = struct.unpack_from('<HHHH', self.d, a)[1]
            if n > 16:
                return None
            return [a + 8 + 4 * i for i in range(n)]
        return [a + 4 * i for i in range(size // 4)]
