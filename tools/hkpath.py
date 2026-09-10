#!/usr/bin/env python3
"""
Find the player's own Hollow Knight and Silksong installs.

The tools read assets out of Hollow Knight, so they need to know where it is. Nothing is
shipped with the mod - you point it at your own copy.

Order: the HOLLOW_KNIGHT_DATA / SILKSONG_DATA environment variables, then the usual
install locations for Steam, GOG and itch on Windows, macOS and Linux.
"""
import os
import sys

_HK_LEAF = "Hollow Knight_Data"
_SS_LEAF = "Hollow Knight Silksong_Data"

_HOME = os.path.expanduser("~")

# Every place the two games normally land, per store and platform.
_ROOTS = [
    # Windows
    r"C:\Program Files (x86)\Steam\steamapps\common",
    r"C:\Program Files\Steam\steamapps\common",
    r"C:\GOG Games",
    r"C:\Program Files (x86)\GOG Galaxy\Games",
    os.path.join(_HOME, "AppData", "Roaming", "itch", "apps"),
    # macOS
    os.path.join(_HOME, "Library", "Application Support", "Steam", "steamapps", "common"),
    "/Applications",
    os.path.join(_HOME, "Applications"),
    os.path.join(_HOME, "Downloads"),
    # Linux
    os.path.join(_HOME, ".steam", "steam", "steamapps", "common"),
    os.path.join(_HOME, ".local", "share", "Steam", "steamapps", "common"),
    os.path.join(_HOME, "GOG Games"),
]

# Wineskin and .app wrappers bury the real data directory a long way down.
_INNER = [
    "",
    "Contents/Resources/Data",
    "Contents/SharedSupport/prefix/drive_c/GOG Games/Hollow Knight",
    "Contents/SharedSupport/prefix/drive_c/GOG Games/Hollow Knight Silksong",
    "Contents/SharedSupport/prefix/drive_c/Program Files/Hollow Knight",
    "drive_c/GOG Games/Hollow Knight",
]


def _candidates(leaf, names):
    for root in _ROOTS:
        if not os.path.isdir(root):
            continue
        for name in names:
            base = os.path.join(root, name)
            for inner in _INNER:
                p = os.path.join(base, inner, leaf) if inner else os.path.join(base, leaf)
                yield p
        # One level of "anything that looks right", for unusual folder names.
        try:
            for entry in os.listdir(root):
                low = entry.lower()
                if "hollow" not in low and "silksong" not in low:
                    continue
                for inner in _INNER:
                    base = os.path.join(root, entry)
                    p = os.path.join(base, inner, leaf) if inner else os.path.join(base, leaf)
                    yield p
        except OSError:
            pass


def _find(env, leaf, names, what):
    fromenv = os.environ.get(env)
    if fromenv:
        p = os.path.expanduser(fromenv)
        if os.path.isdir(p):
            return p
        raise SystemExit(f"{env} is set to '{p}', which is not a folder.")

    for p in _candidates(leaf, names):
        if os.path.isdir(p):
            return p

    raise SystemExit(
        f"\nCouldn't find {what}.\n\n"
        f"Set {env} to its data folder and try again. It is the folder called\n"
        f"'{leaf}', next to the game's executable. For example:\n\n"
        f"  Windows:  set {env}=C:\\GOG Games\\{names[0]}\\{leaf}\n"
        f"  macOS:    export {env}=\"$HOME/Library/Application Support/Steam/"
        f"steamapps/common/{names[0]}/{names[0]}.app/Contents/Resources/Data\"\n"
        f"  Linux:    export {env}=\"$HOME/.steam/steam/steamapps/common/{names[0]}/{leaf}\"\n")


def hollow_knight_data():
    """The Hollow Knight_Data folder of the player's own install."""
    return _find("HOLLOW_KNIGHT_DATA", _HK_LEAF, ["Hollow Knight"], "your Hollow Knight install")


def silksong_data():
    """The Hollow Knight Silksong_Data folder of the player's own install."""
    return _find("SILKSONG_DATA", _SS_LEAF, ["Hollow Knight Silksong"],
                 "your Silksong install")


def silksong_root():
    """The folder holding Silksong's executable - where BepInEx lives."""
    return os.path.dirname(silksong_data())


if __name__ == "__main__":
    for label, fn in (("Hollow Knight", hollow_knight_data), ("Silksong", silksong_data)):
        try:
            print(f"{label}: {fn()}")
        except SystemExit as e:
            print(f"{label}: {e}")
            sys.exit(1)
