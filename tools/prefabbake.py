#!/usr/bin/env python3
"""
Writing an object's behaviour, and writing a prefab as a tree of them.

Scene objects and prefab nodes carry exactly the same payload - tk2d sprite and animator,
FSMs, and any other component - so the writing lives here and both callers use it. A
prefab is then just a flat, parent-before-child node list with that payload on each node,
which is the same shape the scene itself uses.
"""
from ggformat import HAS_TK2D, HAS_FSM, HAS_COMPS
from monoread import script_ptr


def monos_of(scene, ctx, gpid):
    """[(className, raw)] for one GameObject in one assets file, in component order."""
    out = []
    for c in (ctx.go.get(gpid, {}).get("m_Component") or []):
        ptr = c.get("component") if isinstance(c, dict) else None
        obj = scene.resolve(ptr, ctx.file) if ptr else None
        if obj is None or obj.type.name != "MonoBehaviour":
            continue
        try:
            raw = obj.get_raw_data()
            ms = scene.resolve(script_ptr(raw), ctx.file)
            if ms is not None:
                out.append((ms.read_typetree().get("m_ClassName"), raw))
        except Exception:
            pass
    return out


def physics_of(scene, ctx, gpid):
    """Rigidbody2D and 2D colliders, which are engine types rather than MonoBehaviours."""
    rb = None
    boxes, circles, polys, edges = [], [], [], []
    for c in (ctx.go.get(gpid, {}).get("m_Component") or []):
        ptr = c.get("component") if isinstance(c, dict) else None
        obj = scene.resolve(ptr, ctx.file) if ptr else None
        if obj is None:
            continue
        n = obj.type.name
        try:
            if n == "Rigidbody2D":
                rb = obj.read_typetree()
            elif n == "BoxCollider2D":
                boxes.append(obj.read_typetree())
            elif n == "CircleCollider2D":
                circles.append(obj.read_typetree())
            elif n == "PolygonCollider2D":
                polys.append(obj.read_typetree())
            elif n == "EdgeCollider2D":
                edges.append(obj.read_typetree())
        except Exception:
            pass
    return rb, boxes, circles, polys, edges


def write_behaviour(w, rec):
    """The tk2d / FSM / component sections of one object, in mask-bit order."""
    if rec["mask"] & HAS_TK2D:
        tk, anim = rec["tk2d"]
        w.boolean(tk is not None)
        if tk is not None:
            ci, sp = tk
            w.i32(ci)
            w.i32(sp["spriteId"])
            w.f32(sp["colorR"]); w.f32(sp["colorG"])
            w.f32(sp["colorB"]); w.f32(sp["colorA"])
            w.vec3(sp["scaleX"], sp["scaleY"], sp["scaleZ"])
            w.i32(sp["renderLayer"])
        w.boolean(anim is not None)
        if anim is not None:
            li, an = anim
            w.i32(li)
            w.i32(an["defaultClipId"])
            w.boolean(an["playAutomatically"])

    if rec["mask"] & HAS_FSM:
        n, buf = rec["fsms"]
        w.i32(n)
        w.buf += buf

    if rec["mask"] & HAS_COMPS:
        n, buf = rec["comps"]
        w.i32(n)
        w.buf += buf


