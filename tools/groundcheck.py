#!/usr/bin/env python3
"""
Is there floor under Godhome's spawn point?

Hollow Knight's room terrain is EdgeCollider2Ds on the tilemap chunks, several per
chunk GameObject. This walks the baked edges, finds the highest one directly beneath the
respawn marker, and reports the drop - a quick way to tell whether the rebuilt scene is
actually standable before launching the game.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ggformat import (MAGIC, FORMAT_VERSION, HAS_SPRITE, HAS_BOX, HAS_EDGE,
                      HAS_POLY, HAS_CAMLOCK, HAS_RESPAWN, HAS_HAZARD,
                      HAS_TRANSITION, HAS_SIMPLE,
                      HAS_MESH, HAS_SEQDOOR, HAS_STATUE,
                      HAS_AUDIO)
from verify_baked import Reader
from preview_scene import world_transforms, BAKED


def read(path):
    r = Reader(open(path, "rb").read())
    assert r.take(4) == MAGIC
    assert r.i32() == FORMAT_VERSION
    name = r.string()
    bounds = (r.f32(), r.f32())
    if r.boolean():
        r.i32(); r.f32()
        [r.f32() for _ in range(4)]; r.f32(); [r.f32() for _ in range(4)]
        for _ in range(3):
            for _ in range(r.i32()):
                [r.f32() for _ in range(4)]
    [r.string() for _ in range(r.i32())]          # shaders
    for _ in range(r.i32()):                      # audio clips
        r.string(); r.i32(); r.i32()
    [r.string() for _ in range(r.i32())]          # pages
    for _ in range(r.i32()):                      # sprites
        r.string(); r.i32()
        [r.f32() for _ in range(4)]; [r.f32() for _ in range(2)]
        r.f32(); [r.f32() for _ in range(4)]

    objs = []
    for _ in range(r.i32()):
        o = {"name": r.string(), "parent": r.i32(), "layer": r.i32(), "active": r.boolean(),
             "pos": (r.f32(), r.f32(), r.f32()),
             "rot": (r.f32(), r.f32(), r.f32(), r.f32()),
             "scale": (r.f32(), r.f32(), r.f32())}
        m = r.i32(); o["mask"] = m; o["edges"] = []
        if m & HAS_SPRITE:
            r.i32(); r.i32(); [r.f32() for _ in range(4)]; r.i32(); r.i32()
            r.boolean(); r.boolean(); r.boolean()
        if m & HAS_BOX:
            for _ in range(r.i32()):
                [r.f32() for _ in range(4)]; r.boolean(); r.boolean()
        if m & HAS_EDGE:
            for _ in range(r.i32()):
                ox, oy = r.f32(), r.f32()
                pts = [(r.f32(), r.f32()) for _ in range(r.i32())]
                r.boolean(); r.boolean()
                o["edges"].append((ox, oy, pts))
        if m & HAS_POLY:
            for _ in range(r.i32()):
                r.f32(); r.f32()
                for _ in range(r.i32()):
                    for _ in range(r.i32()):
                        r.f32(); r.f32()
                r.boolean(); r.boolean()
        if m & HAS_CAMLOCK:
            [r.f32() for _ in range(4)]; r.boolean(); r.boolean(); r.boolean()
        if m & HAS_RESPAWN: r.boolean()
        if m & HAS_HAZARD:  r.boolean()
        if m & HAS_SEQDOOR:
            r.string(); r.string()
            r.i32(); r.i32(); r.i32()
        if m & HAS_AUDIO:
            r.i32(); r.f32(); r.f32(); r.f32()
            r.boolean(); r.boolean(); r.boolean()
        if m & HAS_STATUE:
            r.string(); r.string()
        if m & HAS_MESH:
            vn = r.i32()
            for _ in range(vn):
                [r.f32() for _ in range(5)]
            for _ in range(r.i32() * 3): r.i32()
            r.i32(); r.i32(); r.i32(); r.i32(); r.boolean()
        if m & HAS_SIMPLE:
            for _ in range(r.i32()): r.string()
        if m & HAS_TRANSITION:
            r.string(); r.string(); r.f32(); r.f32(); r.f32()
            for _ in range(6): r.boolean()
        objs.append(o)
    return name, bounds, objs


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "GG_Atrium"
    sname, bounds, objs = read(os.path.join(BAKED, f"{name}.scene"))
    tf = world_transforms(objs)

    target = "Death Respawn Marker"
    sx = sy = None
    for i, o in enumerate(objs):
        if o["name"] == target:
            sx, sy = tf[i][0], tf[i][1]
    if sx is None:
        raise SystemExit(f"no '{target}' in {sname}")

    print(f"{sname}: spawn '{target}' at ({sx:.2f}, {sy:.2f}), bounds {bounds[0]:.0f}x{bounds[1]:.0f}")

    total = 0
    best = None
    for i, o in enumerate(objs):
        if not o["edges"]:
            continue
        x, y, scx, scy, rot, active = tf[i]
        total += len(o["edges"])
        if not active:
            continue
        for ox, oy, pts in o["edges"]:
            for j in range(len(pts) - 1):
                (x1, y1), (x2, y2) = pts[j], pts[j + 1]
                wx1, wy1 = x + (ox + x1) * scx, y + (oy + y1) * scy
                wx2, wy2 = x + (ox + x2) * scx, y + (oy + y2) * scy
                lo, hi = min(wx1, wx2), max(wx1, wx2)
                if lo - 0.5 <= sx <= hi + 0.5:
                    t = 0.0 if wx2 == wx1 else (sx - wx1) / (wx2 - wx1)
                    yy = wy1 + t * (wy2 - wy1)
                    if yy <= sy + 1.0 and (best is None or yy > best[0]):
                        best = (yy, o["name"])

    print(f"  edge colliders in scene: {total}")
    if best:
        print(f"  ground below spawn: y={best[0]:.2f} on '{best[1]}' -> drop of {sy - best[0]:.2f} units")
    else:
        print("  ground below spawn: NONE - Hornet would fall out of the world")
    return 0 if best else 1


if __name__ == "__main__":
    sys.exit(main())
