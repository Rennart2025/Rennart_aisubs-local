"""Пробел между словами: правка слова не должна склеивать его с соседним.

Whisper пишет каждое слово с ведущим пробелом (" слово"), и слово без него —
продолжение предыдущего: так токенизатор разбивает «19-литровой». Редактор
показывает слово без пробела, поэтому обратно приходит голый текст — вот тут
пробел и терялся, а «к 19-литровой» превращалось в «к19-литровой».
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

import segment_parser
from lib.transcript_revisions import TranscriptStore


def transcription(*words):
    return {"language": "ru", "duration": 20.0, "segments": [{
        "start": 0.0, "end": float(len(words)),
        "text": "".join(w for w in words),
        "words": [{"word": word, "start": float(i), "end": float(i) + 0.5,
                   "probability": 0.9} for i, word in enumerate(words)],
    }]}


class SpacingTests(unittest.TestCase):
    def setUp(self):
        self.store = TranscriptStore(tempfile.mkdtemp())

    def revision(self, *words):
        return self.store.create("item-1", "clip.mp4", transcription(*words), {})

    def words_for_render(self, revision):
        segments = self.store.render_segments("item-1", revision["revision"])
        return [word["word"] for word in segments[0]["words"]]

    def on_screen(self, revision):
        segments = self.store.render_segments("item-1", revision["revision"])
        return [caption["text"] for caption in
                segment_parser.parse(segments, lambda _text: True)]

    def test_an_inserted_word_gets_its_own_space(self):
        base = self.revision(" к", " бутылке,")
        after = self.store.apply_patch("item-1", base["revision"], [{
            "op": "insert_after", "word_id": base["words"][0]["id"],
            "text": "19-литровой", "start": 0.6, "end": 0.9,
        }])

        self.assertEqual([" к", " 19-литровой", " бутылке,"], self.words_for_render(after))
        self.assertEqual([" к 19-литровой бутылке,"], self.on_screen(after))

    def test_an_edited_word_keeps_the_space_it_had(self):
        base = self.revision(" к", " бутылке,")
        after = self.store.apply_patch("item-1", base["revision"], [{
            "op": "replace", "word_id": base["words"][1]["id"], "text": "бутыли,",
        }])

        self.assertEqual([" к", " бутыли,"], self.words_for_render(after))

    def test_a_continuation_stays_glued_when_edited(self):
        """«19» + «-литровой» — один токен, разбитый моделью: склейка нужна."""
        base = self.revision(" к", " 19", "-литровой")
        after = self.store.apply_patch("item-1", base["revision"], [{
            "op": "replace", "word_id": base["words"][2]["id"], "text": "-литровому",
        }])

        self.assertEqual([" к", " 19", "-литровому"], self.words_for_render(after))
        self.assertEqual([" к 19-литровому"], self.on_screen(after))

    def test_a_word_after_a_deleted_one_does_not_stick_to_the_new_neighbour(self):
        """Слово-продолжение теряет своего хозяина — значит, пробел ему нужен."""
        base = self.revision(" к", " 19", "-литровой")
        after = self.store.apply_patch("item-1", base["revision"], [{
            "op": "delete", "word_id": base["words"][1]["id"],
        }])

        self.assertEqual([" к", " -литровой"], self.words_for_render(after))
        self.assertNotIn("к-литровой", self.on_screen(after)[0])

    def test_a_word_split_into_three_is_glued_whole(self):
        """Раньше склейка пропускала каждое второе продолжение."""
        base = self.revision(" к", " 19", "-литр", "овой")

        self.assertEqual([" к 19-литровой"], self.on_screen(base))

    def test_the_stored_text_is_not_padded_twice(self):
        base = self.revision(" слово")
        after = self.store.apply_patch("item-1", base["revision"], [{
            "op": "replace", "word_id": base["words"][0]["id"], "text": "  слово  ",
        }])

        self.assertEqual(" слово", after["words"][0]["word"])


if __name__ == "__main__":
    unittest.main()
