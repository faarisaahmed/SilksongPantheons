#!/usr/bin/env python3
"""
Prove the FSM parser against real data.

The parser's correctness claim is simple and falsifiable: parse a PlayMakerFSM component
and the cursor must land exactly on the end of its byte buffer. A wrong field order or a
missed [SerializeField] shows up immediately as a short/long read, so a clean run over
thousands of FSMs is strong evidence the layouts are right.

    python3 fsmvalidate.py                 # every baked scene
    python3 fsmvalidate.py GG_Gruz_Mother
"""

import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hkpath import hollow_knight_data, silksong_data
from hkassets import HKBuild
from monoread import script_ptr, HEADER
from fsmparse import FsmReader

HK = hollow_knight_data()


def parse_fsm_component(raw):
    """Returns (fsm_dict, bytes_consumed)."""
    r = FsmReader(raw, HEADER)
    r.string()              # m_Name
    fsm = r.fsm()
    r.pptr()                # fsmTemplate
    r.boolean()             # eventHandlerComponentsAdded
    return fsm, r.i


def validate(build, scene_name):
    idx = build.find_scene(scene_name)
    if idx is None:
        return None
    scene = build.load_scene(idx)
    lvl = scene.level_file

    ok = bad = 0
    states = actions = 0
    failures = []

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

        try:
            fsm, used = parse_fsm_component(raw)
            if used != len(raw):
                bad += 1
                failures.append(f"{fsm['name']}: consumed {used} of {len(raw)}")
                continue
            ok += 1
            states += len(fsm["states"])
            actions += sum(len(s["actionData"]["actionNames"]) for s in fsm["states"])
        except Exception as e:
            bad += 1
            failures.append(f"<unparsed>: {type(e).__name__}: {str(e)[:60]}")

    return ok, bad, states, actions, failures


def main():
    build = HKBuild(HK)
    args = sys.argv[1:]
    if args:
        scenes = args
    else:
        baked = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "SilksongGodhome", "Baked")
        scenes = sorted(f[:-6] for f in os.listdir(baked) if f.endswith(".scene"))

    t_ok = t_bad = t_states = t_actions = 0
    for s in scenes:
        r = validate(build, s)
        if r is None:
            print(f"{s:24} not in build")
            continue
        ok, bad, states, actions, failures = r
        t_ok += ok; t_bad += bad; t_states += states; t_actions += actions
        flag = "" if bad == 0 else f"   <-- {bad} FAILED"
        print(f"{s:24} {ok:4} FSMs exact, {states:5} states, {actions:6} actions{flag}")
        for f in failures[:3]:
            print(f"     {f}")

    print()
    print(f"TOTAL: {t_ok} FSMs byte-exact, {t_bad} failed, "
          f"{t_states} states, {t_actions} actions")
    return 0 if t_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
