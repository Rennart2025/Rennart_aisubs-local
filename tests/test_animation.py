"""How a caption arrives on screen: fade, pop or rise."""

import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import renderer


def block(width=400, height=200, box=(100, 60, 300, 140)):
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(box, fill=(255, 255, 255, 255))
    return image


class AnimationTests(unittest.TestCase):
    def test_clip_is_cropped_to_the_ink_and_placed_where_it_was(self):
        clip = renderer._image_clip(block(), start=1.0, duration=2.0)

        self.assertEqual((201, 81), tuple(clip.size))
        self.assertEqual((100, 60), clip.pos(0))
        self.assertEqual(1.0, clip.start)

    def test_nothing_is_drawn_for_an_empty_image_or_zero_length(self):
        self.assertIsNone(renderer._image_clip(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), 0, 1))
        self.assertIsNone(renderer._image_clip(block(), 0, 0))

    def test_pop_grows_into_place_and_keeps_the_centre(self):
        clip = renderer._image_clip(block(), 0, 2.0, ("pop", 0.3))
        sizes = [clip.get_frame(t).shape[1] for t in (0.0, 0.15, 0.4)]

        self.assertLess(sizes[0], sizes[2])      # starts smaller
        self.assertLess(sizes[1], sizes[2] * 1.2)
        centres = [clip.pos(t)[0] + clip.get_frame(t).shape[1] / 2 for t in (0.0, 0.4)]
        self.assertAlmostEqual(centres[0], centres[1], delta=2)

    def test_rise_travels_up_to_its_place_without_overshooting(self):
        clip = renderer._image_clip(block(), 0, 2.0, ("rise", 0.3))
        tops = [clip.pos(t)[1] for t in (0.0, 0.1, 0.2, 0.5)]

        self.assertGreater(tops[0], tops[1])
        self.assertGreater(tops[1], tops[2])
        self.assertEqual(60, tops[3])
        self.assertGreaterEqual(min(tops), 60)   # never above the final position

    def test_style_switch_and_bad_values_fall_back_to_no_animation(self):
        self.assertEqual((None, 0.0), renderer._animation_for({"word_animation": "none"}))
        self.assertEqual((None, 0.0), renderer._animation_for({"word_animation": "pop", "word_animation_ms": 0}))
        self.assertEqual((None, 0.0), renderer._animation_for({"word_animation": "wat", "word_animation_ms": 200}))
        self.assertEqual(("fade", 0.2), renderer._animation_for({"word_animation": "fade", "word_animation_ms": 200}))

    def test_animation_never_outlasts_the_caption(self):
        clip = renderer._image_clip(block(), 0, 0.1, ("pop", 0.5))
        self.assertAlmostEqual(0.1, clip.duration, places=3)


if __name__ == "__main__":
    unittest.main()
