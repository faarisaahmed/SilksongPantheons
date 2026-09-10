#!/usr/bin/env python3
"""
Render a baked scene to a PNG using only the baked data.

This is the cheap way to tell whether the extraction is actually right before
launching Silksong: it applies the same world transforms and the same
rect/pivot interpretation that SceneRebuilder.cs will, so if Godhome looks like
Godhome here, the pivot maths and hierarchy are correct.

    python3 preview_scene.py                 # GG_Atrium -> /tmp/GG_Atrium_preview.png
"""

import math
import os
import struct
import sys

from PIL import Image

from ggformat import (MAGIC, FORMAT_VERSION, HAS_SPRITE, HAS_BOX, HAS_EDGE, HAS_POLY,
                      HAS_CAMLOCK, HAS_RESPAWN, HAS_HAZARD,
                      HAS_TRANSITION, HAS_SIMPLE,
                      HAS_MESH, HAS_SEQDOOR, HAS_STATUE,
                      HAS_AUDIO)
from verify_baked import Reader

BAKED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "SilksongGodhome", "Baked")
MAX_DIM = 2600


def read_scene(path):
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
    shaders = [r.string() for _ in range(r.i32())]
    clips = [(r.string(), r.i32(), r.i32()) for _ in range(r.i32())]
    pages = [r.string() for _ in range(r.i32())]

    sprites = []
    for _ in range(r.i32()):
        sprites.append({
            "name": r.string(), "page": r.i32(),
            "rect": (r.f32(), r.f32(), r.f32(), r.f32()),
            "pivot": (r.f32(), r.f32()), "ppu": r.f32(),
            "border": (r.f32(), r.f32(), r.f32(), r.f32()),
        })

    objs = []
    for _ in range(r.i32()):
        o = {"name": r.string(), "parent": r.i32(), "layer": r.i32(), "active": r.boolean(),
             "pos": (r.f32(), r.f32(), r.f32()),
             "rot": (r.f32(), r.f32(), r.f32(), r.f32()),
             "scale": (r.f32(), r.f32(), r.f32())}
        m = r.i32()
        o["mask"] = m
        if m & HAS_SPRITE:
            o["sprite"] = r.i32()
            o["shader"] = r.i32()
            o["color"] = (r.f32(), r.f32(), r.f32(), r.f32())
            o["order"] = r.i32(); r.i32()
            o["flipX"] = r.boolean(); o["flipY"] = r.boolean(); o["renderer"] = r.boolean()
        if m & HAS_BOX:
            for _ in range(r.i32()):
                [r.f32() for _ in range(4)]; r.boolean(); r.boolean()
        if m & HAS_EDGE:
            for _ in range(r.i32()):
                r.f32(); r.f32()
                for _ in range(r.i32()): r.f32(); r.f32()
                r.boolean(); r.boolean()
        if m & HAS_POLY:
            for _ in range(r.i32()):
                r.f32(); r.f32()
                for _ in range(r.i32()):
                    for _ in range(r.i32()): r.f32(); r.f32()
                r.boolean(); r.boolean()
        if m & HAS_CAMLOCK:
            [r.f32() for _ in range(4)]
            r.boolean(); r.boolean(); r.boolean()
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
    return name, bounds, shaders, pages, sprites, objs


