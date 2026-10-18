"""«Без точек в конце предложений» и выключатель видимости заголовка."""

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

import renderer
import segment_parser


def segments(text):
    at = 0.0
    words = []
    for piece in text.split():
        words.append({"word": " " + piece, "start": at, "end": at + 0.3})
        at += 0.4
    return [{"start": 0.0, "end": at, "text": text, "words": words}]


def captions_of(text, **flags):
    return segment_parser.parse(copy.deepcopy(segments(text)), lambda _t: True, **flags)


def texts(captions):
    return [caption["text"].strip() for caption in captions]


class EndDotTests(unittest.TestCase):
    def test_the_dot_at_the_end_of_a_word_goes(self):
        self.assertEqual("кухни", segment_parser.strip_end_dot("кухни."))
        self.assertEqual(" кухни", segment_parser.strip_end_dot(" кухни."))

    def test_question_and_exclamation_stay(self):
        self.assertEqual("да?", segment_parser.strip_end_dot("да?"))
        self.assertEqual("да!", segment_parser.strip_end_dot("да!"))

    def test_dots_inside_a_word_are_left_alone(self):
        self.assertEqual("3.5", segment_parser.strip_end_dot("3.5"))
        self.assertEqual("т.е", segment_parser.strip_end_dot("т.е"))

    def test_a_word_that_is_only_dots_survives(self):
        self.assertEqual("...", segment_parser.strip_end_dot("..."))

    def test_captions_lose_their_full_stops(self):
        plain = texts(captions_of("Первое предложение. Второе."))
        clean = texts(captions_of("Первое предложение. Второе.", no_end_dots=True))

        self.assertEqual(["Первое предложение.", "Второе."], plain)
        self.assertEqual(["Первое предложение", "Второе"], clean)

    def test_sentences_still_break_where_the_dot_was(self):
        """Точку убираем после разбивки — иначе две фразы слиплись бы в одну."""
        clean = captions_of("Первое предложение. Второе.", no_end_dots=True)

        self.assertEqual(2, len(clean))

    def test_the_option_is_off_by_default(self):
        self.assertFalse(renderer.DEFAULT_STYLE["no_end_dots"])


class TitleVisibilityTests(unittest.TestCase):
    def overlay(self, **changes):
        base = {"text": "Заголовок", "start": 0.0, "end": 2.0}
        base.update(changes)
        return base

    def test_a_switched_off_title_is_not_drawn(self):
        clips = renderer.title_clips(1080, 1920, 5.0, [self.overlay(enabled=False)], {})

        self.assertEqual([], clips)

    def test_a_switched_on_title_is_drawn(self):
        clips = renderer.title_clips(1080, 1920, 5.0, [self.overlay(enabled=True)], {})

        self.assertTrue(clips)

    def test_titles_saved_before_the_switch_existed_are_shown(self):
        clips = renderer.title_clips(1080, 1920, 5.0, [self.overlay()], {})

        self.assertTrue(clips, "у старых заголовков флага нет — их видно")

    def test_switching_one_title_off_leaves_the_other(self):
        clips = renderer.title_clips(1080, 1920, 5.0, [
            self.overlay(text="Первый", enabled=False),
            self.overlay(text="Второй", enabled=True),
        ], {})

        self.assertTrue(clips)


if __name__ == "__main__":
    unittest.main()
