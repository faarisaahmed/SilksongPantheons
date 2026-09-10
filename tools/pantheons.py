#!/usr/bin/env python3
"""
Build the four Pantheon lists.

The order is Pantheon of Pharloom's, which is the convention the Silksong boss-rush mods
have settled on: three authored Pantheons, and a fourth that is the first three run back
to back. Its lists are plain text and so are these - one entry per line, editable without
rebuilding anything.

What this adds is the mapping from a boss's *name* to the scene it actually lives in and
the object inside it, resolved against enemies.json rather than guessed. Anything that
cannot be resolved is written out commented, with the closest candidates beside it, so an
unresolved boss is visible instead of silently missing.

    python3 silksong_index.py     # first, to build enemies.json
    python3 pantheons.py
"""
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "enemies.json")
OUT_DIR = os.path.join(os.path.dirname(HERE), "SilksongGodhome", "Baked", "pantheons")

# Pantheon of Pharloom's order. "Bench" is a rest stop, not a fight.
PANTHEONS = [
    ("Pantheon of the Judge", [
        "Moss Mother", "Skull Tyrant", "Bell Beast", "Savage Beastfly", "Fourth Chorus",
        "Fire Lace", "Bench", "Double Conchfly", "Moorwing", "Sister Splinter", "Widow",
        "Phantom", "Last Judge",
    ]),
    ("Pantheon of the Sinner", [
        "Garmond and Zaza", "Cogwork Dancers", "Trobbio", "Chef Lugoli", "Broodmother",
        "Groal", "Bench", "Moss Mother 2", "Single Conchfly", "Zango", "Voltvyrm",
        "Savage Beastfly 2", "Shakra", "Bench", "Father of Flame", "Signis and Gron",
        "Second Sentinel", "Unravelled", "Flower Lace", "First Sinner",
    ]),
    ("Pantheon of the Void", [
        "Bell Eater", "Crawfather", "Gurr", "Lost Garmond", "Pinstress", "Watcher",
        "Tormented Trobbio", "Bench", "Palestag", "Clover Dancer", "Seth", "Nyleth",
        "Khann", "Kramelita", "Bench", "Grandmother", "Lost Lace",
    ]),
]

# Boss display name -> the object name Silksong actually uses, and where more than one
# scene contains it, the scene to prefer. Everything here was read out of the game with
# silksong_bosses.py; anything not listed falls through to fuzzy matching and is flagged.
ALIASES = {
    "Bell Beast":          ("Bone Beast", "bone_05_boss"),
    "Skull Tyrant":        ("Skull King", "bonetown_boss"),
    "Savage Beastfly":     ("Bone Flyer Giant", "bone_east_08_boss_beastfly"),
    "Savage Beastfly 2":   ("Bone Flyer Giant", "bone_east_08_boss_beastfly"),
    "Moorwing":            ("Vampire Gnat", "greymoor_05_boss"),
    "Sister Splinter":     ("Splinter Queen", "shellwood_18"),
    "Widow":               ("Spinner Boss", "belltown_shrine"),
    "Last Judge":          ("Last Judge", "coral_judge_arena"),
    "Phantom":             ("Phantom", "organ_01"),
    "Cogwork Dancers":     ("Dancer A", "cog_dancers_boss"),
    "Clover Dancer":       ("Dancer A", "clover_10"),
    "Trobbio":             ("Trobbio", "library_13"),
    "Tormented Trobbio":   ("Tormented Trobbio", "library_13"),
    "Chef Lugoli":         ("Roachkeeper Chef (1)", "dust_chef"),
    "Broodmother":         ("Slab Fly Broodmother", "slab_16b"),
    "Crawfather":          ("Crawfather", "room_crowcourt_02"),
    "Pinstress":           ("Pinstress Boss", "peak_07"),
    "Seth":                ("Seth", "shellwood_22"),
    "Lost Lace":           ("Lost Lace Boss", "abyss_cocoon"),
    "Palestag":            ("Cloverstag White Boss", "clover_19"),
    "Fire Lace":           ("Lace Boss1", "bone_east_12"),
    "Flower Lace":         ("Lace Boss2 New", "song_tower_01"),
    "Garmond and Zaza":    ("Garmond Fighter", "library_09"),
    "Lost Garmond":        ("Garmond Black Threaded Fighter", "coral_33"),
    "Second Sentinel":     ("Song Knight", "hang_17b"),
    "Fourth Chorus":       ("Conductor Boss", "ward_02_boss"),
    "Grandmother":         ("First Weaver", "slab_10b"),
    "Groal":               ("Swamp Shaman", "shadow_18"),
    "Voltvyrm":            ("Zap Core Enemy", "coral_29"),
    "Khann":               ("Blue Assistant", "crawl_10"),
    "Moss Mother":         ("Mossbone Mother A", "weave_03"),
    "Moss Mother 2":       ("Mossbone Mother B", "weave_03"),
    "Double Conchfly":     ("Coral Conch Driller Giant Solo", "coral_27"),
    "Single Conchfly":     ("Driller A", "coral_11"),
    "Bell Eater":          ("Giant Centipede Head", "bellway_centipede_arena"),
    # Shakra is Pharloom's cartographer, and the duel with her is a "spar".
    "Shakra":              ("Mapper Spar NPC", "greymoor_08_mapper"),
    # Nyleth is the bloom boss; the Flower Queen sits in a Shellwood memory.
    "Nyleth":              ("Flower Queen Boss", "shellwood_11b_memory"),
    # The Cradle's boss is the grandmother of the whole thing.
    "Grandmother":         ("Silk Boss", "cradle_03"),
    # The Slab is Pharloom's prison, and its boss is the First Weaver.
    "First Sinner":        ("First Weaver", "slab_10b"),
}


