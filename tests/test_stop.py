"""Stop: the file being processed is interrupted, not left half-written."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

from lib.cancellation import Cancelled, check
from lib.manual_jobs import ManualJobService


TRANSCRIPT = {"language": "ru", "duration": 3.0, "segments": [{
    "start": 0.1, "end": 0.9, "text": " привет мир",
    "words": [{"word": " привет", "start": 0.1, "end": 0.5, "probability": 0.9},
              {"word": " мир", "start": 0.5, "end": 0.9, "probability": 0.9}],
}]}


def transcriber(path, progress_cb=None, abort=None, **params):
    check(abort)
    return {"transcript": TRANSCRIPT}


class CheckTests(unittest.TestCase):
    def test_no_callable_never_stops_anything(self):
        check(None)                      # must not raise

    def test_a_false_answer_lets_the_work_continue(self):
        check(lambda: False)

    def test_a_true_answer_stops_it(self):
        with self.assertRaises(Cancelled):
            check(lambda: True)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.video = os.path.join(self.work, "clip.mp4")
        Path(self.video).write_bytes(b"not really a video")
        self.rendered = []

    def service(self, render_fn):
        return ManualJobService(os.path.join(self.work, "rev"), transcriber, render_fn)

    def ready_item(self, service):
        job = service.workspace()
        service.add_items(job["job_id"], [self.video])
        item_id = service.workspace()["items"][0]["item_id"]
        service.run_transcription(job["job_id"])
        return job["job_id"], item_id

    def test_a_stopped_render_leaves_the_file_ready_to_render_again(self):
        def render_fn(path, output, segments, abort=None, **kw):
            check(abort)
            raise AssertionError("рендер не должен был дойти сюда")

        service = self.service(render_fn)
        job_id, _item_id = self.ready_item(service)
        before = service.workspace()["items"][0]["state"]

        result = service.run_render(job_id, {}, os.path.join(self.work, "out"),
                                    abort=lambda: True)
        item = service.workspace()["items"][0]

        self.assertEqual(0, result["failed"], "остановка — это не ошибка рендера")
        self.assertEqual(before, item["state"], "файл должен вернуться в прежнее состояние")
        self.assertEqual("cancelled", item["stage"])
        self.assertIsNone(item["error"])

    def test_a_stopped_render_does_not_start_the_next_file(self):
        second = os.path.join(self.work, "clip2.mp4")
        Path(second).write_bytes(b"not really a video")
        started = []

        def render_fn(path, output, segments, abort=None, **kw):
            started.append(path)
            check(abort)
            return {"output": str(output)}

        service = self.service(render_fn)
        job = service.workspace()
        service.add_items(job["job_id"], [self.video, second])
        service.run_transcription(job["job_id"])

        service.run_render(job["job_id"], {}, os.path.join(self.work, "out"),
                           abort=lambda: True)

        self.assertEqual(1, len(started), "после Stop очередь не продолжается")

    def test_a_stopped_transcription_can_be_started_again(self):
        def transcriber_that_stops(path, progress_cb=None, abort=None, **params):
            raise Cancelled()

        service = ManualJobService(os.path.join(self.work, "rev2"),
                                   transcriber_that_stops, lambda *a, **k: None)
        job = service.workspace()
        service.add_items(job["job_id"], [self.video])

        service.run_transcription(job["job_id"], abort=lambda: True)
        item = service.workspace()["items"][0]

        self.assertEqual("cancelled", item["state"])
        self.assertIsNone(item["error"], "остановка — не ошибка распознавания")
        # "cancelled" is a state Transcribe picks up again.
        from lib.manual_jobs import TRANSCRIBABLE
        self.assertIn(item["state"], TRANSCRIBABLE)


if __name__ == "__main__":
    unittest.main()
