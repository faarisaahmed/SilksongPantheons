#!/usr/bin/env python3
"""
Work out how any Hollow Knight component serialises, automatically.

Hollow Knight ships no type trees for MonoBehaviours, so every component has to be read
as raw bytes against a layout derived from the C# class. Hand-writing those layouts got us
a boss; an arena has a hundred component types and hand-writing them all is not on.

So the layout is derived from the decompiled class instead: fields in declaration order,
base class first, keeping only what Unity actually serialises - public fields, or private
ones carrying [SerializeField], of a serialisable type, and never [NonSerialized] or
static or const.

The safety property is the same one that has caught every format bug in this project: a
layout is only trusted if reading a real component with it lands exactly on the end of its
byte buffer. A layout that is wrong by a single field lands somewhere else and is
discarded, so a bad guess costs a skipped component rather than a corrupted scene.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Layouts derived once and shipped, so baking needs neither a decompiler nor the .NET
# SDK. They describe Hollow Knight's field names and types - metadata, not content - and
# are regenerated with `python3 typelayout.py --dump`.
CACHE_FILE = os.path.join(HERE, "layouts.json")

_HK_MANAGED = None


def hk_managed():
    global _HK_MANAGED
    if _HK_MANAGED is None:
        from hkpath import hollow_knight_data
        _HK_MANAGED = os.path.join(hollow_knight_data(), "Managed")
    return _HK_MANAGED

# PlayMaker is in the list because components reference PlayMakerFSM by field, and tk2d's
# types live in Assembly-CSharp-firstpass alongside the rest of the third-party code.
_ASM = ["Assembly-CSharp.dll", "Assembly-CSharp-firstpass.dll", "PlayMaker.dll"]

# One decompile of each assembly, indexed by type, instead of a process per type. A bake
# asks for well over a hundred layouts; at a second or two each that is minutes of
# subprocess overhead per scene.
DECOMP_DIR = "/tmp/hkdec2"
_bulk = None
_src_cache = {}
_layout_cache = {}
_kind_cache = {}
_all_types = None
# Types currently being laid out. A [Serializable] type that reaches itself - directly or
# through a field - would otherwise recurse until the stack runs out, which is how
# Journal_Update_Msg killed a whole prefab.
_inflight = set()
_cache_loaded = False
_disk_cache = {}
DEBUG = bool(os.environ.get("LAYOUT_DEBUG"))


def _env():
    e = dict(os.environ)
    e["DOTNET_ROOT"] = os.path.expanduser("~/.dotnet")
    e["PATH"] = os.path.expanduser("~/.dotnet") + ":" + \
        os.path.expanduser("~/.dotnet/tools") + ":" + e.get("PATH", "")
    return e


def all_types():
    """Every type name Hollow Knight's own assemblies define, short name -> full name."""
    global _all_types
    if _all_types is not None:
        return _all_types
    _all_types = {}

    # The bulk decompile already names every type; deriving the kind from its own
    # declaration avoids ten ilspycmd invocations per run.
    bulk = _bulk_index()
    if bulk:
        for name, text in bulk.items():
            head = text[:text.find("{")] if "{" in text else text
            if re.search(r"\benum\s+" + re.escape(name) + r"\b", head):
                kind = "enum"
            elif re.search(r"\bstruct\s+" + re.escape(name) + r"\b", head):
                kind = "struct"
            elif re.search(r"\binterface\s+" + re.escape(name) + r"\b", head):
                kind = "interface"
            else:
                kind = "class"
            _all_types[name] = (kind, name)
        return _all_types

    # One kind per invocation: this ilspycmd takes a single -l value, and a comma list
    # silently produces nothing at all.
    for dll in _ASM:
        p = os.path.join(hk_managed(), dll)
        if not os.path.exists(p):
            continue
        for kind in ("c", "s", "e", "i", "d"):
            r = subprocess.run(["ilspycmd", "-l", kind, p],
                               capture_output=True, text=True, env=_env())
            for line in r.stdout.splitlines():
                line = line.strip()
                if not line or " " not in line:
                    continue
                kindword, full = line.split(" ", 1)
                full = full.strip()
                _all_types.setdefault(full.split(".")[-1], (kindword.lower(), full))
    return _all_types


