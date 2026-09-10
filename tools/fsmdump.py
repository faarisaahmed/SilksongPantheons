#!/usr/bin/env python3
"""
Print a boss FSM's state graph out of Hollow Knight.

Diagnosing ported behaviour means reading the original graph: which state the FSM starts
in, what event moves it on, and which actions run there. Without this you are guessing at
why a boss sits still or launches itself out of the arena.

    python3 fsmdump.py GG_Mega_Moss_Charger "Mega Moss Charger"          # list FSMs
    python3 fsmdump.py GG_Mega_Moss_Charger "Mega Moss Charger" Control  # one graph
    python3 fsmdump.py GG_Nailmasters Oro "Control" --state "Jump"       # one state
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hkpath import hollow_knight_data, silksong_data
from hkassets import HKBuild
from monoread import script_ptr
from fsmvalidate import parse_fsm_component
from fsmparams import describe

HK = hollow_knight_data()


def fsms_on(scene_name, object_name):
    build = HKBuild(HK)
    idx = build.find_scene(scene_name)
    if idx is None:
        raise SystemExit(f"{scene_name} not in build")
    scene = build.load_scene(idx)
    lvl = scene.level_file

    names = {}
    for g in scene.scene_objects("GameObject"):
        try:
            names[g.path_id] = g.read_typetree().get("m_Name")
        except Exception:
            pass

    out = []
    for o in scene.scene_objects("MonoBehaviour"):
        raw = o.get_raw_data()
        ms = scene.resolve(script_ptr(raw), lvl)
        if ms is None or ms.read_typetree().get("m_ClassName") != "PlayMakerFSM":
            continue
        gid = struct.unpack_from("<q", raw, 4)[0]
        owner = names.get(gid) or ""
        if object_name and object_name.lower() not in owner.lower():
            continue
        try:
            fsm, used = parse_fsm_component(raw)
        except Exception as e:
            print(f"  ! {owner}: {e!r}")
            continue
        if used != len(raw):
            print(f"  ! {owner}/{fsm['name']}: consumed {used} of {len(raw)}")
        out.append((owner, fsm))
    return out


def show(fsm, owner, only_state=None):
    states = fsm["states"]
    print(f"\n=== {owner} / {fsm['name']}  ({len(states)} states) ===")
    # PlayMaker starts in the first state unless startState says otherwise.
    start = fsm.get("startState") or (states[0]["name"] if states else "?")
    print(f"start: {start}")
    for s in states:
        if only_state and only_state.lower() not in s["name"].lower():
            continue
        print(f"\n  [{s['name']}]")
        for line in describe(s["actionData"]):
            print(line)
        for t in s["transitions"]:
            ev = t["event"]
            ev = ev.get("name") if isinstance(ev, dict) else ev
            print(f"      -> {t['toState']}   on {ev or 'FINISHED'}")
    if fsm.get("globalTransitions"):
        print("\n  global transitions:")
        for t in fsm["globalTransitions"]:
            ev = t["event"]
            ev = ev.get("name") if isinstance(ev, dict) else ev
            print(f"      -> {t['toState']}   on {ev}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    scene, obj = sys.argv[1], sys.argv[2]
    want = None
    only_state = None
    rest = sys.argv[3:]
    if rest and not rest[0].startswith("--"):
        want = rest[0]
        rest = rest[1:]
    if "--state" in rest:
        only_state = rest[rest.index("--state") + 1]

    found = fsms_on(scene, obj)
    if not found:
        print(f"no FSMs on an object matching '{obj}' in {scene}")
        return 1
    if want is None:
        for owner, f in found:
            print(f"{owner:24} {f['name']:24} {len(f['states'])} states")
        return 0
    for owner, f in found:
        if want.lower() in f["name"].lower():
            show(f, owner, only_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
