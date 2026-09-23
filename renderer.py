"""
Renders word-highlighted captions onto a video.
Supports two highlight styles:
  - "color": the active word's text switches to word_highlight_color (classic karaoke)
  - "box":   the active word gets a rounded pill/background behind it (VK/CapCut ad style)

Takes pre-computed word-level segments (see transcribe.py) so transcription and
rendering are decoupled - you can re-render with a new style without re-transcribing.
"""

import os
import sys
import json
import copy
import math

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import VideoFileClip, ImageClip, CompositeVideoClip, vfx
import proglog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import segment_parser
from typography import is_hanging as _is_hanging

DEFAULT_STYLE = {
    "font": "fonts/Montserrat-var.ttf#ExtraBold",
    "font_size": 90,
    "text_case": "upper",           # "upper" | "lower" | "none" (as recognised)

    "text_color": "#FFFFFF",
    "stroke_color": "#000000",
    "stroke_width": 2,

    "shadow_enabled": True,
    "shadow_color": "#000000",
    "shadow_opacity": 0.55,
    "shadow_blur": 8,
    "shadow_offset": [0, 4],

    # A second, independent shadow drawn under the first (e.g. a soft wide
    # glow under a tight drop shadow).
    "shadow2_enabled": False,
    "shadow2_color": "#000000",
    "shadow2_opacity": 0.35,
    "shadow2_blur": 18,
    "shadow2_offset": [0, 10],

    "highlight_style": "box",       # "color" | "box" | "none"
    "word_highlight_color": "#FF3B30",
    "active_text_color": "#FFFFFF",
    "box_color": "#3FA9E8",
    "box_opacity": 1.0,
    "box_radius": 16,
    "box_padding_x": 20,
    "box_padding_y": 10,

    "line_count": 1,
    "max_width_ratio": 0.86,
    "line_spacing": 1.18,

    # How words become captions: "phrases" (as many as fit), "sentences"
    # (no full stops, each sentence starts a new caption) or "words" (one word
    # at a time, no punctuation). Older presets carry sentence_breaks instead,
    # which is why neither key has a default here: see caption_mode().

    "position": "bottom",           # "bottom" | "center" | "top"
    "position_margin": 190,

    # How a caption arrives on screen: "none" | "fade" | "pop" | "rise".
    "word_animation": "none",
    "word_animation_ms": 220,
}

# Manual titles ("Заголовки"): static text shown between two timestamps. No
# case transform and no line limit - the text is wrapped and shrunk until it
# fits the block. The word highlight becomes a plain static effect: a plate
# behind the text ("box") or another text colour ("color").
TITLE_STYLE = {
    "font": "fonts/Montserrat-var.ttf#ExtraBold",
    "font_size": 96,

    "text_color": "#FFFFFF",
    "stroke_color": "#000000",
    "stroke_width": 0,

    "shadow_enabled": True,
    "shadow_color": "#000000",
    "shadow_opacity": 0.55,
    "shadow_blur": 8,
    "shadow_offset": [0, 4],

    "shadow2_enabled": False,
    "shadow2_color": "#000000",
    "shadow2_opacity": 0.35,
    "shadow2_blur": 18,
    "shadow2_offset": [0, 10],

    "highlight_style": "none",      # "box" | "color" | "none"
    "word_highlight_color": "#FF3B30",
    "active_text_color": "#FFFFFF",
    "box_color": "#3FA9E8",
    "box_opacity": 1.0,
    "box_radius": 16,
    "box_padding_x": 24,
    "box_padding_y": 12,

    "max_width_ratio": 0.86,
    "line_spacing": 1.18,

    "position": "center",
    "position_margin": 190,
    # Horizontal shift from the centre, in source pixels: minus left, plus
    # right. Clamped at render time so a title never leaves the frame.
    "offset_x": 0,

    # Arrival and departure, set apart: each has a switch, a kind and a length.
    "anim_in_enabled": True,
    "anim_in_kind": "fade",
    "anim_in_ms": 400,
    "anim_out_enabled": True,
    "anim_out_kind": "fade",
    "anim_out_ms": 400,
}

# What a title can do on its way in and out. A side means where it comes from
# (in) or where it leaves to (out).
TITLE_ANIMATIONS = ("fade", "slide_left", "slide_right", "slide_up", "slide_down", "zoom", "blur")
_BLUR_STEPS = 10

def _hex_to_rgba(color, opacity=1.0):
    if isinstance(color, (list, tuple)):
        r, g, b = color[:3]
    else:
        color = color.lstrip("#")
        if len(color) == 3:
            color = "".join(c * 2 for c in color)
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    return (r, g, b, int(255 * opacity))

def _case_transform(style):
    """Returns the text transform, or None to keep the recognised casing.

    Accepts the old boolean `uppercase` key so presets saved before text_case
    existed keep working.
    """
    mode = style.get("text_case")
    if mode is None:
        mode = "upper" if style.get("uppercase") else "none"
    if mode == "upper":
        return str.upper
    if mode == "lower":
        return str.lower
    return None

