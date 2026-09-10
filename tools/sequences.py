"""
Baking Godhome's Pantheons.

A Pantheon is a BossSequence ScriptableObject in Hollow Knight's resources.assets: an
ordered list of BossScene assets, each naming one arena scene. Silksong still has both
classes and, crucially, still has BossSequenceController.SetupNewSequence - so once the
lists are recreated at runtime the game's own sequence machinery drives them.

bossScenes is BossSequence's first serialised field and sceneName is BossScene's, so
both are reachable without parsing the nested BossTest arrays that follow.
"""

import os

from ggformat import Writer
from hkassets import SceneEnv
from monoread import (script_ptr, read_fields, MonoReader, HEADER,
                      BOSS_SEQUENCE_HEAD, BOSS_SCENE_HEAD)

MAGIC = b"GGSQ"
VERSION = 1


def _class_of(scene, o):
    try:
        ms = scene.resolve(script_ptr(o.get_raw_data()), scene.file_of(o))
        return ms.read_typetree().get("m_ClassName") if ms else None
    except Exception:
        return None


def _asset_name(o):
    return MonoReader(o.get_raw_data(), HEADER).string()


def collect(hk_data_dir, log):
    """[(sequenceName, [sceneName, ...])] for every Pantheon in the build."""
    scene = SceneEnv(hk_data_dir, os.path.join(hk_data_dir, "resources.assets"))

    out = []
    for o in scene.env.objects:
        if o.type.name != "MonoBehaviour" or _class_of(scene, o) != "BossSequence":
            continue
        name = _asset_name(o)
        try:
            f = read_fields(o.get_raw_data(), BOSS_SEQUENCE_HEAD)
        except Exception as e:
            log(f"  ! sequence '{name}' unparsed: {e!r}")
            continue

        scenes = []
        for ptr in f["bossScenes"]:
            bs = scene.resolve(ptr, scene.file_of(o))
            if bs is None:
                continue
            raw = bs.get_raw_data()
            try:
                sn = read_fields(raw, BOSS_SCENE_HEAD)["sceneName"]
            except Exception:
                sn = None
            if sn:
                scenes.append(sn)
        if scenes:
            out.append((name, scenes))

    out.sort(key=lambda p: p[0])
    return out


def write(sequences, out_dir, log):
    w = Writer()
    w.buf += MAGIC
    w.i32(VERSION)
    w.i32(len(sequences))
    for name, scenes in sequences:
        w.string(name)
        w.i32(len(scenes))
        for s in scenes:
            w.string(s)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "sequences.bin")
    with open(path, "wb") as f:
        f.write(w.bytes())

    log(f"  {len(sequences)} pantheons -> sequences.bin ({os.path.getsize(path)} bytes)")
    for name, scenes in sequences:
        log(f"    {name}: {len(scenes)} bosses")
    return path
