"""Комплектные пресеты: каждый шрифт в них должен открываться движком."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def presets():
    for path in sorted((ROOT / "presets").glob("*.json")):
        yield path.name, json.loads(path.read_text(encoding="utf-8"))


def fonts_of(preset):
    yield preset.get("font")
    for title in preset.get("title_styles") or []:
        yield title.get("font")


def instance_names(path):
    from PIL import ImageFont
    file_path = (ROOT / path.partition("#")[0])
    font = ImageFont.truetype(str(file_path), 40)
    try:
        return [n.decode() if isinstance(n, bytes) else n for n in font.get_variation_names()]
    except OSError:
        return []           # не вариативный шрифт


class BundledPresetTests(unittest.TestCase):
    def test_every_font_file_exists(self):
        for name, preset in presets():
            for font in filter(None, fonts_of(preset)):
                self.assertTrue((ROOT / font.partition("#")[0]).is_file(), f"{name}: {font}")

    def test_every_named_instance_exists_in_its_font(self):
        """«#600» вместо «#SemiBold» ронял рендер заголовков целиком."""
        for name, preset in presets():
            for font in filter(None, fonts_of(preset)):
                _file, _, instance = font.partition("#")
                if instance:
                    self.assertIn(instance, instance_names(font), f"{name}: {font}")

    def test_every_font_is_one_the_dropdown_offers_and_speaks_russian(self):
        """Шрифт без кириллицы движок молча подменяет запасным — в пресете это
        выглядело бы как один шрифт, а в видео получалось бы другое."""
        for name, preset in presets():
            for font in filter(None, fonts_of(preset)):
                self.assertIn(font, renderer.BUNDLED_FONT_LABELS, f"{name}: {font}")
                self.assertTrue(renderer.BUNDLED_FONT_LABELS[font]["cyrillic"], f"{name}: {font}")

    def test_titles_are_placed_from_the_centre(self):
        for name, preset in presets():
            for title in preset.get("title_styles") or []:
                self.assertNotIn("position", title, name)
                self.assertNotIn("position_margin", title, name)
                self.assertIsInstance(title.get("offset_y", 0), int, name)

    def test_an_unknown_instance_falls_back_instead_of_failing(self):
        font = renderer._get_font(str(ROOT / "fonts" / "Oswald-var.ttf") + "#600", 41)

        self.assertIsNotNone(font)


if __name__ == "__main__":
    unittest.main()


class FontCoverageTests(unittest.TestCase):
    """Флаг «есть кириллица» должен говорить правду — по нему работает и
    фильтр в списке шрифтов, и подмена шрифта при рендере."""

    def test_the_cyrillic_flag_matches_the_font_file(self):
        for path, info in renderer.BUNDLED_FONT_LABELS.items():
            font = renderer._get_font(str(ROOT / path.partition("#")[0])
                                      + ("#" + path.partition("#")[2] if "#" in path else ""), 40)
            self.assertEqual(info["cyrillic"], renderer._font_covers(font, "Жёлтый заголовок"), path)

    def test_a_latin_only_font_is_recognised_as_such(self):
        font = renderer._get_font(str(ROOT / "fonts" / "BebasNeue-Regular.ttf"), 40)

        self.assertTrue(renderer._font_covers(font, "TITLE"))
        self.assertFalse(renderer._font_covers(font, "Заголовок"))

    def test_russian_text_in_a_latin_font_falls_back_instead_of_boxes(self):
        style = dict(renderer.TITLE_STYLE, font="fonts/BebasNeue-Regular.ttf",
                     font_size=90, shadow_enabled=False)
        image = renderer.render_title_image(1080, 600, "Заголовок", style)
        crossed = renderer.render_title_image(1080, 600, "￿" * 9, style)

        # Квадраты .notdef и настоящие буквы дают разную картинку.
        self.assertNotEqual(image.getbbox(), crossed.getbbox())