def _bulk_index():
    """
    type name -> the decompiled source declaring it, brace-matched.

    ILSpy emits one file per assembly containing every type, so this scans for each
    declaration and takes it through to its matching close. Nested types are indexed too,
    under their own short name, which is what a field's type annotation gives us.
    """
    global _bulk
    if _bulk is not None:
        return _bulk
    _bulk = {}
    if not os.path.isdir(DECOMP_DIR):
        return _bulk
    decl = re.compile(r"(?:^|\n)([ \t]*)(?:(?:public|internal|private|protected|abstract|"
                      r"sealed|static|partial|readonly|new|unsafe)\s+)*"
                      r"(?:class|struct|enum|interface)\s+([A-Za-z_]\w*)")
    for fn in sorted(os.listdir(DECOMP_DIR)):
        if not fn.endswith(".cs"):
            continue
        text = open(os.path.join(DECOMP_DIR, fn), encoding="utf-8", errors="replace").read()
        for m in decl.finditer(text):
            name = m.group(2)
            if name in _bulk:
                continue
            # Back up over the attribute lines above the declaration. [Serializable] is
            # the difference between a field written inline and one Unity skips
            # entirely, so losing it shifts every field after it.
            start = m.start()
            while True:
                prev = text.rfind("\n", 0, start - 1)
                line = text[prev + 1:start].strip()
                if line.startswith("[") and line.endswith("]"):
                    start = prev + 1 if prev >= 0 else 0
                    continue
                break

            open_at = text.find("{", m.end())
            if open_at < 0:
                continue
            depth, i = 0, open_at
            while i < len(text):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            _bulk[name] = text[start:i + 1]
    return _bulk


def source(type_name):
    """The decompiled source of one type, or None."""
    if type_name in _src_cache:
        return _src_cache[type_name]

    # A nested type's declaration lives inside its outer type's text, so both resolve
    # through the outer name.
    short = type_name.split(".")[0].split("+")[0]
    bulk = _bulk_index().get(short) or _bulk_index().get(type_name.split(".")[-1])
    if bulk:
        _src_cache[type_name] = bulk
        return bulk
    info = all_types().get(type_name.split(".")[-1])
    full = info[1] if info else type_name
    text = None
    for dll in _ASM:
        p = os.path.join(hk_managed(), dll)
        if not os.path.exists(p):
            continue
        r = subprocess.run(["ilspycmd", "-t", full, p],
                           capture_output=True, text=True, env=_env())
        if r.returncode == 0 and r.stdout.strip() and "Could not find type" not in r.stdout:
            text = r.stdout
            break
    # Nested types (HealthManager.HPScaleGG) are not decompilable on their own; their
    # declaration lives inside the outer type's source.
    if text is None and "." in full:
        outer = source(full.split(".")[0])
        if outer:
            text = outer
    _src_cache[type_name] = text
    return text


# ---------------------------------------------------------------- type kinds

PRIMITIVES = {
    "bool": "bool", "byte": "u8", "sbyte": "i8", "char": "u16",
    "short": "i16", "ushort": "u16", "int": "i32", "uint": "u32",
    "long": "i64", "ulong": "u64", "float": "f32", "double": "f64",
    "string": "string",
}

# Unity value types with a fixed serialised shape.
STRUCTS = {
    "Vector2": "vec2", "Vector2Int": "vec2i", "Vector3": "vec3", "Vector3Int": "vec3i",
    "Vector4": "vec4", "Quaternion": "vec4", "Color": "color", "Color32": "color32",
    "Rect": "vec4", "Bounds": "bounds", "LayerMask": "i32",
    "AnimationCurve": "curve", "Matrix4x4": "matrix",
}

CONTAINER = re.compile(r"^(?:System\.Collections\.Generic\.)?List<(.+)>$")

# UnityEngine's own Object types. A field of any of these is a reference, so it
# serialises as a PPtr - Hollow Knight's assemblies do not define them, so they cannot be
# discovered the way the game's own types are.
UNITY_OBJECTS = {
    "Object", "GameObject", "Component", "Behaviour", "MonoBehaviour", "ScriptableObject",
    "Transform", "RectTransform", "Rigidbody", "Rigidbody2D", "Collider", "Collider2D",
    "BoxCollider", "BoxCollider2D", "CircleCollider2D", "PolygonCollider2D",
    "EdgeCollider2D", "CapsuleCollider2D", "CompositeCollider2D", "PhysicsMaterial2D",
    "Renderer", "MeshRenderer", "SkinnedMeshRenderer", "SpriteRenderer", "LineRenderer",
    "TrailRenderer", "ParticleSystem", "ParticleSystemRenderer", "MeshFilter", "Mesh",
    "Material", "Shader", "Texture", "Texture2D", "Cubemap", "RenderTexture", "Sprite",
    "AudioClip", "AudioSource", "AudioMixer", "AudioMixerSnapshot", "AudioMixerGroup",
    "Animation", "AnimationClip", "Animator", "RuntimeAnimatorController",
    "AnimatorOverrideController", "Avatar", "Camera", "Light", "Projector", "Canvas",
    "CanvasGroup", "CanvasRenderer", "Graphic", "Image", "RawImage", "Text", "Button",
    "Slider", "Scrollbar", "Toggle", "InputField", "Dropdown", "ScrollRect", "Mask",
    "TextAsset", "Font", "PhysicMaterial", "NavMeshAgent", "TerrainData", "Terrain",
    "Flare", "LensFlare", "ReflectionProbe", "SpriteMask", "Grid", "Tilemap",
    "PlayableAsset", "TimelineAsset", "VideoClip", "VideoPlayer", "EventSystem",
}


