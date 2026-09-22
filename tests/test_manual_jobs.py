import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.manual_jobs import ManualJobService


def transcript_for(text):
    return {
        "language": "ru",
        "duration": 2.0,
        "segments": [{
            "start": 0.1,
            "end": 0.8,
            "text": " " + text,
            "words": [{
                "word": " " + text, "start": 0.1, "end": 0.8, "probability": 0.95,
            }],
        }],
    }


class ManualJobServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.good = root / "good.mp4"
        self.bad = root / "bad.mp4"
        self.good.write_bytes(b"good")
        self.bad.write_bytes(b"bad")
        self.rendered = []

        def transcribe(path, **_params):
            if Path(path).name == "bad.mp4":
                raise RuntimeError("audio cannot be decoded")
            return {"transcript": transcript_for("готово"), "cached": False}

        def render(path, output, segments, **_params):
            self.rendered.append((Path(path).name, Path(output).name, segments))
            return {"output": str(output)}

        self.service = ManualJobService(root / "revisions", transcribe, render)

    def tearDown(self):
        self.temp.cleanup()

    def test_failed_file_does_not_stop_batch_transcription(self):
        job = self.service.create_job([self.bad, self.good], {"model_size": "small"})
        self.service.run_transcription(job["job_id"])
        snapshot = self.service.snapshot(job["job_id"])

        self.assertEqual(["failed", "transcribed"], [item["state"] for item in snapshot["items"]])
        self.assertEqual("audio cannot be decoded", snapshot["items"][0]["error"])

    def test_render_gate_opens_for_approved_items_after_all_transcriptions_are_terminal(self):
        job = self.service.create_job([self.good, self.bad], {"model_size": "small"})
        first_id = job["items"][0]["item_id"]
        self.service.run_transcription(job["job_id"])
        revision = self.service.get_transcript(first_id)
        self.service.approve(first_id, revision["revision"])

        snapshot = self.service.snapshot(job["job_id"])
        self.assertTrue(snapshot["render_ready"])
        self.assertEqual(1, snapshot["approved_count"])

    def test_batch_render_only_processes_approved_items(self):
        job = self.service.create_job([self.good, self.bad], {"model_size": "small"})
        self.service.run_transcription(job["job_id"])
        first = job["items"][0]
        revision = self.service.get_transcript(first["item_id"])
        self.service.approve(first["item_id"], revision["revision"])

        result = self.service.run_render(job["job_id"], {}, Path(self.temp.name) / "output")

        self.assertEqual(1, result["completed"])
        self.assertEqual(1, result["skipped"])
        self.assertEqual(["good.mp4"], [entry[0] for entry in self.rendered])

    def test_retry_can_process_only_selected_failed_items(self):
        attempts = {"bad.mp4": 0}

        def succeeds_on_retry(path, **_params):
            name = Path(path).name
            attempts[name] = attempts.get(name, 0) + 1
            if name == "bad.mp4" and attempts[name] == 1:
                raise RuntimeError("temporary decoder error")
            return {"transcript": transcript_for("повтор"), "cached": False}

        self.service.transcribe_fn = succeeds_on_retry
        job = self.service.create_job([self.bad, self.good], {"model_size": "small"})
        self.service.run_transcription(job["job_id"])
        bad_id = job["items"][0]["item_id"]
        self.service.run_transcription(job["job_id"], selected_ids=[bad_id])

        snapshot = self.service.snapshot(job["job_id"])
        self.assertEqual(["transcribed", "transcribed"], [item["state"] for item in snapshot["items"]])
        self.assertEqual(2, attempts["bad.mp4"])
        self.assertEqual(1, attempts["good.mp4"])

    def test_cancelled_item_can_be_retried(self):
        job = self.service.create_job([self.good], {"model_size": "small"})
        item_id = job["items"][0]["item_id"]
        self.service.run_transcription(job["job_id"], cancelled=lambda: True)
        self.assertEqual("cancelled", self.service.snapshot(job["job_id"])["items"][0]["state"])

        self.service.run_transcription(job["job_id"], selected_ids=[item_id])

        self.assertEqual("transcribed", self.service.snapshot(job["job_id"])["items"][0]["state"])

    def test_retranscription_keeps_previous_approved_revision(self):
        job = self.service.create_job([self.good], {"model_size": "small"})
        item_id = job["items"][0]["item_id"]
        self.service.run_transcription(job["job_id"])
        first = self.service.get_transcript(item_id)
        self.service.approve(item_id, first["revision"])

        self.service.retranscribe(item_id)

        latest = self.service.get_transcript(item_id)
        self.assertEqual(2, latest["revision"])
        self.assertEqual("transcribed", self.service.snapshot(job["job_id"])["items"][0]["state"])
        self.assertEqual("approved", self.service.store.get_revision(item_id, 1)["status"])

    def test_job_and_transcript_are_recovered_after_service_restart(self):
        job = self.service.create_job([self.good], {"model_size": "small"})
        item_id = job["items"][0]["item_id"]
        self.service.run_transcription(job["job_id"])

        restarted = ManualJobService(
            Path(self.temp.name) / "revisions", self.service.transcribe_fn, self.service.render_fn
        )

        recovered = restarted.snapshot(job["job_id"])
        self.assertEqual("transcribed", recovered["items"][0]["state"])
        self.assertEqual(" готово", restarted.get_transcript(item_id)["words"][0]["word"])
        self.assertEqual(job["job_id"], restarted.latest_snapshot()["job_id"])



