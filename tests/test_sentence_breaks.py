"""Optional caption style: no full stops, every sentence on a fresh caption."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import segment_parser


def segments_of(*words):
    t = 0.0
    out = []
    for text in words:
        out.append({"word": text, "start": t, "end": t + 0.3})
        t += 0.4
    return [{"start": 0, "end": t, "words": out}]


def fits_everything(_text):
    return True


def caption_texts(captions):
    return [" ".join(w["word"].strip() for w in c["words"]) for c in captions]


class SentenceBreakTests(unittest.TestCase):
    def test_periods_are_dropped_and_each_sentence_gets_its_own_caption(self):
        captions = segment_parser.parse(
            segments_of(" основной", " кухни.", " Тут", " нужно", " пояснить."),
            fits_everything, sentence_breaks=True,
        )
        self.assertEqual(["основной кухни", "Тут нужно пояснить"], caption_texts(captions))

    def test_question_and_exclamation_marks_stay_but_still_break(self):
        captions = segment_parser.parse(
            segments_of(" Готово?", " Да!", " Поехали"), fits_everything, sentence_breaks=True,
        )
        self.assertEqual(["Готово?", "Да!", "Поехали"], caption_texts(captions))

    def test_ellipsis_is_removed_too(self):
        captions = segment_parser.parse(
            segments_of(" ну…", " ладно..."), fits_everything, sentence_breaks=True,
        )
        self.assertEqual(["ну", "ладно"], caption_texts(captions))

    def test_periods_inside_a_word_are_kept(self):
        captions = segment_parser.parse(
            segments_of(" версия", " 3.5", " вышла."), fits_everything, sentence_breaks=True,
        )
        self.assertEqual(["версия 3.5 вышла"], caption_texts(captions))

    def test_long_sentence_is_still_split_by_width(self):
        captions = segment_parser.parse(
            segments_of(" один", " два", " три.", " четыре"),
            lambda text: len(text.split()) <= 2, sentence_breaks=True,
        )
        self.assertEqual(["один два", "три", "четыре"], caption_texts(captions))

    def test_off_by_default_keeps_the_text_as_recognised(self):
        captions = segment_parser.parse(
            segments_of(" кухни.", " Тут"), fits_everything,
        )
        self.assertIn("кухни.", " ".join(caption_texts(captions)))


if __name__ == "__main__":
    unittest.main()


class OneWordTests(unittest.TestCase):
    def test_every_word_is_alone_and_bare(self):
        captions = segment_parser.parse(
            segments_of(" Рубрика", " «Особые", " пожелания", " от", " заказчика».", " Он", " говорит,"),
            fits_everything, one_word=True,
        )
        self.assertEqual(["Рубрика", "Особые", "пожелания", "от", "заказчика", "Он", "говорит"],
                         caption_texts(captions))

    def test_inner_hyphen_and_decimal_survive(self):
        for raw, clean in [(" какой-то,", " какой-то"), (" 3.5.", " 3.5"), (" (да)", " да"),
                           (" — ", " "), (" don't!", " don't"), (" «Ура»!..", " Ура")]:
            self.assertEqual(clean, segment_parser.clean_word(raw))

    def test_lone_dash_disappears_instead_of_showing_an_empty_caption(self):
        captions = segment_parser.parse(segments_of(" да", " —", " нет"), fits_everything, one_word=True)
        self.assertEqual(["да", "нет"], caption_texts(captions))

    def test_word_stays_until_the_next_one_across_a_short_pause(self):
        segments = [{"start": 0, "end": 3, "words": [
            {"word": " раз", "start": 0.0, "end": 0.3},
            {"word": " два", "start": 0.5, "end": 0.8},
            {"word": " три", "start": 2.5, "end": 2.8},
        ]}]
        captions = segment_parser.parse(segments, fits_everything, one_word=True)
        self.assertEqual([0.5, 0.8, 2.8], [c["end"] for c in captions])

    def test_mode_falls_back_to_the_older_flag(self):
        self.assertEqual("sentences", segment_parser.caption_mode({"sentence_breaks": True}))
        self.assertEqual("phrases", segment_parser.caption_mode({}))
        self.assertEqual("words", segment_parser.caption_mode({"caption_mode": "words", "sentence_breaks": True}))