def _resolve_font_path(style_or_path):
    path = style_or_path["font"] if isinstance(style_or_path, dict) else style_or_path
    file_path, sep, variation = path.partition("#")
    if not os.path.isabs(file_path):
        file_path = os.path.join(os.path.dirname(__file__), file_path)
    return file_path + sep + variation

def _load_font(style):
    return ImageFont.truetype(_resolve_font_path(style), style["font_size"])

_font_cache = {}

# The faces shipped with the app. Single source of truth for both the GUI
# dropdown and fontlist.py; css_family must match a @font-face in index.html.
BUNDLED_FONT_LABELS = {
    "fonts/Montserrat-var.ttf#ExtraBold": {"label": "Montserrat ExtraBold", "css_family": "Montserrat", "css_weight": 800, "cyrillic": True},
    "fonts/Montserrat-var.ttf#Bold": {"label": "Montserrat Bold", "css_family": "Montserrat", "css_weight": 700, "cyrillic": True},
    "fonts/FiraSans-ExtraBold.ttf": {"label": "Fira Sans ExtraBold", "css_family": "Fira Sans ExtraBold", "css_weight": 400, "cyrillic": True},
    "fonts/FiraSans-Black.ttf": {"label": "Fira Sans Black", "css_family": "Fira Sans Black", "css_weight": 400, "cyrillic": True},
    "fonts/FiraSans-Medium.ttf": {"label": "Fira Sans Medium", "css_family": "Fira Sans Medium", "css_weight": 400, "cyrillic": True},
    "fonts/Oswald-var.ttf#Bold": {"label": "Oswald Bold", "css_family": "Oswald", "css_weight": 700, "cyrillic": True},
    "fonts/Rubik-var.ttf#ExtraBold": {"label": "Rubik ExtraBold", "css_family": "Rubik", "css_weight": 800, "cyrillic": True},
    "fonts/PTSans-Bold.ttf": {"label": "PT Sans Bold", "css_family": "PT Sans Bold", "css_weight": 400, "cyrillic": True},
    "fonts/BebasNeue-Regular.ttf": {"label": "Bebas Neue", "css_family": "Bebas Neue", "css_weight": 400, "cyrillic": True},
    "fonts/Poppins-ExtraBold.ttf": {"label": "Poppins ExtraBold", "css_family": "Poppins ExtraBold", "css_weight": 400, "cyrillic": False},
    "fonts/Poppins-Black.ttf": {"label": "Poppins Black", "css_family": "Poppins Black", "css_weight": 400, "cyrillic": False},
    "fonts/Anton-Regular.ttf": {"label": "Anton", "css_family": "Anton", "css_weight": 400, "cyrillic": False},
    "fonts/ArchivoBlack-Regular.ttf": {"label": "Archivo Black", "css_family": "Archivo Black", "css_weight": 400, "cyrillic": False},
    "fonts/Bangers-Regular.ttf": {"label": "Bangers", "css_family": "Bangers", "css_weight": 400, "cyrillic": False},
}

# Tried in order when the chosen font has no glyph for the text (e.g. a
# latin-only display face picked for Russian speech).
FALLBACK_FONTS = [
    "fonts/Montserrat-var.ttf#ExtraBold",
    "fonts/FiraSans-ExtraBold.ttf",
    "fonts/Rubik-var.ttf#Bold",
    "fonts/PTSans-Bold.ttf",
]

def _get_font(path, size):
    """Path may carry a variable-font instance: "Montserrat-var.ttf#ExtraBold"."""
    key = (path, size)
    if key not in _font_cache:
        file_path, _, variation = path.partition("#")
        font = ImageFont.truetype(file_path, size)
        if variation:
            font.set_variation_by_name(variation)
        _font_cache[key] = font
    return _font_cache[key]

def _glyph_raster(font, ch):
    mask = font.getmask(ch)
    return bytes(mask) if mask.size != (0, 0) else b""

def _font_covers(font, text):
    """True if every visible character renders as something other than .notdef."""
    notdef = _glyph_raster(font, "")
    return all(_glyph_raster(font, ch) != notdef for ch in set(text) if ch.strip())

def _fit_font_for_lines(lines, font_path, base_font, base_size, stroke_width, max_width, draw, extra_gap=0, min_scale=0.4):
    """Shrinks the font just enough that every line in this chunk fits within
    max_width, so long words / large font sizes can never draw past the frame
    edge. Returns (font, style_scale) - style_scale also shrinks padding/stroke
    proportionally so the box highlight stays visually consistent."""
    scale = 1.0
    for line_words in lines:
        text = " ".join(line_words)
        width, _ = _measure(draw, text, base_font, stroke_width)
        width += extra_gap * (len(line_words) - 1)
        if width > max_width > 0:
            scale = min(scale, max_width / width)
    if scale >= 0.999:
        return base_font, 1.0
    scale = max(scale, min_scale)
    new_size = max(10, int(base_size * scale))
    return _get_font(font_path, new_size), new_size / base_size

def _text_bbox(draw, text, font, stroke_width):
    """Ink bounds relative to the draw origin. bbox[1] is > 0 because text is
    drawn from the ascender line, not from the top of the glyphs - the box
    highlight has to account for that or it sits too high."""
    return draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)

