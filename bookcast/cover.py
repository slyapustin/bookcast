from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

# Apple Podcasts requires 1400x1400 minimum, square, JPG/PNG.
_TARGET = (1400, 1400)


def render_cover(*, raw: bytes | None, title: str, author: str | None, out_path: Path) -> Path:
    """Produce a 1400x1400 JPG suitable for Apple Podcasts artwork."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if raw:
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            padded = _pad_square(img)
            padded.save(out_path, "JPEG", quality=88)
            return out_path
        except Exception:
            pass  # fall through to generated cover
    _generate_text_cover(title=title, author=author).save(out_path, "JPEG", quality=88)
    return out_path


def _pad_square(img: Image.Image) -> Image.Image:
    bg = _dominant_edge_color(img)
    return ImageOps.pad(img, _TARGET, color=bg, method=Image.Resampling.LANCZOS)


def _dominant_edge_color(img: Image.Image) -> tuple[int, int, int]:
    small = img.resize((40, 60))
    pixels = list(small.getdata())
    edge: list[tuple[int, int, int]] = []
    w, h = small.size
    for x in range(w):
        edge.append(pixels[x])
        edge.append(pixels[(h - 1) * w + x])
    for y in range(h):
        edge.append(pixels[y * w])
        edge.append(pixels[y * w + (w - 1)])
    r = sum(p[0] for p in edge) // len(edge)
    g = sum(p[1] for p in edge) // len(edge)
    b = sum(p[2] for p in edge) // len(edge)
    return (r, g, b)


def _generate_text_cover(*, title: str, author: str | None) -> Image.Image:
    bg = _color_from_string(title)
    img = Image.new("RGB", _TARGET, bg)
    draw = ImageDraw.Draw(img)
    title_font = _load_font(140)
    author_font = _load_font(70)
    margin = 100
    max_width = _TARGET[0] - 2 * margin

    title_lines = _wrap(draw, title, title_font, max_width)
    line_height = title_font.size + 30
    total_h = len(title_lines) * line_height
    y = (_TARGET[1] - total_h) // 2 - 60
    for line in title_lines:
        w = draw.textlength(line, font=title_font)
        draw.text(((_TARGET[0] - w) // 2, y), line, font=title_font, fill=(255, 255, 255))
        y += line_height
    if author:
        author_text = author
        w = draw.textlength(author_text, font=author_font)
        draw.text(((_TARGET[0] - w) // 2, y + 40), author_text, font=author_font, fill=(230, 230, 230))
    return img


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        candidate = f"{cur} {w}"
        if draw.textlength(candidate, font=font) <= max_w:
            cur = candidate
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _color_from_string(s: str) -> tuple[int, int, int]:
    h = abs(hash(s))
    palette = ["#1F3A5F", "#2A4D69", "#3E2F5B", "#5B2A2A", "#2F4F4F", "#264653", "#5C374C"]
    return ImageColor.getrgb(palette[h % len(palette)])


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size=size)
        except OSError:
            continue
    return ImageFont.load_default()
