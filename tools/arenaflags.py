#!/usr/bin/env python3
"""
The save flags each Pantheon arena needs set.

A Silksong room decides what to put in itself by testing the player's save. Bone_05
loads Bone_05_boss when `defeatedBellBeast` is false and Bone_05_bellway when it is
true, and inside the boss piece `seenBellBeast` is what separates the first meeting -
with its cutscene - from a rematch.

A Godseeker save has none of these set, which is usually the right answer by luck and
occasionally the wrong one. Rather than force-loading pieces and skipping cutscenes by
hand, this reads the conditions out of each room and writes down what to set so the game
composes the arena itself:

  * whatever the room's SceneAdditiveLoadConditional tests, set so the boss piece loads
  * every `seen...` flag in the piece set true, so a Pantheon is always a rematch

Writes pantheons/flags.txt, read at runtime before travelling to an arena.
"""
import json
import os
import re
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "6000.0.50f1"
warnings.filterwarnings("ignore", module="UnityPy")

from hkpath import silksong_data

HERE = os.path.dirname(os.path.abspath(__file__))
LISTS = os.path.join(os.path.dirname(HERE), "SilksongGodhome", "Baked", "pantheons")
OUT = os.path.join(LISTS, "flags.txt")


def bundle(scene):
    return os.path.join(silksong_data(),
                        "StreamingAssets/aa/StandaloneWindows64/scenes_scenes_scenes",
                        scene.lower() + ".bundle")


def additive_tests(room):
    """{sub-scene lower: [(field, wantedBool)]} for one room's additive loaders."""
    p = bundle(room)
    if not os.path.exists(p):
        return {}
    env = UnityPy.load(p)
    out = {}
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read_typetree()
        except Exception:
            continue
        name = d.get("sceneNameToLoad")
        if not isinstance(name, str) or not name:
            continue
        wants = []
        tests = d.get("tests") or {}
        for group in (tests.get("TestGroups") or []):
            for t in (group.get("Tests") or []):
                f = t.get("FieldName")
                if isinstance(f, str) and f:
                    wants.append((f, bool(t.get("BoolValue"))))
        out[name.lower()] = wants
    return out


def seen_flags(scene):
    """Every `seen...` PlayerData name mentioned in a scene."""
    p = bundle(scene)
    if not os.path.exists(p):
        return []
    env = UnityPy.load(p)
    found = set()
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read_typetree()
        except Exception:
            continue

        def walk(v):
            if isinstance(v, dict):
                for k, x in v.items():
                    if isinstance(x, str) and re.match(r"^seen[A-Z]", x or ""):
                        found.add(x)
                    else:
                        walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
        walk(d)
    return sorted(found)


def arenas():
    """(displayName, room, piece) for every entry in the Pantheon lists."""
    out = []
    for f in sorted(os.listdir(LISTS)):
        if not f.startswith("pantheon") or not f.endswith(".txt"):
            continue
        for line in open(os.path.join(LISTS, f), encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            display, rhs = line.split("=", 1)
            left = rhs.split(":")[0]
            room, _, piece = left.partition("+")
            out.append((display.strip(), room.strip(), piece.strip()))
    return out


def main():
    seen_rooms = {}
    lines = [
        "# Save flags each arena needs, so the room composes itself correctly.",
        "#",
        "#   Scene: field=true, field=false",
        "#",
        "# Read out of the game: the first entries are whatever the room's",
        "# SceneAdditiveLoadConditional tests, set so the boss piece loads rather than",
        "# the post-victory one. The `seen...` flags are set true so a Pantheon fight is",
        "# always a rematch - no first-meeting cutscene.",
        "",
    ]

    done = set()
    for display, room, piece in arenas():
        key = (room, piece)
        if key in done:
            continue
        done.add(key)

        flags = []
        if piece:
            if room not in seen_rooms:
                seen_rooms[room] = additive_tests(room)
            for field, want in seen_rooms[room].get(piece.lower(), []):
                flags.append((field, want))
            for s in seen_flags(piece):
                flags.append((s, True))
        else:
            for s in seen_flags(room):
                flags.append((s, True))

        # Deduplicate, keeping the first opinion on each field.
        uniq = []
        have = set()
        for f, v in flags:
            if f in have:
                continue
            have.add(f)
            uniq.append((f, v))

        if not uniq:
            continue
        target = piece or room
        body = ", ".join(f"{f}={'true' if v else 'false'}" for f, v in uniq)
        lines.append(f"{target}: {body}")
        print(f"  {display:32} {target:34} {body}")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
