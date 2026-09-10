#!/usr/bin/env python3
"""
Check every component in the Godhome arenas against its derived layout.

A layout is only usable if it reads a real component exactly - cursor on the last byte,
no more and no less. This reports, per component type, how many instances read exactly,
how many failed, and which types have no usable layout at all. Those are the ones that
have to be handled by hand.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hkpath import hollow_knight_data, silksong_data
from hkassets import HKBuild
from monoread import script_ptr
from typelayout import layout_of
from layoutread import parse

HK = hollow_knight_data()

SCENES = ["GG_Vengefly", "GG_Gruz_Mother", "GG_False_Knight", "GG_Mega_Moss_Charger",
          "GG_Hornet_1", "GG_Ghost_Gorb", "GG_Dung_Defender", "GG_Mage_Knight",
          "GG_Brooding_Mawlek", "GG_Nailmasters", "GG_Atrium"]


def main():
    scenes = sys.argv[1:] or SCENES
    build = HKBuild(HK)
    ok = collections.Counter()
    bad = collections.Counter()
    nolayout = collections.Counter()

    for sn in scenes:
        idx = build.find_scene(sn)
        if idx is None:
            continue
        scene = build.load_scene(idx)
        lvl = scene.level_file
        for o in scene.scene_objects("MonoBehaviour"):
            raw = o.get_raw_data()
            try:
                ms = scene.resolve(script_ptr(raw), lvl)
                cn = ms.read_typetree().get("m_ClassName") if ms else None
            except Exception:
                cn = None
            if not cn:
                continue
            lay = layout_of(cn)
            if lay is None:
                nolayout[cn] += 1
                continue
            try:
                _, exact = parse(raw, lay)
            except Exception:
                exact = False
            (ok if exact else bad)[cn] += 1

    total_ok = sum(ok.values())
    total_bad = sum(bad.values())
    total_no = sum(nolayout.values())

    print(f"{'component':38} {'exact':>6} {'wrong':>6}")
    for cn in sorted(set(ok) | set(bad), key=lambda c: -(ok[c] + bad[c])):
        flag = "" if not bad[cn] else "   <-- layout wrong"
        print(f"{cn:38} {ok[cn]:6} {bad[cn]:6}{flag}")

    if nolayout:
        print(f"\nno layout derivable ({total_no} instances):")
        for cn, n in nolayout.most_common():
            print(f"  {cn:36} {n}")

    tot = total_ok + total_bad + total_no
    print(f"\n{total_ok}/{tot} instances read byte-exactly "
          f"({total_bad} wrong, {total_no} no layout)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