def kind_of(csharp_type):
    """
    A reader kind for one C# type, or None when it cannot be serialised (and so is
    skipped) - or is something this does not attempt, in which case the whole layout is
    abandoned rather than guessed at.
    """
    t = csharp_type.strip()
    if t in _kind_cache:
        return _kind_cache[t]
    k = _kind_of(t)
    if not _inflight:
        _kind_cache[t] = k
    return k


def _kind_of(t):
    # Not cached: the answer depends on what is currently in flight.
    t = t.replace("UnityEngine.", "").replace("System.", "").strip()
    if t in PRIMITIVES:
        return PRIMITIVES[t]
    if t in STRUCTS:
        return STRUCTS[t]

    if t.endswith("[]"):
        inner = kind_of(t[:-2])
        return ("array", inner) if inner else None
    m = CONTAINER.match(t)
    if m:
        inner = kind_of(m.group(1))
        return ("array", inner) if inner else None

    short = t.split(".")[-1].split("<")[0]
    if short in UNITY_OBJECTS:
        return "pptr"

    info = all_types().get(short)
    if not info:
        return None
    kindword, full = info

    if kindword.startswith("enum"):
        return "i32"

    # A reference to another Unity object is a PPtr wherever it appears.
    if _is_unity_object(full):
        return "pptr"

    # A [Serializable] class or struct is written inline, field by field.
    src = source(full)
    if src and "[Serializable]" in src:
        sub = layout_of(full, inline=True)
        return ("inline", full, sub) if sub is not None else None
    return None


_unity_object_cache = {}


def _is_unity_object(full):
    if full in _unity_object_cache:
        return _unity_object_cache[full]
    src = source(full)
    r = False
    if src:
        # The word boundary matters: without it "BossDoorTarget" matches the declaration
        # of "BossDoorTargetLock : MonoBehaviour", and a [Serializable] class nested
        # inside a component gets mistaken for a reference to one.
        m = re.search(r"^\s*(?:public |internal |abstract |sealed )*(?:class|struct)\s+"
                      + re.escape(full.split(".")[-1]) + r"\b[^\n:{]*:\s*([^\n{]+)",
                      src, re.M)
        if m:
            bases = [b.strip().split("<")[0] for b in m.group(1).split(",")]
            for b in bases:
                b = b.replace("UnityEngine.", "")
                if b in ("MonoBehaviour", "ScriptableObject", "Component", "Behaviour",
                         "Object", "GameObject", "Transform", "Collider2D", "Renderer"):
                    r = True
                    break
                if b and b[0].isupper() and b not in ("IEnumerator",) and not b.startswith("I"):
                    r = _is_unity_object(all_types().get(b, ("", b))[1])
                    if r:
                        break
    _unity_object_cache[full] = r
    return r


# ---------------------------------------------------------------- field scan

FIELD = re.compile(
    r"^\s*(?P<mods>(?:public|private|protected|internal|static|readonly|const|new|volatile|event|extern|unsafe)\s+)*"
    r"(?P<type>[A-Za-z_][\w.<>,\[\] ]*?)\s+(?P<name>[A-Za-z_]\w*)\s*(?:=(?!>)[^;]*)?;\s*$")


def _class_body(src, short):
    """
    The declaration's own body, and its base class.

    Nested types, properties and methods are dropped by tracking brace depth line by
    line: only declarations at the class's own level are fields. ILSpy puts the opening
    brace on its own line, so the declaration match has to reach across the newline.
    """
    m = re.search(r"(?:class|struct)\s+" + re.escape(short) + r"\b(?P<rest>[^{]*)\{", src)
    if not m:
        return None, None

    base = None
    bm = re.search(r":\s*(.+)$", m.group("rest").strip(), re.S)
    if bm:
        base = bm.group(1).split(",")[0].strip().split("<")[0].strip()

    start = m.end()
    depth = 1
    i = start
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    body = src[start:i - 1]

    kept = []
    depth = 0
    for line in body.split("\n"):
        stripped = line.strip()
        if depth == 0 and stripped:
            kept.append(stripped)
        depth += line.count("{") - line.count("}")
        if depth < 0:
            depth = 0
    return "\n".join(kept), base


