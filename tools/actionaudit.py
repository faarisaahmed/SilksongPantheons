#!/usr/bin/env python3
"""
Which PlayMaker actions a boss needs, and whether Silksong has them.

This is the question that matters most for a ported FSM. PlayMaker builds its actions by
reflection on the type name in ActionData; when the type is missing it substitutes a
placeholder that never calls Finish(). A state containing one is a dead end - the FSM
stops there and the boss stands still forever, with no error after the first line.

So: collect every action type name Hollow Knight's boss FSMs use, and check each against
the types Silksong actually ships.
"""
import collections
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hkpath import hollow_knight_data, silksong_data
from hkassets import HKBuild
from fsmdump import fsms_on

HK = hollow_knight_data()
SS = os.path.join(silksong_data(), "Managed")


def silksong_types():
    """Every type name Silksong's managed assemblies define."""
    out = set()
    env = dict(os.environ)
    env["DOTNET_ROOT"] = os.path.expanduser("~/.dotnet")
    env["PATH"] = os.path.expanduser("~/.dotnet") + ":" + \
        os.path.expanduser("~/.dotnet/tools") + ":" + env.get("PATH", "")
    for dll in ("Assembly-CSharp.dll", "PlayMaker.dll", "Assembly-CSharp-firstpass.dll"):
        p = os.path.join(SS, dll)
        if not os.path.exists(p):
            continue
        r = subprocess.run(["ilspycmd", "-l", "c", p], capture_output=True, text=True, env=env)
        # "Class Some.Name.Space.TypeName" per line.
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or " " not in line:
                continue
            full = line.split(" ", 1)[1].strip()
            out.add(full)
            out.add(full.split(".")[-1])
    return out


def main():
    scenes = sys.argv[1:] or [
        "GG_Vengefly", "GG_Gruz_Mother", "GG_False_Knight", "GG_Mega_Moss_Charger",
        "GG_Hornet_1", "GG_Ghost_Gorb", "GG_Dung_Defender", "GG_Mage_Knight",
        "GG_Brooding_Mawlek", "GG_Nailmasters",
    ]
    have = silksong_types()
    print(f"Silksong defines {len(have)} types\n")

    used = collections.Counter()
    where = collections.defaultdict(set)
    for sc in scenes:
        for owner, f in fsms_on(sc, ""):
            for s in f["states"]:
                for a in s["actionData"]["actionNames"]:
                    used[a] += 1
                    where[a].add(f"{sc}/{owner}/{f['name']}")

    missing = []
    for name, n in used.most_common():
        short = name.split(".")[-1]
        if short in have or name in have:
            continue
        missing.append((n, name))

    print(f"{len(used)} distinct actions used, {len(missing)} missing from Silksong\n")
    for n, name in sorted(missing, reverse=True):
        w = sorted(where[name])
        print(f"  {n:5}x  {name}")
        for x in w[:3]:
            print(f"           {x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
