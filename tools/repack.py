"""
Repack the sprites a scene actually uses into tight atlas pages.

Baking whole Hollow Knight atlas pages is wasteful: GG_Atrium uses 106 sprites but
they're spread across 24 shared pages totalling ~16 MB, nearly all of it sprites for
other scenes. Since this data gets embedded into the mod DLL, we crop out just the
rects in use and shelf-pack them into fresh pages.

Coordinate systems, because they bite here:
  * Unity sprite rects are bottom-left origin.
  * UnityPy hands back a PIL image that is top-left origin (already flipped upright).
So cropping and placement convert both ways, and the rects written to the baked file
are converted back to bottom-left so Sprite.Create sees what it expects.
"""

from PIL import Image

MAX_PAGE = 2048
PAD = 2


def _shelf_pack(sizes, max_page=MAX_PAGE, pad=PAD):
    """
    Classic shelf packer: sort by height, lay out rows.

    Returns (placements, pages) where placements[i] = (page, x, y_top) and
    pages = [(width, height), ...].
    """
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0]))
    placements = [None] * len(sizes)
    pages = []

    page = 0
    x = y = shelf_h = 0
    used_w = used_h = 0

    def new_page():
        nonlocal page, x, y, shelf_h, used_w, used_h
        pages.append((max(used_w, 1), max(used_h, 1)))
        page += 1
        x = y = shelf_h = 0
        used_w = used_h = 0

    for i in order:
        w, h = sizes[i]
        w += pad
        h += pad
        if w > max_page or h > max_page:
            # Oversized sprite gets a page to itself rather than being dropped.
            if used_w or used_h:
                new_page()
            placements[i] = (page, 0, 0)
            pages.append((w, h))
            page += 1
            x = y = shelf_h = 0
            used_w = used_h = 0
            continue

        if x + w > max_page:          # next shelf
            y += shelf_h
            x = 0
            shelf_h = 0
        if y + h > max_page:          # next page
            new_page()

        placements[i] = (page, x, y)
        x += w
        shelf_h = max(shelf_h, h)
        used_w = max(used_w, x)
        used_h = max(used_h, y + shelf_h)

    pages.append((max(used_w, 1), max(used_h, 1)))
    return placements, pages


# Unity SpriteSettings packing rotation (settingsRaw bits 2-4).
PACK_NONE = 0
PACK_FLIP_H = 1
PACK_FLIP_V = 2
PACK_ROT_180 = 3
PACK_ROT_90 = 4


def unpack_rotation(img, pack_rot):
    """
    Undo the transform Unity applied when it packed this sprite into the atlas.

    The atlas stores the pixels already rotated/mirrored; the engine reverses it via the
    sprite's UVs. We crop straight out of the page, so the reversal has to happen here or
    those sprites come out mirrored - or, for rot180, upside down.
    """
    if pack_rot == PACK_FLIP_H:
        return img.transpose(Image.FLIP_LEFT_RIGHT)
    if pack_rot == PACK_FLIP_V:
        return img.transpose(Image.FLIP_TOP_BOTTOM)
    if pack_rot == PACK_ROT_180:
        return img.transpose(Image.ROTATE_180)
    if pack_rot == PACK_ROT_90:
        # Stored rotated 90; the rect's width/height are swapped relative to the sprite.
        return img.transpose(Image.ROTATE_270)
    return img


def premultiply(img):
    """
    RGB *= alpha, so the sprite can be drawn additively.

    Hollow Knight draws Godhome's glows and hazes with UI/BlendModes/Screen, which
    Silksong doesn't have. Additive is the closest shader it does ship, and additive
    ignores alpha for blending - so a soft-edged white haze would otherwise add at full
    strength across its whole quad and read as a bright rectangle. Folding alpha into
    the colour first restores the falloff.
    """
    r, g, b, a = img.split()
    from PIL import ImageChops
    return Image.merge("RGBA", (ImageChops.multiply(r, a),
                                ImageChops.multiply(g, a),
                                ImageChops.multiply(b, a),
                                a))


def repack(baker, scene_name, screen_sprites, log):
    """
    Rewrites baker.sprites to point at newly built pages.

    Returns a list of (name, PIL.Image) to write out, replacing baker.pages.
    """
    # Source page images, loaded once.
    src_images = []
    for tex_obj, name in baker.pages:
        try:
            src_images.append(tex_obj.read().image)
        except Exception as e:
            log(f"  ! source page '{name}' unreadable ({e!r}); its sprites will be dropped")
            src_images.append(None)

    crops = []
    keep = []
    for i, s in enumerate(baker.sprites):
        img = src_images[s["page"]]
        if img is None:
            continue
        x, y, w, h = s["rect"]
        w_i, h_i = int(round(w)), int(round(h))
        if w_i <= 0 or h_i <= 0:
            continue
        # bottom-left (Unity) -> top-left (PIL)
        left = int(round(x))
        top = img.height - int(round(y)) - h_i
        box = (max(0, left), max(0, top),
               min(img.width, left + w_i), min(img.height, top + h_i))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        crop = img.crop(box).convert("RGBA")
        crop = unpack_rotation(crop, s.get("pack_rot", 0))
        if i in screen_sprites:
            crop = premultiply(crop)
        crops.append(crop)
        keep.append(i)

    if not crops:
        log("  ! nothing to repack")
        return None

    sizes = [(c.width, c.height) for c in crops]
    placements, page_sizes = _shelf_pack(sizes)

    pages = [Image.new("RGBA", (max(w, 1), max(h, 1)), (0, 0, 0, 0)) for w, h in page_sizes]
    for n, i in enumerate(keep):
        page, px, py = placements[n]
        pages[page].paste(crops[n], (px, py))

    # Point every kept sprite at its new home, converting back to bottom-left.
    for n, i in enumerate(keep):
        page, px, py = placements[n]
        c = crops[n]
        ph = pages[page].height
        baker.sprites[i]["page"] = page
        baker.sprites[i]["rect"] = (float(px), float(ph - py - c.height),
                                    float(c.width), float(c.height))

    # Drop sprites whose source page was unreadable, remapping object references.
    kept = set(keep)
    remap = {}
    new_sprites = []
    for i, s in enumerate(baker.sprites):
        if i in kept:
            remap[i] = len(new_sprites)
            new_sprites.append(s)
    baker.sprites = new_sprites
    baker.sprite_remap = remap

    # Page names double as embedded-resource names, so they must be unique
    # across every baked scene.
    named = [(f"{scene_name}_page_{i}", p) for i, p in enumerate(pages)]
    before = sum(1 for im in src_images if im is not None)
    log(f"    repacked {len(new_sprites)} sprites from {before} source pages "
        f"into {len(named)} page(s) " +
        ", ".join(f"{p.width}x{p.height}" for _, p in named))
    return named
