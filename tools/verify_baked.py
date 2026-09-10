#!/usr/bin/env python3
"""
Read a baked .scene back the way GodhomeData.cs does and sanity-check it.

The C# side uses a plain BinaryReader, so this mirrors it field for field: any
mismatch between writer and reader shows up here as a short read, a bad magic, or a
count that runs off the end - rather than as a crash inside the game.

    python3 verify_baked.py ../SilksongGodhome/Baked/GG_Atrium.scene
"""

import os
import struct
import sys

from ggformat import (MAGIC, FORMAT_VERSION, decompress, HAS_SPRITE, HAS_BOX, HAS_EDGE, HAS_POLY,
                      HAS_CAMLOCK, HAS_RESPAWN, HAS_HAZARD,
                      HAS_TRANSITION, HAS_SIMPLE, HAS_TK2D, HAS_FSM, HAS_COMPS, HAS_PHYS,
                      HAS_MESH, HAS_SEQDOOR, HAS_STATUE,
                      HAS_AUDIO)


class Reader:
    def __init__(self, data):
        self.d = data
        self.i = 0

    def take(self, n):
        if self.i + n > len(self.d):
            raise EOFError(f"short read at offset {self.i}: wanted {n}, "
                           f"{len(self.d) - self.i} left")
        b = self.d[self.i:self.i + n]
        self.i += n
        return b

    def i32(self):  return struct.unpack("<i", self.take(4))[0]
    def f32(self):  return struct.unpack("<f", self.take(4))[0]
    def i64(self):  return struct.unpack("<q", self.take(8))[0]
    def f64(self):  return struct.unpack("<d", self.take(8))[0]
    def boolean(self): return struct.unpack("<?", self.take(1))[0]

    def string(self):
        n = 0
        shift = 0
        while True:
            b = self.take(1)[0]
            n |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return self.take(n).decode("utf-8")


def read_fsm_blob(r):
    """Skip one baked FSM. Mirrors FsmData.ReadFsm, which is the point of the exercise."""
    def named():
        r.boolean(); r.string(); r.string(); r.boolean(); r.boolean()
    def F(): named(); r.f32()
    def I(): named(); r.i32()
    def B(): named(); r.boolean()
    def S(): named(); r.string()
    def V2(): named(); r.f32(); r.f32()
    def V3(): named(); [r.f32() for _ in range(3)]
    def V4(): named(); [r.f32() for _ in range(4)]
    def OBJ(): named(); r.string(); r.string()
    def GO(): named(); r.string()
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
        r.i32()
        lst(GO)
        for _ in range(r.i32()): r.i32(); GO()
        for _ in range(r.i32()):
            for _ in range(r.i32()): [r.f32() for _ in range(4)]
        for _ in range(r.i32()):
            r.string(); r.string()
            B(); F(); I(); GO(); OBJ(); S(); V2(); V3(); V4(); V4()
            OBJ(); OBJ(); V4(); EN(); ARR()
        r.i32()
        for _ in range(r.i32()):
            r.i32(); B(); r.i32(); GO(); S(); B()
        for _ in range(r.i32()):
            OBJ(); r.string(); r.string()
            B(); F(); I(); GO(); S(); V2(); V3(); V4(); V4()
            OBJ(); OBJ(); OBJ(); V4(); EN(); ARR(); r.boolean()
        for _ in range(r.i32()): r.i32(); F(); B()
        lst(S); lst(OBJ)
        for _ in range(r.i32()):
            r.string(); r.string(); r.boolean(); r.i32()
            r.f32(); r.i32(); r.boolean(); r.string()
            [r.f32() for _ in range(4)]; ARR()
        for _ in range(r.i32()): ARR()
        lst(EN); lst(F); lst(I); lst(B); lst(V2); lst(V3); lst(V4); lst(V4); lst(V4)
        strs()
        r.take(r.i32())
        ints(); strs(); ints(); strs()
        ints(); strs(); ints(); ints()
        return len(names_)

    r.string(); r.string()
    lst(F); lst(I); lst(B); lst(S); lst(V2); lst(V3); lst(V4); lst(V4); lst(V4)
    lst(GO); lst(OBJ)
    for _ in range(r.i32()): ARR()
    lst(EN)
    for _ in range(r.i32()): r.string(); r.boolean(); r.boolean()
    nstate = r.i32()
    nact = 0
    for _ in range(nstate):
        r.string()
        for _ in range(r.i32()): r.string(); r.string()
        nact += action_data()
    return nstate, nact


# Field kinds, mirroring compbake.py.
K_BOOL, K_I32, K_I64, K_F32, K_F64, K_STRING = 0, 1, 2, 3, 4, 5
K_VEC2, K_VEC3, K_VEC4, K_REF, K_ARRAY, K_INLINE = 6, 7, 8, 9, 10, 11


