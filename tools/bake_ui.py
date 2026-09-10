#!/usr/bin/env python3
"""
Bake Hollow Knight's binding icons for the Pantheon challenge screen.

The real BossDoorChallengeUI is a Canvas prefab we can't reconstruct - Animator with
Open/Close clips, four wired BossDoorChallengeUIBindingButtons - but its most recognisable
part is just four sprites: the nail, shell, charm and soul bindings, each with a lit and
an unlit state. Those we can lift and draw ourselves.

Writes SilksongGodhome/Baked/ui_*.png, which the csproj embeds like any other page.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hkpath import hollow_knight_data, silksong_data
from hkassets import HKBuild
from spritebake import SpriteBaker

DEFAULT_HK = hollow_knight_data()
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "SilksongGodhome", "Baked")

# (sprite name in Hollow Knight, name we embed it under)
WANTED = [
    ("GG_UI_pieces_nail",       "ui_bind_nail_on"),
    ("GG_UI_pieces_nail_off",   "ui_bind_nail_off"),
    ("GG_UI_pieces_shell",      "ui_bind_shell_on"),
    ("GG_UI_pieces_shell_off",  "ui_bind_shell_off"),
    ("GG_UI_pieces_charm",      "ui_bind_charm_on"),
    ("GG_UI_pieces_charm_off",  "ui_bind_charm_off"),
    ("GG_UI_pieces_soul",       "ui_bind_soul_on"),
    ("GG_UI_pieces_soul_off",   "ui_bind_soul_off"),
]


def main():
    hk = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HK
    build = HKBuild(hk)
    idx = build.find_scene("GG_Atrium")
    if idx is None:
        raise SystemExit("GG_Atrium not found in this build")

    scene = build.load_scene(idx)
    baker = SpriteBaker(scene)

    by_name = {}
    for o in scene.env.objects:
        if o.type.name != "Sprite":
            continue
        try:
            nm = o.read_typetree().get("m_Name")
        except Exception:
            continue
        if nm and nm not in by_name:
            by_name[nm] = o

    os.makedirs(OUT, exist_ok=True)
    from PIL import Image
    ok = 0

    for hk_name, out_name in WANTED:
        obj = by_name.get(hk_name)
        if obj is None:
            print(f"  ! '{hk_name}' not found")
            continue

        # Reuse the scene baker's atlas resolution, then crop the page ourselves - the
        # same path the scene sprites take, so trimmed/atlas-packed sprites come out right.
        i = baker.add(obj)
        if i < 0:
            print(f"  ! '{hk_name}' could not be resolved to an atlas rect")
            continue

        s = baker.sprites[i]
        tex_obj, _ = baker.pages[s["page"]]
        try:
            page = tex_obj.read().image
        except Exception as e:
            print(f"  ! page for '{hk_name}' unreadable: {e!r}")
            continue

        x, y, w, h = [int(round(v)) for v in s["rect"]]
        if w <= 0 or h <= 0:
            print(f"  ! '{hk_name}' has an empty rect")
            continue

        top = page.height - y - h
        crop = page.crop((max(0, x), max(0, top),
                          min(page.width, x + w), min(page.height, top + h))).convert("RGBA")
        path = os.path.join(OUT, out_name + ".png")
        crop.save(path, optimize=True)
        print(f"  {out_name}.png  {crop.width}x{crop.height}  ({os.path.getsize(path)} bytes)")
        ok += 1

    print(f"{ok}/{len(WANTED)} binding icons baked into {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
