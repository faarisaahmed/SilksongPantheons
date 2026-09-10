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
SCENES = os.path.join(HERE, "scenes.json")
NAMES = os.path.join(HERE, "names.json")
OUT_DIR = os.path.join(os.path.dirname(HERE), "SilksongGodhome", "Baked", "pantheons")

# The four Pantheons, as the user laid them out. "Bench" is a rest stop, not a fight.
PANTHEONS = [
    ("Pantheon of the Judge", [
        "Moss Mother", "Bell Beast", "Lace", "Fourth Chorus", "Savage Beastfly",
        "Sister Splinter", "Skull Tyrant", "Moorwing", "Widow", "Moss Mother Duo",
        "Great Conchflies", "Last Judge",
    ]),
    ("Pantheon of the Weaver", [
        "Phantom", "Cogwork Dancers", "Trobbio", "Garmond And Zaza",
        "Forebrothers Signis and Gron", "Savage Beastfly 2", "The Unravelled",
        "Disgraced Chef Lugoli", "Father Of The Flame", "First Sinner",
    ]),
    ("Pantheon of the Monarch", [
        "Groal The Great", "Voltvyrm", "Raging Conchfly", "Broodmother",
        "Second Sentinel", "Shakra", "Lace 2", "Grand Mother Silk",
    ]),
    ("Pantheon of the Imperators", [
        "Bell Eater", "Lost Garmond", "Crawfather", "Plasmified Zango",
        "Watcher At The Edge", "Gurr The Outcast", "Tormented Trobbio", "Pinstress",
        "Palestag", "Clover Dancers", "Shrine Guardian Seth", "Nyleth",
        "Skarrsinger Karmelita", "Crust King Khann",
    ]),
]

# Boss display name -> the object name Silksong actually uses, and where more than one
# scene contains it, the scene to prefer. Everything here was read out of the game with
# silksong_bosses.py; anything not listed falls through to fuzzy matching and is flagged.
ALIASES = {
    # -- Pantheon of the Judge -------------------------------------------------
    "Moss Mother":            ("Mossbone Mother", "tut_03"),
    "Moss Mother Duo":        ("Mossbone Mother A", "weave_03"),
    "Bell Beast":             ("Bone Beast", "bone_05_boss"),
    "Lace":                   ("Lace Boss1", "bone_east_12"),
    "Fourth Chorus":          ("Conductor Boss", "ward_02_boss"),
    "Savage Beastfly":        ("Bone Flyer Giant", "bone_east_08_boss_beastfly"),
    "Sister Splinter":        ("Splinter Queen", "shellwood_18"),
    "Skull Tyrant":           ("Skull King", "bonetown_boss"),
    "Moorwing":               ("Vampire Gnat", "greymoor_05_boss"),
    "Widow":                  ("Spinner Boss", "belltown_shrine"),
    "Great Conchflies":       ("Coral Conch Driller Giant Solo", "coral_27"),
    "Last Judge":             ("Last Judge", "coral_judge_arena"),

    # -- Pantheon of the Weaver ------------------------------------------------
    "Phantom":                ("Phantom", "organ_01"),
    "Cogwork Dancers":        ("Dancer A", "cog_dancers_boss"),
    "Trobbio":                ("Trobbio", "library_13"),
    "Garmond And Zaza":       ("Garmond Fighter", "library_09"),
    "Savage Beastfly 2":      ("Bone Flyer Giant", "ant_19"),
    "Disgraced Chef Lugoli":  ("Roachkeeper Chef (1)", "dust_chef"),
    "First Sinner":           ("First Weaver", "slab_10b"),

    # -- Pantheon of the Monarch -----------------------------------------------
    "Groal The Great":        ("Swamp Shaman", "shadow_18"),
    "Voltvyrm":               ("Zap Core Enemy", "coral_29"),
    "Raging Conchfly":        ("Driller A", "coral_11"),
    "Broodmother":            ("Slab Fly Broodmother", "slab_16b"),
    "Second Sentinel":        ("Song Knight", "hang_17b"),
    "Shakra":                 ("Mapper Spar NPC", "greymoor_08_mapper"),
    "Lace 2":                 ("Lace Boss2 New", "song_tower_01"),
    "Grand Mother Silk":      ("Silk Boss", "cradle_03"),

    # -- Pantheon of the Imperators --------------------------------------------
    "Bell Eater":             ("Giant Centipede Head", "bellway_centipede_arena"),
    "Lost Garmond":           ("Garmond Black Threaded Fighter", "coral_33"),
    "Crawfather":             ("Crawfather", "room_crowcourt_02"),
    "Tormented Trobbio":      ("Tormented Trobbio", "library_13"),
    "Pinstress":              ("Pinstress Boss", "peak_07"),
    "Palestag":               ("Cloverstag White Boss", "clover_19"),
    "Clover Dancers":         ("Dancer A", "clover_10"),
    "Shrine Guardian Seth":   ("Seth", "shellwood_22"),
    "Nyleth":                 ("Flower Queen Boss", "shellwood_11b_memory"),
    "Skarrsinger Karmelita":  ("SG_head", "bone_east_08_boss_golem"),
    "Crust King Khann":       ("Blue Assistant", "crawl_10"),

}

