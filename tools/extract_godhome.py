#!/usr/bin/env python3
"""
Bake Hollow Knight's Godhome scenes into data the Silksong mod can rebuild at runtime.

Silksong is Unity 6000.0.50f1 and Hollow Knight is Unity 2020.2.2f1, so HK's compiled
scenes can't be loaded by Silksong at any price - AssetBundles are version-locked.
What *is* portable is the description of a scene: a transform hierarchy, which sprite
each renderer draws, and where the colliders are. This tool writes that description,
plus the atlas pages the sprites live on, into SilksongGodhome/Baked/. The csproj
embeds that directory into the DLL.

Usage:
    python3 extract_godhome.py                     # bake the default scene set
    python3 extract_godhome.py --scenes GG_Atrium  # bake specific scenes
    python3 extract_godhome.py --list              # show every Godhome scene in the build
    python3 extract_godhome.py --all               # bake all 78 of them

The Hollow Knight path defaults to the GOG/Wineskin install; override with --hk.
"""

import argparse
import collections
import os
import struct
import sys

from ggformat import (Writer, MAGIC, FORMAT_VERSION,
                      HAS_SPRITE, HAS_BOX, HAS_EDGE, HAS_POLY,
                      HAS_CAMLOCK, HAS_RESPAWN, HAS_HAZARD, HAS_TRANSITION,
                      HAS_SIMPLE, HAS_MESH, HAS_SEQDOOR, HAS_STATUE, HAS_AUDIO,
                      HAS_TK2D, HAS_FSM, HAS_COMPS, HAS_PHYS)
from assetreg import AssetRegistry
from typelayout import layout_of
from layoutread import parse as parse_layout
from compbake import write_component
from fsmvalidate import parse_fsm_component
import fsmbake
from fsmbake import write_fsm
from bossbake import read_sprite, read_animator
from prefabbake import write_prefab, write_behaviour
from monoread import (script_ptr, read_fields,
                      CAMERA_LOCK_AREA, RESPAWN_MARKER, HAZARD_RESPAWN_MARKER,
                      TK2D_TILEMAP, SCENE_MANAGER, TRANSITION_POINT,
                      BOSS_SEQUENCE_DOOR_FULL, BOSS_STATUE_HEAD, BOSS_SCENE_HEAD)
from hkassets import HKBuild
from spritebake import SpriteBaker
from repack import repack
from meshbake import decode_mesh
from audiobake import decode_clip, TARGET_RATE
from monoread import MonoReader, HEADER
import sequences as seqtool
from hkpath import hollow_knight_data

DEFAULT_HK = hollow_knight_data()

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(os.path.dirname(HERE), "SilksongGodhome", "Baked")

# The hub first - it's the scene you actually stand in.
# The hub, plus every arena in Pantheon of the Master so that door leads somewhere.
# Every scene the hub's own transitions lead to, so no door in the hub is a dead end.
HUB_SCENES = ["GG_Atrium", "GG_Workshop", "GG_Atrium_Roof", "GG_Blue_Room",
              "GG_Land_of_Storms"]

TIER1_ARENAS = [
    "GG_Vengefly", "GG_Gruz_Mother", "GG_False_Knight", "GG_Mega_Moss_Charger",
    "GG_Hornet_1", "GG_Spa", "GG_Ghost_Gorb", "GG_Dung_Defender",
    "GG_Mage_Knight", "GG_Brooding_Mawlek", "GG_Engine", "GG_Nailmasters",
]

DEFAULT_SCENES = HUB_SCENES + TIER1_ARENAS

# Hollow Knight components that exist in Silksong under the same name and carry no
# serialised fields worth configuring - attaching the bare component is the whole
# behaviour. RestBench, for instance, only tells HeroController it is near a bench.
SIMPLE_COMPONENTS = [
    "RestBench",
    "NonBouncer",
    "NonSlider",
    "NonThunker",
    "Roof",
]


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------
# Scene graph
# ----------------------------------------------------------------------

def build_hierarchy(scene):
    """
    Walk the level's Transforms into a flat, parent-before-child ordered list.

    Baking in that order means the C# side can create each object and immediately
    parent it, with no fix-up pass.
    """
    transforms = {}
    for t in scene.scene_objects("Transform"):
        try:
            transforms[t.path_id] = t.read_typetree()
        except Exception:
            continue
    # RectTransforms are Transforms too, and Godhome's UI bits use them.
    for t in scene.scene_objects("RectTransform"):
        if t.path_id not in transforms:
            try:
                transforms[t.path_id] = t.read_typetree()
            except Exception:
                continue

    children = {pid: [] for pid in transforms}
    roots = []
    for pid, d in transforms.items():
        parent = (d.get("m_Father") or {}).get("m_PathID", 0)
        if parent and parent in transforms:
            children[parent].append(pid)
        else:
            roots.append(pid)

    # Deterministic output: same input build always bakes byte-identical data.
    roots.sort()
    for v in children.values():
        v.sort()

    order = []
    index_of = {}
    stack = [(pid, -1) for pid in reversed(roots)]
    while stack:
        pid, parent_idx = stack.pop()
        idx = len(order)
        index_of[pid] = idx
        order.append((pid, transforms[pid], parent_idx))
        for c in reversed(children[pid]):
            stack.append((c, idx))
    return order, transforms


