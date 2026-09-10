"""
Shared definition of the baked Godhome scene format.

Written by extract_godhome.py, read by SilksongGodhome/Rebuild/GodhomeData.cs.
Keep the two in step: FORMAT_VERSION must match GodhomeData.FormatVersion.

Strings use .NET BinaryWriter's length-prefixed UTF-8 (7-bit encoded length), so the
C# side can use a plain BinaryReader with no custom parsing.
"""

import struct

MAGIC = b"GGHM"

# A deflate wrapper around the above. The behaviour layer is mostly PlayMaker action
# names and strings, which repeat heavily: a baked room compresses to about 15% of its
# size, and across the seventeen rooms that is forty megabytes off the DLL.
ZMAGIC = b"GGHZ"


def compress(raw):
    """ZMAGIC + uncompressed length + raw deflate, which is what DeflateStream reads."""
    import struct as _s
    import zlib
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    body = co.compress(raw) + co.flush()
    return ZMAGIC + _s.pack("<i", len(raw)) + body


def decompress(data):
    """Undo compress(), or return the data unchanged if it was never compressed."""
    import struct as _s
    import zlib
    if not data.startswith(ZMAGIC):
        return data
    n = _s.unpack_from("<i", data, 4)[0]
    out = zlib.decompress(data[8:], -15)
    if len(out) != n:
        raise ValueError(f"scene inflated to {len(out)}, header says {n}")
    return out
FORMAT_VERSION = 12

# Component bitmask stored per object.
HAS_SPRITE   = 1 << 0
HAS_BOX      = 1 << 1   # v3: a count followed by that many box blocks
HAS_EDGE     = 1 << 2   # v3: ditto - tilemap chunks carry several each
HAS_POLY     = 1 << 3   # v3: ditto
HAS_CAMLOCK  = 1 << 4   # CameraLockArea - exists in Silksong too, so it re-attaches
HAS_RESPAWN  = 1 << 5   # RespawnMarker - what HeroController.LocateSpawnPoint looks for
HAS_HAZARD   = 1 << 6   # HazardRespawnMarker
HAS_TRANSITION = 1 << 7 # TransitionPoint - the doors between Godhome's rooms
HAS_SIMPLE   = 1 << 8   # named components that carry no fields we need to configure
HAS_SEQDOOR  = 1 << 10  # BossSequenceDoor - a Pantheon entrance
HAS_STATUE   = 1 << 11  # BossStatue - one Hall of Gods plinth
HAS_AUDIO    = 1 << 12  # AudioSource - Godhome's ambience and one-shots
HAS_MESH     = 1 << 9   # MeshFilter + MeshRenderer - the tilemap chunks are Godhome's
                        # actual floors and walls, so without these the level is invisible

# v12: the behaviour layer. Godhome's rooms are not scenery - the objects that start a
# fight, end it, knock a boss back and play its death are all components and FSMs on
# ordinary GameObjects, and without them an arena is a photograph of one.
HAS_TK2D     = 1 << 13  # tk2dSprite / tk2dSpriteAnimator, into the shared tables
HAS_FSM      = 1 << 14  # PlayMakerFSMs on this object
HAS_COMPS    = 1 << 15  # any other Hollow Knight component, by name and field
HAS_PHYS     = 1 << 16  # Rigidbody2D and CircleCollider2D. Without a body a boss cannot
                        # move at all: every SetVelocity2d in its FSM pushes one.


class Writer:
    """Minimal .NET-BinaryWriter-compatible little-endian writer."""

    def __init__(self):
        self.buf = bytearray()

    def u8(self, v):    self.buf += struct.pack("<B", v)
    def i32(self, v):   self.buf += struct.pack("<i", v)
    def f32(self, v):   self.buf += struct.pack("<f", float(v))
    def f64(self, v):   self.buf += struct.pack("<d", float(v))
    def i64(self, v):   self.buf += struct.pack("<q", int(v))
    def boolean(self, v): self.buf += struct.pack("<?", bool(v))

    def string(self, s):
        """BinaryWriter.Write(string): 7-bit encoded length, then UTF-8 bytes."""
        data = (s or "").encode("utf-8")
        n = len(data)
        while n >= 0x80:
            self.buf += struct.pack("<B", (n & 0x7F) | 0x80)
            n >>= 7
        self.buf += struct.pack("<B", n)
        self.buf += data

    def vec2(self, x, y):
        self.f32(x); self.f32(y)

    def vec3(self, x, y, z):
        self.f32(x); self.f32(y); self.f32(z)

    def vec4(self, x, y, z, w):
        self.f32(x); self.f32(y); self.f32(z); self.f32(w)

    def bytes(self):
        return bytes(self.buf)
