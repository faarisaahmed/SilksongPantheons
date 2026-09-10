#!/usr/bin/env python3
"""
Serialise any Hollow Knight component so Silksong can rebuild it.

Two decisions carry this module.

First, fields are written **by name**, not by offset. Hollow Knight's HealthManager and
Silksong's are not the same class - Silksong has had five more years of fields added to
it - so a positional copy would be nonsense. Reading Hollow Knight's layout positionally
(which is the only way, since release builds ship no type trees) and then writing it out
named means the C# side can set exactly the fields that still exist and leave the rest at
their defaults.

Second, references are resolved into three kinds of thing a port can actually honour:

  - another object in the same scene, written as its index in the baked object list
  - a baked asset, written as its resource name (audio clips)
  - a prefab, written as its prefab-table name

Anything else - a material, a sprite, a prefab we chose not to bake - is written as an
empty reference, and the C# side leaves that field alone rather than nulling something
AddComponent may have set up.
"""

# Wire kinds.
K_BOOL, K_I32, K_I64, K_F32, K_F64, K_STRING = 0, 1, 2, 3, 4, 5
K_VEC2, K_VEC3, K_VEC4, K_REF, K_ARRAY, K_INLINE = 6, 7, 8, 9, 10, 11

_SCALAR = {
    "bool": K_BOOL, "u8": K_I32, "i8": K_I32, "i16": K_I32, "u16": K_I32,
    "i32": K_I32, "u32": K_I64, "i64": K_I64, "u64": K_I64,
    "f32": K_F32, "f64": K_F64, "string": K_STRING,
    "vec2": K_VEC2, "vec2i": K_VEC2, "vec3": K_VEC3, "vec3i": K_VEC3,
    "vec4": K_VEC4, "color": K_VEC4, "pptr": K_REF,
}

# Kinds with no sensible port: an AnimationCurve or Matrix4x4 field is left at whatever
# the component's own constructor gives it.
_UNPORTABLE = {"curve", "matrix", "bounds", "color32"}


def kind_tag(kind):
    """The wire kind for a layout kind, or None if the field is not carried."""
    if isinstance(kind, tuple):
        if kind[0] == "array":
            return K_ARRAY if kind_tag(kind[1]) is not None else None
        if kind[0] == "inline":
            return K_INLINE
        return None
    if kind in _UNPORTABLE:
        return None
    return _SCALAR.get(kind)


def write_component(w, type_name, layout, values, resolve_ref):
    """
    Write one component: its type name, then every field that can be carried.

    `resolve_ref(pptr)` returns (object_index, component_type, asset_name) - all three
    empty/-1 when the pointer cannot be honoured.
    """
    fields = []
    for name, kind in layout:
        tag = kind_tag(kind)
        if tag is None:
            continue
        fields.append((name, kind, tag, values.get(name)))

    w.string(type_name)
    w.i32(len(fields))
    for name, kind, tag, val in fields:
        w.string(name)
        w.i32(tag)
        _write_value(w, kind, tag, val, resolve_ref)


def _write_value(w, kind, tag, val, resolve_ref):
    if tag == K_ARRAY:
        inner = kind[1]
        itag = kind_tag(inner)
        seq = val or []
        w.i32(itag)
        w.i32(len(seq))
        for v in seq:
            _write_value(w, inner, itag, v, resolve_ref)
        return

    if tag == K_INLINE:
        sub = kind[2]
        keep = [(n, k, kind_tag(k)) for n, k in sub]
        keep = [(n, k, t) for n, k, t in keep if t is not None]
        w.i32(len(keep))
        d = val if isinstance(val, dict) else {}
        for n, k, t in keep:
            w.string(n)
            w.i32(t)
            _write_value(w, k, t, d.get(n), resolve_ref)
        return

    if tag == K_REF:
        oi, ctype, asset = resolve_ref(val)
        w.i32(oi)
        w.string(ctype or "")
        w.string(asset or "")
        return

    if tag == K_BOOL:
        w.boolean(bool(val))
    elif tag == K_I32:
        w.i32(int(val or 0))
    elif tag == K_I64:
        w.i64(int(val or 0))
    elif tag == K_F32:
        w.f32(float(val or 0.0))
    elif tag == K_F64:
        w.f64(float(val or 0.0))
    elif tag == K_STRING:
        w.string(val if isinstance(val, str) else "")
    elif tag == K_VEC2:
        v = val or (0.0, 0.0)
        w.f32(float(v[0])); w.f32(float(v[1]))
    elif tag == K_VEC3:
        v = val or (0.0, 0.0, 0.0)
        for i in range(3):
            w.f32(float(v[i]))
    elif tag == K_VEC4:
        v = val or (0.0, 0.0, 0.0, 0.0)
        for i in range(4):
            w.f32(float(v[i]))
    else:
        raise ValueError(f"unwritable tag {tag}")