def collect_components(scene, go_ptr, from_file):
    """Map component type name -> typetree for one GameObject."""
    go = scene.resolve(go_ptr, from_file)
    if go is None:
        return None, {}, {}, []
    try:
        god = go.read_typetree()
    except Exception:
        return None, {}, {}, []

    comps = {}
    monos = {}
    mono_list = []          # (className, raw) in component order, duplicates kept
    for c in (god.get("m_Component") or []):
        ptr = c.get("component") if isinstance(c, dict) else None
        if ptr is None and isinstance(c, dict):
            ptr = c.get("second")
        obj = scene.resolve(ptr, from_file) if ptr else None
        if obj is None:
            continue
        name = obj.type.name
        if name in ("SpriteRenderer", "BoxCollider2D", "EdgeCollider2D", "PolygonCollider2D",
                    "MeshFilter", "MeshRenderer", "AudioSource",
                    "Rigidbody2D", "CircleCollider2D"):
            # A list, not a single value: Hollow Knight's tilemap chunks carry several
            # EdgeCollider2Ds on one GameObject (Chunk 1 4 has four), and keying by type
            # name alone silently kept one and dropped the rest - which is most of
            # GG_Atrium's floor.
            try:
                comps.setdefault(name, []).append(obj.read_typetree())
            except Exception:
                pass
        elif name == "MonoBehaviour":
            # Hollow Knight ships no type trees for MonoBehaviours, so these are parsed
            # from raw bytes against hand-written field specs (see monoread.py). The
            # script pointer itself sits at a fixed offset and is always readable.
            try:
                raw = obj.get_raw_data()
                ms = scene.resolve(script_ptr(raw), from_file)
                if ms is not None:
                    cn = ms.read_typetree().get("m_ClassName")
                    monos[cn] = raw
                    mono_list.append((cn, raw))
            except Exception:
                pass
    return god, comps, monos, mono_list


def find_scene_bounds(scene, log):
    """
    (width, height) in world units, from the scene's tk2dTileMap.

    CameraController does `sceneWidth = tilemap.width; xLimit = sceneWidth - 14.6f`, so
    these are the numbers that decide where the camera stops. Falls back to Hollow
    Knight's default tilemap size if the scene somehow has none.
    """
    lvl = scene.level_file
    for o in scene.scene_objects("MonoBehaviour"):
        try:
            raw = o.get_raw_data()
            ms = scene.resolve(script_ptr(raw), lvl)
            if ms is None or ms.read_typetree().get("m_ClassName") != "tk2dTileMap":
                continue
            f = read_fields(raw, TK2D_TILEMAP)
            log(f"    scene bounds {f['width']} x {f['height']} (from tk2dTileMap)")
            return float(f["width"]), float(f["height"])
        except Exception:
            continue
    log("    ! no tk2dTileMap found; falling back to 128 x 128 bounds")
    return 128.0, 128.0


def find_scene_lighting(scene, log):
    """
    Hollow Knight's per-room colour grading, from the scene's own SceneManager.

    Silksong's CustomSceneManager kept all of these fields under the same names, so the
    values copy straight across. Without them Godhome inherits the donor room's grading -
    which is why an un-lit rebuild comes out sepia instead of Godhome's cold blue.
    """
    lvl = scene.level_file
    for o in scene.scene_objects("MonoBehaviour"):
        try:
            raw = o.get_raw_data()
            ms = scene.resolve(script_ptr(raw), lvl)
            if ms is None or ms.read_typetree().get("m_ClassName") != "SceneManager":
                continue
            f = read_fields(raw, SCENE_MANAGER)
            log(f"    lighting: saturation {f['saturation']:.2f}, darkness {f['darknessLevel']}, "
                f"mapZone {f['mapZone']}")
            return f
        except Exception as e:
            log(f"    ! SceneManager unparsed: {e!r}")
            continue
    log("    ! no SceneManager in this scene; it will inherit the donor room's grading")
    return None


