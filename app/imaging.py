"""Image fingerprinting: Pillow decodes, the C++ core hashes and searches."""
import io

import numpy as np
from PIL import Image, ImageOps

import rentshield_core as core

MAX_DISTANCE = 10        # pHash Hamming distance (out of 64) that still counts as the same photo
MAX_DHASH_DISTANCE = 16  # dHash must also agree, which cuts false matches between similar-looking rooms

_index = core.ImageIndex()


def _load(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    return img.convert("L")


def _hash_pair(img: Image.Image) -> tuple[int, int]:
    p = np.asarray(img.resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
    d = np.asarray(img.resize((9, 8), Image.Resampling.LANCZOS), dtype=np.float64)
    return core.phash(p), core.dhash(d)


def _center_crop(img: Image.Image, keep: float) -> Image.Image:
    w, h = img.size
    cw, ch = int(w * keep), int(h * keep)
    left, top = (w - cw) // 2, (h - ch) // 2
    return img.crop((left, top, left + cw, top + ch))


def fingerprint(data: bytes, variants: bool = True) -> tuple[list[int], list[int]]:
    """Hash the full photo, plus crop/mirror variants so edited re-uploads still match."""
    img = _load(data)
    imgs = [img]
    if variants:
        imgs += [_center_crop(img, k) for k in (0.9, 0.8, 0.7)]
        imgs.append(ImageOps.mirror(img))
    pairs = [_hash_pair(i) for i in imgs]
    return [p for p, _ in pairs], [d for _, d in pairs]


def validate_image(data: bytes) -> None:
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types
        raise ValueError("Not a valid image file") from exc


def index_add(listing_id: str, image_id: str, phashes: list[int], dhashes: list[int]) -> None:
    _index.add(listing_id, image_id, phashes, dhashes)


def index_query(data: bytes, exclude_listing: str = ""):
    # Query with the full frame and a mirror; stored crop variants cover cropping.
    img = _load(data)
    pairs = [_hash_pair(img), _hash_pair(ImageOps.mirror(img))]
    matches = _index.query([p for p, _ in pairs], [d for _, d in pairs], MAX_DISTANCE, exclude_listing)
    return [m for m in matches if m.dhash_distance <= MAX_DHASH_DISTANCE]


def index_size() -> int:
    return _index.size()


def index_reset() -> None:
    _index.clear()