class WorkspaceTests(unittest.TestCase):
    """The GUI's single list: files come and go, each on its own track."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rendered = []

        def transcribe(path, **_params):
            return {"transcript": transcript_for(Path(path).stem), "cached": False}

        def render(path, output, segments, **_params):
            self.rendered.append(Path(path).name)
            return {"output": str(output)}

        self.service = ManualJobService(self.root / "revisions", transcribe, render)
        self.output = self.root / "output"

    def tearDown(self):
        self.temp.cleanup()

    def video(self, name):
        path = self.root / name
        path.write_bytes(b"video")
        return path

    def states(self):
        return [item["state"] for item in self.service.workspace()["items"]]

    def test_video_added_after_a_render_waits_for_transcription(self):
        job = self.service.workspace()
        snapshot, (first_id,) = self.service.add_items(job["job_id"], [self.video("one.mp4")])
        self.service.run_transcription(job["job_id"])
        self.service.run_render(job["job_id"], {}, self.output)
        self.assertEqual(["completed"], self.states())

        _, added = self.service.add_items(job["job_id"], [self.video("two.mp4")])

        self.assertEqual(["completed", "pending"], self.states())
        self.assertEqual(1, len(added))
        self.service.run_transcription(job["job_id"])
        self.assertEqual(["completed", "transcribed"], self.states())
        self.service.run_render(job["job_id"], {}, self.output)
        self.assertEqual(["one.mp4", "two.mp4"], self.rendered)

    def test_same_file_is_not_added_twice(self):
        job = self.service.workspace()
        path = self.video("one.mp4")
        self.service.add_items(job["job_id"], [path])
        _, added = self.service.add_items(job["job_id"], [path])
        self.assertEqual([], added)
        self.assertEqual(1, len(self.service.workspace()["items"]))

    def test_render_does_not_need_an_approval_step(self):
        job = self.service.workspace()
        self.service.add_items(job["job_id"], [self.video("one.mp4")])
        self.service.run_transcription(job["job_id"])

        result = self.service.run_render(job["job_id"], {}, self.output)

        self.assertEqual(1, result["completed"])

    def test_editing_a_rendered_file_makes_it_ready_again(self):
        job = self.service.workspace()
        _, (item_id,) = self.service.add_items(job["job_id"], [self.video("one.mp4")])
        self.service.run_transcription(job["job_id"])
        self.service.run_render(job["job_id"], {}, self.output)

        transcript = self.service.get_transcript(item_id)
        word_id = transcript["words"][0]["id"]
        self.service.apply_patch(item_id, transcript["revision"],
                                 [{"op": "replace", "word_id": word_id, "text": " правка"}])

        self.assertEqual(1, self.service.workspace()["ready_count"])

    def test_rendered_file_can_be_rendered_again_when_selected(self):
        job = self.service.workspace()
        _, (item_id,) = self.service.add_items(job["job_id"], [self.video("one.mp4")])
        self.service.run_transcription(job["job_id"])
        self.service.run_render(job["job_id"], {}, self.output)
        (self.output / "one_captioned.mp4").write_bytes(b"x")

        result = self.service.run_render(job["job_id"], {}, self.output, selected_ids=[item_id])

        self.assertEqual(1, result["completed"])
        self.assertTrue(self.service.workspace()["items"][0]["output"].endswith("one_captioned_2.mp4"))

    def test_removed_file_leaves_the_list_and_its_transcript(self):
        job = self.service.workspace()
        _, (first, second) = self.service.add_items(
            job["job_id"], [self.video("one.mp4"), self.video("two.mp4")])
        self.service.run_transcription(job["job_id"])

        snapshot = self.service.remove_items(job["job_id"], [first])

        self.assertEqual(["two.mp4"], [item["name"] for item in snapshot["items"]])
        self.assertEqual(0, snapshot["items"][0]["index"])
        self.assertFalse((self.root / "revisions" / f"{first}.revisions.json").exists())

    def test_deleted_source_fails_that_file_with_a_clear_message(self):
        job = self.service.workspace()
        path = self.video("gone.mp4")
        self.service.add_items(job["job_id"], [path, self.video("kept.mp4")])
        path.unlink()

        self.service.run_transcription(job["job_id"])

        items = self.service.workspace()["items"]
        self.assertEqual(["failed", "transcribed"], [item["state"] for item in items])
        self.assertIn("не найден", items[0]["error"])

    def test_cancelled_render_keeps_the_transcript_ready(self):
        job = self.service.workspace()
        self.service.add_items(job["job_id"], [self.video("one.mp4")])
        self.service.run_transcription(job["job_id"])

        self.service.run_render(job["job_id"], {}, self.output, cancelled=lambda: True)

        self.assertEqual(["transcribed"], self.states())

    def test_workspace_survives_a_restart(self):
        job = self.service.workspace()
        self.service.add_items(job["job_id"], [self.video("one.mp4")])
        restarted = ManualJobService(self.root / "revisions",
                                     self.service.transcribe_fn, self.service.render_fn)
        self.assertEqual(job["job_id"], restarted.workspace()["job_id"])
        self.assertEqual(["pending"], [item["state"] for item in restarted.workspace()["items"]])


if __name__ == "__main__":
    unittest.main()
