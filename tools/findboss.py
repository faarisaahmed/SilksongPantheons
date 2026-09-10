#!/usr/bin/env python3
"""
Search every Silksong scene for GameObjects whose name contains a keyword.

The enemy index only keeps HealthManagers, which misses anything that fights through a
different component - the NPC duels especially. This looks at names alone, which is the
last resort when a boss is known by a title the game does not use internally.

    python3 findboss.py zango gron khann
"""
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "6000.0.50f1"
warnings.filterwarnings("ignore", module="UnityPy")

from hkpath import silksong_data


def main():
    words = [w.lower() for w in sys.argv[1:]]
    if not words:
        print(__doc__)
        return 1

    d = os.path.join(silksong_data(),
                     "StreamingAssets/aa/StandaloneWindows64/scenes_scenes_scenes")
    bundles = sorted(f for f in os.listdir(d) if f.endswith(".bundle"))
    hits = {}
    for i, f in enumerate(bundles, 1):
        scene = f[:-len(".bundle")]
        try:
            env = UnityPy.load(os.path.join(d, f))
            for o in env.objects:
                if o.type.name != "GameObject":
                    continue
                try:
                    n = o.read_typetree().get("m_Name") or ""
                except Exception:
                    continue
                low = n.lower()
                for w in words:
                    if w in low:
                        hits.setdefault(w, set()).add((n, scene))
        except Exception:
            pass
        if i % 80 == 0:
            print(f"[{i}/{len(bundles)}]", flush=True)

    print()
    for w in words:
        found = sorted(hits.get(w, ()))
        print(f"== {w}: {len(found)} match(es)")
        for n, sc in found[:12]:
            print(f"     {n:40} {sc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