# Bosses Silksong does not name anywhere in its scenes - findboss.py finds zero
# GameObjects containing "zango", "signis", "gron", "khann", "gurr", "groal",
# "karmelita" or "watcher" in all 590 of them. These are the best fit from the enemies
# that no Pantheon uses, and they are written into the lists with the reasoning attached
# so a wrong one is visible and one edit away rather than silently wrong.
INFERRED = {
    # A slasher and a thrower in one room is the shape of a two-brother fight.
    "Forebrothers Signis and Gron": ("Dock Guard Slasher", "dock_09",
                                     "a slasher and a thrower share this room"),
    # Abyss-themed, and the Unravelled are what the void makes of people.
    "The Unravelled":               ("Abyss Mass", "bone_steel_servant",
                                     "abyss-themed, no better candidate"),
    "Father Of The Flame":          ("Coral King", "memory_coral_tower",
                                     "a memory boss of the right scale"),
    "Plasmified Zango":             ("Bone Hunter Trapper", "bone_east_18b",
                                     "a hunter duel, which is what Zango is"),
    "Watcher At The Edge":          ("Coral Warrior Grey", "coral_39",
                                     "unused boss-sized enemy; weak match"),
    "Gurr The Outcast":             ("Hunter Queen Boss", "memory_ant_queen",
                                     "unused boss-sized enemy; weak match"),
}


_names = None


def scene_key(bundle_name):
    """
    The name Silksong itself uses for a scene.

    Bundle files are lowercased and the Addressables catalog holds both spellings, so
    neither can be trusted: capitalising the first letter gets Weave_03 right and
    coral_judge_arena wrong, and 32 of 42 arena keys were wrong that way. names.json is
    harvested from the game's own TransitionPoint.targetScene and
    SceneAdditiveLoadConditional.sceneNameToLoad strings, which are by definition the
    names it passes to Addressables.
    """
    global _names
    if _names is None:
        if os.path.exists(NAMES):
            with open(NAMES, encoding="utf-8") as f:
                _names = json.load(f)
        else:
            raise SystemExit(f"{NAMES} is missing - run silksong_names.py first.")
    if not bundle_name:
        return bundle_name
    return _names.get(bundle_name.lower(), bundle_name)


def load_index():
    if not os.path.exists(INDEX):
        raise SystemExit(f"{INDEX} is missing - run silksong_index.py first.")
    with open(INDEX, encoding="utf-8") as f:
        return json.load(f)


def load_scenes():
    if not os.path.exists(SCENES):
        raise SystemExit(f"{SCENES} is missing - run silksong_scenes.py first.")
    with open(SCENES, encoding="utf-8") as f:
        return json.load(f)