def _measure(draw, text, font, stroke_width):
    bbox = _text_bbox(draw, text, font, stroke_width)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

def _line_width(draw, words, font, stroke_width, extra_gap):
    if not words:
        return 0
    width, _ = _measure(draw, " ".join(words), font, stroke_width)
    return width + extra_gap * (len(words) - 1)

def _wrap_into_lines(draw, words, font, stroke_width, max_width, max_lines, extra_gap=0):
    """Greedy word-wrap. Returns None if it doesn't fit within max_lines.
    extra_gap mirrors the per-word gap the renderer adds for pill highlights so
    wrapping and drawing agree on how wide a line really is."""
    lines = []
    current = []
    for w in words:
        trial = current + [w]
        if _line_width(draw, trial, font, stroke_width, extra_gap) <= max_width or not current:
            current = trial
            continue

        # Line is full. Pull any trailing prepositions/conjunctions down with
        # the word they belong to - but only while the new line still fits,
        # so typography never causes an overflow.
        carry = []
        while len(current) > 1 and _is_hanging(current[-1]):
            candidate = [current[-1]] + carry + [w]
            if _line_width(draw, candidate, font, stroke_width, extra_gap) > max_width:
                break
            carry.insert(0, current.pop())

        lines.append(current)
        current = carry + [w]
        if len(lines) > max_lines:
            return None
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        return None
    return lines

def _fit_function(draw, font, stroke_width, max_width, max_lines, extra_gap=0):
    def fits(text):
        words = text.split()
        return _wrap_into_lines(draw, words, font, stroke_width, max_width, max_lines, extra_gap) is not None
    return fits

_cap_band_cache = {}

def _cap_band(draw, font, stroke_width):
    """Offsets of the capital-letter band relative to the draw origin:
    (top of a capital, baseline). This is the band the eye reads as 'the text',
    so the pill is centred on it rather than on the ink bounding box - letters
    like Д, Ц, Щ hang below the baseline and would otherwise push the whole
    pill down and leave the word sitting optically high."""
    key = (id(font), stroke_width)
    if key not in _cap_band_cache:
        bbox = _text_bbox(draw, "НXО", font, stroke_width)
        _cap_band_cache[key] = (bbox[1], bbox[3])
    return _cap_band_cache[key]

def pill_vertical_band(draw, positions, font, stroke_width, pad_y):
    """Top and bottom of the word highlight, relative to the line's draw origin.

    Optical centring: the pill is built around the capital band with equal
    padding rather than around the ink box, so a word is never pushed off
    centre by neighbours that happen to have descenders.

    The top edge follows the capital line only - diacritics (the breve on Й)
    are allowed to overhang, as they do in hand-made captions, because letting
    them lift the pill unbalances every other word on the line. Descenders
    (Д, Ц, Щ) are part of the letterform, so the bottom does grow for them.

    Measured across the whole line, so the pill keeps a constant height as it
    steps from word to word.
    """
    cap_top, baseline = _cap_band(draw, font, stroke_width)
    band_bottom = max(p["ink_bottom"] for p in positions)
    inner = pad_y * 0.4     # descenders keep a little breathing room
    return cap_top - pad_y, max(baseline + pad_y, band_bottom + inner)

def _word_gap_for(style):
    """Pill highlights bleed box_padding_x past each side of the active word."""
    return style["box_padding_x"] * 1.6 if style["highlight_style"] == "box" else 0

def _valid_safe_inset(value):
    if isinstance(value, bool):
        return None
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    return ratio if math.isfinite(ratio) and 0.0 <= ratio <= 0.5 else None

def _shadow_layers(style):
    """Enabled shadows as (rgba, blur, (dx, dy)), bottom layer first."""
    layers = []
    for prefix in ("shadow2", "shadow"):
        if not style.get(f"{prefix}_enabled"):
            continue
        offset = style.get(f"{prefix}_offset") or [0, 0]
        try:
            dx, dy = float(offset[0] or 0), float(offset[1] or 0)
        except (TypeError, ValueError, IndexError):
            dx, dy = 0.0, 0.0
        layers.append((
            _hex_to_rgba(style.get(f"{prefix}_color") or "#000000",
                         max(0.0, min(1.0, float(style.get(f"{prefix}_opacity", 0.5) or 0)))),
            max(0.0, float(style.get(f"{prefix}_blur", 0) or 0)),
            (dx, dy),
        ))
    return layers

def _visual_overflow(style, position):
    pill = max(0.0, float(style.get("box_padding_y", 0) or 0)) \
        if style.get("highlight_style") == "box" else 0.0
    stroke = max(0.0, float(style.get("stroke_width", 0) or 0))
    bleed = 0.0
    for _rgba, blur, (_dx, dy) in _shadow_layers(style):
        directional_offset = max(0.0, -dy) if position == "top" else max(0.0, dy)
        bleed = max(bleed, math.ceil(2.5 * blur) + directional_offset)
    return max(pill, stroke) + bleed

