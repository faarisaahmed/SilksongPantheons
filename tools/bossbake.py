#!/usr/bin/env python3
"""
Bake a Hollow Knight boss into data the mod can rebuild.

A boss is a hierarchy, not a single sprite. Brooding Mawlek's body, head and two arms
are four separate objects, each with its own tk2dSprite and tk2dSpriteAnimator, and each
driven by its own FSMs - baking only the root gave an invisible Mawlek, because the root
sprite is the one part of it you never see. So every node in the tree carries its own
sprite id, animator and behaviour.

The parts share their art: all four Mawlek objects point at the one "Egg Guardian"
collection, as False Knight's do at "False Knight". Collections and animation libraries
are therefore written once into shared tables and referenced by index, which keeps a
four-part boss the same size on disk as a one-part boss.

Both structures are byte-identical between Hollow Knight's tk2d and Silksong's
TeamCherry.TK2D, so they rebuild as real tk2dSpriteCollectionData / tk2dSpriteAnimation
assets at runtime - which is also what gives Tk2dPlayAnimation actions in the FSMs
something real to drive.

    python3 bossbake.py GG_Gruz_Mother "Giant Fly"
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hkpath import hollow_knight_data, silksong_data
from ggformat import Writer
from hkassets import HKBuild
from monoread import script_ptr, HEADER, read_fields, MonoReader
from tk2dparse import Tk2dReader
from fsmvalidate import parse_fsm_component
import fsmbake
from fsmbake import write_fsm, FSM_MAGIC, FSM_VERSION
from audiobake import decode_clip

MAGIC = b"GGBS"
VERSION = 6

HK = hollow_knight_data()
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "SilksongGodhome", "Baked")


# HealthManager's serialised head, down to hp. AudioEvent is clip + 3 floats.
HEALTH_HEAD = [
    ("audioPlayerPrefab", "pptr"),
    ("inv_clip", "pptr"), ("inv_pmin", "f32"), ("inv_pmax", "f32"), ("inv_vol", "f32"),
    ("blockHitPrefab", "pptr"), ("strikeNailPrefab", "pptr"), ("slashImpactPrefab", "pptr"),
    ("fireballHitPrefab", "pptr"), ("sharpShadowImpactPrefab", "pptr"),
    ("corpseSplatPrefab", "pptr"),
    ("dsw_clip", "pptr"), ("dsw_pmin", "f32"), ("dsw_pmax", "f32"), ("dsw_vol", "f32"),
    ("dmg_clip", "pptr"), ("dmg_pmin", "f32"), ("dmg_pmax", "f32"), ("dmg_vol", "f32"),
    ("smallGeoPrefab", "pptr"), ("mediumGeoPrefab", "pptr"), ("largeGeoPrefab", "pptr"),
    ("hp", "i32"),
]

DAMAGE_HERO = [("damageDealt", "i32"), ("hazardType", "i32")]


def read_sprite(raw):
    """
    tk2dSprite's serialised fields, in tk2dBaseSprite declaration order.

    collectionInst and _cachedRenderer are not serialised (one is plain private, the
    other has no [SerializeField]), so _spriteId lands right after the colour and scale.
    tk2dSprite itself adds no serialised fields of its own. Verified byte-exact on all
    204 tk2dSprite/tk2dSpriteAnimator components across ten Godhome arenas.
    """
    r = MonoReader(raw, HEADER)
    r.string()
    d = {"collection": r.pptr(),
         "colorR": r.f32(), "colorG": r.f32(), "colorB": r.f32(), "colorA": r.f32(),
         "scaleX": r.f32(), "scaleY": r.f32(), "scaleZ": r.f32(),
         "spriteId": r.i32()}
    r.pptr()                                    # boxCollider2D
    for _ in range(r.i32()): r.pptr()           # polygonCollider2D
    for _ in range(r.i32()): r.pptr()           # edgeCollider2D
    r.pptr(); r.pptr()                          # boxCollider, meshCollider
    for _ in range(r.i32()):                    # meshColliderPositions
        r.f32(); r.f32(); r.f32()
    r.pptr()                                    # meshColliderMesh
    d["renderLayer"] = r.i32()
    if r.i != len(raw):
        raise ValueError(f"tk2dSprite consumed {r.i} of {len(raw)}")
    return d


def read_animator(raw):
    """tk2dSpriteAnimator: library, defaultClipId, playAutomatically."""
    r = MonoReader(raw, HEADER)
    r.string()
    d = {"library": r.pptr(), "defaultClipId": r.i32(), "playAutomatically": r.boolean()}
    r.align(4)
    if r.i != len(raw):
        raise ValueError(f"tk2dSpriteAnimator consumed {r.i} of {len(raw)}")
    return d


def class_of(scene, o, lvl):
    try:
        ms = scene.resolve(script_ptr(o.get_raw_data()), lvl)
        return ms.read_typetree().get("m_ClassName") if ms else None
    except Exception:
        return None


def bake(scene_name, boss_name, log=print):
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

    # Audio referenced by the boss's FSMs. These are the boss's own sounds - the buzz,
    # the charge, the slam - and they're the one referenced asset type that transfers
    # whole, so they're baked and re-linked by name on the other side.
    audio_seen = {}

    def resolve_audio(ptr):
        if not ptr or not ptr.get("m_PathID"):
            return ""
        key = (ptr.get("m_FileID"), ptr.get("m_PathID"))
        if key in audio_seen:
            return audio_seen[key]
        obj = scene.resolve(ptr, lvl)
        if obj is None or obj.type.name != "AudioClip":
            audio_seen[key] = ""
            return ""
        try:
            cname = obj.read_typetree().get("m_Name") or "clip"
        except Exception:
            cname = "clip"
        rname = "audio_" + "".join(c if c.isalnum() or c in "._-" else "_" for c in cname)
        decoded = decode_clip(obj)
        if decoded is None:
            log(f"    ! boss clip '{cname}' could not be decoded")
            audio_seen[key] = ""
            return ""
        pcm, count, rate = decoded
        apath = os.path.join(OUT, rname + ".pcm")
        if not os.path.exists(apath):
            os.makedirs(OUT, exist_ok=True)
            with open(apath, "wb") as af:
                af.write(pcm)
        audio_seen[key] = rname
        boss_clips[rname] = (count, rate)
        return rname

    boss_clips = {}
    fsmbake.ASSET_RESOLVER = resolve_audio

    # -- hierarchy -----------------------------------------------------
    #
    # Per assets file, not just the level: the prefabs a boss spawns - Gorb's needles,
    # every hit effect - live in shared assets files, and their own hierarchies have to
    # be walked the same way.
    file_maps = {}

    class Ctx:
        """The GameObject/Transform tables of one assets file."""

        def __init__(self, fname):
            self.file = fname
            self.go = {}
            self.tr = {}
            for o in scene.env.objects:
                if scene.file_of(o) != fname:
                    continue
                try:
                    if o.type.name == "GameObject":
                        self.go[o.path_id] = o.read_typetree()
                    elif o.type.name == "Transform":
                        self.tr[o.path_id] = o.read_typetree()
                except Exception:
                    pass
            self.g2t = {}
            for pid, d in self.tr.items():
                self.g2t[(d.get("m_GameObject") or {}).get("m_PathID")] = pid

    def ctx_for(fname):
        if fname not in file_maps:
            file_maps[fname] = Ctx(fname)
        return file_maps[fname]

    level = ctx_for(lvl)
    go, tr, g2t = level.go, level.tr, level.g2t

    boss_gid = None
    for pid, d in go.items():
        if d.get("m_Name") == boss_name:
            boss_gid = pid
            break
    if boss_gid is None:
        raise SystemExit(f"no GameObject named '{boss_name}' in {scene_name}")

    def components(ctx, gpid):
        out = []
        for c in (ctx.go.get(gpid, {}).get("m_Component") or []):
            ptr = c.get("component") if isinstance(c, dict) else None
            o = scene.resolve(ptr, ctx.file) if ptr else None
            if o is not None:
                out.append(o)
        return out

    def world_of(gpid):
        """
        Accumulated position and scale up the parent chain.

        A boss's own transform is local to whatever it's parented under, and in Hollow
        Knight that's often an offset container - False Knight and Brooding Mawlek both
        sit under a "Battle Scene" object about 14 units across and 32 up. Spawning at the
        local position puts them in the wrong part of the arena.
        """
        x = y = z = 0.0
        sx = sy = sz = 1.0
        cur = tr.get(g2t.get(gpid))
        guard = 0
        while cur is not None and guard < 32:
            guard += 1
            p = cur.get("m_LocalPosition") or {}
            sc_ = cur.get("m_LocalScale") or {}
            x += p.get("x", 0.0); y += p.get("y", 0.0); z += p.get("z", 0.0)
            sx *= sc_.get("x", 1.0); sy *= sc_.get("y", 1.0); sz *= sc_.get("z", 1.0)
            f = (cur.get("m_Father") or {}).get("m_PathID", 0)
            cur = tr.get(f) if f else None
        return (x, y, z), (sx, sy, sz)

    # -- shared tk2d tables --------------------------------------------
    #
    # Keyed by the asset the component points at, not by name: two collections can share
    # a name across files, and the parts of one boss always point at the same object.
    collections = []      # (name, [texture resource names], defs)
    coll_index = {}
    libraries = []        # (name, clips)
    lib_index = {}

    def parse_asset(obj, fn):
        raw = obj.get_raw_data()
        r = Tk2dReader(raw, HEADER)
        r.string()
        d = getattr(r, fn)()
        if r.i != len(raw):
            raise SystemExit(f"{fn} parse consumed {r.i} of {len(raw)} - layout is wrong")
        return d

    def register_collection(obj):
        key = (scene.file_of(obj), obj.path_id)
        if key in coll_index:
            return coll_index[key]
        coll = parse_asset(obj, "sprite_collection")
        cname = coll["spriteCollectionName"] or f"coll{len(collections)}"
        # Atlases are named after the collection, not the boss: bosses that share a
        # collection share its sheet, and those sheets are the biggest thing in the bake.
        # False Knight and its Head are one 9.7 MB atlas; so are Mato and Oro.
        coll_safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in cname)
        tex_names = []
        for i, tptr in enumerate(coll["textures"]):
            t = scene.resolve(tptr, scene.file_of(obj))
            if t is None:
                continue
            rname = f"boss_atlas_{coll_safe}_{i}"
            path = os.path.join(OUT, rname + ".png")
            if os.path.exists(path):
                tex_names.append(rname)
                continue
            try:
                os.makedirs(OUT, exist_ok=True)
                t.read().image.save(path, optimize=True)
                tex_names.append(rname)
                log(f"    atlas {rname}.png ({os.path.getsize(path)//1024} KB)")
            except Exception as e:
                log(f"    ! texture {i} of '{cname}' failed: {e!r}")
        idx = len(collections)
        collections.append((cname, tex_names, coll["spriteDefinitions"]))
        coll_index[key] = idx
        log(f"    collection[{idx}] '{cname}': {len(coll['spriteDefinitions'])} defs, "
            f"{len(tex_names)} page(s)")
        return idx

    def register_library(obj):
        key = (scene.file_of(obj), obj.path_id)
        if key in lib_index:
            return lib_index[key]
        anim = parse_asset(obj, "sprite_animation")
        idx = len(libraries)
        # tk2dSpriteAnimation is a MonoBehaviour, and a MonoBehaviour's m_Name is empty -
        # the readable name is on the GameObject hosting it.
        lname = f"lib{idx}"
        try:
            raw = obj.get_raw_data()
            fid, pid = struct.unpack_from("<i", raw, 0)[0], struct.unpack_from("<q", raw, 4)[0]
            host = scene.resolve({"m_FileID": fid, "m_PathID": pid}, scene.file_of(obj))
            if host is not None:
                lname = host.read_typetree().get("m_Name") or lname
        except Exception:
            pass
        # Each frame names its own collection. Usually that is the one collection the
        # library belongs to, but honouring the pointer costs nothing and an animation
        # that borrows a frame from another sheet then still resolves.
        lfile = scene.file_of(obj)
        for c in anim["clips"]:
            for fr in c["frames"]:
                fci = -1
                fobj = scene.resolve(fr["spriteCollection"], lfile)
                if fobj is not None:
                    try:
                        fci = register_collection(fobj)
                    except SystemExit as e:
                        log(f"    ! frame collection in '{lname}': {e}")
                fr["collIndex"] = fci
        libraries.append((lname, anim["clips"]))
        lib_index[key] = idx
        log(f"    library[{idx}] '{lname}': {len(anim['clips'])} clips")
        return idx

    # -- spawned prefabs ------------------------------------------------
    #
    # Gorb has no needles in his hierarchy: his Attacking FSM calls
    # SpawnObjectFromGlobalPool 26 times on one prefab, and that prefab lives in a shared
    # assets file. Without it he is defenseless. The same is true of every hit effect,
    # dust cloud and corpse a boss throws.
    #
    # So an FSM's GameObject parameters and variables are resolved here: if the pointer
    # is a prefab, its hierarchy is baked into a prefab table and the parameter records
    # the table entry's name. The C# side builds each prefab once, inactive, and hands it
    # to the FsmGameObject - after which PlayMaker's own spawn actions do the rest.
    prefabs = []          # (name, file, gpid)
    prefab_index = {}     # (file, path_id) -> name
    prefab_queue = []
    fsm_file = [lvl]      # which file the FSM currently being written came from

    def resolve_prefab(ptr):
        if not ptr or not ptr.get("m_PathID"):
            return ""
        obj = scene.resolve(ptr, fsm_file[0])
        if obj is None or obj.type.name != "GameObject":
            return ""

        # Only assets outside the level file. A pointer *into* the level is a reference to
        # a live scene object - the arena's Battle Scene, the boss's own Boss Holder, Mato
        # and Oro's shared Brothers container - and the FSM wants that object, not a copy
        # of it. Baking those as templates duplicated whole arenas: False Knight's bake
        # was 92 objects, most of them the arena he stands in, and Mato's included Oro.
        if scene.file_of(obj) == lvl:
            return ""

        key = (scene.file_of(obj), obj.path_id)
        if key in prefab_index:
            return prefab_index[key]

        pctx = ctx_for(scene.file_of(obj))
        if obj.path_id not in pctx.go:
            return ""

        # Bake from the top of the prefab, not from whichever object the pointer names.
        # A pointer into the middle of a prefab would otherwise lose its parent's
        # transform - and PlayMaker spawns the root.
        root = obj.path_id
        guard = 0
        while guard < 32:
            guard += 1
            t = pctx.tr.get(pctx.g2t.get(root))
            f = (t or {}).get("m_Father", {}).get("m_PathID", 0)
            if not f or f not in pctx.tr:
                break
            pg = (pctx.tr[f].get("m_GameObject") or {}).get("m_PathID")
            if not pg or pg not in pctx.go:
                break
            root = pg
        rkey = (pctx.file, root)
        if rkey in prefab_index:
            prefab_index[key] = prefab_index[rkey]
            return prefab_index[rkey]

        base = pctx.go[root].get("m_Name") or "prefab"
        name = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)
        n, taken = name, {p[0] for p in prefabs}
        i = 2
        while name in taken:
            name = f"{n}_{i}"
            i += 1
        prefab_index[rkey] = name
        prefab_index[key] = name
        prefabs.append((name, pctx.file, root))
        prefab_queue.append((name, pctx.file, root))
        return name

    fsmbake.GAMEOBJECT_RESOLVER = resolve_prefab

    # -- nodes ---------------------------------------------------------
    #
    # write_fsm resolves audio as it goes and the collection tables are filled in while
    # walking the tree, so the whole node tree is serialised into a scratch writer first
    # and the tables are written ahead of it afterwards.
    scratch = Writer()
    stats = {"sprites": 0, "animators": 0, "fsms": 0, "states": 0, "actions": 0, "nodes": 0}

    def write_node(w, ctx, gpid, is_root=False):
        d = ctx.go[gpid]
        t = ctx.tr.get(ctx.g2t.get(gpid)) or {}
        pos = t.get("m_LocalPosition") or {}
        rot = t.get("m_LocalRotation") or {}
        scl = t.get("m_LocalScale") or {}

        stats["nodes"] += 1
        w.string(d.get("m_Name") or "")
        w.i32(int(d.get("m_Layer") or 0))
        w.boolean(bool(d.get("m_IsActive", True)))

        # The root is written in world space - it has no parent on the Silksong side, so
        # a local position would be measured against the wrong origin. Children keep
        # their local transforms.
        if is_root:
            wp, ws = world_of(gpid)
            w.vec3(*wp)
            w.vec4(rot.get("x", 0.0), rot.get("y", 0.0), rot.get("z", 0.0), rot.get("w", 1.0))
            w.vec3(*ws)
        else:
            w.vec3(pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0))
            w.vec4(rot.get("x", 0.0), rot.get("y", 0.0), rot.get("z", 0.0), rot.get("w", 1.0))
            w.vec3(scl.get("x", 1.0), scl.get("y", 1.0), scl.get("z", 1.0))

        rb = None
        boxes = []
        circles = []
        health = None
        damage = None
        sprite = None
        animator = None
        node_fsms = []

        for o in components(ctx, gpid):
            n = o.type.name
            if n == "Rigidbody2D":
                rb = o.read_typetree()
            elif n == "BoxCollider2D":
                boxes.append(o.read_typetree())
            elif n == "CircleCollider2D":
                circles.append(o.read_typetree())
            elif n != "MonoBehaviour":
                continue
            else:
                raw2 = o.get_raw_data()
                cn = class_of(scene, o, ctx.file)
                if cn == "HealthManager":
                    try:
                        health = read_fields(raw2, HEALTH_HEAD)["hp"]
                    except Exception:
                        health = None
                elif cn == "DamageHero":
                    try:
                        damage = read_fields(raw2, DAMAGE_HERO)
                    except Exception:
                        damage = None
                elif cn == "tk2dSprite":
                    try:
                        sprite = read_sprite(raw2)
                    except Exception as e:
                        log(f"    ! tk2dSprite on '{d.get('m_Name')}' failed: {e!r}")
                elif cn == "tk2dSpriteAnimator":
                    try:
                        animator = read_animator(raw2)
                    except Exception as e:
                        log(f"    ! tk2dSpriteAnimator on '{d.get('m_Name')}' failed: {e!r}")
                elif cn == "PlayMakerFSM":
                    try:
                        fsm_file[0] = ctx.file
                        fsm, used = parse_fsm_component(raw2)
                        if used != len(raw2):
                            log(f"  ! FSM on '{d.get('m_Name')}' consumed {used} of "
                                f"{len(raw2)}; skipped")
                        else:
                            node_fsms.append((fsm, ctx.file))
                    except Exception as e:
                        log(f"  ! FSM parse on '{d.get('m_Name')}' failed: {e!r}")

        # Sprite. The collection index is what matters: the parts of a multi-part boss
        # all point at one collection and differ only in which sprite of it they show.
        ci = -1
        if sprite is not None:
            cobj = scene.resolve(sprite["collection"], ctx.file)
            if cobj is not None:
                try:
                    ci = register_collection(cobj)
                except SystemExit as e:
                    log(f"    ! collection for '{d.get('m_Name')}': {e}")
                    ci = -1
        w.boolean(ci >= 0)
        if ci >= 0:
            stats["sprites"] += 1
            w.i32(ci)
            w.i32(sprite["spriteId"])
            w.f32(sprite["colorR"]); w.f32(sprite["colorG"])
            w.f32(sprite["colorB"]); w.f32(sprite["colorA"])
            w.vec3(sprite["scaleX"], sprite["scaleY"], sprite["scaleZ"])
            w.i32(sprite["renderLayer"])

        li = -1
        if animator is not None:
            aobj = scene.resolve(animator["library"], ctx.file)
            if aobj is not None:
                try:
                    li = register_library(aobj)
                except SystemExit as e:
                    log(f"    ! library for '{d.get('m_Name')}': {e}")
                    li = -1
        w.boolean(li >= 0)
        if li >= 0:
            stats["animators"] += 1
            w.i32(li)
            w.i32(animator["defaultClipId"])
            w.boolean(animator["playAutomatically"])

        w.boolean(rb is not None)
        if rb is not None:
            w.f32(rb.get("m_Mass", 1.0))
            w.f32(rb.get("m_GravityScale", 1.0))
            w.f32(rb.get("m_LinearDrag", 0.0))
            w.f32(rb.get("m_AngularDrag", 0.0))
            w.i32(int(rb.get("m_BodyType", 0)))
            w.i32(int(rb.get("m_Constraints", 0)))
            w.i32(int(rb.get("m_CollisionDetection", 0)))
            w.i32(int(rb.get("m_Interpolate", 0)))

        w.i32(len(boxes))
        for bx in boxes:
            off = bx.get("m_Offset") or {}
            size = bx.get("m_Size") or {}
            w.vec2(off.get("x", 0.0), off.get("y", 0.0))
            w.vec2(size.get("x", 1.0), size.get("y", 1.0))
            w.boolean(bool(bx.get("m_IsTrigger", False)))
            w.boolean(bool(bx.get("m_Enabled", True)))

        w.i32(len(circles))
        for cc in circles:
            off = cc.get("m_Offset") or {}
            w.vec2(off.get("x", 0.0), off.get("y", 0.0))
            w.f32(cc.get("m_Radius", 0.5))
            w.boolean(bool(cc.get("m_IsTrigger", False)))
            w.boolean(bool(cc.get("m_Enabled", True)))

        w.boolean(health is not None)
        if health is not None:
            w.i32(int(health))

        w.boolean(damage is not None)
        if damage is not None:
            w.i32(int(damage["damageDealt"]))
            w.i32(int(damage["hazardType"]))

        w.i32(len(node_fsms))
        for f, ffile in node_fsms:
            stats["fsms"] += 1
            stats["states"] += len(f["states"])
            stats["actions"] += sum(len(s["actionData"]["actionNames"]) for s in f["states"])
            fsm_file[0] = ffile
            write_fsm(w, f)

        kids = []
        for c in ((ctx.tr.get(ctx.g2t.get(gpid)) or {}).get("m_Children") or []):
            cp = (ctx.tr.get(c["m_PathID"]) or {}).get("m_GameObject", {}).get("m_PathID")
            if cp and cp in ctx.go:
                kids.append(cp)
        w.i32(len(kids))
        for k in kids:
            write_node(w, ctx, k)

    write_node(scratch, level, boss_gid, is_root=True)

    # Prefabs, in discovery order, until the queue stops growing: a prefab's own FSMs can
    # name further prefabs (a needle that spawns an impact effect).
    prefab_bufs = []
    drained = 0
    while prefab_queue:
        name, pfile, pgid = prefab_queue.pop(0)
        pw = Writer()
        write_node(pw, ctx_for(pfile), pgid, is_root=False)
        prefab_bufs.append((name, pw.bytes()))
        drained += 1
        if drained > 256:
            log("    ! prefab queue over 256 entries; stopping")
            break
    if prefab_bufs:
        log(f"  prefabs: {len(prefab_bufs)} ({', '.join(n for n, _ in prefab_bufs[:6])}"
            f"{', ...' if len(prefab_bufs) > 6 else ''})")

    log(f"  {stats['nodes']} nodes: {stats['sprites']} sprite(s), "
        f"{stats['animators']} animator(s), {stats['fsms']} FSM(s) "
        f"({stats['states']} states, {stats['actions']} actions)")
    if stats["sprites"] == 0:
        raise SystemExit(f"'{boss_name}' has no tk2dSprite anywhere in its hierarchy")

    # -- write ---------------------------------------------------------
    w = Writer()
    w.buf += MAGIC
    w.i32(VERSION)
    w.string(boss_name)
    w.string(scene_name)

    w.i32(len(collections))
    for cname, tex_names, defs in collections:
        w.string(cname)
        w.i32(len(tex_names))
        for n in tex_names:
            w.string(n)
        w.i32(len(defs))
        for d in defs:
            w.string(d["name"])
            w.i32(d["materialId"])
            w.vec2(*d["texelSize"])
            for arr, wr in ((d["positions"], w.vec3), (d["uvs"], w.vec2),
                            (d["boundsData"], w.vec3), (d["untrimmedBoundsData"], w.vec3)):
                w.i32(len(arr))
                for v in arr:
                    wr(*v)
            w.i32(len(d["indices"]))
            for i in d["indices"]:
                w.i32(i)

    w.i32(len(libraries))
    for lname, clips in libraries:
        w.string(lname)
        w.i32(len(clips))
        for c in clips:
            w.string(c["name"])
            w.f32(c["fps"])
            w.i32(c["loopStart"])
            w.i32(c["wrapMode"])
            w.i32(len(c["frames"]))
            for fr in c["frames"]:
                w.i32(fr.get("collIndex", -1))
                w.i32(fr["spriteId"])
                w.boolean(fr["triggerEvent"])
                w.string(fr["eventInfo"] or "")
                w.i32(fr["eventInt"])
                w.f32(fr["eventFloat"])

    w.i32(len(boss_clips))
    for rname, (count, rate) in sorted(boss_clips.items()):
        w.string(rname)
        w.i32(count)
        w.i32(rate)
    if boss_clips:
        log(f"  audio: {len(boss_clips)} clips referenced by the FSMs")

    w.i32(len(prefab_bufs))
    for name, buf in prefab_bufs:
        w.string(name)
        w.buf += buf

    w.buf += scratch.bytes()

    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in boss_name)
    path = os.path.join(OUT, f"boss_{safe}.boss")
    os.makedirs(OUT, exist_ok=True)
    with open(path, "wb") as f:
        f.write(w.bytes())
    log(f"  -> {os.path.basename(path)} ({os.path.getsize(path)//1024} KB)")
    return path


def find_bosses(scene_name, log=print):
    """
    Objects in a scene that look like a boss: a HealthManager (so it can be killed) and a
    tk2dSpriteAnimator (so it has animation to bake).
    """
    build = HKBuild(HK)
    idx = build.find_scene(scene_name)
    if idx is None:
        return []
    scene = build.load_scene(idx)
    lvl = scene.level_file

    names = {}
    for g in scene.scene_objects("GameObject"):
        try:
            names[g.path_id] = g.read_typetree().get("m_Name")
        except Exception:
            pass

    have = {}
    for o in scene.scene_objects("MonoBehaviour"):
        cn = class_of(scene, o, lvl)
        if cn not in ("HealthManager", "tk2dSpriteAnimator"):
            continue
        gid = struct.unpack_from("<q", o.get_raw_data(), 4)[0]
        have.setdefault(gid, set()).add(cn)

    candidates = [gid for gid, kinds in have.items()
                  if {"HealthManager", "tk2dSpriteAnimator"} <= kinds]

    # Drop anything that already sits inside another candidate. False Knight's "Head" is
    # a child of "False Knight New" and is baked as part of it, so spawning it separately
    # would put a second, headless-boss's head in the arena.
    tr = {}
    for o in scene.scene_objects("Transform"):
        try:
            tr[o.path_id] = o.read_typetree()
        except Exception:
            pass
    g2t = {}
    for pid, d in tr.items():
        g2t[(d.get("m_GameObject") or {}).get("m_PathID")] = pid

    def ancestors(gid):
        out = set()
        cur = tr.get(g2t.get(gid))
        guard = 0
        while cur is not None and guard < 32:
            guard += 1
            f = (cur.get("m_Father") or {}).get("m_PathID", 0)
            if not f or f not in tr:
                break
            cur = tr[f]
            pg = (cur.get("m_GameObject") or {}).get("m_PathID")
            if pg:
                out.add(pg)
        return out

    cand_set = set(candidates)
    roots = [gid for gid in candidates if not (ancestors(gid) & cand_set)]

    out = []
    for gid in roots:
        n = names.get(gid)
        if n:
            out.append(n)
    return sorted(set(out))


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--find":
        for scene in sys.argv[2:]:
            print(f"{scene}: {find_bosses(scene)}")
        return 0

    if len(sys.argv) >= 2 and sys.argv[1] == "--auto":
        total = 0
        for scene in sys.argv[2:]:
            for b in find_bosses(scene):
                print(f"[{b} in {scene}]")
                try:
                    bake(scene, b)
                    total += 1
                except SystemExit as e:
                    print(f"  ! {e}")
        print(f"\nbaked {total} boss(es)")
        return 0

    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    print(f"[{sys.argv[2]} in {sys.argv[1]}]")
    bake(sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
