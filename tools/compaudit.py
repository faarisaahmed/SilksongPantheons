#!/usr/bin/env python3
"""
What a Godhome arena actually contains, and how much of it Silksong could take.

The boss baker brings across a boss's transform, sprite, animator, colliders, HealthManager
and DamageHero. A Hollow Knight arena is a great deal more than that: the objects that
start the fight, the ones that end it, the ones that make a hit knock the boss back and
the ones that play its death. This lists every component type in the scene, how many
there are, and whether Silksong defines a type of the same name - which is the test for
whether it can simply be rebuilt rather than reimplemented.
"""
import collections
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hkpath import hollow_knight_data, silksong_data
from hkassets import HKBuild
from monoread import script_ptr

HK = hollow_knight_data()
SS = os.path.join(silksong_data(), "Managed")


def silksong_types():
    out = set()
    env = dict(os.environ)
    env["DOTNET_ROOT"] = os.path.expanduser("~/.dotnet")
    env["PATH"] = os.path.expanduser("~/.dotnet") + ":" + \
        os.path.expanduser("~/.dotnet/tools") + ":" + env.get("PATH", "")
    for dll in ("Assembly-CSharp.dll", "PlayMaker.dll", "Assembly-CSharp-firstpass.dll",
                "TeamCherry.TK2D.dll"):
        p = os.path.join(SS, dll)
        if not os.path.exists(p):
            continue
        r = subprocess.run(["ilspycmd", "-l", "c", p], capture_output=True, text=True, env=env)
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or " " not in line:
                continue
            out.add(line.split(" ", 1)[1].strip().split(".")[-1])
    return out


def main():
    scenes = sys.argv[1:] or ["GG_Gruz_Mother"]
    have = silksong_types()
    build = HKBuild(HK)

    counts = collections.Counter()
    objs = collections.Counter()
    for sn in scenes:
        idx = build.find_scene(sn)
        if idx is None:
            continue
        scene = build.load_scene(idx)
        lvl = scene.level_file
        objs[sn] = sum(1 for _ in scene.scene_objects("GameObject"))
        for o in scene.scene_objects("MonoBehaviour"):
            try:
                ms = scene.resolve(script_ptr(o.get_raw_data()), lvl)
                cn = ms.read_typetree().get("m_ClassName") if ms else None
            except Exception:
                cn = None
            if cn:
                counts[cn] += 1

    print(f"scenes: {', '.join(f'{k} ({v} objects)' for k, v in objs.items())}\n")
    print(f"{'component':38} {'count':>6}  in Silksong")
    yes = no = 0
    for cn, n in counts.most_common():
        ok = cn in have
        yes += n if ok else 0
        no += 0 if ok else n
        print(f"{cn:38} {n:6}  {'yes' if ok else 'NO'}")
    print(f"\n{yes} component instances have a Silksong type, {no} do not")
    return 0


if __name__ == "__main__":
    sys.exit(main())
