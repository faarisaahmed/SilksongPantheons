"""
Turning Hollow Knight sprites into (atlas page PNG + rect + pivot) triples that
Unity's Sprite.Create can rebuild verbatim on the Silksong side.

Most Godhome scenery is packed into SpriteAtlases (the scenery sprites carry
m_AtlasTags ['GG'] and an empty m_RD.texture), so the real texture and rect have to
come from the atlas's m_RenderDataMap keyed by the sprite's m_RenderDataKey.

We deliberately do not use UnityPy's `sprite.image`. It reconstructs the sprite mesh
to crop, which throws on a chunk of Hollow Knight's atlas sprites (numpy 'solve1'
and NaN errors on ~37% of GG_Atrium's sprites). Shipping whole atlas pages plus rects
is both more robust and closer to what the engine does anyway.
"""

from ggformat import Writer


def _key_of(render_data_key):
    """m_RenderDataKey is ((guid words), local id). Normalise for dict lookup."""
    if isinstance(render_data_key, (list, tuple)) and len(render_data_key) == 2:
        guid, lid = render_data_key
        if isinstance(guid, dict):
            guid = tuple(guid[k] for k in sorted(guid.keys()))
        elif isinstance(guid, (list, tuple)):
            guid = tuple(guid)
        return (guid, lid)
    return None


