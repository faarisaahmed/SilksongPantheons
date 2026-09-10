"""
Reading MonoBehaviour fields out of a Hollow Knight build, which ships no type trees.

UnityPy can only deserialise a MonoBehaviour when the file carries a type tree for it.
Release builds strip those, so 361 of GG_Atrium's 385 MonoBehaviours fail to parse -
including every CameraLockArea and TransitionPoint we care about.

What we do have is the exact field layout, from decompiling Hollow Knight's own
Assembly-CSharp. So we parse the raw bytes against a hand-written spec.

Unity's serialised MonoBehaviour begins with a fixed header:

    m_GameObject   PPtr  (int32 fileID + int64 pathID)   12 bytes
    m_Enabled      uint8, then align to 4                 4 bytes
    m_Script       PPtr                                  12 bytes
    m_Name         int32 length + utf8 bytes + align 4

after which the class's own serialised fields follow in declaration order. Only fields
Unity actually serialises count: public ones, plus private ones marked [SerializeField].
Private fields without it are skipped - getting that wrong shifts every later field.
"""

import struct

HEADER = 12 + 4 + 12   # m_GameObject, m_Enabled(+pad), m_Script


class MonoReader:
    def __init__(self, data, pos=0):
        self.d = data
        self.i = pos

    def align(self, n=4):
        r = self.i % n
        if r:
            self.i += n - r

    def _take(self, n):
        if self.i + n > len(self.d):
            raise EOFError(f"short read at {self.i} (+{n}), have {len(self.d)}")
        b = self.d[self.i:self.i + n]
        self.i += n
        return b

    def f32(self):  return struct.unpack("<f", self._take(4))[0]
    def i32(self):  return struct.unpack("<i", self._take(4))[0]
    def u8(self):   return self._take(1)[0]

    def boolean(self):
        v = self.u8() != 0
        return v

    def string(self):
        n = self.i32()
        if n < 0 or self.i + n > len(self.d):
            raise EOFError(f"bad string length {n} at {self.i}")
        s = self._take(n).decode("utf-8", "replace")
        self.align(4)
        return s

    def pptr(self):
        fid = self.i32()
        pid = struct.unpack("<q", self._take(8))[0]
        return {"m_FileID": fid, "m_PathID": pid}

    def vec2(self):
        return (self.f32(), self.f32())

    def pptr_array(self):
        n = self.i32()
        return [self.pptr() for _ in range(n)]

    def color(self):
        return (self.f32(), self.f32(), self.f32(), self.f32())

    def curve(self):
        """
        AnimationCurve: a keyframe array, then wrap modes.

        Unity 2018+ Keyframe is time, value, inSlope, outSlope, weightedMode,
        inWeight, outWeight - 28 bytes. The array is length-prefixed and aligned,
        then m_PreInfinity, m_PostInfinity, m_RotationOrder follow as ints.
        """
        n = self.i32()
        keys = []
        for _ in range(n):
            keys.append({
                "time": self.f32(), "value": self.f32(),
                "inSlope": self.f32(), "outSlope": self.f32(),
                "weightedMode": self.i32(),
                "inWeight": self.f32(), "outWeight": self.f32(),
            })
        self.align(4)
        return {
            "keys": keys,
            "preInfinity": self.i32(),
            "postInfinity": self.i32(),
            "rotationOrder": self.i32(),
        }


def script_ptr(raw):
    """m_Script sits at a fixed offset, readable without any type information."""
    fid, pid = struct.unpack_from("<iq", raw, 16)
    return {"m_FileID": fid, "m_PathID": pid}


def read_fields(raw, spec):
    """
    Parse a MonoBehaviour's own fields.

    `spec` is a list of (name, kind) in declaration order, kind in
    {'f32','i32','bool','string','pptr'}. Returns a dict, or raises EOFError.

    Unity carries an "align" flag on bool/byte fields, so it pads to 4 bytes after
    *each* one - they are not packed together. Getting this wrong reads later bools out
    of the padding of earlier ones, which looks like every flag being false.

    Verified against object sizes in GG_Atrium: a component with no serialised fields
    (Roof) is 32 bytes = 28 header + 4 empty name; CameraLockArea is 60 = 32 + 4 floats
    + 3 individually-aligned bools.
    """
    r = MonoReader(raw, HEADER)
    r.string()          # m_Name
    out = {}
    for name, kind in spec:
        if kind == "f32":      out[name] = r.f32()
        elif kind == "i32":    out[name] = r.i32()
        elif kind == "bool":
            out[name] = r.boolean()
            r.align(4)
        elif kind == "string": out[name] = r.string()
        elif kind == "pptr":   out[name] = r.pptr()
        elif kind == "vec2":   out[name] = r.vec2()
        elif kind == "pptr_array": out[name] = r.pptr_array()
        elif kind == "color":  out[name] = r.color()
        elif kind == "curve":  out[name] = r.curve()
        else: raise ValueError(f"unknown kind {kind}")
    out["_end"] = r.i
    return out


# Field layouts, taken from decompiled Hollow Knight Assembly-CSharp.
# Only serialised fields appear; private-without-[SerializeField] are omitted.

CAMERA_LOCK_AREA = [
    ("cameraXMin", "f32"),
    ("cameraYMin", "f32"),
    ("cameraXMax", "f32"),
    ("cameraYMax", "f32"),
    ("preventLookUp", "bool"),
    ("preventLookDown", "bool"),
    ("maxPriority", "bool"),
]