def scene_key(bundle_name):
    """Bundle file names are lowercased; the Addressables scene key is capitalised."""
    return bundle_name[0].upper() + bundle_name[1:] if bundle_name else bundle_name


def load_index():
    if not os.path.exists(INDEX):
        raise SystemExit(f"{INDEX} is missing - run silksong_index.py first.")
    with open(INDEX, encoding="utf-8") as f:
        return json.load(f)


def resolve(display, index):
    """(scene, object, note) - note is empty when the mapping is a known one."""
    alias = ALIASES.get(display)
    if alias:
        obj, scene = alias
        for e in index.get(scene, []):
            if e["name"] == obj:
                return scene, obj, ""
        return scene, obj, f"'{obj}' not found in {scene}"

    # Nothing known: offer the closest names in the whole game, and leave it unresolved.
    every = {}
    for scene, es in index.items():
        for e in es:
            every.setdefault(e["name"], []).append((scene, e["hp"]))
    close = difflib.get_close_matches(display, every.keys(), n=3, cutoff=0.55)
    if close:
        best = close[0]
        scene, hp = max(every[best], key=lambda x: x[1])
        return scene, best, f"guessed from the name; candidates: {', '.join(close)}"
    return None, None, "no candidate found"


def main():
    index = load_index()
    os.makedirs(OUT_DIR, exist_ok=True)

    resolved = unresolved = 0
    made = []
    for n, (title, entries) in enumerate(PANTHEONS, 1):
        lines = [
            f"# {title}",
            "#",
            "# One entry per line:  Display Name = Scene : Boss Object",
            "# 'Bench' on its own is a rest stop between fights.",
            "# Lines starting with # are ignored; edit freely, no rebuild needed.",
            "#",
            "# Order follows Pantheon of Pharloom, the convention the Silksong",
            "# boss-rush mods use.",
            "",
        ]
        for e in entries:
            if e == "Bench":
                lines.append("Bench")
                continue
            scene, obj, note = resolve(e, index)
            if scene and not note:
                lines.append(f"{e} = {scene_key(scene)} : {obj}")
                resolved += 1
            elif scene:
                lines.append(f"# UNRESOLVED  {e} = {scene_key(scene)} : {obj}    # {note}")
                unresolved += 1
            else:
                lines.append(f"# UNRESOLVED  {e}    # {note}")
                unresolved += 1
        path = os.path.join(OUT_DIR, f"pantheon{n}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        made.append(path)
        print(f"  pantheon{n}.txt  {title}")

    # The fourth is the first three back to back, which is what the mods do and what
    # the door in the Atrium has always been for.
    p4 = os.path.join(OUT_DIR, "pantheon4.txt")
    with open(p4, "w", encoding="utf-8") as f:
        f.write("# Pantheon of Pharloom\n#\n"
                "# The first three, run back to back, with no rest between them beyond\n"
                "# the benches the earlier lists already carry. Built at load time from\n"
                "# pantheon1-3, so editing those changes this one too.\n#\n"
                "@include pantheon1\n@include pantheon2\n@include pantheon3\n")
    print(f"  pantheon4.txt  Pantheon of Pharloom (pantheon1 + 2 + 3)")

    # Everything boss-sized the lists do not use, so the unresolved entries above can be
    # filled in by looking at one file instead of searching the game again.
    used = set()
    for p in made:
        for line in open(p, encoding="utf-8"):
            if line.startswith("#") or "=" not in line:
                continue
            rhs = line.split("=", 1)[1]
            sc, _, ob = rhs.partition(":")
            used.add((sc.strip().lower(), ob.strip()))

    spare = []
    for scene, es in index.items():
        for e in es:
            if e["hp"] < 300 or e["hp"] > 50000:
                continue
            if (scene, e["name"]) in used:
                continue
            spare.append((e["hp"], e["name"], scene))
    spare.sort(reverse=True)
    seen = set()
    with open(os.path.join(OUT_DIR, "UNASSIGNED.txt"), "w", encoding="utf-8") as f:
        f.write("# Boss-sized enemies the Pantheon lists do not use yet.\n"
                "# Paste one of these into a pantheon file to fill an UNRESOLVED line.\n"
                "#\n#   hp     scene : object\n\n")
        for hp, n, sc in spare:
            if (n, sc) in seen:
                continue
            seen.add((n, sc))
            f.write(f"# {hp:6}  {scene_key(sc)} : {n}\n")
    print(f"  UNASSIGNED.txt {len(seen)} boss-sized enemies not used by any Pantheon")

    print(f"\n{resolved} bosses resolved, {unresolved} left unresolved "
          f"(written as # UNRESOLVED lines).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