def room_for(scene, scenes):
    """
    (room to load, sub-scene to force) for an arena.

    Silksong composes a room from a main scene plus additive pieces, and its bosses often
    live in a piece: bone_05_boss has no _SceneManager, no _Managers and no TileMap.
    Loading one of those directly puts the player in a void with no terrain - which is
    what being teleported out of bounds at the Bell Beast actually was. So an arena that
    is a piece names its room instead, and the piece alongside it.
    """
    info = scenes.get(scene)
    if info is None or info.get("standalone"):
        return scene, None
    parent = info.get("parent")
    if not parent:
        return scene, None      # a piece with no known room; flagged by the caller
    return parent, scene


def resolve(display, index, scenes):
    guess = INFERRED.get(display)
    if guess:
        obj, scene, why = guess
        for e in index.get(scene, []):
            if e["name"] == obj:
                return room_for(scene, scenes), obj, "GUESS: " + why
        return (scene, None), obj, f"GUESS ({why}) but '{obj}' not found in {scene}"

    """(scene, object, note) - note is empty when the mapping is a known one."""
    alias = ALIASES.get(display)
    if alias:
        obj, scene = alias
        for e in index.get(scene, []):
            if e["name"] == obj:
                room, sub = room_for(scene, scenes)
                if sub and not scenes.get(scene, {}).get("parent"):
                    return scene, obj, f"{scene} is a scene piece with no known room"
                return (room, sub), obj, ""
        return (scene, None), obj, f"'{obj}' not found in {scene}"

    # Nothing known: offer the closest names in the whole game, and leave it unresolved.
    every = {}
    for scene, es in index.items():
        for e in es:
            every.setdefault(e["name"], []).append((scene, e["hp"]))
    close = difflib.get_close_matches(display, every.keys(), n=3, cutoff=0.55)
    if close:
        best = close[0]
        scene, hp = max(every[best], key=lambda x: x[1])
        return room_for(scene, scenes), best, \
            f"guessed from the name; candidates: {', '.join(close)}"
    return None, None, "no candidate found"


def render(where, obj):
    room, sub = where
    left = scene_key(room) if not sub else f"{scene_key(room)} + {scene_key(sub)}"
    return f"{left} : {obj}"


def main():
    index = load_index()
    scenes = load_scenes()
    os.makedirs(OUT_DIR, exist_ok=True)

    resolved = unresolved = 0
    guessed = []
    made = []
    for n, (title, entries) in enumerate(PANTHEONS, 1):
        lines = [
            f"# {title}",
            "#",
            "# One entry per line:  Display Name = Room : Boss Object",
            "# or, when the boss lives in one of the room's additive pieces:",
            "#                      Display Name = Room + Piece : Boss Object",
            "# 'Bench' on its own is a rest stop between fights.",
            "# Lines starting with # are ignored; edit freely, no rebuild needed.",
            "#",
            "",
        ]
        for e in entries:
            if e == "Bench":
                lines.append("Bench")
                continue
            where, obj, note = resolve(e, index, scenes)
            if where and not note:
                lines.append(f"{e} = {render(where, obj)}")
                resolved += 1
            elif where and note.startswith("GUESS: "):
                # Written live, but labelled - the mapping is a judgement, not a lookup.
                lines.append(f"{e} = {render(where, obj)}    # {note}")
                resolved += 1
                guessed.append(e)
            elif where:
                lines.append(f"# UNRESOLVED  {e} = {render(where, obj)}    # {note}")
                unresolved += 1
            else:
                lines.append(f"# UNRESOLVED  {e}    # {note}")
                unresolved += 1
        path = os.path.join(OUT_DIR, f"pantheon{n}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        made.append(path)
        print(f"  pantheon{n}.txt  {title}")

    # Everything boss-sized the lists do not use, so the unresolved entries above can be
    # filled in by looking at one file instead of searching the game again.
    used = set()
    for p in made:
        for line in open(p, encoding="utf-8"):
            if line.startswith("#") or "=" not in line:
                continue
            rhs = line.split("=", 1)[1]
            sc, _, ob = rhs.partition(":")
            for part in sc.split("+"):
                used.add((part.strip().lower(), ob.strip()))

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
    if guessed:
        print(f"{len(guessed)} of those are inferred, not looked up, and are labelled "
              f"GUESS in the lists:")
        for g in guessed:
            print(f"    {g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
