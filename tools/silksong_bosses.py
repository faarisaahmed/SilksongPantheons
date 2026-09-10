#!/usr/bin/env python3
"""
Find Silksong's bosses, and the scenes they live in.

Unlike the Hollow Knight side of this project, nothing here has to be parsed from raw
bytes: Silksong's Addressables bundles ship full type trees, so every component reads
straight out. This is a survey, not a port.

A boss is taken to be a HealthManager with a lot of health, on an object that isn't
obviously scenery. Health is the honest discriminator - Silksong's ordinary enemies sit
in the tens, its bosses in the hundreds.

    python3 silksong_bosses.py                 # every scene, written to bosses.json
    python3 silksong_bosses.py bone_05_boss    # one scene, printed
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
OUT = os.path.join(HERE, "bosses.json")

# Below this, it is an ordinary enemy. Silksong's bosses start around 200.
BOSS_HP = 150


def scene_dir():
    return os.path.join(silksong_data(),
                        "StreamingAssets/aa/StandaloneWindows64/scenes_scenes_scenes")


def scan(path):
    """[(objectName, hp, isActive)] for every big HealthManager in one scene bundle."""
    env = UnityPy.load(path)
    objs = list(env.objects)

    names = {}
    for o in objs:
        if o.type.name != "GameObject":
            continue
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
            continue                      # not a HealthManager
        hp = d.get("hp") or 0
        if hp < BOSS_HP:
            continue
        gid = (d.get("m_GameObject") or {}).get("m_PathID")
        god = names.get(gid)
        if god is None:
            continue
        out.append((god.get("m_Name") or "?", int(hp), bool(god.get("m_IsActive", True))))
    return out


def main():
    d = scene_dir()
    if len(sys.argv) > 1:
        for name in sys.argv[1:]:
            p = os.path.join(d, name.lower() + ".bundle")
            if not os.path.exists(p):
                print(f"{name}: no such scene bundle")
                continue
            for nm, hp, active in sorted(scan(p), key=lambda x: -x[1]):
                print(f"  {name:34} {nm:34} {hp:5} hp{'' if active else '  (inactive)'}")
        return 0

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
            found[scene] = [{"name": n, "hp": h, "active": a}
                            for n, h, a in sorted(hits, key=lambda x: -x[1])]
            top = found[scene][0]
            print(f"[{i:3}/{len(bundles)}] {scene:38} {top['name']:30} {top['hp']:5} hp"
                  f"{'' if len(hits) == 1 else f'  (+{len(hits)-1} more)'}", flush=True)
        elif i % 50 == 0:
            print(f"[{i:3}/{len(bundles)}] ...", flush=True)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(found, fh, indent=1, sort_keys=True)
    print(f"\n{len(found)} scenes with a boss-sized HealthManager -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