def _load_cache():
    global _cache_loaded, _disk_cache
    if _cache_loaded:
        return _disk_cache
    _cache_loaded = True
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        # JSON has no tuples; kinds come back as lists and have to be restored.
        _disk_cache = {k: (None if v is None else [(n, _untuple(t)) for n, t in v])
                       for k, v in raw.items()}
    except Exception:
        _disk_cache = {}
    return _disk_cache


def _untuple(k):
    if isinstance(k, list):
        if k[0] == "array":
            return ("array", _untuple(k[1]))
        if k[0] == "inline":
            return ("inline", k[1], [(n, _untuple(t)) for n, t in k[2]])
    return k


def _retuple(k):
    if isinstance(k, tuple):
        if k[0] == "array":
            return ["array", _retuple(k[1])]
        if k[0] == "inline":
            return ["inline", k[1], [[n, _retuple(t)] for n, t in k[2]]]
    return k


def layout_of(type_name, inline=False, _seen=None):
    """
    [(field_name, kind), ...] in serialised order, or None if the type cannot be laid out.
    """
    if not inline:
        cache = _load_cache()
        if type_name in cache:
            return cache[type_name]

    key = (type_name, inline)
    if key in _layout_cache:
        return _layout_cache[key]
    if type_name in _inflight:
        return None
    _seen = _seen or set()
    if type_name in _seen:
        return None
    _seen = _seen | {type_name}
    _inflight.add(type_name)
    try:
        return _layout_body(type_name, inline, _seen, key)
    finally:
        _inflight.discard(type_name)


def _layout_body(type_name, inline, _seen, key):

    src = source(type_name)
    if src is None:
        _layout_cache[key] = None
        return None
    short = type_name.split(".")[-1]
    body, base = _class_body(src, short)
    if body is None:
        _layout_cache[key] = None
        return None

    fields = []

    # Unity writes base class fields first.
    if base and base not in ("MonoBehaviour", "ScriptableObject", "object",
                             "Object", "Component", "Behaviour"):
        binfo = all_types().get(base)
        if binfo:
            bfields = layout_of(binfo[1], inline=True, _seen=_seen)
            if bfields is None:
                _layout_cache[key] = None
                return None
            fields += bfields

    # Attributes attach to the declaration that follows them.
    pending = []
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("["):
            pending.append(line)
            continue
        m = FIELD.match(line)
        if not m:
            pending = []
            continue

        attrs = " ".join(pending)
        pending = []
        mods = (m.group("mods") or "")
        if "static" in mods or "const" in mods or "event" in mods:
            continue
        if "NonSerialized" in attrs:
            continue
        is_public = "public" in mods
        if not is_public and "SerializeField" not in attrs:
            continue

        k = kind_of(m.group("type"))
        if k is None:
            if DEBUG:
                print(f"    ! {type_name}.{m.group('name')}: unhandled type "
                      f"'{m.group('type')}'", file=sys.stderr)
            # An unserialisable type is simply skipped by Unity (delegates, interfaces),
            # but one this does not understand would shift everything after it. There is
            # no way to tell those apart from here, so the layout is abandoned; the
            # byte-exactness check would reject it anyway.
            _layout_cache[key] = None
            return None
        fields.append((m.group("name"), k))

    _layout_cache[key] = fields
    return fields


def dump_cache(type_names, path=CACHE_FILE):
    """Derive layouts for these types and write them where the baker will find them."""
    global _cache_loaded, _disk_cache
    _cache_loaded, _disk_cache = True, {}      # derive fresh, ignore any existing file
    out = {}
    for t in sorted(set(type_names)):
        lay = layout_of(t)
        out[t] = None if lay is None else [[n, _retuple(k)] for n, k in lay]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=0, sort_keys=True)
    known = sum(1 for v in out.values() if v is not None)
    return known, len(out)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--dump"]:
        names = sys.argv[2:]
        if not names:
            print("usage: typelayout.py --dump <TypeName> ...")
            sys.exit(1)
        k, n = dump_cache(names)
        print(f"wrote {CACHE_FILE}: {k} of {n} types laid out")
        sys.exit(0)

    for t in sys.argv[1:]:
        f = layout_of(t)
        print(f"{t}: {'UNSUPPORTED' if f is None else ''}")
        for n, k in (f or []):
            print(f"    {n:34} {k}")
