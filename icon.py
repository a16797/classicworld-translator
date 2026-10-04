"""The app logo: the in-game "Reddened Maple Leaf" item sprite (红枫叶, item 03994011).

Source: https://mscw-guidebook.com/generated/assets/items/03994011.png, saved as data/logo-leaf.png.
Pixel art is enlarged by whole multiples (nearest neighbour) so edges stay crisp.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

_BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
SPRITE = _BASE / "data" / "logo-leaf.png"


def make_icon(size: int = 64) -> Image.Image:
    """Square transparent icon with the leaf centred."""
    sprite = Image.open(SPRITE).convert("RGBA")
    sprite = sprite.crop(sprite.getbbox())
    side = max(sprite.size)
    factor = size // side
    if factor >= 2:  # room for a whole multiple: perfectly crisp pixels
        leaf = sprite.resize((sprite.width * factor, sprite.height * factor), Image.Resampling.NEAREST)
    else:  # fit exactly: enlarge crisply first, then scale down smoothly
        big = sprite.resize((sprite.width * 8, sprite.height * 8), Image.Resampling.NEAREST)
        ratio = size / (side * 8)
        leaf = big.resize((max(1, round(big.width * ratio)), max(1, round(big.height * ratio))),
                          Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(leaf, ((size - leaf.width) // 2, (size - leaf.height) // 2))
    return canvas