def write_physics(w, rb, boxes, circles, polys, edges):
    w.boolean(rb is not None)
    if rb is not None:
        w.f32(rb.get("m_Mass", 1.0))
        w.f32(rb.get("m_GravityScale", 1.0))
        w.f32(rb.get("m_LinearDrag", 0.0))
        w.f32(rb.get("m_AngularDrag", 0.0))
        w.i32(int(rb.get("m_BodyType", 0)))
        w.i32(int(rb.get("m_Constraints", 0)))
        w.i32(int(rb.get("m_CollisionDetection", 0)))
        w.i32(int(rb.get("m_Interpolate", 0)))

    w.i32(len(boxes))
    for b in boxes:
        off = b.get("m_Offset") or {}
        size = b.get("m_Size") or {}
        w.vec2(off.get("x", 0.0), off.get("y", 0.0))
        w.vec2(size.get("x", 1.0), size.get("y", 1.0))
        w.boolean(bool(b.get("m_IsTrigger", False)))
        w.boolean(bool(b.get("m_Enabled", True)))

    w.i32(len(circles))
    for c in circles:
        off = c.get("m_Offset") or {}
        w.vec2(off.get("x", 0.0), off.get("y", 0.0))
        w.f32(c.get("m_Radius", 0.5))
        w.boolean(bool(c.get("m_IsTrigger", False)))
        w.boolean(bool(c.get("m_Enabled", True)))

    # Offset before geometry, matching the scene format's own collider records.
    w.i32(len(polys))
    for p in polys:
        off = p.get("m_Offset") or {}
        w.vec2(off.get("x", 0.0), off.get("y", 0.0))
        paths = ((p.get("m_Points") or {}).get("m_Paths") or [])
        w.i32(len(paths))
        for path in paths:
            w.i32(len(path))
            for pt in path:
                w.vec2(pt.get("x", 0.0), pt.get("y", 0.0))
        w.boolean(bool(p.get("m_IsTrigger", False)))
        w.boolean(bool(p.get("m_Enabled", True)))

    w.i32(len(edges))
    for e in edges:
        off = e.get("m_Offset") or {}
        w.vec2(off.get("x", 0.0), off.get("y", 0.0))
        pts = e.get("m_Points") or []
        w.i32(len(pts))
        for pt in pts:
            w.vec2(pt.get("x", 0.0), pt.get("y", 0.0))
        w.boolean(bool(e.get("m_IsTrigger", False)))
        w.boolean(bool(e.get("m_Enabled", True)))


def write_prefab(w, scene, reg, pfile, root_gpid, bake_behaviour):
    """
    One prefab as a flat, parent-before-child node list.

    `bake_behaviour(rec, monos, from_file)` is the scene baker's own pass, so a prefab's
    components and FSMs go through exactly the same parsing, layout checking and
    reference resolution as the room's.
    """
    ctx = reg.ctx(pfile)

    # Iterative, with a visited set. A few of Hollow Knight's prefabs have a transform
    # that reaches itself again through its children - Journal_Update_Msg does - and a
    # plain recursive walk runs out of stack on them.
    nodes = []
    seen = set()
    stack = [(root_gpid, -1)]
    while stack:
        gpid, parent = stack.pop()
        if gpid in seen:
            continue
        seen.add(gpid)
        i = len(nodes)
        nodes.append((gpid, parent))
        t = ctx.tr.get(ctx.g2t.get(gpid))
        kids = []
        for c in ((t or {}).get("m_Children") or []):
            cp = (ctx.tr.get(c["m_PathID"]) or {}).get("m_GameObject", {}).get("m_PathID")
            if cp and cp in ctx.go and cp not in seen:
                kids.append((cp, i))
        # Reversed, so popping keeps Hollow Knight's own child order.
        stack.extend(reversed(kids))

    w.i32(len(nodes))
    for gpid, parent in nodes:
        god = ctx.go[gpid]
        t = ctx.tr.get(ctx.g2t.get(gpid)) or {}
        pos = t.get("m_LocalPosition") or {}
        rot = t.get("m_LocalRotation") or {}
        scl = t.get("m_LocalScale") or {}

        rec = {"mask": 0}
        bake_behaviour(rec, monos_of(scene, ctx, gpid), ctx.file)

        w.string(god.get("m_Name") or "")
        w.i32(parent)
        w.i32(int(god.get("m_Layer") or 0))
        w.boolean(bool(god.get("m_IsActive", True)))
        w.vec3(pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0))
        w.vec4(rot.get("x", 0.0), rot.get("y", 0.0), rot.get("z", 0.0), rot.get("w", 1.0))
        w.vec3(scl.get("x", 1.0), scl.get("y", 1.0), scl.get("z", 1.0))
        w.i32(rec["mask"])
        write_physics(w, *physics_of(scene, ctx, gpid))
        write_behaviour(w, rec)
    return len(nodes)