def _effective_position_margin(style, video_h):
    try:
        manual = max(0, int(float(style.get("position_margin", 0) or 0)))
    except (TypeError, ValueError, OverflowError):
        manual = 0

    ratio = _valid_safe_inset(style.get("position_safe_inset_ratio"))
    position = style.get("position")
    if (style.get("position_mode") != "safe" or ratio is None
            or position not in {"top", "bottom"} or video_h <= 0):
        return manual
    return max(0, math.ceil(video_h * ratio + _visual_overflow(style, position)))

def _layout_line(draw, words, font, stroke_width, extra_gap=0):
    space_w, _ = _measure(draw, " ", font, stroke_width)
    space_w += extra_gap
    positions = []
    x = 0
    for w in words:
        width, height = _measure(draw, w, font, stroke_width)
        bbox = _text_bbox(draw, w, font, stroke_width)
        positions.append({
            "word": w, "x": x, "width": width, "height": height,
            "ink_left": bbox[0], "ink_right": bbox[2],
            "ink_top": bbox[1], "ink_bottom": bbox[3],
        })
        x += width + space_w
    total_width = x - space_w if words else 0
    return positions, total_width

def _render_state_image(video_w, video_h, lines, active_line_idx, active_word_idx, font, style, max_width):
    stroke_width = style["stroke_width"]
    canvas = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    ascent, descent = font.getmetrics()
    line_height = int((ascent + descent) * style["line_spacing"])
    block_height = line_height * len(lines)

    position_margin = _effective_position_margin(style, video_h)
    if style["position"] == "bottom":
        block_top = video_h - position_margin - block_height
    elif style["position"] == "top":
        block_top = position_margin
    else:
        block_top = video_h // 2 - block_height // 2

    # Never let the caption block start above the top edge or spill past the
    # bottom edge, even with an aggressive position_margin/line_count combo.
    block_top = max(0, min(block_top, video_h - block_height))

    block_left = (video_w - max_width) // 2

    extra_gap = _word_gap_for(style)

    laid_out_lines = []
    for line_words in lines:
        positions, total_width = _layout_line(draw, line_words, font, stroke_width, extra_gap)
        line_offset = (max_width - total_width) // 2
        laid_out_lines.append((positions, line_offset))

    # Shadow passes: "Тень 2" first, the main shadow on top of it.
    for shadow_rgba, blur, (ox, oy) in _shadow_layers(style):
        shadow_layer = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        for li, (positions, line_offset) in enumerate(laid_out_lines):
            y = block_top + li * line_height
            for wp in positions:
                x = block_left + line_offset + wp["x"]
                shadow_draw.text((x + ox, y + oy), wp["word"], font=font, fill=shadow_rgba)
        if blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
        canvas = Image.alpha_composite(canvas, shadow_layer)
        draw = ImageDraw.Draw(canvas)

    # Box pass (drawn under text, above shadow)
    highlight_style = style["highlight_style"]
    if highlight_style == "box":
        box_rgba = _hex_to_rgba(style["box_color"], style["box_opacity"])
        positions, line_offset = laid_out_lines[active_line_idx]
        wp = positions[active_word_idx]
        y = block_top + active_line_idx * line_height
        x = block_left + line_offset + wp["x"]
        pad_x, pad_y = style["box_padding_x"], style["box_padding_y"]

        top, bottom = pill_vertical_band(draw, positions, font, stroke_width, pad_y)

        box_rect = [
            x + wp["ink_left"] - pad_x, y + top,
            x + wp["ink_right"] + pad_x, y + bottom,
        ]
        # Belt-and-suspenders: clamp to the canvas even if padding/scale math
        # above somehow leaves the pill touching an edge.
        box_rect = [
            max(0, box_rect[0]), max(0, box_rect[1]),
            min(video_w, box_rect[2]), min(video_h, box_rect[3]),
        ]
        draw.rounded_rectangle(box_rect, radius=style["box_radius"], fill=box_rgba)

    # Text pass
    text_rgba = _hex_to_rgba(style["text_color"])
    active_rgba = _hex_to_rgba(style.get("active_text_color", style["text_color"]))
    highlight_rgba = _hex_to_rgba(style.get("word_highlight_color", style["text_color"]))
    stroke_rgba = _hex_to_rgba(style["stroke_color"]) if stroke_width > 0 else None

    for li, (positions, line_offset) in enumerate(laid_out_lines):
        y = block_top + li * line_height
        for wi, wp in enumerate(positions):
            is_active = (li == active_line_idx and wi == active_word_idx)
            if is_active and highlight_style == "box":
                fill = active_rgba
            elif is_active and highlight_style == "color":
                fill = highlight_rgba
            else:
                fill = text_rgba
            x = block_left + line_offset + wp["x"]
            kwargs = {"fill": fill}
            if stroke_rgba:
                kwargs["stroke_width"] = stroke_width
                kwargs["stroke_fill"] = stroke_rgba
            draw.text((x, y), wp["word"], font=font, **kwargs)

    return canvas

def _ease_out_back(p):
    """0 -> 1 with a small overshoot, so a caption lands with a little bounce."""
    c = 1.70158
    q = p - 1.0
    return 1 + (c + 1) * q ** 3 + c * q ** 2


def _ease_out_cubic(p):
    """0 -> 1, fast then settling, without overshooting the target."""
    return 1 - (1 - p) ** 3


