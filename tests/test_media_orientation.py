import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mediaserver


class DisplayDimensionsTests(unittest.TestCase):
    def test_quarter_turns_swap_dimensions(self):
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, 90), (1080, 1920))
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, -90), (1080, 1920))
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, 270), (1080, 1920))

    def test_half_turn_and_bad_metadata_keep_dimensions(self):
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, 180), (1920, 1080))
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, "bad"), (1920, 1080))
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, None), (1920, 1080))

    def test_side_data_rotation_takes_precedence_over_legacy_tag(self):
        stream = {
            "tags": {"rotate": "0"},
            "side_data_list": [{"rotation": -90}],
        }

        self.assertEqual(mediaserver._stream_rotation(stream), -90.0)

    def test_legacy_rotation_tag_remains_supported(self):
        stream = {"tags": {"rotate": "90"}}

        self.assertEqual(mediaserver._stream_rotation(stream), 90.0)


if __name__ == "__main__":
    unittest.main()