def read_value(r, kind, stats):
    if kind == K_BOOL:   r.boolean()
    elif kind == K_I32:  r.i32()
    elif kind == K_I64:  r.i64()
    elif kind == K_F32:  r.f32()
    elif kind == K_F64:  r.f64()
    elif kind == K_STRING: r.string()
    elif kind == K_VEC2: r.f32(); r.f32()
    elif kind == K_VEC3: [r.f32() for _ in range(3)]
    elif kind == K_VEC4: [r.f32() for _ in range(4)]
    elif kind == K_REF:
        oi = r.i32(); r.string(); asset = r.string()
        if oi >= 0: stats["ref_obj"] += 1
        elif asset: stats["ref_asset"] += 1
    elif kind == K_ARRAY:
        ek = r.i32()
        for _ in range(r.i32()): read_value(r, ek, stats)
    elif kind == K_INLINE:
        for _ in range(r.i32()):
            r.string(); read_value(r, r.i32(), stats)
    else:
        raise AssertionError(f"unknown field kind {kind}")


def read_behaviour(r, mask, stats, ncoll, nlib):
    """tk2d, FSMs and components for one object or prefab node."""
    if mask & HAS_TK2D:
        if r.boolean():
            ci = r.i32(); r.i32()
            [r.f32() for _ in range(4)]; [r.f32() for _ in range(3)]; r.i32()
            assert 0 <= ci < ncoll, f"collection index {ci} of {ncoll}"
            stats["tk2d_sprite"] += 1
        if r.boolean():
            li = r.i32(); r.i32(); r.boolean()
            assert 0 <= li < nlib, f"library index {li} of {nlib}"
            stats["tk2d_anim"] += 1
    if mask & HAS_FSM:
        for _ in range(r.i32()):
            ns, na = read_fsm_blob(r)
            stats["fsm"] += 1
            stats["fsm_states"] += ns
            stats["fsm_actions"] += na
    if mask & HAS_COMPS:
        for _ in range(r.i32()):
            r.string()
            for _ in range(r.i32()):
                r.string()
                read_value(r, r.i32(), stats)
            stats["comp"] += 1


def read_physics(r):
    if r.boolean():
        [r.f32() for _ in range(4)]; [r.i32() for _ in range(4)]
    for _ in range(r.i32()):
        [r.f32() for _ in range(4)]; r.boolean(); r.boolean()
    for _ in range(r.i32()):
        r.f32(); r.f32(); r.f32(); r.boolean(); r.boolean()
    for _ in range(r.i32()):
        r.f32(); r.f32()
        for _ in range(r.i32()):
            for _ in range(r.i32()): r.f32(); r.f32()
        r.boolean(); r.boolean()
    for _ in range(r.i32()):
        r.f32(); r.f32()
        for _ in range(r.i32()): r.f32(); r.f32()
        r.boolean(); r.boolean()


def read_tables(r, stats):
    """The behaviour layer's shared tables: collections, libraries, sounds, prefabs."""
    ncoll = r.i32()
    coll_defs = []
    for _ in range(ncoll):
        r.string()
        for _ in range(r.i32()): r.string()
        nd = r.i32()
        for _ in range(nd):
            r.string(); r.i32(); r.f32(); r.f32()
            for comp in (3, 2, 3, 3):
                for _ in range(r.i32() * comp): r.f32()
            for _ in range(r.i32()): r.i32()
        coll_defs.append(nd)

    nlib = r.i32()
    for _ in range(nlib):
        r.string()
        for _ in range(r.i32()):
            r.string(); r.f32(); r.i32(); r.i32()
            for _ in range(r.i32()):
                ci = r.i32(); sid = r.i32()
                r.boolean(); r.string(); r.i32(); r.f32()
                assert -1 <= ci < ncoll, f"frame collection {ci} of {ncoll}"
                if ci >= 0:
                    assert 0 <= sid < coll_defs[ci], f"frame sprite {sid} of {coll_defs[ci]}"

    # ScriptableObjects - MusicCue and friends - then the sound table.
    nasset = r.i32()
    for _ in range(nasset):
        r.string(); r.string()
        for _ in range(r.i32()):
            r.string(); read_value(r, r.i32(), stats)
        stats["asset"] += 1

    nmusic = 0
    for _ in range(r.i32()):
        r.string(); r.i32(); r.i32()
        if r.i32() == 1:
            nmusic += 1
    stats["music"] = nmusic

    nprefab = r.i32()
    for _ in range(nprefab):
        r.string()
        for _ in range(r.i32()):
            r.string(); r.i32(); r.i32(); r.boolean()
            [r.f32() for _ in range(3)]; [r.f32() for _ in range(4)]; [r.f32() for _ in range(3)]
            m = r.i32()
            read_physics(r)
            read_behaviour(r, m, stats, ncoll, nlib)
        stats["prefab"] += 1
    return ncoll, nlib, nprefab