# How much of the animation the fade-in takes. Movement has to stay visible
# while the caption is still see-through: a pop that finishes under a fade
# reads as a plain fade.
_FADE_SHARE = {"fade": 1.0, "pop": 0.45, "rise": 0.6}


def _animation_for(style):
    """(kind, seconds) for the appearance animation, or (None, 0)."""
    kind = str(style.get("word_animation") or "none").lower()
    if kind not in ("fade", "pop", "rise"):
        return None, 0.0
    try:
        seconds = max(0.0, float(style.get("word_animation_ms", 0) or 0)) / 1000.0
    except (TypeError, ValueError):
        seconds = 0.0
    return (kind, seconds) if seconds > 0 else (None, 0.0)


def _image_clip(frame_img, start, duration, animation=(None, 0.0)):
    """An ImageClip cropped to the ink, placed where the ink was.

    Cropping keeps the clip small (a caption covers a fraction of the frame)
    and gives the animation a box to scale and move around, which a
    full-frame image cannot have.
    """
    import numpy as np

    bbox = frame_img.getbbox()
    if not bbox or duration <= 0:
        return None
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    clip = ImageClip(np.array(frame_img.crop(bbox)), transparent=True)
    clip = clip.with_start(start).with_duration(duration)

    kind, seconds = animation
    seconds = min(seconds, duration)
    if not kind or seconds <= 0:
        return clip.with_position((left, top))

    if kind == "pop":
        center_x, center_y = left + width / 2.0, top + height / 2.0

        def scale(t):
            if t >= seconds:
                return 1.0
            return 0.55 + 0.45 * _ease_out_back(t / seconds)

        clip = clip.resized(scale)
        clip = clip.with_position(
            lambda t: (center_x - width * scale(t) / 2.0, center_y - height * scale(t) / 2.0)
        )
    elif kind == "rise":
        travel = height * 0.8

        def offset(t):
            if t >= seconds:
                return 0.0
            return travel * (1.0 - _ease_out_cubic(t / seconds))

        clip = clip.with_position(lambda t: (left, top + offset(t)))
    else:
        clip = clip.with_position((left, top))

    # Fade is part of every animation: appearing hard while moving looks like
    # a glitch rather than an effect.
    try:
        clip = clip.with_effects([vfx.CrossFadeIn(seconds * _FADE_SHARE.get(kind, 1.0))])
    except Exception:
        pass
    return clip


def _wrap_free(draw, words, font, stroke_width, max_width):
    """Greedy wrap with no line limit - used by titles, which must simply fit."""
    lines, current = [], []
    for word in words:
        trial = current + [word]
        if _line_width(draw, trial, font, stroke_width, 0) <= max_width or not current:
            current = trial
            continue
        carry = []
        while len(current) > 1 and _is_hanging(current[-1]):
            candidate = [current[-1]] + carry + [word]
            if _line_width(draw, candidate, font, stroke_width, 0) > max_width:
                break
            carry.insert(0, current.pop())
        lines.append(current)
        current = carry + [word]
    if current:
        lines.append(current)
    return lines


