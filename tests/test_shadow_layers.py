""""Тень 2": a second shadow under the main one, both with an X/Y offset."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import renderer


def style_with(**changes):
    style = copy.deepcopy(renderer.DEFAULT_STYLE)
    style.update(highlight_style="none", stroke_width=0, **changes)
    return style


class ShadowLayerTests(unittest.TestCase):
    def test_second_shadow_is_off_by_default_so_old_presets_render_as_before(self):
        layers = renderer._shadow_layers(style_with())
        self.assertEqual(1, len(layers))

    def test_second_shadow_is_drawn_under_the_main_one(self):
        layers = renderer._shadow_layers(style_with(
            shadow_offset=[2, 3], shadow2_enabled=True, shadow2_offset=[-5, 12],
            shadow2_blur=20, shadow2_opacity=0.5,
        ))
        self.assertEqual([(-5.0, 12.0), (2.0, 3.0)], [offset for _c, _b, offset in layers])
        self.assertEqual(127, layers[0][0][3])

    def test_safe_margin_accounts_for_the_wider_shadow(self):
        one = renderer._visual_overflow(style_with(shadow_blur=4, shadow_offset=[0, 2]), "bottom")
        two = renderer._visual_overflow(style_with(
            shadow_blur=4, shadow_offset=[0, 2],
            shadow2_enabled=True, shadow2_blur=10, shadow2_offset=[0, 8]), "bottom")
        self.assertEqual(10 + 2, one)
        self.assertEqual(25 + 8, two)

    def test_offset_moves_the_shadow_pixels(self):
        font = renderer._get_font(renderer._resolve_font_path(renderer.DEFAULT_STYLE), 84)

        def shadow_box(dx):
            style = style_with(text_color="#FFFFFF", shadow_blur=0, shadow_opacity=1.0,
                               shadow_offset=[dx, 0], position="center")
            img = renderer._render_state_image(1080, 1920, [["ТЕСТ"]], -1, -1, font, style, 900)
            # Shadow is black at full opacity: find pure-black opaque pixels.
            xs = [i % 1080 for i, px in enumerate(img.getdata()) if px[3] == 255 and px[0] < 10]
            return min(xs), max(xs)

        # With no offset the white text hides its own shadow, so compare two
        # offsets: the shadow's right edge must move by their difference.
        _, right10 = shadow_box(10)
        _, right40 = shadow_box(40)
        self.assertEqual(right10 + 30, right40)


if __name__ == "__main__":
    unittest.main()
