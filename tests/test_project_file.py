"""Проект: работа целиком в одном файле — список, текст с правками, заголовки."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

from lib import project_file
from lib.manual_jobs import ManualJobService


TRANSCRIPT = {"language": "ru", "duration": 20.0, "segments": [{
    "start": 0.0, "end": 2.0, "text": " Он запитывается к 19-литровой бутылке,",
    "words": [
        {"word": " Он", "start": 0.0, "end": 0.4, "probability": 0.9},
        {"word": " запитывается", "start": 0.4, "end": 1.0, "probability": 0.9},
        {"word": " к", "start": 1.0, "end": 1.2, "probability": 0.9},
        {"word": " 19-литровой", "start": 1.2, "end": 1.7, "probability": 0.9},
        {"word": " бутылке,", "start": 1.7, "end": 2.0, "probability": 0.9},
    ],
}]}


def transcriber(path, progress_cb=None, abort=None, **params):
    return {"transcript": TRANSCRIPT}


class ProjectRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.video = os.path.join(self.work, "clip.mp4")
        Path(self.video).write_bytes(b"video")
        self.service = ManualJobService(os.path.join(self.work, "rev"),
                                        transcriber, lambda *a, **k: None)

    def prepared(self):
        """Файл с распознанным текстом, правкой и двумя заголовками."""
        job = self.service.workspace()
        self.service.add_items(job["job_id"], [self.video])
        item_id = self.service.workspace()["items"][0]["item_id"]
        self.service.run_transcription(job["job_id"])
        latest = self.service.get_transcript(item_id)
        self.service.apply_patch(item_id, latest["revision"], [
            {"op": "replace", "word_id": latest["words"][1]["id"], "text": "подключается"},
            {"op": "delete", "word_id": latest["words"][0]["id"]},
        ])
        self.service.set_overlays(item_id, [
            {"text": "Лайфхак", "start": 0.0, "end": 1.5, "enabled": True},
            {"text": "скрытый", "start": 0.0, "end": 1.5, "enabled": False},
        ])
        return item_id

    def saved_project(self, style=None):
        self.prepared()
        data = self.service.export_project(style or {"font_size": 77}, "1.5.0")
        path = os.path.join(self.work, "project" + project_file.SUFFIX)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        return path, data

    def reopened(self, path):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        fresh = ManualJobService(os.path.join(self.work, "rev2"),
                                 transcriber, lambda *a, **k: None)
        return fresh, fresh.import_project(data, os.path.dirname(path))

    def test_the_edited_text_comes_back(self):
        path, _data = self.saved_project()

        fresh, restored = self.reopened(path)
        item = restored["job"]["items"][0]
        words = [word["word"] for word in fresh.get_transcript(item["item_id"])["words"]]

        self.assertEqual([" подключается", " к", " 19-литровой", " бутылке,"], words)

    def test_a_deleted_word_does_not_come_back(self):
        path, data = self.saved_project()

        self.assertNotIn(" Он", [w["word"] for w in data["items"][0]["words"]])

    def test_titles_come_back_with_their_switches(self):
        path, _data = self.saved_project()

        _fresh, restored = self.reopened(path)
        overlays = restored["job"]["items"][0]["overlays"]

        self.assertEqual("Лайфхак", overlays[0]["text"])
        self.assertTrue(overlays[0]["enabled"])
        self.assertFalse(overlays[1]["enabled"])

    def test_the_style_comes_back(self):
        path, _data = self.saved_project({"font_size": 77, "no_end_dots": True})

        _fresh, restored = self.reopened(path)

        self.assertEqual(77, restored["style"]["font_size"])
        self.assertTrue(restored["style"]["no_end_dots"])

    def test_a_restored_file_is_ready_to_render_without_transcribing_again(self):
        path, _data = self.saved_project()

        _fresh, restored = self.reopened(path)
        item = restored["job"]["items"][0]

        self.assertEqual("needs_review", item["state"])
        self.assertTrue(item["revision"])

    def test_a_video_that_moved_is_found_next_to_the_project(self):
        """Проект и видео переехали в другую папку — путь внутри файла устарел."""
        path, data = self.saved_project()
        elsewhere = tempfile.mkdtemp()
        moved_project = os.path.join(elsewhere, "project" + project_file.SUFFIX)
        Path(os.path.join(elsewhere, "clip.mp4")).write_bytes(b"video")
        with open(moved_project, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        os.remove(self.video)

        _fresh, restored = self.reopened(moved_project)

        self.assertEqual([], restored["missing"])
        self.assertEqual(elsewhere, os.path.dirname(restored["job"]["items"][0]["path"]))

    def test_a_video_that_is_really_gone_is_reported(self):
        path, _data = self.saved_project()
        os.remove(self.video)

        _fresh, restored = self.reopened(path)

        self.assertEqual(["clip.mp4"], restored["missing"])

    def test_someone_elses_json_is_refused(self):
        path = os.path.join(self.work, "not-a-project.aisubs")
        Path(path).write_text('{"hello": "world"}', encoding="utf-8")

        with self.assertRaises(ValueError):
            self.reopened(path)

    def test_a_project_from_a_newer_version_is_refused(self):
        path, data = self.saved_project()
        data["version"] = project_file.VERSION + 1
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)

        with self.assertRaises(ValueError):
            self.reopened(path)


if __name__ == "__main__":
    unittest.main()
