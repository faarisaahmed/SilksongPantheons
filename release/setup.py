#!/usr/bin/env python3
"""
Set up Silksong Godhome.

Run this once. It finds both games, extracts Godhome from your own copy of Hollow
Knight, and puts everything where Silksong will find it. Nothing here is downloaded and
nothing is sent anywhere - the Hollow Knight data never leaves your machine.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "tools")


def say(msg=""):
    print(msg, flush=True)


def step(n, total, msg):
    say(f"\n[{n}/{total}] {msg}")


def die(msg):
    say("\n" + "=" * 68)
    say("Setup stopped.")
    say("=" * 68)
    say(msg.rstrip())
    say()
    input("Press Enter to close.")
    sys.exit(1)


def main():
    say("=" * 68)
    say("  Silksong Godhome - setup")
    say("=" * 68)
    say()
    say("You need both Hollow Knight and Silksong installed, and BepInEx")
    say("already working in Silksong.")

    total = 5

    # 1 -----------------------------------------------------------------
    step(1, total, "Checking Python packages...")
    missing = []
    for mod, pkg in (("UnityPy", "UnityPy"), ("PIL", "Pillow")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        say(f"      Installing: {', '.join(missing)}")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", *missing])
        if r.returncode != 0:
            die("Couldn't install the Python packages this needs.\n\n"
                f"Try running this yourself:\n\n"
                f"  {sys.executable} -m pip install --user {' '.join(missing)}")
    say("      OK")

    # 2 -----------------------------------------------------------------
    step(2, total, "Looking for your games...")
    sys.path.insert(0, TOOLS)
    try:
        from hkpath import hollow_knight_data, silksong_data
        hk = hollow_knight_data()
        ss = silksong_data()
    except SystemExit as e:
        die(str(e))
    say(f"      Hollow Knight: {hk}")
    say(f"      Silksong:      {ss}")

    ss_root = os.path.dirname(ss)
    plugins = os.path.join(ss_root, "BepInEx", "plugins")
    if not os.path.isdir(os.path.join(ss_root, "BepInEx")):
        die("Silksong is there, but BepInEx is not installed in it.\n\n"
            "Install BepInEx first, run Silksong once so it creates its folders,\n"
            "then run this setup again.\n\n"
            f"Expected to find: {os.path.join(ss_root, 'BepInEx')}")

    # 3 -----------------------------------------------------------------
    step(3, total, "Extracting Godhome from your Hollow Knight (5-30 minutes)...")
    say("      This is the slow part. It reads Hollow Knight's rooms, art, sounds")
    say("      and boss logic, and converts them into something Silksong can load.")
    say("      Leave it running.")
    say()
    baked = os.path.join(HERE, "Godhome")
    r = subprocess.run([sys.executable, "-u", os.path.join(TOOLS, "extract_godhome.py"),
                        "--out", baked],
                       cwd=TOOLS)
    if r.returncode != 0:
        die("Extraction failed. The messages above say why.")

    # 4 -----------------------------------------------------------------
    step(4, total, "Installing into Silksong...")
    dest = os.path.join(plugins, "SilksongGodhome")
    os.makedirs(dest, exist_ok=True)

    dll = os.path.join(HERE, "SilksongGodhome.dll")
    if not os.path.isfile(dll):
        die(f"SilksongGodhome.dll is missing from {HERE}.\n"
            "Unzip the whole download and run setup from inside it.")
    shutil.copy2(dll, os.path.join(dest, "SilksongGodhome.dll"))

    dest_data = os.path.join(dest, "Godhome")
    if os.path.isdir(dest_data):
        shutil.rmtree(dest_data)
    shutil.copytree(baked, dest_data)

    n = len([f for f in os.listdir(dest_data) if f.endswith(".scene")])
    size = sum(os.path.getsize(os.path.join(dest_data, f)) for f in os.listdir(dest_data))
    say(f"      {n} rooms, {size / (1024 * 1024):.0f} MB -> {dest}")

    # 5 -----------------------------------------------------------------
    step(5, total, "Done.")
    say()
    say("=" * 68)
    say("  Ready. Start Silksong and pick GODSEEKER on the play-mode menu.")
    say("=" * 68)
    say()
    say("Read this bit before you play:")
    say()
    say("  This is an unfinished mod and development has stopped. Godhome's")
    say("  rooms, doors, benches, statues, Pantheon doors and music work. The")
    say("  boss fights do not play through properly - that is the part that")
    say("  was never finished.")
    say()
    say("  If something goes wrong, the log at")
    say(f"  {os.path.join(ss_root, 'BepInEx', 'LogOutput.log')}")
    say("  says what happened.")
    say()
    input("Press Enter to close.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\nCancelled.")
    except Exception as e:
        die(f"Something unexpected went wrong:\n\n  {e!r}")