def world_transforms(objs):
    """Accumulate local TRS down the hierarchy. Returns (x, y, sx, sy, zdeg, active)."""
    out = []
    for i, o in enumerate(objs):
        px, py, psx, psy, prot, pactive = (0.0, 0.0, 1.0, 1.0, 0.0, True)
        if o["parent"] >= 0:
            px, py, psx, psy, prot, pactive = out[o["parent"]]

        lx, ly = o["pos"][0], o["pos"][1]
        # Rotate the local offset by the parent's z rotation.
        if prot:
            a = math.radians(prot)
            ca, sa = math.cos(a), math.sin(a)
            lx, ly = lx * ca - ly * sa, lx * sa + ly * ca
        x = px + lx * psx
        y = py + ly * psy

        sx = psx * o["scale"][0]
        sy = psy * o["scale"][1]

        # Quaternion -> z euler (Godhome scenery is planar).
        qx, qy, qz, qw = o["rot"]
        zdeg = prot + math.degrees(math.atan2(2.0 * (qw * qz + qx * qy),
                                              1.0 - 2.0 * (qy * qy + qz * qz)))
        out.append((x, y, sx, sy, zdeg, pactive and o["active"]))
    return out


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "GG_Atrium"
    path = os.path.join(BAKED, f"{name}.scene")
    if not os.path.exists(path):
        raise SystemExit(f"No baked scene at {path}")

    sname, bounds, shaders, pages, sprites, objs = read_scene(path)
    page_imgs = [Image.open(os.path.join(BAKED, p + ".png")).convert("RGBA") for p in pages]
    tf = world_transforms(objs)

    # Draw list, sorted the way the renderer would.
    draw = []
    for i, o in enumerate(objs):
        if not (o["mask"] & HAS_SPRITE):
            continue
        x, y, sx, sy, rot, active = tf[i]
        if not active or not o.get("renderer", True):
            continue
        if o["color"][3] <= 0.02:
            continue
        s = sprites[o["sprite"]]
        w = s["rect"][2] / s["ppu"] * abs(sx)
        h = s["rect"][3] / s["ppu"] * abs(sy)
        if w <= 0 or h <= 0 or w > 400 or h > 400:
            continue
        shname = shaders[o["shader"]] if 0 <= o.get("shader", -1) < len(shaders) else ""
        draw.append((o["order"], i, x, y, w, h, rot, s, o, shname))
    draw.sort(key=lambda d: (d[0], d[1]))

    xs = [d[2] for d in draw]; ys = [d[3] for d in draw]
    if not xs:
        raise SystemExit("nothing to draw")
    pad = 8.0
    minx, maxx = min(xs) - pad, max(xs) + pad
    miny, maxy = min(ys) - pad, max(ys) + pad
    span_x, span_y = maxx - minx, maxy - miny
    scale = min(MAX_DIM / span_x, MAX_DIM / span_y)
    W, H = int(span_x * scale), int(span_y * scale)

    canvas = Image.new("RGBA", (W, H), (16, 16, 24, 255))
    drawn = 0
    for order, i, x, y, w, h, rot, s, o, shname in draw:
        pw, ph = max(1, int(w * scale)), max(1, int(h * scale))
        rx, ry, rw, rh = s["rect"]
        img = page_imgs[s["page"]]
        top = img.height - int(ry) - int(rh)
        crop = img.crop((int(rx), top, int(rx) + int(rw), top + int(rh)))
        if crop.width == 0 or crop.height == 0:
            continue
        crop = crop.resize((pw, ph), Image.LANCZOS)
        if o["flipX"]:
            crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
        if o["flipY"]:
            crop = crop.transpose(Image.FLIP_TOP_BOTTOM)
        if abs(rot) > 0.5:
            crop = crop.rotate(rot, expand=True, resample=Image.BICUBIC)

        a = o["color"][3]
        if a < 0.999:
            alpha = crop.getchannel("A").point(lambda v: int(v * a))
            crop.putalpha(alpha)

        # Pivot -> top-left corner, then world -> image space (y flips).
        cx = (x - minx) * scale
        cy = (maxy - y) * scale
        px = cx - s["pivot"][0] * crop.width
        py = cy - (1.0 - s["pivot"][1]) * crop.height
        # Screen blend: 1-(1-a)(1-b). Godhome's dream beams and glows use it; compositing
        # them as plain alpha is what makes them look like solid white bars.
        if "Screen" in shname:
            box = (int(px), int(py), int(px) + crop.width, int(py) + crop.height)
            box = (max(0, box[0]), max(0, box[1]), min(W, box[2]), min(H, box[3]))
            if box[2] > box[0] and box[3] > box[1]:
                sub = crop.crop((box[0] - int(px), box[1] - int(py),
                                 box[2] - int(px), box[3] - int(py)))
                base = canvas.crop(box)
                import PIL.ImageChops as IC
                inv_b = IC.invert(base.convert("RGB"))
                inv_s = IC.invert(sub.convert("RGB"))
                screened = IC.invert(IC.multiply(inv_b, inv_s)).convert("RGBA")
                screened.putalpha(sub.getchannel("A"))
                base.alpha_composite(screened)
                canvas.paste(base, box)
        else:
            canvas.alpha_composite(crop, (int(px), int(py)))
        drawn += 1

    out = f"/tmp/{name}_preview.png"
    canvas.convert("RGB").save(out, quality=92)
    print(f"{sname}: drew {drawn}/{len(draw)} sprites")
    print(f"declared scene bounds {bounds[0]:.0f} x {bounds[1]:.0f}; shaders {len(shaders)}")
    print(f"world bounds x[{minx:.1f},{maxx:.1f}] y[{miny:.1f},{maxy:.1f}]  ({span_x:.0f} x {span_y:.0f} units)")
    print(f"-> {out}  ({W}x{H}, {os.path.getsize(out)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