def render_title_image(video_w, video_h, text, style):
    """Static title text, wrapped and shrunk until it fits the block."""
    merged = copy.deepcopy(TITLE_STYLE)
    if style:
        merged.update({k: v for k, v in style.items() if v is not None})
    style = merged

    text = " ".join(str(text).split())
    if not text:
        return None

    font_path = _resolve_font_path(style)
    if not _font_covers(_get_font(font_path, 32), text):
        for candidate in FALLBACK_FONTS:
            candidate_path = _resolve_font_path(candidate)
            if os.path.exists(candidate_path.partition("#")[0]) \
                    and _font_covers(_get_font(candidate_path, 32), text):
                font_path = candidate_path
                break

    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    stroke_width = int(style["stroke_width"])
    max_width = int(video_w * style["max_width_ratio"])
    if style["highlight_style"] == "box":
        max_width = min(max_width, video_w - 2 * (style["box_padding_x"] + 4))
    max_width = max(64, max_width)
    # Height budget: the text keeps its distance from the edge it is anchored
    # to, and must not run past the opposite one. A title that would need more
    # room is shrunk, never cropped.
    margin = _effective_position_margin(style, video_h)
    if style["position"] == "center":
        room = video_h - 2 * margin
    else:
        room = video_h - margin - int(video_h * 0.08)
    # A title stays a title: never past the free space, and never more than
    # about a third of the frame. Longer text is shrunk, never cropped.
    max_height = max(int(video_h * 0.22), min(room, int(video_h * 0.38)))

    words = text.split()
    size = max(10, int(style["font_size"]))
    for _ in range(60):   # shrink until the block fits both ways
        font = _get_font(font_path, size)
        lines = _wrap_free(draw, words, font, stroke_width, max_width)
        widest = max(_line_width(draw, line, font, stroke_width, 0) for line in lines)
        ascent, descent = font.getmetrics()
        line_height = int((ascent + descent) * style["line_spacing"])
        if (widest <= max_width and line_height * len(lines) <= max_height) or size <= 10:
            break
        size = max(10, int(size * 0.92))

    scale = size / max(1, int(style["font_size"]))
    pad_x = style["box_padding_x"] * scale
    pad_y = style["box_padding_y"] * scale
    radius = style["box_radius"] * scale

    block_height = line_height * len(lines)
    if style["position"] == "top":
        block_top = margin
    elif style["position"] == "bottom":
        block_top = video_h - margin - block_height
    else:
        block_top = video_h // 2 - block_height // 2
    block_top = max(0, min(block_top, video_h - block_height))

    canvas = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))
    measured = []
    for line_words in lines:
        line_text = " ".join(line_words)
        width, _ = _measure(draw, line_text, font, stroke_width)
        measured.append((line_text, width))

    # One shift for the whole block, so the lines keep their relative centring.
    # It stops at the frame edge: the widest line (plus its plate) decides how
    # much room is left, and the canvas is exactly the frame, so anything past
    # that would be cropped rather than moved.
    edge = pad_x + stroke_width if style["highlight_style"] == "box" else 0
    widest = max(width for _text, width in measured)
    room = max(0, (video_w - widest) // 2 - int(edge))
    shift = int(max(-room, min(int(style.get("offset_x") or 0), room)))

    laid_out = []
    for index, (line_text, width) in enumerate(measured):
        laid_out.append((line_text, (video_w - width) // 2 + shift,
                         block_top + index * line_height, width))

    for shadow_rgba, blur, (ox, oy) in _shadow_layers(style):
        layer = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)
        for line_text, x, y, _w in laid_out:
            layer_draw.text((x + ox, y + oy), line_text, font=font, fill=shadow_rgba)
        if blur > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(blur))
        canvas = Image.alpha_composite(canvas, layer)

    painter = ImageDraw.Draw(canvas)
    if style["highlight_style"] == "box":
        # Static version of the word pill: one plate behind each line.
        box_rgba = _hex_to_rgba(style["box_color"], style["box_opacity"])
        cap_top, baseline = _cap_band(painter, font, stroke_width)
        for line_text, x, y, width in laid_out:
            bbox = _text_bbox(painter, line_text, font, stroke_width)
            top = y + cap_top - pad_y
            bottom = y + max(baseline + pad_y, bbox[3] + pad_y * 0.4)
            painter.rounded_rectangle(
                [max(0, x - pad_x), max(0, top),
                 min(video_w, x + width + pad_x), min(video_h, bottom)],
                radius=radius, fill=box_rgba,
            )

    if style["highlight_style"] == "box":
        fill = _hex_to_rgba(style.get("active_text_color", style["text_color"]))
    elif style["highlight_style"] == "color":
        fill = _hex_to_rgba(style.get("word_highlight_color", style["text_color"]))
    else:
        fill = _hex_to_rgba(style["text_color"])
    kwargs = {"fill": fill}
    if stroke_width > 0:
        kwargs["stroke_width"] = stroke_width
        kwargs["stroke_fill"] = _hex_to_rgba(style["stroke_color"])
    for line_text, x, y, _w in laid_out:
        painter.text((x, y), line_text, font=font, **kwargs)

    return canvas


def _title_phase(style, phase):
    """(kind, seconds) for "in" or "out" of one title, or (None, 0)."""
    if not style.get(f"anim_{phase}_enabled"):
        return None, 0.0
    kind = str(style.get(f"anim_{phase}_kind") or "fade").lower()
    if kind not in TITLE_ANIMATIONS:
        return None, 0.0
    try:
        seconds = max(0.0, float(style.get(f"anim_{phase}_ms", 0) or 0)) / 1000.0
    except (TypeError, ValueError):
        seconds = 0.0
    return (kind, seconds) if seconds > 0 else (None, 0.0)


def _slide_offset(kind, left, top, width, height, video_w, video_h):
    """Where the title sits before it arrives (or after it leaves), in pixels
    relative to its place: just outside the frame on the named side."""
    if kind == "slide_left":
        return -(left + width), 0.0
    if kind == "slide_right":
        return video_w - left, 0.0
    if kind == "slide_up":
        return 0.0, -(top + height)
    if kind == "slide_down":
        return 0.0, video_h - top
    return 0.0, 0.0


