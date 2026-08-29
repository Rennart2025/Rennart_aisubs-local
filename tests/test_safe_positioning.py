import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import renderer


class EffectivePositionMarginTests(unittest.TestCase):
    def test_resolves_same_safe_rule_for_each_video_height(self):
        style = copy.deepcopy(renderer.DEFAULT_STYLE)
        style.update(
            position="bottom",
            position_mode="safe",
            position_safe_inset_ratio=0.22,
            highlight_style="none",
            stroke_width=0,
            shadow_enabled=False,
        )

        self.assertEqual(renderer._effective_position_margin(style, 1920), 423)
        self.assertEqual(renderer._effective_position_margin(style, 3840), 845)

    def test_legacy_and_invalid_safe_styles_use_manual_pixels(self):
        legacy = copy.deepcopy(renderer.DEFAULT_STYLE)
        legacy["position_margin"] = 317
        invalid = dict(legacy, position_mode="safe", position_safe_inset_ratio=0.75)

        self.assertEqual(renderer._effective_position_margin(legacy, 3840), 317)
        self.assertEqual(renderer._effective_position_margin(invalid, 3840), 317)

    def test_numeric_preset_strings_are_safe_but_booleans_fall_back_to_manual(self):
        style = copy.deepcopy(renderer.DEFAULT_STYLE)
        style.update(
            position="bottom",
            position_margin=190,
            position_mode="safe",
            highlight_style="none",
            stroke_width=0,
            shadow_enabled=False,
        )

        self.assertEqual(renderer._effective_position_margin(
            dict(style, position_safe_inset_ratio="0.22"), 1920,
        ), 423)
        self.assertEqual(renderer._effective_position_margin(
            dict(style, position_safe_inset_ratio=False), 1920,
        ), 190)
        self.assertEqual(renderer._effective_position_margin(
            dict(style, position_safe_inset_ratio=True), 1920,
        ), 190)
        self.assertEqual(renderer._effective_position_margin(
            dict(style, position_safe_inset_ratio=[]), 1920,
        ), 190)
        self.assertEqual(renderer._effective_position_margin(
            dict(style, position_safe_inset_ratio=[0.22]), 1920,
        ), 190)

    def test_fractional_visual_overflow_matches_browser_rounding(self):
        style = copy.deepcopy(renderer.DEFAULT_STYLE)
        style.update(
            position="bottom",
            position_margin=190,
            position_mode="safe",
            position_safe_inset_ratio=0.22,
            highlight_style="box",
            box_padding_y=10.2,
            stroke_width=0,
            shadow_enabled=False,
        )

        self.assertEqual(renderer._effective_position_margin(style, 1920), 433)

    def test_safe_mode_keeps_maximum_blur_inside_top_boundary(self):
        image = self._render_blurred_state("top", 0.10)
        alpha_bbox = image.getchannel("A").getbbox()

        self.assertIsNotNone(alpha_bbox)
        self.assertGreaterEqual(alpha_bbox[1], math.floor(1920 * 0.10))

    def test_safe_mode_keeps_maximum_blur_inside_bottom_boundary(self):
        image = self._render_blurred_state("bottom", 0.22)
        alpha_bbox = image.getchannel("A").getbbox()

        self.assertIsNotNone(alpha_bbox)
        self.assertLessEqual(alpha_bbox[3], math.ceil(1920 * (1 - 0.22)))

    @staticmethod
    def _render_blurred_state(position, inset_ratio):
        style = copy.deepcopy(renderer.DEFAULT_STYLE)
        style.update(
            font_size=84,
            position=position,
            position_mode="safe",
            position_safe_inset_ratio=inset_ratio,
            position_margin=190,
            highlight_style="none",
            stroke_width=0,
            shadow_enabled=True,
            shadow_blur=20,
            shadow_offset=[0, 4],
        )
        font = renderer._get_font(renderer._resolve_font_path(style), style["font_size"])
        return renderer._render_state_image(
            1080, 1920, [["ТЕСТ"]], 0, 0, font, style, 928,
        )


if __name__ == "__main__":
    unittest.main()
