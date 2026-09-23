import struct
import unittest
import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PageContractParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.images = []
        self.stylesheets = []
        self.external_runtime_assets = []
        self.heading_counts = {"h1": 0, "h2": 0}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag == "img":
            self.images.append((values.get("src"), values.get("alt", "")))
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.stylesheets.append(values["href"])
        if tag in self.heading_counts:
            self.heading_counts[tag] += 1
        asset = values.get("src") if tag == "script" else values.get("href")
        if tag in {"script", "link"} and asset and asset.startswith(("http://", "https://")):
            self.external_runtime_assets.append(asset)


def png_dimensions(path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"Not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


class ScreenshotTests(unittest.TestCase):
    def test_the_interface_screenshot_is_present_and_readable(self):
        shot = ROOT / "docs" / "screen-main.png"

        self.assertTrue(shot.is_file())
        self.assertGreater(shot.stat().st_size, 50_000)
        width, height = png_dimensions(shot)
        self.assertGreaterEqual(width, 1280, "скриншот слишком мелкий для страницы")
        self.assertGreater(width, height, "ожидается снимок окна целиком")


    def test_the_panel_screenshots_are_present(self):
        for name in ("screen-editor.png", "screen-style.png",
                     "screen-titles.png", "result-frame.png"):
            shot = ROOT / "docs" / name
            self.assertTrue(shot.is_file(), name)
            self.assertGreater(shot.stat().st_size, 20_000, name)
            png_dimensions(shot)


class GitHubPagesTests(unittest.TestCase):
    """docs/index.html is the project page; it must stand on its own."""

    def setUp(self):
        self.path = ROOT / "docs" / "index.html"
        self.html = self.path.read_text(encoding="utf-8")
        self.parser = PageContractParser()
        self.parser.feed(self.html)

    def test_page_covers_the_sections_a_visitor_comes_for(self):
        self.assertEqual(1, self.parser.heading_counts["h1"])
        for heading in ("Что умеет", "Как это работает", "Экран программы",
                        "Установка", "Требования"):
            self.assertIn(f"<h2>{heading}</h2>", self.html)

    def test_page_credits_this_fork_and_the_original_project(self):
        self.assertIn("https://github.com/Rennart2025/Rennart_aisubs-local", self.parser.links)
        self.assertIn("https://t.me/rinatmaksutov", self.parser.links)
        self.assertIn("https://github.com/jimmorisedu-boop/aisubs-local", self.parser.links)
        self.assertIn("https://t.me/daipotestit", self.parser.links)

    def test_nothing_is_left_from_the_interface_before_the_single_screen(self):
        for phrase in ("Режимы обработки", "Мануал", "Manual Mode", "Авто-режим"):
            self.assertNotIn(phrase, self.html)

    def test_every_image_has_a_description_and_exists(self):
        self.assertTrue(self.parser.images, "на странице нет ни одного скриншота")
        for src, alt in self.parser.images:
            self.assertTrue(alt.strip(), src)
            if src and not src.startswith(("http://", "https://", "/")):
                self.assertTrue((self.path.parent / src).is_file(), src)

    def test_thumbnails_open_the_full_size_screenshot(self):
        """Панели сняты узкими и высокими — превью подрезано, полный размер по клику."""
        for name in ("screen-editor.png", "screen-style.png", "screen-titles.png"):
            self.assertIn(name, self.parser.links, name)

    def test_page_loads_nothing_from_the_internet(self):
        """A project page that fetches fonts or scripts breaks without them."""
        self.assertEqual([], self.parser.external_runtime_assets)
        for href in self.parser.stylesheets:
            if not href.startswith(("http://", "https://", "/")):
                self.assertTrue((self.path.parent / href).is_file(), href)


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "README.md"
        self.markdown = self.path.read_text(encoding="utf-8")

    def test_readme_credits_this_fork_and_keeps_the_original_attribution(self):
        """MIT only asks that the original author stays credited."""
        targets = re.findall(r"\[[^]]*\]\(([^)]+)\)", self.markdown)

        self.assertIn("https://github.com/Rennart2025/Rennart_aisubs-local", targets)
        self.assertIn("https://t.me/rinatmaksutov", targets)
        self.assertIn("https://github.com/jimmorisedu-boop/aisubs-local", targets)
        self.assertIn("https://t.me/daipotestit", targets)

    def test_readme_opens_with_a_screenshot_of_the_current_interface(self):
        images = re.findall(r"!\[[^]]*\]\(([^)]+)\)", self.markdown)

        self.assertTrue(images, "README has no screenshot")
        self.assertTrue((self.path.parent / images[0]).is_file(), images[0])

    def test_readme_relative_images_resolve(self):
        targets = re.findall(r"!\[[^]]*\]\(([^)]+)\)", self.markdown)
        targets += re.findall(r'<img[^>]*\ssrc="([^"]+)"', self.markdown)

        for target in targets:
            if target.startswith(("http://", "https://", "/")):
                continue
            self.assertTrue((self.path.parent / target).is_file(), target)

    def test_readme_documents_the_titles_feature(self):
        self.assertIn("## Заголовки", self.markdown)
        for phrase in ("Fade in", "Fade out", "Заголовок 2"):
            self.assertIn(phrase, self.markdown)


if __name__ == "__main__":
    unittest.main()
