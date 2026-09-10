"""
Decoding Hollow Knight's tilemap chunk meshes.

Godhome's actual structure - floors, walls, platform surfaces - is drawn by the tk2d
tilemap's generated chunk meshes, not by sprites. Baking only the sprite layer gives you
Godhome's decoration floating in mid-air with invisible ground, which is exactly how the
first playable build looked.

A chunk mesh is a plain interleaved vertex buffer: position (3 floats), colour (4
floats, uniformly white in practice) and UV0 (2 floats), 36 bytes per vertex, with a
16-bit index buffer. All chunks in a scene share one material - 'atlas0 material',
shader tk2d/BlendVertexColor, over a small tile atlas texture.
"""

import struct

# Unity VertexChannelFormat
FMT_FLOAT = 0
FMT_FLOAT16 = 1
FMT_UNORM8 = 2

_FMT_SIZE = {FMT_FLOAT: 4, FMT_FLOAT16: 2, FMT_UNORM8: 1}

CHAN_POSITION = 0
CHAN_COLOR = 3
CHAN_UV0 = 4


def _stride(channels, stream=0):
    s = 0
    for c in channels:
        if c["dimension"] and c["stream"] == stream:
            size = _FMT_SIZE.get(c["format"], 4)
            s = max(s, c["offset"] + size * c["dimension"])
    return s


def decode_mesh(md):
    """
    (vertices, uvs, triangles) from a Mesh typetree, or None if unsupported.

    vertices are (x, y, z) tuples, uvs (u, v), triangles a flat index list.
    """
    vd = md.get("m_VertexData") or {}
    n = vd.get("m_VertexCount") or 0
    channels = vd.get("m_Channels") or []
    data = bytes(vd.get("m_DataSize") or b"")
    if not n or not data:
        return None

    stride = _stride(channels)
    if not stride or stride * n > len(data):
        return None

    def chan(i):
        return channels[i] if i < len(channels) and channels[i]["dimension"] else None

    pos = chan(CHAN_POSITION)
    uv = chan(CHAN_UV0)
    if pos is None or pos["format"] != FMT_FLOAT:
        return None

    verts = []
    uvs = []
    for v in range(n):
        base = v * stride
        x, y, z = struct.unpack_from("<3f", data, base + pos["offset"])
        verts.append((x, y, z))
        if uv is not None and uv["format"] == FMT_FLOAT:
            u, w = struct.unpack_from("<2f", data, base + uv["offset"])
            uvs.append((u, w))
        else:
            uvs.append((0.0, 0.0))

    # Indices. m_IndexFormat 0 is UInt16, 1 is UInt32.
    idx_bytes = bytes(md.get("m_IndexBuffer") or b"")
    fmt16 = (md.get("m_IndexFormat", 0) == 0)
    step = 2 if fmt16 else 4
    code = "<H" if fmt16 else "<I"

    tris = []
    submeshes = md.get("m_SubMeshes") or []
    if submeshes:
        for sm in submeshes:
            first = sm.get("firstByte", 0)
            count = sm.get("indexCount", 0)
            for i in range(count):
                off = first + i * step
                if off + step > len(idx_bytes):
                    break
                tris.append(struct.unpack_from(code, idx_bytes, off)[0])
    else:
        for off in range(0, len(idx_bytes) - step + 1, step):
            tris.append(struct.unpack_from(code, idx_bytes, off)[0])

    # Drop degenerate/out-of-range triangles rather than shipping a mesh Unity rejects.
    clean = []
    for i in range(0, len(tris) - 2, 3):
        a, b, c = tris[i], tris[i + 1], tris[i + 2]
        if a < n and b < n and c < n:
            clean.append((a, b, c))
    return verts, uvs, clean