RESPAWN_MARKER = [
    ("respawnFacingRight", "bool"),
]

HAZARD_RESPAWN_MARKER = [
    ("respawnFacingRight", "bool"),
]

# Godhome's Pantheon lists. bossScenes is the first serialised field, so the ordered
# boss list is reachable without parsing the nested BossTest arrays that follow.
BOSS_SEQUENCE_HEAD = [
    ("bossScenes", "pptr_array"),
    ("useSceneUnlocks", "bool"),
]

# BossScene.sceneName is likewise the first field.
BOSS_SCENE_HEAD = [
    ("sceneName", "string"),
]

# tk2dSprite's serialised head. collectionInst and _cachedRenderer are not serialised,
# so spriteId lands at offset 40 after m_Name.
TK2D_SPRITE_HEAD = [
    ("collection", "pptr"),
    ("colorR", "f32"), ("colorG", "f32"), ("colorB", "f32"), ("colorA", "f32"),
    ("scaleX", "f32"), ("scaleY", "f32"), ("scaleZ", "f32"),
    ("spriteId", "i32"),
]

TK2D_ANIMATOR_HEAD = [
    ("library", "pptr"),
    ("defaultClipId", "i32"),
    ("playAutomatically", "bool"),
]

# A Hall of Gods statue. bossScene and dreamBossScene are the first two serialised
# fields; the BossUIDetails structs that follow are not needed.
BOSS_STATUE_HEAD = [
    ("bossScene", "pptr"),
    ("dreamBossScene", "pptr"),
]

# A Pantheon entrance. playerDataString is the first serialised field; `completion` is
# private without [SerializeField] and so is not serialised.
BOSS_SEQUENCE_DOOR_HEAD = [
    ("playerDataString", "string"),
    ("bossSequence", "pptr"),
]

# The full head, down to the objects that decide whether a door *looks* locked.
# BossSequenceDoor.Start() normally hides lockSet and shows unlockedSet; without it the
# padlock geometry stays visible and every Pantheon reads as sealed.
BOSS_SEQUENCE_DOOR_FULL = [
    ("playerDataString", "string"),
    ("bossSequence", "pptr"),
    ("titleSuperKey", "string"),
    ("titleSuperSheet", "string"),
    ("titleMainKey", "string"),
    ("titleMainSheet", "string"),
    ("descriptionKey", "string"),
    ("descriptionSheet", "string"),
    ("requiredComplete", "pptr_array"),
    ("completedDisplay", "pptr"),
    ("completedAllDisplay", "pptr"),
    ("completedNoHitsDisplay", "pptr"),
    ("boundNailDisplay", "pptr"),
    ("boundHeartDisplay", "pptr"),
    ("boundCharmsDisplay", "pptr"),
    ("boundSoulDisplay", "pptr"),
    ("boundAllDisplay", "pptr"),
    ("boundAllBackboard", "pptr"),
    ("lockSet", "pptr"),
    ("lockInteractPrompt", "pptr"),
    ("cameraLock", "pptr"),
    ("unlockedSet", "pptr"),
]

# Doors between Godhome's rooms.
TRANSITION_POINT = [
    ("isADoor", "bool"),
    ("dontWalkOutOfDoor", "bool"),
    ("entryDelay", "f32"),
    ("alwaysEnterRight", "bool"),
    ("alwaysEnterLeft", "bool"),
    ("hardLandOnExit", "bool"),
    ("targetScene", "string"),
    ("entryPoint", "string"),
    ("entryOffset", "vec2"),
    ("alwaysUnloadUnusedAssets", "bool"),
    ("customFadeFSM", "pptr"),
    ("nonHazardGate", "bool"),
    ("respawnMarker", "pptr"),
    ("atmosSnapshot", "pptr"),
    ("enviroSnapshot", "pptr"),
    ("actorSnapshot", "pptr"),
    ("musicSnapshot", "pptr"),
    ("sceneLoadVisualization", "i32"),
    ("customFade", "bool"),
    ("forceWaitFetch", "bool"),
]

# Hollow Knight's per-room look. Silksong's CustomSceneManager kept every one of these
# fields under the same names, so the values transfer directly - which is what stops
# Godhome from being rendered with the donor room's colour grading.
SCENE_MANAGER = [
    ("sceneType", "i32"),
    ("mapZone", "i32"),
    ("isWindy", "bool"),
    ("isTremorZone", "bool"),
    ("environmentType", "i32"),
    ("darknessLevel", "i32"),
    ("noLantern", "bool"),
    ("saturation", "f32"),
    ("ignorePlatformSaturationModifiers", "bool"),
    ("redChannel", "curve"),
    ("greenChannel", "curve"),
    ("blueChannel", "curve"),
    ("defaultColor", "color"),
    ("defaultIntensity", "f32"),
    ("heroLightColor", "color"),
]

# Only the leading fields are needed; the rest of the tilemap is huge and irrelevant.
# width/height are the scene's world dimensions - CameraController derives sceneWidth,
# sceneHeight, xLimit and yLimit straight from them.
TK2D_TILEMAP = [
    ("editorDataGUID", "string"),
    ("data", "pptr"),
    ("renderData", "pptr"),
    ("spriteCollection", "pptr"),
    ("spriteCollectionKey", "i32"),
    ("width", "i32"),
    ("height", "i32"),
]
