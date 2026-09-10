"""
Loading and cross-file pointer resolution for a Hollow Knight build.

A scene in a shipped Unity game is a `levelN` file that points at assets living in
`sharedassetsN.assets` / `resources.assets`. Those references are (m_FileID, m_PathID)
pairs where m_FileID indexes *that file's own* externals table - so resolution has to
be per-file. Getting this wrong silently resolves to the wrong asset or to nothing.
"""

import os
import UnityPy


class HKBuild:
    """A Hollow Knight _Data folder, loaded lazily one scene at a time."""

    def __init__(self, data_dir):
        self.data_dir = data_dir
        if not os.path.isdir(data_dir):
            raise SystemExit(f"Not a directory: {data_dir}")
        ggm = os.path.join(data_dir, "globalgamemanagers")
        if not os.path.exists(ggm):
            raise SystemExit(f"No globalgamemanagers in {data_dir} - is that a Hollow Knight _Data folder?")
        self._scene_list = None

    # -- build settings -------------------------------------------------

    def scene_paths(self):
        """Ordered scene list; index == the levelN suffix."""
        if self._scene_list is None:
            env = UnityPy.load(os.path.join(self.data_dir, "globalgamemanagers"))
            for o in env.objects:
                if o.type.name == "BuildSettings":
                    self._scene_list = o.read_typetree().get("scenes") or []
                    break
            if self._scene_list is None:
                raise SystemExit("Couldn't read BuildSettings from globalgamemanagers.")
        return self._scene_list

    def find_scene(self, name):
        """Build index for a scene short name, e.g. 'GG_Atrium'. None if absent."""
        target = f"/{name}.unity"
        for i, p in enumerate(self.scene_paths()):
            if p.endswith(target):
                return i
        return None

    def godhome_scenes(self):
        """(index, shortname) for every scene under Scenes/Gods_Glory."""
        out = []
        for i, p in enumerate(self.scene_paths()):
            if "/Gods_Glory/" in p and p.endswith(".unity"):
                out.append((i, os.path.basename(p)[:-len(".unity")]))
        return out

    # -- scene loading --------------------------------------------------

    def load_scene(self, index):
        """Load levelN plus the transitive closure of its externals."""
        level = os.path.join(self.data_dir, f"level{index}")
        if not os.path.exists(level):
            raise SystemExit(f"Missing {level}")
        return SceneEnv(self.data_dir, level)


class SceneEnv:
    """One loaded scene and everything it references."""

    def __init__(self, data_dir, level_path):
        self.data_dir = data_dir
        self.level_path = level_path
        self.level_file = os.path.basename(level_path)

        # Pull in externals until the set stops growing. Two passes is usually enough
        # (a scene's sharedassets rarely reach further), but loop to be safe.
        paths = {level_path}
        env = None
        for _ in range(8):
            env = UnityPy.load(*sorted(paths))
            added = set()
            for name, f in env.files.items():
                for e in getattr(f, "externals", []) or []:
                    p = os.path.join(data_dir, e.path)
                    if os.path.exists(p) and p not in paths:
                        added.add(p)
            if not added:
                break
            paths |= added

        self.env = env
        self.file_count = len(paths)

        # Per-file externals table, and a (file, path_id) -> object index.
        self.externals = {}
        for name, f in env.files.items():
            self.externals[os.path.basename(name)] = [
                os.path.basename(e.path) for e in (getattr(f, "externals", []) or [])
            ]

        self.index = {}
        for o in env.objects:
            src = os.path.basename(getattr(o.assets_file, "name", "") or "")
            self.index[(src, o.path_id)] = o

    def file_of(self, obj):
        return os.path.basename(getattr(obj.assets_file, "name", "") or "")

    def resolve(self, ptr, from_file):
        """Resolve a (m_FileID, m_PathID) PPtr read out of `from_file`."""
        if not ptr:
            return None
        pid = ptr.get("m_PathID", 0)
        if not pid:
            return None
        fid = ptr.get("m_FileID", 0)
        if fid == 0:
            return self.index.get((from_file, pid))
        ext = self.externals.get(from_file, [])
        if fid > len(ext):
            return None
        return self.index.get((ext[fid - 1], pid))

    def scene_objects(self, type_name):
        """Objects of a type that belong to the level file itself."""
        for o in self.env.objects:
            if o.type.name == type_name and self.file_of(o) == self.level_file:
                yield o
