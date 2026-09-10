#!/usr/bin/env python3
"""
The tables a rebuilt Hollow Knight object needs: sprite collections, animation
libraries, audio, and the prefabs its FSMs spawn.

Shared by the boss baker and the scene baker, because an arena contains its bosses and
both need exactly the same machinery. Everything here is registered on first sight and
referenced by index or name afterwards, so a four-part boss sharing one collection, or
ten arenas sharing EnemyHitEffects, costs one copy.
"""
import os
import struct

from monoread import HEADER, script_ptr
from tk2dparse import Tk2dReader
from audiobake import decode_clip, MAX_SECONDS, MUSIC_SECONDS
import adpcm
from typelayout import layout_of
from layoutread import parse as parse_layout


# Above this many samples a clip is treated as music rather than an effect: about
# twenty seconds at 22 kHz.
LONG_CLIP_SAMPLES = 22050 * 20


def safe(name, fallback="asset"):
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (name or fallback))


class FileCtx:
    """The GameObject and Transform tables of one assets file."""

    def __init__(self, scene, fname):
        self.file = fname
        self.go = {}
        self.tr = {}
        for o in scene.env.objects:
            if scene.file_of(o) != fname:
                continue
            try:
                if o.type.name == "GameObject":
                    self.go[o.path_id] = o.read_typetree()
                elif o.type.name in ("Transform", "RectTransform"):
                    self.tr[o.path_id] = o.read_typetree()
            except Exception:
                pass
        self.g2t = {}
        for pid, d in self.tr.items():
            self.g2t[(d.get("m_GameObject") or {}).get("m_PathID")] = pid


