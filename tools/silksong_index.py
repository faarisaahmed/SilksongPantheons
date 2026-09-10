#!/usr/bin/env python3
"""
An index of every enemy in Silksong, by scene.

silksong_bosses.py only keeps HealthManagers above a health threshold, which is right for
"what are the bosses" and wrong for "where is the boss called X". This records every
HealthManager in the game with its health and scene, so a roster can be resolved by name
rather than guessed at.

Writes enemies.json: {scene: [{name, hp, active}]}.
"""
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "6000.0.50f1"
warnings.filterwarnings("ignore", module="UnityPy")

from hkpath import silksong_data

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "enemies.json")
MIN_HP = 1


def scan(path):
    env = UnityPy.load(path)
    objs = list(env.objects)
    names = {}
    for o in objs:
        if o.type.name == "GameObject":
            try:
                names[o.path_id] = o.read_typetree()
            except Exception:
                pass
    out = []
    for o in objs:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read_typetree()
        except Exception:
            continue
        if "hp" not in d or "enemyType" not in d:
            continue
        hp = int(d.get("hp") or 0)
        if hp < MIN_HP:
            continue
        g = names.get((d.get("m_GameObject") or {}).get("m_PathID"))
        if g is None:
            continue
        out.append({"name": g.get("m_Name") or "?", "hp": hp,
                    "active": bool(g.get("m_IsActive", True))})
    return out


def main():
    d = os.path.join(silksong_data(),
                     "StreamingAssets/aa/StandaloneWindows64/scenes_scenes_scenes")
    bundles = sorted(f for f in os.listdir(d) if f.endswith(".bundle"))
    found = {}
    for i, f in enumerate(bundles, 1):
        scene = f[:-len(".bundle")]
        try:
            hits = scan(os.path.join(d, f))
        except Exception as e:
            print(f"  ! {scene}: {e!r}", flush=True)
            continue
        if hits:
            found[scene] = hits
        if i % 40 == 0:
            print(f"[{i}/{len(bundles)}] {sum(len(v) for v in found.values())} enemies",
                  flush=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(found, fh, indent=0, sort_keys=True)
    print(f"\n{len(found)} scenes, {sum(len(v) for v in found.values())} enemies -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
