#!/usr/bin/env python3
"""
How portable is a Hollow Knight boss?

A boss is a GameObject with tk2d animation, colliders, a HealthManager and - the hard
part - PlayMaker FSMs. Those FSMs are built from typed action classes, so the question
that decides whether porting is even possible is: does Silksong still have those action
classes?

Mostly, yes. Both games are the same codebase lineage and share PlayMaker plus Team
Cherry's custom action set. This prints the per-scene breakdown so the gaps are known
before any porting work starts.

    python3 boss_survey.py                    # every baked arena
    python3 boss_survey.py GG_Gruz_Mother
"""

import collections
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hkpath import hollow_knight_data, silksong_data
from hkassets import HKBuild
from monoread import script_ptr

HK = hollow_knight_data()
SS_MANAGED = os.path.join(silksong_data(), "Managed")

ACTION_RE = re.compile(rb"HutongGames\.PlayMaker\.Actions\.[A-Za-z0-9_]{2,60}")


def silksong_symbols():
    """Every identifier that appears in Silksong's managed assemblies."""
    syms = set()
    for dll in ("Assembly-CSharp.dll", "PlayMaker.dll", "Assembly-CSharp-firstpass.dll"):
        p = os.path.join(SS_MANAGED, dll)
        if not os.path.exists(p):
            continue
        with os.popen(f"strings -n 3 '{p}'") as f:
            syms |= set(re.findall(r"[A-Za-z][A-Za-z0-9_]{2,60}", f.read()))
    return syms


def survey(build, scene_name, avail):
    idx = build.find_scene(scene_name)
    if idx is None:
        print(f"{scene_name}: not in this build")
        return None

    scene = build.load_scene(idx)
    lvl = scene.level_file

    names = {}
    for g in scene.scene_objects("GameObject"):
        try:
            names[g.path_id] = g.read_typetree().get("m_Name")
        except Exception:
            pass

    actions = set()
    fsm_count = 0
    owners = collections.Counter()

    for o in scene.scene_objects("MonoBehaviour"):
        raw = o.get_raw_data()
        ms = scene.resolve(script_ptr(raw), lvl)
        if ms is None:
            continue
        try:
            if ms.read_typetree().get("m_ClassName") != "PlayMakerFSM":
                continue
        except Exception:
            continue
        fsm_count += 1
        gid = struct.unpack_from("<q", raw, 4)[0]
        owners[names.get(gid, "?")] += 1
        actions |= {m.decode().rsplit(".", 1)[1] for m in ACTION_RE.findall(raw)}

    missing = sorted(a for a in actions if a not in avail)
    have = len(actions) - len(missing)
    pct = (100.0 * have / len(actions)) if actions else 100.0

    print(f"\n{scene_name}: {fsm_count} FSMs, {len(actions)} distinct actions, "
          f"{have} present in Silksong ({pct:.0f}%)")
    top = [f"{n}x{c}" for n, c in owners.most_common(5)]
    print(f"  FSM owners: {', '.join(top)}")
    if missing:
        print(f"  missing: {', '.join(missing)}")
    return missing


def main():
    args = sys.argv[1:]
    build = HKBuild(HK)
    avail = silksong_symbols()

    if args:
        scenes = args
    else:
        baked = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "SilksongGodhome", "Baked")
        scenes = sorted(f[:-6] for f in os.listdir(baked) if f.endswith(".scene"))

    all_missing = collections.Counter()
    for s in scenes:
        m = survey(build, s, avail)
        if m:
            all_missing.update(m)

    if all_missing:
        print("\nActions missing across all surveyed scenes:")
        for a, c in all_missing.most_common():
            print(f"   {c:3}x  {a}")
        print("\nMost of these are Hollow Knight's numbered duplicates of an action that "
              "does exist (FaceObject0 -> FaceObject), so they can be aliased.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
