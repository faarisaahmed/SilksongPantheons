#!/usr/bin/env python3
"""
Read a component's fields using a layout derived by typelayout.

Unity's rules, all of which this project has been bitten by at least once:

  - sub-4-byte fields (bool, byte, char, short) pad to 4 bytes *after each one*, not
    after a run of them
  - a string is int32 length, utf8 bytes, then align 4
  - an array is int32 count then the elements, aligned after if the element is a
    sub-4-byte type
  - base class fields come before derived ones
  - a PPtr is int32 fileID + int64 pathID, and never survives a port

The result is only used when the cursor lands exactly on the end of the buffer.
"""
import struct

from monoread import MonoReader, HEADER


class LayoutReader(MonoReader):
    def i8(self):   return struct.unpack("<b", self._take(1))[0]
    def i16(self):  return struct.unpack("<h", self._take(2))[0]
    def u16(self):  return struct.unpack("<H", self._take(2))[0]
    def u32(self):  return struct.unpack("<I", self._take(4))[0]
    def i64(self):  return struct.unpack("<q", self._take(8))[0]
    def u64(self):  return struct.unpack("<Q", self._take(8))[0]
    def f64(self):  return struct.unpack("<d", self._take(8))[0]

    def read(self, kind):
        if isinstance(kind, tuple):
            if kind[0] == "array":
                n = self.i32()
                if n < 0 or n > 1 << 22:
                    raise EOFError(f"absurd array count {n}")
                out = [self.read(kind[1]) for _ in range(n)]
                if _small(kind[1]):
                    self.align(4)
                return out
            if kind[0] == "inline":
                return {name: self.read(k) for name, k in kind[2]}
            raise ValueError(kind)

        if kind == "bool":
            v = self.u8() != 0; self.align(4); return v
        if kind == "u8":
            v = self.u8(); self.align(4); return v
        if kind == "i8":
            v = self.i8(); self.align(4); return v
        if kind == "i16":
            v = self.i16(); self.align(4); return v
        if kind == "u16":
            v = self.u16(); self.align(4); return v
        if kind == "i32":     return self.i32()
        if kind == "u32":     return self.u32()
        if kind == "i64":     return self.i64()
        if kind == "u64":     return self.u64()
        if kind == "f32":     return self.f32()
        if kind == "f64":     return self.f64()
        if kind == "string":  return self.string()
        if kind == "pptr":    return self.pptr()
        if kind == "vec2":    return (self.f32(), self.f32())
        if kind == "vec3":    return (self.f32(), self.f32(), self.f32())
        if kind == "vec4":    return (self.f32(), self.f32(), self.f32(), self.f32())
        if kind == "vec2i":   return (self.i32(), self.i32())
        if kind == "vec3i":   return (self.i32(), self.i32(), self.i32())
        if kind == "color":   return (self.f32(), self.f32(), self.f32(), self.f32())
        if kind == "color32": return self.u32()
        if kind == "bounds":  return tuple(self.f32() for _ in range(6))
        if kind == "matrix":  return tuple(self.f32() for _ in range(16))
        if kind == "curve":   return self.curve()
        raise ValueError(f"unknown kind {kind!r}")


def _small(kind):
    return kind in ("bool", "u8", "i8", "i16", "u16")


def parse(raw, layout):
    """
    (fields, exact) - exact is True only when the read landed on the end of the buffer.
    """
    r = LayoutReader(raw, HEADER)
    r.string()                                   # m_Name
    out = {}
    for name, kind in layout:
        out[name] = r.read(kind)
    return out, r.i == len(raw)