def verify(path):
    on_disk = open(path, "rb").read()
    data = decompress(on_disk)
    r = Reader(data)

    magic = r.take(4)
    assert magic == MAGIC, f"bad magic {magic!r}"
    version = r.i32()
    assert version == FORMAT_VERSION, f"version {version} != {FORMAT_VERSION}"
    name = r.string()
    bounds = (r.f32(), r.f32())
    if r.boolean():
        r.i32(); r.f32()
        [r.f32() for _ in range(4)]; r.f32(); [r.f32() for _ in range(4)]
        for _ in range(3):
            for _ in range(r.i32()):
                [r.f32() for _ in range(4)]
    shaders = [r.string() for _ in range(r.i32())]
    clips = [(r.string(), r.i32(), r.i32()) for _ in range(r.i32())]

    pages = [r.string() for _ in range(r.i32())]

    nsprites0 = r.i32()
    nsprites = nsprites0
    sprites = []
    for _ in range(nsprites):
        s = {
            "name": r.string(),
            "page": r.i32(),
            "rect": (r.f32(), r.f32(), r.f32(), r.f32()),
            "pivot": (r.f32(), r.f32()),
            "ppu": r.f32(),
            "border": (r.f32(), r.f32(), r.f32(), r.f32()),
        }
        sprites.append(s)

    stats = {"sprite": 0, "box": 0, "edge": 0, "poly": 0, "inactive": 0,
             "camlock": 0, "respawn": 0, "hazard": 0, "transition": 0, "seqdoor": 0,
             "statue": 0, "audio": 0, "mesh": 0, "meshverts": 0,
             "tk2d_sprite": 0, "tk2d_anim": 0, "fsm": 0, "fsm_states": 0,
             "fsm_actions": 0, "comp": 0, "prefab": 0, "ref_obj": 0, "ref_asset": 0,
             "asset": 0, "music": 0, "body": 0, "circle": 0}

    ncoll, nlib, nprefab = read_tables(r, stats)

    nobj = r.i32()
    respawn_names = []
    exits = set()
    parents_ok = True
    for i in range(nobj):
        oname = r.string()
        parent = r.i32()
        r.i32()                    # layer
        if not r.boolean():
            stats["inactive"] += 1
        [r.f32() for _ in range(3)]   # pos
        [r.f32() for _ in range(4)]   # rot
        [r.f32() for _ in range(3)]   # scale
        mask = r.i32()

        if parent >= i:
            parents_ok = False      # must be strictly parent-before-child

        if mask & HAS_SPRITE:
            si = r.i32()
            sh = r.i32()
            assert -1 <= sh < len(shaders), f"object {i} '{oname}' shader index {sh} out of range"
            [r.f32() for _ in range(4)]
            r.i32(); r.i32()
            r.boolean(); r.boolean(); r.boolean()
            assert 0 <= si < nsprites, f"object {i} '{oname}' sprite index {si} out of range"
            stats["sprite"] += 1
        if mask & HAS_BOX:
            n = r.i32()
            for _ in range(n):
                [r.f32() for _ in range(4)]
                r.boolean(); r.boolean()
            stats["box"] += n
        if mask & HAS_EDGE:
            n = r.i32()
            for _ in range(n):
                r.f32(); r.f32()
                for _ in range(r.i32()):
                    r.f32(); r.f32()
                r.boolean(); r.boolean()
            stats["edge"] += n
        if mask & HAS_POLY:
            n = r.i32()
            for _ in range(n):
                r.f32(); r.f32()
                for _ in range(r.i32()):
                    for _ in range(r.i32()):
                        r.f32(); r.f32()
                r.boolean(); r.boolean()
            stats["poly"] += n
        if mask & HAS_CAMLOCK:
            [r.f32() for _ in range(4)]
            r.boolean(); r.boolean(); r.boolean()
            stats["camlock"] += 1
        if mask & HAS_RESPAWN:
            r.boolean()
            stats["respawn"] += 1
            respawn_names.append(oname)
        if mask & HAS_HAZARD:
            r.boolean()
            stats["hazard"] += 1
        if mask & HAS_SEQDOOR:
            r.string(); r.string()
            r.i32(); r.i32(); r.i32()
            stats["seqdoor"] += 1
        if mask & HAS_AUDIO:
            r.i32(); r.f32(); r.f32(); r.f32()
            r.boolean(); r.boolean(); r.boolean()
            stats["audio"] += 1
        if mask & HAS_STATUE:
            r.string(); r.string()
            stats["statue"] += 1
        if mask & HAS_MESH:
            vn = r.i32()
            for _ in range(vn):
                [r.f32() for _ in range(5)]
            tn = r.i32()
            for _ in range(tn * 3):
                r.i32()
            r.i32(); r.i32(); r.i32(); r.i32(); r.boolean()
            stats["mesh"] += 1
            stats["meshverts"] += vn
        if mask & HAS_SIMPLE:
            for _ in range(r.i32()):
                r.string()
        if mask & HAS_TRANSITION:
            tgt = r.string(); r.string()
            r.f32(); r.f32(); r.f32()
            for _ in range(6): r.boolean()
            stats["transition"] += 1
            if tgt: exits.add(tgt)

        if mask & HAS_PHYS:
            if r.boolean():
                [r.f32() for _ in range(4)]; [r.i32() for _ in range(4)]
                stats["body"] += 1
            for _ in range(r.i32()):
                r.f32(); r.f32(); r.f32(); r.boolean(); r.boolean()
                stats["circle"] += 1

        read_behaviour(r, mask, stats, ncoll, nlib)

    leftover = len(data) - r.i
    print(f"{os.path.basename(path)}")
    print(f"  on disk         {len(on_disk) // 1024} KB "
          f"({'deflated from ' + str(len(data) // 1024) + ' KB' if len(on_disk) != len(data) else 'uncompressed'})")
    print(f"  scene name      {name}")
    print(f"  format version  {version}")
    print(f"  scene bounds    {bounds[0]:.0f} x {bounds[1]:.0f} world units")
    print(f"  shaders         {len(shaders)}  {shaders}")
    print(f"  atlas pages     {len(pages)}  {pages}")
    print(f"  sprites         {nsprites}")
    print(f"  objects         {nobj}")
    print(f"  with sprite     {stats['sprite']}")
    print(f"  colliders       box {stats['box']} / edge {stats['edge']} / poly {stats['poly']}"
          f" / circle {stats['circle']}")
    print(f"  rigidbodies     {stats['body']}")
    print(f"  camera locks    {stats['camlock']}")
    print(f"  respawn markers {stats['respawn']}  {respawn_names}")
    print(f"  hazard markers  {stats['hazard']}")
    print(f"  transitions     {stats['transition']}  -> {sorted(exits)}")
    print(f"  pantheon doors  {stats['seqdoor']}")
    print(f"  boss statues    {stats['statue']}")
    print(f"  audio sources   {stats['audio']} on {len(clips)} clips")
    print(f"  meshes          {stats['mesh']} ({stats['meshverts']} verts)")
    print(f"  inactive        {stats['inactive']}")
    print(f"  parent ordering {'OK (parent always precedes child)' if parents_ok else 'BROKEN'}")
    print(f"  tk2d            {stats['tk2d_sprite']} sprites / {stats['tk2d_anim']} animators "
          f"on {ncoll} collections, {nlib} libraries")
    print(f"  components      {stats['comp']}")
    print(f"  FSMs            {stats['fsm']} ({stats['fsm_states']} states, "
          f"{stats['fsm_actions']} actions)")
    print(f"  prefabs         {nprefab}")
    print(f"  scriptables     {stats['asset']} (MusicCue and friends)")
    print(f"  music tracks    {stats['music']} (ADPCM)")
    print(f"  references      {stats['ref_obj']} in-scene, {stats['ref_asset']} baked assets")
    print(f"  trailing bytes  {leftover}")

    # Page files must exist next to the .scene, since the csproj globs them in.
    d = os.path.dirname(path)
    missing = [p for p in pages if not os.path.exists(os.path.join(d, p + ".png"))]
    print(f"  page files      {'all present' if not missing else 'MISSING ' + str(missing)}")

    # Rects must sit inside their page.
    try:
        from PIL import Image
        bad = 0
        dims = {p: Image.open(os.path.join(d, p + ".png")).size for p in pages}
        for s in sprites:
            w, h = dims[pages[s["page"]]]
            x, y, rw, rh = s["rect"]
            if x < 0 or y < 0 or x + rw > w + 0.5 or y + rh > h + 0.5:
                bad += 1
        print(f"  rects in bounds {'all OK' if not bad else f'{bad} OUT OF BOUNDS'}")
    except ImportError:
        pass

    ok = (leftover == 0 and parents_ok and not missing)
    print(f"  => {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:] or [os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "SilksongGodhome", "Baked", "GG_Atrium.scene")]
    sys.exit(max(verify(a) for a in args))
