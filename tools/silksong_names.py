#!/usr/bin/env python3
"""
The scene names Silksong actually uses.

Bundle files are lowercased and the Addressables catalog holds both spellings, so
neither tells you what to pass to a scene load. The game does: every TransitionPoint
carries the `targetScene` it leads to, and every SceneAdditiveLoadConditional carries
the `sceneNameToLoad` of the piece it pulls in. Those strings are what Silksong itself
hands to Addressables, so they are the names by definition.

Writes names.json: {lowercased: "TrueCasedName"}.
"""
import json
import os
import sys
import warnings
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "6000.0.50f1"
warnings.filterwarnings("ignore", module="UnityPy")

from hkpath import silksong_data

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "names.json")


def scan(path):
    env = UnityPy.load(path)
    out = []
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read_typetree()
        except Exception:
            continue
        for key in ("targetScene", "sceneNameToLoad", "altSceneNameToLoad"):
            v = d.get(key)
            if isinstance(v, str) and v:
                out.append(v)
    return out


def main():
    d = os.path.join(silksong_data(),
                     "StreamingAssets/aa/StandaloneWindows64/scenes_scenes_scenes")
    bundles = sorted(f for f in os.listdir(d) if f.endswith(".bundle"))

    votes = collections.defaultdict(collections.Counter)
    for i, f in enumerate(bundles, 1):
        try:
            for n in scan(os.path.join(d, f)):
                votes[n.lower()][n] += 1
        except Exception as e:
            print(f"  ! {f}: {e!r}", flush=True)
        if i % 80 == 0:
            print(f"[{i}/{len(bundles)}] {len(votes)} names", flush=True)

    # A scene is occasionally referred to with different casing; take the commonest.
    names = {k: c.most_common(1)[0][0] for k, c in votes.items()}

    # Anything never referenced keeps its bundle spelling, which is the best guess left.
    for f in bundles:
        b = f[:-len(".bundle")]
        names.setdefault(b, b)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(names, fh, indent=0, sort_keys=True)
    referenced = len(votes)
    print(f"\n{len(names)} scenes, {referenced} named by the game itself -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