class SpriteBaker:
    """Collects unique sprites, resolving each to an atlas page and a pixel rect."""

    def __init__(self, scene):
        self.scene = scene
        self._page_index_cache = {}   # (file, path_id) -> page index
        self.pages = []          # [(texture_object, name)]
        self._sprites = {}       # (file, path_id) -> sprite index
        self.sprites = []        # [dict]
        self.failures = []
        self.page_names = None   # set by repack.py once pages are rebuilt
        self.sprite_remap = None

        # RenderDataKey -> SpriteAtlasData, across every atlas in the scene's closure.
        self._atlas_map = {}
        for o in scene.env.objects:
            if o.type.name != "SpriteAtlas":
                continue
            try:
                d = o.read_typetree()
            except Exception:
                continue
            src = scene.file_of(o)
            for entry in (d.get("m_RenderDataMap") or []):
                try:
                    k, v = entry
                except (TypeError, ValueError):
                    continue
                nk = _key_of(k)
                if nk is not None:
                    self._atlas_map[nk] = (v, src)

    # ------------------------------------------------------------------

    def _page_index(self, tex_obj, from_file):
        key = (self.scene.file_of(tex_obj), tex_obj.path_id)
        if key in self._page_index_cache:
            return self._page_index_cache[key]
        idx = len(self.pages)
        try:
            name = tex_obj.read().m_Name or f"page_{idx}"
        except Exception:
            name = f"page_{idx}"
        # Page names must be unique - they become embedded resource names.
        name = f"{name}_{tex_obj.path_id}"
        self.pages.append((tex_obj, name))
        self._page_index_cache[key] = idx
        return idx

    def add(self, sprite_obj):
        """Returns the index of this sprite in the baked table, or -1."""
        key = (self.scene.file_of(sprite_obj), sprite_obj.path_id)
        if key in self._sprites:
            return self._sprites[key]

        try:
            d = sprite_obj.read_typetree()
        except Exception as e:
            self.failures.append((key, f"unreadable: {e!r}"))
            return -1

        src = self.scene.file_of(sprite_obj)
        rd = d.get("m_RD") or {}
        name = d.get("m_Name") or f"sprite_{sprite_obj.path_id}"

        rect = d.get("m_Rect") or {}
        pivot = d.get("m_Pivot") or {"x": 0.5, "y": 0.5}
        ppu = float(d.get("m_PixelsToUnits") or 100.0)
        border = d.get("m_Border") or {"x": 0, "y": 0, "z": 0, "w": 0}

        tex_ptr = rd.get("texture")
        tex_obj = self.scene.resolve(tex_ptr, src) if tex_ptr else None
        tex_rect = rd.get("textureRect")
        rect_offset = rd.get("textureRectOffset") or {"x": 0.0, "y": 0.0}
        settings_raw = rd.get("settingsRaw") or 0

        if tex_obj is None:
            # Atlas-packed: look the sprite up by its render data key.
            nk = _key_of(d.get("m_RenderDataKey"))
            hit = self._atlas_map.get(nk) if nk else None
            if hit is None:
                self.failures.append((key, f"'{name}': no texture and no atlas entry"))
                return -1
            adata, afile = hit
            tex_obj = self.scene.resolve(adata.get("texture"), afile)
            tex_rect = adata.get("textureRect")
            rect_offset = adata.get("textureRectOffset") or {"x": 0.0, "y": 0.0}
            settings_raw = adata.get("settingsRaw") or 0
            if tex_obj is None:
                self.failures.append((key, f"'{name}': atlas entry has no texture"))
                return -1

        if not tex_rect:
            self.failures.append((key, f"'{name}': no textureRect"))
            return -1

        page = self._page_index(tex_obj, src)

        # Pivot correction for trimmed (tight-packed) sprites.
        #
        # m_Pivot is normalised against the sprite's *original* untrimmed rect, but
        # Sprite.Create takes a pivot normalised against the rect we hand it - which is
        # the trimmed textureRect. textureRectOffset is where the trimmed rect sits
        # inside the original, so shift by it before renormalising. Skipping this makes
        # every trimmed sprite sit visibly off-position.
        ow = float(rect.get("width") or 0.0)
        oh = float(rect.get("height") or 0.0)
        tw = float(tex_rect.get("width") or 0.0)
        th = float(tex_rect.get("height") or 0.0)

        if tw > 0 and th > 0 and ow > 0 and oh > 0:
            pivot_px_x = float(pivot.get("x", 0.5)) * ow
            pivot_px_y = float(pivot.get("y", 0.5)) * oh
            px = (pivot_px_x - float(rect_offset.get("x", 0.0))) / tw
            py = (pivot_px_y - float(rect_offset.get("y", 0.0))) / th
        else:
            px = float(pivot.get("x", 0.5))
            py = float(pivot.get("y", 0.5))

        idx = len(self.sprites)
        self.sprites.append({
            "name": name,
            # Bits 2-4 of settingsRaw are the packing rotation: the sprite is stored in
            # the atlas with this transform already applied, so it has to be undone when
            # the rect is cropped out. Roughly one Godhome sprite in eight is affected,
            # and ignoring it renders them mirrored or upside down.
            "pack_rot": (settings_raw >> 2) & 7,
            "page": page,
            "rect": (float(tex_rect.get("x", 0.0)), float(tex_rect.get("y", 0.0)), tw, th),
            "pivot": (px, py),
            "ppu": ppu,
            "border": (float(border.get("x", 0)), float(border.get("y", 0)),
                       float(border.get("z", 0)), float(border.get("w", 0))),
        })
        self._sprites[key] = idx
        return idx

    # ------------------------------------------------------------------

    def write_table(self, w: Writer):
        names = self.page_names if self.page_names is not None else [n for _, n in self.pages]
        w.i32(len(names))
        for name in names:
            w.string(name)

        w.i32(len(self.sprites))
        for s in self.sprites:
            w.string(s["name"])
            w.i32(s["page"])
            w.f32(s["rect"][0]); w.f32(s["rect"][1]); w.f32(s["rect"][2]); w.f32(s["rect"][3])
            w.vec2(*s["pivot"])
            w.f32(s["ppu"])
            w.f32(s["border"][0]); w.f32(s["border"][1])
            w.f32(s["border"][2]); w.f32(s["border"][3])

    def export_pages(self, out_dir, log):
        """Write each atlas page as a PNG. Returns total bytes."""
        import os
        total = 0
        for tex_obj, name in self.pages:
            path = os.path.join(out_dir, f"{name}.png")
            try:
                img = tex_obj.read().image
                img.save(path)
                total += os.path.getsize(path)
            except Exception as e:
                log(f"  ! page '{name}' failed to export: {e!r}")
        return total
