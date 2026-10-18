"""Экспорт распознанного текста: сплошной текст для статьи, не субтитры."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib import plain_text


def words(*items):
    out = []
    at = 0.0
    for item in items:
        if isinstance(item, tuple):
            text, gap = item
        else:
            text, gap = item, 0.1
        at += gap
        out.append({"id": text, "word": " " + text, "start": at, "end": at + 0.4})
        at += 0.4
    return {"words": out}


class PlainTextTests(unittest.TestCase):
    def test_words_come_back_as_a_sentence_with_its_punctuation(self):
        text = plain_text.build(words("Привет,", "как", "дела?"))

        self.assertEqual("Привет, как дела?", text)

    def test_a_long_pause_after_a_sentence_starts_a_paragraph(self):
        text = plain_text.build(words("Первое", "предложение.", ("Второе", 3.0), "тоже."))

        self.assertEqual("Первое предложение.\n\nВторое тоже.", text)

    def test_a_pause_in_the_middle_of_a_sentence_does_not_break_it(self):
        """Спикер задумался посреди фразы — это не новый абзац."""
        text = plain_text.build(words("Первое", "слово", ("и", 3.0), "второе."))

        self.assertEqual("Первое слово и второе.", text)

    def test_deleted_words_stay_out(self):
        source = words("Нужное", "лишнее", "слово.")
        source["words"][1]["deleted"] = True

        self.assertEqual("Нужное слово.", plain_text.build(source))

    def test_an_empty_transcript_gives_an_empty_string(self):
        self.assertEqual("", plain_text.build({"words": []}))
        self.assertEqual("", plain_text.build(None))

    def test_it_is_not_a_subtitle_format(self):
        """Ни таймкодов, ни номеров реплик — только текст."""
        text = plain_text.build(words("Первое.", ("Второе.", 3.0)))

        self.assertNotIn("-->", text)
        self.assertNotIn("00:", text)


if __name__ == "__main__":
    unittest.main()
