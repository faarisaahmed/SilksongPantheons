#!/usr/bin/env python3
"""
Read a baked .boss back the way BossData.cs does, and sanity-check it.

Same rule as everything else here: the reader must land exactly on the end of the file,
and every collection index and sprite id a frame or a node references must be in range.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_baked import Reader

MAGIC = b"GGBS"
VERSION = 6


def verify(path):
    data = open(path, "rb").read()
    r = Reader(data)
    assert r.take(4) == MAGIC, "bad magic"
    v = r.i32()
    assert v == VERSION, f"version {v}"

    name = r.string(); scene = r.string()

    # --- shared collection table ---
    collections = []
    textures = []
    for _ in range(r.i32()):
        cname = r.string()
        tex = [r.string() for _ in range(r.i32())]
        textures += tex
        defs = []
        for _ in range(r.i32()):
            d = {"name": r.string(), "materialId": r.i32(), "texel": (r.f32(), r.f32())}
            for key, comp in (("positions", 3), ("uvs", 2), ("bounds", 3), ("untrimmed", 3)):
                n = r.i32()
                d[key] = [tuple(r.f32() for _ in range(comp)) for _ in range(n)]
            d["indices"] = [r.i32() for _ in range(r.i32())]
            defs.append(d)
        collections.append({"name": cname, "textures": tex, "defs": defs})

    # --- shared library table ---
    libraries = []
    bad_ids = 0
    bad_colls = 0
    for _ in range(r.i32()):
        lname = r.string()
        clips = []
        for _ in range(r.i32()):
            c = {"name": r.string(), "fps": r.f32(), "loopStart": r.i32(), "wrap": r.i32()}
            c["frames"] = []
            for _ in range(r.i32()):
                ci = r.i32(); sid = r.i32()
                r.boolean(); r.string(); r.i32(); r.f32()
                if ci < 0 or ci >= len(collections):
                    bad_colls += 1
                elif sid < 0 or sid >= len(collections[ci]["defs"]):
                    bad_ids += 1
                c["frames"].append(sid)
            clips.append(c)
        libraries.append({"name": lname, "clips": clips})

    # Audio ahead of the tree: write_fsm resolves clips as it walks, so the baker
    # serialises the tree into a scratch buffer and puts the table in front of it.
    nclips = r.i32()
    clip_names = []
    for _ in range(nclips):
        clip_names.append(r.string()); r.i32(); r.i32()

    # --- hierarchy + components (mirrors BossData.ReadNode) ---
    stats = {"nodes": 0, "boxes": 0, "circles": 0, "bodies": 0, "damagers": 0, "hp": None,
             "sprites": 0, "animators": 0, "fsms": 0, "states": 0, "actions": 0,
             "bad_index": 0, "names": []}

    def node():
        stats["nodes"] += 1
        nm = r.string(); layer = r.i32(); r.boolean()
        stats["names"].append(nm)
        [r.f32() for _ in range(3)]; [r.f32() for _ in range(4)]; [r.f32() for _ in range(3)]
        if r.boolean():
            stats["sprites"] += 1
            ci = r.i32(); sid = r.i32()
            [r.f32() for _ in range(4)]; [r.f32() for _ in range(3)]; r.i32()
            if ci < 0 or ci >= len(collections) or sid < 0 or sid >= len(collections[ci]["defs"]):
                stats["bad_index"] += 1
        if r.boolean():
            stats["animators"] += 1
            li = r.i32(); r.i32(); r.boolean()
            if li < 0 or li >= len(libraries):
                stats["bad_index"] += 1
        if r.boolean():
            stats["bodies"] += 1
            [r.f32() for _ in range(4)]; [r.i32() for _ in range(4)]
        nb = r.i32(); stats["boxes"] += nb
        for _ in range(nb):
            [r.f32() for _ in range(4)]; r.boolean(); r.boolean()
        nc = r.i32(); stats["circles"] += nc
        for _ in range(nc):
            r.f32(); r.f32(); r.f32(); r.boolean(); r.boolean()
        if r.boolean():
            hp = r.i32()
            if stats["hp"] is None: stats["hp"] = hp
        if r.boolean():
            stats["damagers"] += 1
            r.i32(); r.i32()
        for _ in range(r.i32()):
            stats["fsms"] += 1
            read_fsm()
        for _ in range(r.i32()): node()

    # --- FSM reader (mirrors FsmData.cs); FSMs now hang off individual nodes ---
    def named():
        r.boolean(); r.string(); r.string(); r.boolean(); r.boolean()
    def F(): named(); r.f32()
    def I(): named(); r.i32()
    def B(): named(); r.boolean()
    def S(): named(); r.string()
    def V2(): named(); r.f32(); r.f32()
    def V3(): named(); [r.f32() for _ in range(3)]
    def V4(): named(); [r.f32() for _ in range(4)]
    def OBJ(): named(); r.string(); r.string()   # typeName + baked resource name
    def GO(): named(); r.string()   # + baked prefab name
    def EN(): named(); r.string(); r.i32()
    def ARR():
        named(); r.i32(); r.string()
        for _ in range(r.i32()): r.f32()
        for _ in range(r.i32()): r.i32()
        for _ in range(r.i32()): r.boolean()
        for _ in range(r.i32()): r.string()
        for _ in range(r.i32()): [r.f32() for _ in range(4)]
    def lst(fn):
        for _ in range(r.i32()): fn()
    def strs(): return [r.string() for _ in range(r.i32())]
    def ints(): return [r.i32() for _ in range(r.i32())]
    def bools(): return [r.boolean() for _ in range(r.i32())]

    def action_data():
        names_ = strs(); strs(); bools(); bools(); ints(); ints()
        r.i32()                                  # unityObjectParams count
        lst(GO)
        for _ in range(r.i32()): r.i32(); GO()   # ownerDefaults
        for _ in range(r.i32()):                 # curves
            for _ in range(r.i32()): [r.f32() for _ in range(4)]
        for _ in range(r.i32()):                 # function calls
            r.string(); r.string()
            B(); F(); I(); GO(); OBJ(); S(); V2(); V3(); V4(); V4()
            OBJ(); OBJ(); V4(); EN(); ARR()
        r.i32()                                  # template controls
        for _ in range(r.i32()):                 # event targets
            r.i32(); B(); r.i32(); GO(); S(); B()
        for _ in range(r.i32()):                 # properties
            OBJ(); r.string(); r.string()
            B(); F(); I(); GO(); S(); V2(); V3(); V4(); V4()
            OBJ(); OBJ(); OBJ(); V4(); EN(); ARR(); r.boolean()
        for _ in range(r.i32()): r.i32(); F(); B()   # layout options
        lst(S); lst(OBJ)
        for _ in range(r.i32()):                 # fsmVars
            r.string(); r.string(); r.boolean(); r.i32()
            r.f32(); r.i32(); r.boolean(); r.string()
            [r.f32() for _ in range(4)]; ARR()
        for _ in range(r.i32()): ARR()
        lst(EN); lst(F); lst(I); lst(B); lst(V2); lst(V3); lst(V4); lst(V4); lst(V4)
        strs()
        r.take(r.i32())                          # byteData
        ints(); strs(); ints(); strs()
        ints(); strs(); ints(); ints()
        return names_

    fsm_names = []

    def read_fsm():
        fname = r.string(); r.string()
        fsm_names.append(fname)
        lst(F); lst(I); lst(B); lst(S); lst(V2); lst(V3); lst(V4); lst(V4); lst(V4)
        lst(GO); lst(OBJ)
        for _ in range(r.i32()): ARR()
        lst(EN)
        for _ in range(r.i32()): r.string(); r.boolean(); r.boolean()
        ns = r.i32(); stats["states"] += ns
        for _ in range(ns):
            r.string()
            for _ in range(r.i32()): r.string(); r.string()
            stats["actions"] += len(action_data())

    nprefab = r.i32()
    prefab_names = []
    for _ in range(nprefab):
        prefab_names.append(r.string())
        node()
    prefab_nodes = stats["nodes"]
    stats["nodes"] = 0

    node()

    leftover = len(data) - r.i
    print(os.path.basename(path))
    print(f"  boss            {name}   (from {scene})")
    for i, c in enumerate(collections):
        print(f"  collection[{i}]   {c['name']}: {len(c['defs'])} defs, pages {c['textures']}")
    for i, l in enumerate(libraries):
        print(f"  library[{i}]      {l['name']}: {len(l['clips'])} clips")
    empty_pos = sum(1 for c in collections for d in c["defs"] if not d["positions"])
    print(f"  sprites w/o geometry {empty_pos}")
    print(f"  frame ids out of range: {bad_ids} sprite, {bad_colls} collection")
    print(f"  node table refs out of range: {stats['bad_index']}")
    print(f"  hierarchy       {stats['nodes']} objects, {stats['sprites']} sprite(s), "
          f"{stats['animators']} animator(s)")
    print(f"                  {stats['bodies']} rigidbody, "
          f"{stats['boxes']} box / {stats['circles']} circle colliders")
    print(f"  hp / damagers   {stats['hp']} / {stats['damagers']}")
    print(f"  prefabs         {nprefab} {prefab_names[:6]} ({prefab_nodes} objects)")
    print(f"  fsm audio       {nclips} clips {clip_names[:4]}")
    print(f"  FSMs            {stats['fsms']} {fsm_names[:8]}")
    print(f"  states/actions  {stats['states']} / {stats['actions']}")
    print(f"  trailing bytes  {leftover}")

    d = os.path.dirname(path)
    missing = [t for t in textures if not os.path.exists(os.path.join(d, t + ".png"))]
    print(f"  texture files   {'all present' if not missing else 'MISSING ' + str(missing)}")

    ok = (leftover == 0 and bad_ids == 0 and bad_colls == 0
          and stats["bad_index"] == 0 and stats["sprites"] > 0 and not missing)
    print(f"  => {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        baked = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "SilksongGodhome", "Baked")
        args = [os.path.join(baked, f) for f in sorted(os.listdir(baked)) if f.endswith(".boss")]
    sys.exit(max(verify(a) for a in args))
