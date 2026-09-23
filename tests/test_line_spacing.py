"""Межстрочный интервал: расстояние между строками субтитра."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import renderer


def two_line_image(spacing):
    style = copy.deepcopy(renderer.DEFAULT_STYLE)
    style.update(highlight_style="none", stroke_width=0, shadow_enabled=False,
                 font_size=70, line_count=2, line_spacing=spacing)
    font = renderer._get_font(renderer._resolve_font_path(style), style["font_size"])
    lines = [["ПЕРВАЯ", "СТРОКА"], ["ВТОРАЯ", "СТРОКА"]]
    return renderer._render_state_image(1080, 1920, lines, 0, 0, font, style, 900)


class LineSpacingTests(unittest.TestCase):
    def test_bigger_spacing_makes_a_taller_block(self):
        tight = two_line_image(1.0).getbbox()
        loose = two_line_image(1.8).getbbox()

        self.assertGreater(loose[3] - loose[1], tight[3] - tight[1])

    def test_the_words_themselves_do_not_change(self):
        """Только промежуток: ширина строк и размер шрифта остаются прежними."""
        tight = two_line_image(1.0).getbbox()
        loose = two_line_image(1.8).getbbox()

        self.assertAlmostEqual(loose[2] - loose[0], tight[2] - tight[0], delta=2)

    def test_the_default_is_the_one_presets_were_saved_with(self):
        self.assertEqual(1.18, renderer.DEFAULT_STYLE["line_spacing"])
        self.assertEqual(1.18, renderer.TITLE_STYLE["line_spacing"])


if __name__ == "__main__":
    unittest.main()