def _blur_phase_clips(crop, left, top, start, duration, arriving, steps=_BLUR_STEPS):
    """A title melting out of (or into) a blur, as a short stack of stills.

    Blurring every frame on the fly would cost a Gaussian per frame; a handful
    of pre-blurred stills reads the same at these lengths.
    """
    import numpy as np

    width, height = crop.size
    radius = max(6.0, height * 0.18)
    pad = int(math.ceil(radius * 2.5))
    padded = Image.new("RGBA", (width + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    padded.paste(crop, (pad, pad))

    clips = []
    step = duration / steps
    for index in range(steps):
        share = (index + 0.5) / steps
        progress = share if arriving else 1.0 - share
        frame = padded.filter(ImageFilter.GaussianBlur(radius * (1.0 - progress)))
        alpha = frame.getchannel("A").point(lambda value, p=progress: int(value * p))
        frame.putalpha(alpha)
        clip = ImageClip(np.array(frame), transparent=True)
        clips.append(clip.with_start(start + index * step)
                         .with_duration(step)
                         .with_position((left - pad, top - pad)))
    return clips


def _title_clips_for(image, start, duration, video_w, video_h, anim_in, anim_out):
    """One title on screen: arrival, the still middle, and departure."""
    import numpy as np

    bbox = image.getbbox()
    if not bbox or duration <= 0:
        return []
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    crop = image.crop(bbox)

    in_kind, in_seconds = anim_in
    out_kind, out_seconds = anim_out
    # Neither half may eat the other: a 1 s title cannot fade in for 2 s.
    in_seconds = min(in_seconds, duration / 2.0) if in_kind else 0.0
    out_seconds = min(out_seconds, duration / 2.0) if out_kind else 0.0

    clips = []
    body_start, body_end = start, start + duration
    if in_kind == "blur":
        clips.extend(_blur_phase_clips(crop, left, top, start, in_seconds, True))
        body_start = start + in_seconds
    if out_kind == "blur":
        clips.extend(_blur_phase_clips(
            crop, left, top, start + duration - out_seconds, out_seconds, False))
        body_end = start + duration - out_seconds

    body = ImageClip(np.array(crop), transparent=True)
    body = body.with_start(body_start).with_duration(max(0.01, body_end - body_start))
    offset_into_title = body_start - start

    moving_in = in_kind and in_kind != "blur" and in_seconds > 0
    moving_out = out_kind and out_kind != "blur" and out_seconds > 0
    in_shift = _slide_offset(in_kind, left, top, width, height, video_w, video_h) if moving_in else (0.0, 0.0)
    out_shift = _slide_offset(out_kind, left, top, width, height, video_w, video_h) if moving_out else (0.0, 0.0)

    def phases(t):
        """(arrival progress, departure progress) at clip time t, 0..1 each."""
        elapsed = offset_into_title + t
        arrive = _ease_out_cubic(min(1.0, elapsed / in_seconds)) if moving_in else 1.0
        left_over = duration - elapsed
        depart = _ease_out_cubic(min(1.0, left_over / out_seconds)) if moving_out else 1.0
        return arrive, depart

    def scale(t):
        arrive, depart = phases(t)
        value = 1.0
        if in_kind == "zoom":
            value *= 0.6 + 0.4 * arrive
        if out_kind == "zoom":
            value *= 0.6 + 0.4 * depart
        return value

    def position(t):
        arrive, depart = phases(t)
        x, y = float(left), float(top)
        x += in_shift[0] * (1.0 - arrive) + out_shift[0] * (1.0 - depart)
        y += in_shift[1] * (1.0 - arrive) + out_shift[1] * (1.0 - depart)
        if in_kind == "zoom" or out_kind == "zoom":
            factor = scale(t)
            x = left + width / 2.0 - width * factor / 2.0 + (x - left)
            y = top + height / 2.0 - height * factor / 2.0 + (y - top)
        return x, y

    if in_kind == "zoom" or out_kind == "zoom":
        body = body.resized(scale)
    body = body.with_position(position if (moving_in or moving_out) else (left, top))

    # Fading belongs to every kind: sliding or zooming in at full opacity
    # looks like a jump cut.
    try:
        effects = []
        if moving_in:
            effects.append(vfx.CrossFadeIn(in_seconds))
        if moving_out:
            effects.append(vfx.CrossFadeOut(out_seconds))
        if effects:
            body = body.with_effects(effects)
    except Exception:
        pass

    clips.append(body)
    return clips


def title_style_for(style, index):
    """The style of title N: its own, the shared one, or the defaults."""
    styles = (style or {}).get("title_styles")
    chosen = None
    if isinstance(styles, (list, tuple)) and styles:
        chosen = styles[index] if index < len(styles) else styles[0]
    if not chosen:
        chosen = (style or {}).get("title_style")
    merged = copy.deepcopy(TITLE_STYLE)
    if chosen:
        merged.update({k: v for k, v in chosen.items() if v is not None})
    return merged


def title_clips(video_w, video_h, video_duration, overlays, style):
    """Clips for the manual titles. Each title carries its own style, so two
    of them can sit on screen at once, in different places and colours."""
    clips = []
    for index, overlay in enumerate(overlays or []):
        text = str((overlay or {}).get("text") or "").strip()
        if not text:
            continue
        try:
            start = max(0.0, float(overlay.get("start") or 0))
            end = float(overlay.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if video_duration:
            end = min(end, float(video_duration))
        if end <= start:
            continue
        title_style = title_style_for(style, index)
        image = render_title_image(video_w, video_h, text, title_style)
        if image is None:
            continue
        clips.extend(_title_clips_for(
            image, start, end - start, video_w, video_h,
            _title_phase(title_style, "in"), _title_phase(title_style, "out"),
        ))
    return clips


class _ProgressLogger(proglog.ProgressBarLogger):
    def __init__(self, cb):
        super().__init__()
        self._cb = cb

    def bars_callback(self, bar, attr, value, old_value=None):
        if self._cb is None or attr != "index":
            return
        total = self.bars[bar].get("total")
        if total:
            self._cb("rendering", int(100 * value / max(total, 1)))

def render_captions(video_path, segments, output_path, style=None, progress_cb=None, overlays=None):
    merged_style = copy.deepcopy(DEFAULT_STYLE)
    if style:
        merged_style.update(style)
    style = merged_style

    if progress_cb:
        progress_cb("preparing", 0)

    font_path = _resolve_font_path(style)
    font = _get_font(font_path, style["font_size"])

    all_text = "".join(w["word"] for seg in segments for w in seg["words"])
    if not _font_covers(font, all_text):
        for candidate in FALLBACK_FONTS:
            candidate_path = _resolve_font_path(candidate)
            if not os.path.exists(candidate_path.partition("#")[0]):
                continue
            candidate_font = _get_font(candidate_path, style["font_size"])
            if _font_covers(candidate_font, all_text):
                print(f"[renderer] '{os.path.basename(font_path)}' has no glyphs for this text, "
                      f"falling back to '{os.path.basename(candidate_path)}'")
                font_path, font = candidate_path, candidate_font
                break

    video = VideoFileClip(video_path)
    max_width = int(video.w * style["max_width_ratio"])
    if style["highlight_style"] == "box":
        # leave room so the pill's padding can never touch the frame edge
        max_width = min(max_width, video.w - 2 * (style["box_padding_x"] + 4))
    max_width = max(max_width, min(int(style["font_size"] * 1.5), video.w - 4))

    word_gap = _word_gap_for(style)
    tmp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    fit_fn = _fit_function(tmp_draw, font, style["stroke_width"], max_width, style["line_count"], word_gap)

    segments_copy = copy.deepcopy(segments)
    transform = _case_transform(style)
    if transform:
        for seg in segments_copy:
            for w in seg["words"]:
                lead = " " if w["word"][:1] == " " else ""
                w["word"] = lead + transform(w["word"].strip())

    mode = segment_parser.caption_mode(style)
    captions = segment_parser.parse(
        segments=segments_copy, fit_function=fit_fn,
        sentence_breaks=mode == "sentences", one_word=mode == "words",
    )

    animation = _animation_for(style)
    clips = [video]
    clips.extend(title_clips(video.w, video.h, video.duration, overlays, style))
    total_words = sum(len(c["words"]) for c in captions)
    done_words = 0

    for caption in captions:
        words = [w["word"].strip() for w in caption["words"]]
        lines = _wrap_into_lines(tmp_draw, words, font, style["stroke_width"], max_width, style["line_count"], word_gap) or [words]

        # Even though the chunk was accepted by fit_fn at the base font size,
        # a single very long word can still be wider than max_width (the
        # wrapper always places it alone rather than dropping it). Shrink the
        # font for this chunk so it's guaranteed to stay inside the frame.
        chunk_font, scale = _fit_font_for_lines(lines, font_path, font, style["font_size"], style["stroke_width"], max_width, tmp_draw, word_gap)
        if scale < 1.0:
            chunk_style = dict(style)
            chunk_style["box_padding_x"] = style["box_padding_x"] * scale
            chunk_style["box_padding_y"] = style["box_padding_y"] * scale
            chunk_style["box_radius"] = style["box_radius"] * scale
            if style["stroke_width"] > 0:
                chunk_style["stroke_width"] = max(1, int(style["stroke_width"] * scale))
        else:
            chunk_style = style

        # figure out which (line_idx, word_idx) each caption-word maps to
        flat_positions = []
        for li, line in enumerate(lines):
            for wi in range(len(line)):
                flat_positions.append((li, wi))

        for i, word in enumerate(caption["words"]):
            start = word["start"]
            end = caption["words"][i + 1]["start"] if i + 1 < len(caption["words"]) else word["end"]
            if end <= start:
                continue

            active_line_idx, active_word_idx = flat_positions[i] if i < len(flat_positions) else (0, 0)

            if style["highlight_style"] == "none":
                active_line_idx, active_word_idx = -1, -1

            frame_img = _render_state_image(video.w, video.h, lines, active_line_idx, active_word_idx, chunk_font, chunk_style, max_width)

            # Only the first image of a caption is an arrival; the images after
            # it just move the highlight, and animating those would make the
            # whole line twitch on every word.
            img_clip = _image_clip(
                frame_img, start, end - start,
                animation if i == 0 else (None, 0.0),
            )
            if img_clip is not None:
                clips.append(img_clip)

            done_words += 1
            if progress_cb and total_words:
                progress_cb("building", int(100 * done_words / total_words))

    if progress_cb:
        progress_cb("compositing", 0)

    final = CompositeVideoClip(clips, size=(video.w, video.h))

    logger = _ProgressLogger(progress_cb) if progress_cb else None
    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        fps=video.fps,
        logger=logger,
        threads=os.cpu_count(),
    )

    if progress_cb:
        progress_cb("done", 100)

    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("words_json")
    parser.add_argument("output")
    parser.add_argument("--preset", default=None)
    args = parser.parse_args()

    with open(args.words_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    style = None
    if args.preset:
        with open(args.preset, "r", encoding="utf-8") as f:
            style = json.load(f)

    render_captions(args.video, data["segments"], args.output, style=style, progress_cb=lambda s, p: print(f"{s}: {p}%"))