class AssetRegistry:
    def __init__(self, scene, out_dir, log=print):
        self.scene = scene
        self.out = out_dir
        self.log = log
        self.lvl = scene.level_file

        self._ctx = {}
        self.collections = []      # (name, [page resource names], defs)
        self._coll = {}
        self.libraries = []        # (name, clips)
        self._lib = {}
        self.clips = {}            # resource name -> (sample count, rate)
        self._audio = {}
        self.prefabs = []          # (name, file, root gpid)
        self._prefab = {}
        self.prefab_queue = []
        self.assets = []           # (name, typeName, layout, values)
        self._asset = {}

    # -- files ---------------------------------------------------------

    def ctx(self, fname):
        if fname not in self._ctx:
            self._ctx[fname] = FileCtx(self.scene, fname)
        return self._ctx[fname]

    # -- tk2d ----------------------------------------------------------

    def _parse(self, obj, fn):
        raw = obj.get_raw_data()
        r = Tk2dReader(raw, HEADER)
        r.string()
        d = getattr(r, fn)()
        if r.i != len(raw):
            raise ValueError(f"{fn} consumed {r.i} of {len(raw)}")
        return d

    def collection_index(self, obj):
        key = (self.scene.file_of(obj), obj.path_id)
        if key in self._coll:
            return self._coll[key]
        coll = self._parse(obj, "sprite_collection")
        cname = coll["spriteCollectionName"] or f"coll{len(self.collections)}"
        csafe = safe(cname)
        pages = []
        for i, tptr in enumerate(coll["textures"]):
            t = self.scene.resolve(tptr, self.scene.file_of(obj))
            if t is None:
                continue
            rname = f"boss_atlas_{csafe}_{i}"
            path = os.path.join(self.out, rname + ".png")
            if os.path.exists(path):
                pages.append(rname)
                continue
            try:
                os.makedirs(self.out, exist_ok=True)
                t.read().image.save(path, optimize=True)
                pages.append(rname)
                self.log(f"    atlas {rname}.png ({os.path.getsize(path)//1024} KB)")
            except Exception as e:
                self.log(f"    ! texture {i} of '{cname}' failed: {e!r}")
        idx = len(self.collections)
        self.collections.append((cname, pages, coll["spriteDefinitions"]))
        self._coll[key] = idx
        return idx

    def library_index(self, obj):
        key = (self.scene.file_of(obj), obj.path_id)
        if key in self._lib:
            return self._lib[key]
        anim = self._parse(obj, "sprite_animation")
        idx = len(self.libraries)
        # tk2dSpriteAnimation is a MonoBehaviour, whose m_Name is empty; the readable
        # name is on the GameObject hosting it.
        lname = f"lib{idx}"
        try:
            raw = obj.get_raw_data()
            host = self.scene.resolve(
                {"m_FileID": struct.unpack_from("<i", raw, 0)[0],
                 "m_PathID": struct.unpack_from("<q", raw, 4)[0]},
                self.scene.file_of(obj))
            if host is not None:
                lname = host.read_typetree().get("m_Name") or lname
        except Exception:
            pass

        lfile = self.scene.file_of(obj)
        for c in anim["clips"]:
            for fr in c["frames"]:
                fci = -1
                fobj = self.scene.resolve(fr["spriteCollection"], lfile)
                if fobj is not None:
                    try:
                        fci = self.collection_index(fobj)
                    except Exception as e:
                        self.log(f"    ! frame collection in '{lname}': {e!r}")
                fr["collIndex"] = fci

        self.libraries.append((lname, anim["clips"]))
        self._lib[key] = idx
        return idx

    # -- scriptable objects ---------------------------------------------

    def scriptable_name(self, ptr, from_file=None):
        """
        Register a ScriptableObject asset and return its table name, or "".

        This is what makes Godhome's music work. "Gods and Glory" is not played by any
        code we could call - it is a MusicCue asset that an ApplyMusicCue action in the
        arena's own FSM hands to the AudioManager at the exact moment Hollow Knight wants
        it. MusicCue exists in Silksong with the same shape, so baking the asset and
        rebuilding it puts the cue back where the FSM can reach it.

        Any ScriptableObject whose layout derives cleanly goes through here, not just
        music - the same path carries boss scene lists and audio event tables.
        """
        if not ptr or not ptr.get("m_PathID"):
            return ""
        obj = self.scene.resolve(ptr, from_file or self.lvl)
        if obj is None or obj.type.name != "MonoBehaviour":
            return ""

        key = (self.scene.file_of(obj), obj.path_id)
        if key in self._asset:
            return self._asset[key]

        raw = obj.get_raw_data()
        try:
            ms = self.scene.resolve(script_ptr(raw), self.scene.file_of(obj))
            cn = ms.read_typetree().get("m_ClassName") if ms else None
        except Exception:
            cn = None
        if not cn:
            return ""

        lay = layout_of(cn)
        if lay is None:
            return ""
        try:
            values, exact = parse_layout(raw, lay)
        except Exception:
            return ""
        if not exact:
            # Same rule as everywhere: a layout that does not land on the end of the
            # buffer is wrong, and a wrong asset is worse than a missing one.
            return ""

        base = safe(cn, "asset")
        name = f"so_{base}_{len(self.assets)}"
        # Reserve the name before recursing: an asset that points at another asset which
        # points back would otherwise register itself twice.
        self._asset[key] = name
        self.assets.append([name, cn, lay, values, self.scene.file_of(obj)])
        return name

    # -- audio ---------------------------------------------------------

    def audio_name(self, ptr, from_file=None, max_seconds=None):
        if not ptr or not ptr.get("m_PathID"):
            return ""
        key = (ptr.get("m_FileID"), ptr.get("m_PathID"), from_file or self.lvl)
        if key in self._audio:
            return self._audio[key]
        obj = self.scene.resolve(ptr, from_file or self.lvl)
        if obj is None or obj.type.name != "AudioClip":
            self._audio[key] = ""
            return ""
        try:
            cname = obj.read_typetree().get("m_Name") or "clip"
        except Exception:
            cname = "clip"
        rname = "audio_" + safe(cname, "clip")
        # Decoded at full length first, then judged. A clip's length is the only
        # reliable way to tell music from a sound effect - and getting it wrong is why
        # "Gods and Glory" was coming across as its first twelve seconds.
        decoded = decode_clip(obj, max_seconds=max_seconds or MUSIC_SECONDS)
        if decoded is None:
            self.log(f"    ! clip '{cname}' could not be decoded")
            self._audio[key] = ""
            return ""
        pcm, count, rate = decoded

        # Anything long enough to be music goes across whole, as ADPCM: a four-minute
        # track is thirteen megabytes as 16-bit PCM and three as four-bit codes, and on
        # orchestral material at 22 kHz that is a far better trade than halving the
        # sample rate. Short clips are effects, and stay as PCM at the effect length.
        fmt = 0
        data = pcm
        ext = ".pcm"
        if count > LONG_CLIP_SAMPLES:
            data = adpcm.encode(pcm)
            fmt = 1
            ext = ".adpcm"
            self.log(f"    music {rname} ({count / rate:.0f}s, {len(data) // 1024} KB ADPCM)")
        else:
            cap = int(MAX_SECONDS * rate)
            if count > cap:
                count = cap
                data = pcm[:cap * 2]

        path = os.path.join(self.out, rname + ext)
        if not os.path.exists(path):
            os.makedirs(self.out, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        self._audio[key] = rname
        self.clips[rname] = (count, rate, fmt)
        return rname

    # -- prefabs -------------------------------------------------------

    def prefab_name(self, ptr, from_file=None):
        """
        The prefab-table name for a GameObject pointer, or "".

        Only assets outside the level file. A pointer into the level is a reference to a
        live scene object, and the FSM wants that object rather than a copy of it.
        """
        if not ptr or not ptr.get("m_PathID"):
            return ""
        obj = self.scene.resolve(ptr, from_file or self.lvl)
        if obj is None or obj.type.name != "GameObject":
            return ""
        if self.scene.file_of(obj) == self.lvl:
            return ""

        key = (self.scene.file_of(obj), obj.path_id)
        if key in self._prefab:
            return self._prefab[key]

        pctx = self.ctx(self.scene.file_of(obj))
        if obj.path_id not in pctx.go:
            return ""

        # Bake from the top of the prefab: PlayMaker spawns the root, and a pointer into
        # the middle of one would lose its parent's transform.
        root = obj.path_id
        for _ in range(32):
            t = pctx.tr.get(pctx.g2t.get(root))
            f = (t or {}).get("m_Father", {}).get("m_PathID", 0)
            if not f or f not in pctx.tr:
                break
            pg = (pctx.tr[f].get("m_GameObject") or {}).get("m_PathID")
            if not pg or pg not in pctx.go:
                break
            root = pg

        rkey = (pctx.file, root)
        if rkey in self._prefab:
            self._prefab[key] = self._prefab[rkey]
            return self._prefab[rkey]

        base = safe(pctx.go[root].get("m_Name"), "prefab")
        name, taken, i = base, {p[0] for p in self.prefabs}, 2
        while name in taken:
            name = f"{base}_{i}"
            i += 1
        self._prefab[rkey] = name
        self._prefab[key] = name
        self.prefabs.append((name, pctx.file, root))
        self.prefab_queue.append((name, pctx.file, root))
        return name

    # -- output --------------------------------------------------------

    def write_collections(self, w):
        w.i32(len(self.collections))
        for cname, pages, defs in self.collections:
            w.string(cname)
            w.i32(len(pages))
            for p in pages:
                w.string(p)
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

    def write_libraries(self, w):
        w.i32(len(self.libraries))
        for lname, clips in self.libraries:
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

    def write_assets(self, w, resolve_ref):
        """
        The ScriptableObject table.

        Serialised last, because an asset's fields can name further assets and the list
        grows while it is being written. `resolve_ref(ptr, from_file)` takes the file the
        asset came from: a MusicCue lives in a shared assets file, and resolving its clip
        pointers against the level's externals table finds the wrong objects or none -
        which is exactly why the music was arriving silent.
        """
        from compbake import write_component
        from ggformat import Writer

        i = 0
        bufs = []
        while i < len(self.assets):
            name, cn, lay, values, afile = self.assets[i]
            aw = Writer()
            write_component(aw, cn, lay, values, lambda p, f=afile: resolve_ref(p, f))
            bufs.append((name, aw.bytes()))
            i += 1
        w.i32(len(bufs))
        for name, buf in bufs:
            w.string(name)
            w.buf += buf

    def write_clips(self, w):
        w.i32(len(self.clips))
        for rname, (count, rate, fmt) in sorted(self.clips.items()):
            w.string(rname)
            w.i32(count)
            w.i32(rate)
            w.i32(fmt)      # 0 = 16-bit PCM, 1 = IMA ADPCM
