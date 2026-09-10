#!/usr/bin/env python3
"""
Which Silksong scenes are rooms, and which are pieces loaded into them.

Silksong composes a room from a main scene plus additive sub-scenes, and its bosses very
often live in one of the pieces: `bone_05_boss` is 202 objects with no _SceneManager, no
_Managers and no TileMap. Sending the player straight to it drops them into a void with
no terrain - which is what "it teleported me out of bounds" looks like.

So this records two things per scene:

  standalone : has the _SceneManager / _Managers / TileMap a real room has
  parent     : the room whose SceneAdditiveLoadConditional loads it, read out of the
               game rather than guessed from the name

Writes scenes.json: {scene: {standalone, parent, objects}}.
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
OUT = os.path.join(HERE, "scenes.json")

ROOM_MARKERS = ("_SceneManager", "_Managers", "TileMap")


def scan(path):
    """(is_standalone, object_count, [sub-scenes this one loads])."""
    env = UnityPy.load(path)
    objs = list(env.objects)

    names = set()
    count = 0
    for o in objs:
        if o.type.name != "GameObject":
            continue
        count += 1
        try:
            names.add(o.read_typetree().get("m_Name"))
        except Exception:
            pass

    loads = []
    for o in objs:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read_typetree()
        except Exception:
            continue
        # SceneAdditiveLoadConditional: the component that composes a room.
        if "sceneNameToLoad" not in d:
            continue
        for key in ("sceneNameToLoad", "altSceneNameToLoad"):
            v = d.get(key)
            if isinstance(v, str) and v:
                loads.append(v)

    standalone = sum(1 for m in ROOM_MARKERS if m in names) >= 2
    return standalone, count, loads


def main():
    d = os.path.join(silksong_data(),
                     "StreamingAssets/aa/StandaloneWindows64/scenes_scenes_scenes")
    bundles = sorted(f for f in os.listdir(d) if f.endswith(".bundle"))

    info = {}
    loads = {}
    for i, f in enumerate(bundles, 1):
        scene = f[:-len(".bundle")]
        try:
            standalone, count, subs = scan(os.path.join(d, f))
        except Exception as e:
            print(f"  ! {scene}: {e!r}", flush=True)
            continue
        info[scene] = {"standalone": standalone, "parent": None, "objects": count}
        loads[scene] = subs
        if i % 60 == 0:
            print(f"[{i}/{len(bundles)}]", flush=True)

    # A scene's parent is whoever loads it additively.
    for parent, subs in loads.items():
        for sub in subs:
            key = sub.lower()
            if key in info and info[key]["parent"] is None and key != parent:
                info[key]["parent"] = parent

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=0, sort_keys=True)

    add = sum(1 for v in info.values() if not v["standalone"])
    par = sum(1 for v in info.values() if v["parent"])
    print(f"\n{len(info)} scenes: {len(info)-add} standalone rooms, {add} pieces, "
          f"{par} with a known parent -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