def bake_scene(build, name, out_dir, verbose=False, no_repack=False):
    idx = build.find_scene(name)
    if idx is None:
        log(f"  ! '{name}' is not in this Hollow Knight build; skipping.")
        return None

    log(f"  loading level{idx} ({name}) ...")
    scene = build.load_scene(idx)
    log(f"    {scene.file_count} files in its dependency closure")

    order, transforms = build_hierarchy(scene)
    log(f"    {len(order)} transforms")

    baker = SpriteBaker(scene)
    lvl = scene.level_file

    # Scene dimensions come from the tk2dTileMap, exactly where CameraController reads
    # them (sceneWidth/sceneHeight, and xLimit/yLimit derived from those). Without this
    # the rebuilt scene inherits the donor room's bounds and the camera is wrong.
    bounds = find_scene_bounds(scene, log)
    lighting = find_scene_lighting(scene, log)

    shader_index = {}
    shader_names = []

    # Sprites drawn with a screen-blend material. Their pixels get premultiplied by alpha
    # during repack so that additive blending reproduces the look - see repack.premultiply.
    screen_sprites = set()

    # Textures used by mesh materials (the tilemap's tile atlas, effect sheets). These
    # are not sprites, so they get appended to the page list after repacking rather than
    # going through the sprite packer.
    mesh_tex_index = {}
    mesh_tex_objs = []

    # Audio clips, keyed by identity so a clip used by several sources is decoded once.
    # Resource names are derived from the clip name, so clips shared across scenes also
    # share one file on disk.
    audio_index = {}
    audio_clips = []          # (resource_name, pcm_bytes, sample_count, rate)

    def sanitize(n):
        return "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in (n or "clip"))

    def audio_clip_of(src):
        ptr = src.get("m_audioClip")
        clip = scene.resolve(ptr, lvl) if ptr else None
        if clip is None:
            return -1
        key = (scene.file_of(clip), clip.path_id)
        if key in audio_index:
            return audio_index[key]
        try:
            cname = clip.read_typetree().get("m_Name") or "clip"
        except Exception:
            cname = "clip"
        decoded = decode_clip(clip)
        if decoded is None:
            log(f"    ! audio clip '{cname}' could not be decoded")
            audio_index[key] = -1
            return -1
        pcm, count, rate = decoded
        i = len(audio_clips)
        audio_clips.append(("audio_" + sanitize(cname), pcm, count, rate))
        audio_index[key] = i
        return i

    def mesh_texture_of(mr):
        mats = mr.get("m_Materials") or []
        if not mats:
            return -1
        mat = scene.resolve(mats[0], lvl)
        if mat is None:
            return -1
        try:
            md = mat.read_typetree()
        except Exception:
            return -1
        for entry in ((md.get("m_SavedProperties") or {}).get("m_TexEnvs") or []):
            try:
                k, v = entry
            except (TypeError, ValueError):
                continue
            if k != "_MainTex":
                continue
            t = scene.resolve((v or {}).get("m_Texture"), scene.file_of(mat))
            if t is None:
                return -1
            key = (scene.file_of(t), t.path_id)
            if key not in mesh_tex_index:
                mesh_tex_index[key] = len(mesh_tex_objs)
                mesh_tex_objs.append(t)
            return mesh_tex_index[key]
        return -1

    def shader_of(sr):
        """Shader name for a SpriteRenderer's first material, as a table index."""
        mats = sr.get("m_Materials") or []
        if not mats:
            return -1
        mat = scene.resolve(mats[0], lvl)
        if mat is None:
            return -1
        try:
            md = mat.read_typetree()
        except Exception:
            return -1
        sh = scene.resolve(md.get("m_Shader"), scene.file_of(mat))
        if sh is None:
            return -1
        try:
            nm = (sh.read_typetree().get("m_ParsedForm") or {}).get("m_Name")
        except Exception:
            nm = None
        if not nm:
            return -1
        if nm not in shader_index:
            shader_index[nm] = len(shader_names)
            shader_names.append(nm)
        return shader_index[nm]

    objects = []
    order_to_obj = {}     # index in `order` -> index in `objects`
    go_to_obj = {}        # GameObject pathID -> index in `objects`
    counts = {"sprite": 0, "box": 0, "edge": 0, "poly": 0,
              "camlock": 0, "respawn": 0, "hazard": 0, "transition": 0, "simple": 0, "mesh": 0, "seqdoor": 0, "statue": 0, "audio": 0}

    for order_i, (pid, tdata, parent_idx) in enumerate(order):
        god, comps, monos, mono_list = collect_components(scene, tdata.get("m_GameObject"), lvl)
        if god is None:
            # Skipping without remapping would shift every later parent index, so the
            # parent is resolved through order_to_obj rather than used directly.
            continue

        pos = tdata.get("m_LocalPosition") or {}
        rot = tdata.get("m_LocalRotation") or {}
        scl = tdata.get("m_LocalScale") or {}

        rec = {
            "name": god.get("m_Name") or "",
            "parent": order_to_obj.get(parent_idx, -1) if parent_idx >= 0 else -1,
            "layer": int(god.get("m_Layer") or 0),
            "active": bool(god.get("m_IsActive", True)),
            "pos": (pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0)),
            "rot": (rot.get("x", 0.0), rot.get("y", 0.0), rot.get("z", 0.0), rot.get("w", 1.0)),
            "scale": (scl.get("x", 1.0), scl.get("y", 1.0), scl.get("z", 1.0)),
            "mask": 0,
            "monos": mono_list,
            "go_pid": (tdata.get("m_GameObject") or {}).get("m_PathID"),
        }

        srs = comps.get("SpriteRenderer") or []
        sr = srs[0] if srs else None
        if sr is not None:
            sprite_obj = scene.resolve(sr.get("m_Sprite"), lvl)
            sidx = baker.add(sprite_obj) if sprite_obj is not None else -1
            if sidx >= 0:
                sh_idx = shader_of(sr)
                if sh_idx >= 0 and "Screen" in shader_names[sh_idx]:
                    screen_sprites.add(sidx)
                col = sr.get("m_Color") or {}
                rec["mask"] |= HAS_SPRITE
                rec["sprite"] = {
                    "index": sidx,
                    "shader": sh_idx,
                    "color": (col.get("r", 1.0), col.get("g", 1.0), col.get("b", 1.0), col.get("a", 1.0)),
                    "order": int(sr.get("m_SortingOrder") or 0),
                    "layer_id": int(sr.get("m_SortingLayerID") or 0),
                    "flipX": bool(sr.get("m_FlipX", False)),
                    "flipY": bool(sr.get("m_FlipY", False)),
                    "enabled": bool(sr.get("m_Enabled", True)),
                }
                counts["sprite"] += 1

        boxes = []
        for box in (comps.get("BoxCollider2D") or []):
            off = box.get("m_Offset") or {}
            size = box.get("m_Size") or {}
            boxes.append({
                "offset": (off.get("x", 0.0), off.get("y", 0.0)),
                "size": (size.get("x", 1.0), size.get("y", 1.0)),
                "trigger": bool(box.get("m_IsTrigger", False)),
                "enabled": bool(box.get("m_Enabled", True)),
            })
        if boxes:
            rec["mask"] |= HAS_BOX
            rec["box"] = boxes
            counts["box"] += len(boxes)

        edges = []
        for edge in (comps.get("EdgeCollider2D") or []):
            pts = [(p.get("x", 0.0), p.get("y", 0.0)) for p in (edge.get("m_Points") or [])]
            if not pts:
                continue
            off = edge.get("m_Offset") or {}
            edges.append({
                "offset": (off.get("x", 0.0), off.get("y", 0.0)),
                "points": pts,
                "trigger": bool(edge.get("m_IsTrigger", False)),
                "enabled": bool(edge.get("m_Enabled", True)),
            })
        if edges:
            rec["mask"] |= HAS_EDGE
            rec["edge"] = edges
            counts["edge"] += len(edges)

        polys = []
        for poly in (comps.get("PolygonCollider2D") or []):
            paths = []
            for path in ((poly.get("m_Points") or {}).get("m_Paths") or []):
                pts = [(p.get("x", 0.0), p.get("y", 0.0)) for p in path]
                if pts:
                    paths.append(pts)
            if not paths:
                continue
            off = poly.get("m_Offset") or {}
            polys.append({
                "offset": (off.get("x", 0.0), off.get("y", 0.0)),
                "paths": paths,
                "trigger": bool(poly.get("m_IsTrigger", False)),
                "enabled": bool(poly.get("m_Enabled", True)),
            })
        if polys:
            rec["mask"] |= HAS_POLY
            rec["poly"] = polys
            counts["poly"] += len(polys)

        # CameraLockArea, RespawnMarker and HazardRespawnMarker all still exist as
        # classes in Silksong, so these are re-attached rather than reimplemented.
        cam = monos.get("CameraLockArea")
        if cam is not None:
            try:
                f = read_fields(cam, CAMERA_LOCK_AREA)
                rec["mask"] |= HAS_CAMLOCK
                rec["camlock"] = f
                counts["camlock"] += 1
            except Exception as e:
                log(f"    ! CameraLockArea on '{rec['name']}' unparsed: {e!r}")

        rsp = monos.get("RespawnMarker")
        if rsp is not None:
            try:
                rec["mask"] |= HAS_RESPAWN
                rec["respawn"] = read_fields(rsp, RESPAWN_MARKER)
                counts["respawn"] += 1
            except Exception:
                pass

        hz = monos.get("HazardRespawnMarker")
        if hz is not None:
            try:
                rec["mask"] |= HAS_HAZARD
                rec["hazard"] = read_fields(hz, HAZARD_RESPAWN_MARKER)
                counts["hazard"] += 1
            except Exception:
                pass

        simple = [c for c in SIMPLE_COMPONENTS if c in monos]
        if simple:
            rec["mask"] |= HAS_SIMPLE
            rec["simple"] = simple
            counts["simple"] += len(simple)

        st = monos.get("BossStatue")
        if st is not None:
            try:
                f = read_fields(st, BOSS_STATUE_HEAD)

                def arena_of(ptr):
                    a = scene.resolve(ptr, lvl)
                    if a is None:
                        return ""
                    try:
                        return read_fields(a.get_raw_data(), BOSS_SCENE_HEAD)["sceneName"] or ""
                    except Exception:
                        return ""

                boss = arena_of(f["bossScene"])
                dream = arena_of(f["dreamBossScene"])
                if boss or dream:
                    rec["mask"] |= HAS_STATUE
                    rec["statue"] = {"boss": boss, "dream": dream}
                    counts["statue"] += 1
            except Exception as e:
                log(f"    ! BossStatue on '{rec['name']}' unparsed: {e!r}")

        bsd = monos.get("BossSequenceDoor")
        if bsd is not None:
            try:
                f = read_fields(bsd, BOSS_SEQUENCE_DOOR_FULL)
                seq = scene.resolve(f["bossSequence"], lvl)
                seq_name = MonoReader(seq.get_raw_data(), HEADER).string() if seq is not None else ""
                rec["mask"] |= HAS_SEQDOOR
                rec["seqdoor"] = {
                    "playerData": f["playerDataString"] or "",
                    "sequence": seq_name,
                    # Resolved after the loop, once every object has an index.
                    "lockSetPid": (f["lockSet"] or {}).get("m_PathID", 0),
                    "unlockedSetPid": (f["unlockedSet"] or {}).get("m_PathID", 0),
                    "promptPid": (f["lockInteractPrompt"] or {}).get("m_PathID", 0),
                }
                counts["seqdoor"] += 1
            except Exception as e:
                log(f"    ! BossSequenceDoor on '{rec['name']}' unparsed: {e!r}")

        mf = (comps.get("MeshFilter") or [None])[0]
        mr = (comps.get("MeshRenderer") or [None])[0]
        if mf is not None and mr is not None:
            mesh = scene.resolve(mf.get("m_Mesh"), lvl)
            decoded = None
            if mesh is not None:
                try:
                    decoded = decode_mesh(mesh.read_typetree())
                except Exception as e:
                    log(f"    ! mesh on '{rec['name']}' failed to decode: {e!r}")
            if decoded and decoded[2]:
                col = mr.get("m_Color") or {}
                rec["mask"] |= HAS_MESH
                rec["mesh"] = {
                    "verts": decoded[0],
                    "uvs": decoded[1],
                    "tris": decoded[2],
                    "tex": mesh_texture_of(mr),
                    "shader": shader_of(mr),
                    "order": int(mr.get("m_SortingOrder") or 0),
                    "layer_id": int(mr.get("m_SortingLayerID") or 0),
                    "enabled": bool(mr.get("m_Enabled", True)),
                }
                counts["mesh"] += 1

        aud = (comps.get("AudioSource") or [None])[0]
        if aud is not None:
            ai = audio_clip_of(aud)
            if ai >= 0:
                rec["mask"] |= HAS_AUDIO
                rec["audio"] = {
                    "clip": ai,
                    "volume": float(aud.get("m_Volume", 1.0) or 0.0),
                    "pitch": float(aud.get("m_Pitch", 1.0) or 1.0),
                    "loop": bool(aud.get("Loop", False)),
                    "play_awake": bool(aud.get("m_PlayOnAwake", True)),
                    "spatial": float(aud.get("panLevel", 0.0) or 0.0),
                    "enabled": bool(aud.get("m_Enabled", True)),
                }
                counts["audio"] += 1

        # A body and its round hitboxes. Boxes, edges and polygons have their own mask
        # bits already; these two had nowhere to go, and a boss without a Rigidbody2D
        # cannot move - every SetVelocity2d in its FSM pushes one.
        rbs = comps.get("Rigidbody2D") or []
        circles = comps.get("CircleCollider2D") or []
        if rbs or circles:
            rec["mask"] |= HAS_PHYS
            rec["phys"] = (rbs[0] if rbs else None, circles)

        tp = monos.get("TransitionPoint")
        if tp is not None:
            try:
                f = read_fields(tp, TRANSITION_POINT)
                rec["mask"] |= HAS_TRANSITION
                rec["transition"] = f
                counts["transition"] += 1
            except Exception as e:
                log(f"    ! TransitionPoint on '{rec['name']}' unparsed: {e!r}")

        order_to_obj[order_i] = len(objects)
        go_pid = (tdata.get("m_GameObject") or {}).get("m_PathID")
        if go_pid:
            go_to_obj[go_pid] = len(objects)
        objects.append(rec)

    # -- behaviour ------------------------------------------------------
    #
    # A second pass, because everything here needs the finished object index: a component
    # field pointing at another object in the room is written as that object's position
    # in this list, and PlayMaker's own parameters are full of them.
    #
    # These are the components that make Godhome a place rather than a picture of one -
    # Recoil, so a hit knocks a boss back; EnemyDeathEffects, so it dies properly;
    # BossSceneController and the Battle Scene FSMs, which are what actually start and
    # end a fight.
    reg = AssetRegistry(scene, out_dir, log)
    fsm_owner_file = [lvl]

    def resolve_ref(ptr, from_file=None):
        """
        (object index, component type, baked resource name) for a Hollow Knight PPtr.

        `from_file` is the assets file the pointer was read out of, because a PPtr's
        m_FileID indexes that file's own externals table. It defaults to the level, which
        is right for a component on a scene object and wrong for one inside a prefab or a
        ScriptableObject.
        """
        src = from_file or lvl
        if not ptr or not ptr.get("m_PathID"):
            return -1, "", ""
        obj = scene.resolve(ptr, src)
        if obj is None:
            return -1, "", ""

        tname = obj.type.name
        if tname == "GameObject":
            if scene.file_of(obj) == lvl:
                return go_to_obj.get(obj.path_id, -1), "", ""
            return -1, "", reg.prefab_name(ptr, src)

        if tname == "AudioClip":
            return -1, "", reg.audio_name(ptr, src)

        # A ScriptableObject - a MusicCue, an audio event table, a boss scene list. These
        # are what Hollow Knight's own code reaches for, so they are baked and rebuilt
        # rather than dropped.
        if tname == "MonoBehaviour" and scene.file_of(obj) != lvl:
            so = reg.scriptable_name(ptr, src)
            if so:
                return -1, "", so

        # A component reference: record which object holds it and what to look for.
        if scene.file_of(obj) == lvl:
            try:
                raw = obj.get_raw_data()
                owner = struct.unpack_from("<q", raw, 4)[0]
            except Exception:
                owner = 0
            oi = go_to_obj.get(owner, -1)
            if oi < 0:
                return -1, "", ""
            cn = tname
            if tname == "MonoBehaviour":
                try:
                    ms = scene.resolve(script_ptr(obj.get_raw_data()), lvl)
                    cn = ms.read_typetree().get("m_ClassName") if ms else ""
                except Exception:
                    cn = ""
            return oi, cn or "", ""
        return -1, "", ""

    def _fsm_asset(p):
        """
        An FsmObject parameter: a sound, or a ScriptableObject.

        The second is what makes Godhome's music work. "Gods and Glory" is not played by
        any code we could call - it is a MusicCue handed to the AudioManager by an
        ApplyMusicCue action in the arena's own FSM, at the moment Hollow Knight wants it.
        """
        n = reg.audio_name(p, fsm_owner_file[0])
        return n or reg.scriptable_name(p, fsm_owner_file[0])

    fsmbake.ASSET_RESOLVER = _fsm_asset
    fsmbake.GAMEOBJECT_RESOLVER = lambda p: _fsm_go_ref(p)

    def _fsm_go_ref(ptr):
        """
        An FSM GameObject parameter: a prefab name, or an object index written as "#12".

        PlayMaker holds these as plain object references, so both kinds have to fit in one
        string. A prefab is spawned; an object index is looked up in the rebuilt room -
        which is what makes $Battle Scene, $Camera and the rest resolve at all.
        """
        if not ptr or not ptr.get("m_PathID"):
            return ""
        obj = scene.resolve(ptr, fsm_owner_file[0])
        if obj is None:
            return ""
        if obj.type.name == "GameObject" and scene.file_of(obj) == lvl:
            oi = go_to_obj.get(obj.path_id, -1)
            return f"#{oi}" if oi >= 0 else ""
        return reg.prefab_name(ptr, fsm_owner_file[0])

    skipped = collections.Counter()
    bstats = {"comps": 0, "fsms": 0, "tk2d": 0}

    def bake_behaviour(rec, monos, from_file):
        """Components, tk2d and FSMs for one object, into its own buffers."""
        comps_buf = Writer()
        ncomps = 0
        fsms_buf = Writer()
        nfsms = 0
        tk = None
        anim = None

        for cn, raw in monos:
            if cn in ("tk2dSprite", "tk2dSpriteAnimator"):
                try:
                    if cn == "tk2dSprite":
                        sp = read_sprite(raw)
                        cobj = scene.resolve(sp["collection"], from_file)
                        if cobj is not None:
                            tk = (reg.collection_index(cobj), sp)
                    else:
                        an = read_animator(raw)
                        aobj = scene.resolve(an["library"], from_file)
                        if aobj is not None:
                            anim = (reg.library_index(aobj), an)
                except Exception as e:
                    skipped[cn + " (parse)"] += 1
                continue

            if cn == "PlayMakerFSM":
                try:
                    fsm, used = parse_fsm_component(raw)
                    if used != len(raw):
                        skipped["PlayMakerFSM (short)"] += 1
                        continue
                    fsm_owner_file[0] = from_file
                    write_fsm(fsms_buf, fsm)
                    nfsms += 1
                except Exception:
                    skipped["PlayMakerFSM (parse)"] += 1
                continue

            lay = layout_of(cn)
            if lay is None:
                skipped[cn + " (no layout)"] += 1
                continue
            try:
                values, exact = parse_layout(raw, lay)
            except Exception:
                exact = False
                values = None
            if not exact:
                # The layout did not land on the end of the buffer, so it is wrong
                # somewhere and every field after that point is noise. Better no
                # component than a misconfigured one.
                skipped[cn + " (inexact)"] += 1
                continue
            write_component(comps_buf, cn, lay, values,
                            lambda p, f=from_file: resolve_ref(p, f))
            ncomps += 1

        if tk is not None or anim is not None:
            rec["mask"] |= HAS_TK2D
            rec["tk2d"] = (tk, anim)
            bstats["tk2d"] += 1
        if nfsms:
            rec["mask"] |= HAS_FSM
            rec["fsms"] = (nfsms, fsms_buf.bytes())
            bstats["fsms"] += nfsms
        if ncomps:
            rec["mask"] |= HAS_COMPS
            rec["comps"] = (ncomps, comps_buf.bytes())
            bstats["comps"] += ncomps

    for r in objects:
        bake_behaviour(r, r.get("monos") or [], lvl)

    # Prefabs a component or an FSM named, and any they name in turn.
    prefab_bufs = []
    guard = 0
    while reg.prefab_queue and guard < 512:
        guard += 1
        pname, pfile, pgid = reg.prefab_queue.pop(0)
        pw = Writer()
        try:
            write_prefab(pw, scene, reg, pfile, pgid, bake_behaviour)
        except Exception as e:
            import traceback
            log(f"    ! prefab '{pname}' failed: {e!r}")
            log("      " + "\n      ".join(traceback.format_exc().splitlines()[-14:]))
            continue
        prefab_bufs.append((pname, pw.bytes()))

    log(f"    behaviour: {bstats['comps']} components, {bstats['fsms']} FSMs, "
        f"{bstats['tk2d']} tk2d, {len(reg.collections)} collections, "
        f"{len(reg.libraries)} libraries, {len(prefab_bufs)} prefabs")
    if skipped:
        for k, n in skipped.most_common(8):
            log(f"      skipped {n:4} x {k}")

    # GameObject PPtrs point at objects that may appear later in the hierarchy, so the
    # door references are resolved once the whole index is built.
    for r in objects:
        if not (r["mask"] & HAS_SEQDOOR):
            continue
        sd = r["seqdoor"]
        for key, out in (("lockSetPid", "lockSet"), ("unlockedSetPid", "unlockedSet"),
                         ("promptPid", "prompt")):
            pidv = sd.get(key, 0)
            sd[out] = go_to_obj.get(pidv, -1) if pidv else -1

    log(f"    {counts['sprite']} sprite renderers, "
        f"{counts['box']} box / {counts['edge']} edge / {counts['poly']} poly colliders")
    log(f"    {counts['camlock']} camera lock areas, "
        f"{counts['respawn']} respawn / {counts['hazard']} hazard markers, "
        f"{counts['transition']} transition points, {counts['simple']} simple components")
    if counts["audio"]:
        abytes = sum(len(c[1]) for c in audio_clips)
        log(f"    {counts['audio']} audio sources on {len(audio_clips)} clips "
            f"({abytes/1024/1024:.2f} MB of PCM)")
    if counts["statue"]:
        log(f"    {counts['statue']} boss statues")
    if counts["seqdoor"]:
        doors = [(r["name"], r["seqdoor"]["sequence"]) for r in objects if r["mask"] & HAS_SEQDOOR]
        log(f"    {counts['seqdoor']} pantheon doors: " +
            ", ".join(f"{n}->{s or '?'}" for n, s in doors))
    if counts["mesh"]:
        vtot = sum(len(r["mesh"]["verts"]) for r in objects if r["mask"] & HAS_MESH)
        log(f"    {counts['mesh']} meshes ({vtot} vertices) on {len(mesh_tex_objs)} texture(s)")
    exits = sorted({r["transition"]["targetScene"] for r in objects
                    if (r["mask"] & HAS_TRANSITION) and r["transition"]["targetScene"]})
    if exits:
        log(f"    leads to: {', '.join(exits)}")
    log(f"    {len(shader_names)} shaders: {', '.join(shader_names)}")
    log(f"    {len(baker.sprites)} unique sprites on {len(baker.pages)} atlas pages")
    if baker.failures:
        log(f"    {len(baker.failures)} sprites could not be resolved")
        if verbose:
            for k, why in baker.failures[:20]:
                log(f"      - {why}")

    # -- repack --------------------------------------------------------
    #
    # Hollow Knight's atlas pages are shared across many scenes, so baking them whole
    # would embed megabytes of sprites this scene never draws. Crop to what's used.

    repacked = None
    if not no_repack:
        repacked = repack(baker, name, screen_sprites, log)
        if repacked is not None:
            baker.page_names = [n for n, _ in repacked]
            remap = baker.sprite_remap or {}
            for r in objects:
                if not (r["mask"] & HAS_SPRITE):
                    continue
                new = remap.get(r["sprite"]["index"], -1)
                if new < 0:
                    r["mask"] &= ~HAS_SPRITE   # source page was unreadable
                    r.pop("sprite", None)
                else:
                    r["sprite"]["index"] = new

    # -- write ---------------------------------------------------------

    os.makedirs(out_dir, exist_ok=True)

    # Mesh textures become extra pages, after any repacked sprite pages.
    page_names = list(baker.page_names) if baker.page_names is not None else [n for _, n in baker.pages]
    mesh_page_base = len(page_names)
    mesh_page_files = []
    for i, t in enumerate(mesh_tex_objs):
        try:
            td = t.read()
            pname = f"{name}_mesh_{i}_{td.m_Name}"
        except Exception:
            pname = f"{name}_mesh_{i}"
            td = None
        page_names.append(pname)
        mesh_page_files.append((pname, t))
    baker.page_names = page_names

    w = Writer()
    w.buf += MAGIC
    w.i32(FORMAT_VERSION)
    w.string(name)
    w.f32(bounds[0])
    w.f32(bounds[1])

    w.boolean(lighting is not None)
    if lighting is not None:
        w.i32(int(lighting["darknessLevel"]))
        w.f32(lighting["saturation"])
        for v in lighting["defaultColor"]:
            w.f32(v)
        w.f32(lighting["defaultIntensity"])
        for v in lighting["heroLightColor"]:
            w.f32(v)
        for ch in ("redChannel", "greenChannel", "blueChannel"):
            keys = lighting[ch]["keys"]
            w.i32(len(keys))
            for k in keys:
                w.f32(k["time"]); w.f32(k["value"])
                w.f32(k["inSlope"]); w.f32(k["outSlope"])

    w.i32(len(shader_names))
    for sn in shader_names:
        w.string(sn)

    w.i32(len(audio_clips))
    for cname, pcm, count, rate in audio_clips:
        w.string(cname)
        w.i32(count)
        w.i32(rate)

    baker.write_table(w)

    # The behaviour layer's shared tables: sprite collections and animation libraries the
    # room's objects index into, and the prefabs its FSMs spawn.
    reg.write_collections(w)
    reg.write_libraries(w)
    reg.write_assets(w, resolve_ref)
    reg.write_clips(w)
    w.i32(len(prefab_bufs))
    for pname, pbuf in prefab_bufs:
        w.string(pname)
        w.buf += pbuf

    w.i32(len(objects))
    for r in objects:
        w.string(r["name"])
        w.i32(r["parent"])
        w.i32(r["layer"])
        w.boolean(r["active"])
        w.vec3(*r["pos"])
        w.vec4(*r["rot"])
        w.vec3(*r["scale"])
        w.i32(r["mask"])

        if r["mask"] & HAS_SPRITE:
            s = r["sprite"]
            w.i32(s["index"])
            w.i32(s["shader"])
            w.f32(s["color"][0]); w.f32(s["color"][1]); w.f32(s["color"][2]); w.f32(s["color"][3])
            w.i32(s["order"])
            w.i32(s["layer_id"])
            w.boolean(s["flipX"]); w.boolean(s["flipY"]); w.boolean(s["enabled"])

        if r["mask"] & HAS_BOX:
            w.i32(len(r["box"]))
            for b in r["box"]:
                w.vec2(*b["offset"]); w.vec2(*b["size"])
                w.boolean(b["trigger"]); w.boolean(b["enabled"])

        if r["mask"] & HAS_EDGE:
            w.i32(len(r["edge"]))
            for e in r["edge"]:
                w.vec2(*e["offset"])
                w.i32(len(e["points"]))
                for x, y in e["points"]:
                    w.vec2(x, y)
                w.boolean(e["trigger"]); w.boolean(e["enabled"])

        if r["mask"] & HAS_POLY:
            w.i32(len(r["poly"]))
            for p in r["poly"]:
                w.vec2(*p["offset"])
                w.i32(len(p["paths"]))
                for path in p["paths"]:
                    w.i32(len(path))
                    for x, y in path:
                        w.vec2(x, y)
                w.boolean(p["trigger"]); w.boolean(p["enabled"])

        if r["mask"] & HAS_CAMLOCK:
            c = r["camlock"]
            w.f32(c["cameraXMin"]); w.f32(c["cameraYMin"])
            w.f32(c["cameraXMax"]); w.f32(c["cameraYMax"])
            w.boolean(c["preventLookUp"]); w.boolean(c["preventLookDown"])
            w.boolean(c["maxPriority"])

        if r["mask"] & HAS_RESPAWN:
            w.boolean(r["respawn"]["respawnFacingRight"])

        if r["mask"] & HAS_HAZARD:
            w.boolean(r["hazard"]["respawnFacingRight"])

        if r["mask"] & HAS_SEQDOOR:
            w.string(r["seqdoor"]["playerData"])
            w.string(r["seqdoor"]["sequence"])
            w.i32(r["seqdoor"]["lockSet"])
            w.i32(r["seqdoor"]["unlockedSet"])
            w.i32(r["seqdoor"]["prompt"])

        if r["mask"] & HAS_AUDIO:
            a = r["audio"]
            w.i32(a["clip"])
            w.f32(a["volume"]); w.f32(a["pitch"]); w.f32(a["spatial"])
            w.boolean(a["loop"]); w.boolean(a["play_awake"]); w.boolean(a["enabled"])

        if r["mask"] & HAS_STATUE:
            w.string(r["statue"]["boss"])
            w.string(r["statue"]["dream"])

        if r["mask"] & HAS_MESH:
            m = r["mesh"]
            w.i32(len(m["verts"]))
            for (vx, vy, vz), (tu, tv) in zip(m["verts"], m["uvs"]):
                w.f32(vx); w.f32(vy); w.f32(vz)
                w.f32(tu); w.f32(tv)
            w.i32(len(m["tris"]))
            for a, b, c in m["tris"]:
                w.i32(a); w.i32(b); w.i32(c)
            w.i32(mesh_page_base + m["tex"] if m["tex"] >= 0 else -1)
            w.i32(m["shader"])
            w.i32(m["order"])
            w.i32(m["layer_id"])
            w.boolean(m["enabled"])

        if r["mask"] & HAS_SIMPLE:
            w.i32(len(r["simple"]))
            for c in r["simple"]:
                w.string(c)

        if r["mask"] & HAS_TRANSITION:
            t = r["transition"]
            w.string(t["targetScene"] or "")
            w.string(t["entryPoint"] or "")
            w.vec2(*t["entryOffset"])
            w.f32(t["entryDelay"])
            w.boolean(t["isADoor"]); w.boolean(t["dontWalkOutOfDoor"])
            w.boolean(t["alwaysEnterRight"]); w.boolean(t["alwaysEnterLeft"])
            w.boolean(t["hardLandOnExit"]); w.boolean(t["nonHazardGate"])

        if r["mask"] & HAS_PHYS:
            rb, circles = r["phys"]
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
            w.i32(len(circles))
            for c in circles:
                off = c.get("m_Offset") or {}
                w.vec2(off.get("x", 0.0), off.get("y", 0.0))
                w.f32(c.get("m_Radius", 0.5))
                w.boolean(bool(c.get("m_IsTrigger", False)))
                w.boolean(bool(c.get("m_Enabled", True)))

        # Last, so the mask bits above keep their existing order on the wire.
        write_behaviour(w, r)

    scene_path = os.path.join(out_dir, f"{name}.scene")
    from ggformat import compress
    raw = w.bytes()
    packed = compress(raw)
    with open(scene_path, "wb") as f:
        f.write(packed)
    log(f"    packed {len(raw) // 1024} KB -> {len(packed) // 1024} KB")

    # Clip files are named after the clip, so one shared by several scenes is written once.
    audio_bytes = 0
    for cname, pcm, count, rate in audio_clips:
        apath = os.path.join(out_dir, cname + ".pcm")
        if not os.path.exists(apath):
            with open(apath, "wb") as af:
                af.write(pcm)
        audio_bytes += os.path.getsize(apath)

    if repacked is not None:
        png_bytes = 0
        for pname, img in repacked:
            path = os.path.join(out_dir, f"{pname}.png")
            img.save(path, optimize=True)
            png_bytes += os.path.getsize(path)
        for pname, t in mesh_page_files:
            path = os.path.join(out_dir, f"{pname}.png")
            try:
                t.read().image.save(path, optimize=True)
                png_bytes += os.path.getsize(path)
            except Exception as e:
                log(f"    ! mesh texture '{pname}' failed to export: {e!r}")
    else:
        png_bytes = baker.export_pages(out_dir, log)

    for pname, t in mesh_page_files:
        path = os.path.join(out_dir, f"{pname}.png")
        try:
            t.read().image.save(path, optimize=True)
            png_bytes += os.path.getsize(path)
        except Exception as e:
            log(f"    ! mesh texture '{pname}' failed to export: {e!r}")
    scene_bytes = os.path.getsize(scene_path)
    log(f"    -> {name}.scene {scene_bytes/1024:.0f} KB + {png_bytes/1024/1024:.2f} MB of pages"
        + (f" + {audio_bytes/1024/1024:.2f} MB of audio" if audio_bytes else ""))
    return scene_bytes + png_bytes


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hk", default=DEFAULT_HK, help="Hollow Knight _Data folder")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output directory (embedded by the csproj)")
    ap.add_argument("--scenes", nargs="+", help="scene short names, e.g. GG_Atrium")
    ap.add_argument("--all", action="store_true", help="bake every Gods_Glory scene")
    ap.add_argument("--list", action="store_true", help="list Godhome scenes and exit")
    ap.add_argument("--no-repack", action="store_true",
                    help="bake whole source atlas pages instead of cropping to what is used")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    build = HKBuild(args.hk)

    if args.list:
        found = build.godhome_scenes()
        log(f"{len(found)} Godhome scenes in this build:")
        for i, n in found:
            log(f"  level{i:<4} {n}")
        return 0

    if args.all:
        scenes = [n for _, n in build.godhome_scenes()]
    else:
        scenes = args.scenes or DEFAULT_SCENES

    log(f"Hollow Knight: {args.hk}")
    log(f"Output:        {args.out}")
    log(f"Baking {len(scenes)} scene(s)\n")

    log("[pantheons]")
    try:
        seqtool.write(seqtool.collect(args.hk, log), args.out, log)
    except Exception as e:
        log(f"  ! could not bake pantheons: {e!r}")
    log("")

    total = 0
    ok = 0
    for n in scenes:
        log(f"[{n}]")
        got = bake_scene(build, n, args.out, args.verbose, args.no_repack)
        if got:
            total += got
            ok += 1
        log("")

    log(f"Done: {ok}/{len(scenes)} scenes, {total/1024/1024:.2f} MB baked into {args.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
