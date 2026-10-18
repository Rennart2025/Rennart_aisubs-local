"""Подмена видеофайла, черновой рендер, старт первого слова и очередь заголовков."""

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

import renderer
from lib.manual_jobs import ManualJobError, ManualJobService
from lib.transcript_revisions import TranscriptStore


TRANSCRIPT = {"language": "ru", "duration": 20.0, "segments": [{
    "start": 0.0, "end": 1.4, "text": " привет мир",
    "words": [{"word": " привет", "start": 0.0, "end": 0.8, "probability": 0.9},
              {"word": " мир", "start": 0.9, "end": 1.4, "probability": 0.9}],
}]}


def transcriber(path, progress_cb=None, abort=None, **params):
    return {"transcript": copy.deepcopy(TRANSCRIPT)}


class FirstWordTests(unittest.TestCase):
    def setUp(self):
        self.store = TranscriptStore(tempfile.mkdtemp())

    def test_a_word_starting_at_zero_is_pushed_to_a_tenth_of_a_second(self):
        revision = self.store.create("item-1", "clip.mp4", TRANSCRIPT, {})

        self.assertAlmostEqual(0.1, revision["words"][0]["start"])
        self.assertAlmostEqual(0.8, revision["words"][0]["end"], msg="конец не трогаем")
        self.assertAlmostEqual(0.9, revision["words"][1]["start"], msg="остальные слова на месте")

    def test_a_word_that_already_starts_later_is_left_alone(self):
        late = copy.deepcopy(TRANSCRIPT)
        late["segments"][0]["words"][0]["start"] = 1.5
        late["segments"][0]["words"][0]["end"] = 2.0

        revision = self.store.create("item-2", "clip.mp4", late, {})

        self.assertAlmostEqual(1.5, revision["words"][0]["start"])

    def test_a_very_short_first_word_is_not_turned_inside_out(self):
        tight = copy.deepcopy(TRANSCRIPT)
        tight["segments"][0]["words"][0].update(start=0.0, end=0.08)

        revision = self.store.create("item-3", "clip.mp4", tight, {})
        word = revision["words"][0]

        self.assertLess(word["start"], word["end"])

    def test_text_restored_from_a_project_keeps_its_timings(self):
        revision = self.store.create("item-4", "clip.mp4", TRANSCRIPT, {}, lead_in=False)

        self.assertAlmostEqual(0.0, revision["words"][0]["start"])


class ReplaceSourceTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.old = os.path.join(self.work, "old.mp4")
        self.new = os.path.join(self.work, "new.mp4")
        for path in (self.old, self.new):
            Path(path).write_bytes(b"video")
        self.service = ManualJobService(os.path.join(self.work, "rev"),
                                        transcriber, lambda *a, **k: None)
        job = self.service.workspace()
        self.service.add_items(job["job_id"], [self.old])
        self.item_id = self.service.workspace()["items"][0]["item_id"]
        self.service.run_transcription(job["job_id"])
        self.service.set_overlays(self.item_id, [{"text": "Лайфхак", "start": 0.0, "end": 1.0}])

    def item(self):
        return self.service.workspace()["items"][0]

    def test_the_text_and_the_titles_survive_the_swap(self):
        before = [word["word"] for word in self.service.get_transcript(self.item_id)["words"]]

        self.service.replace_source(self.item_id, self.new, duration=19.0)

        after = [word["word"] for word in self.service.get_transcript(self.item_id)["words"]]
        self.assertEqual(before, after)
        self.assertEqual("Лайфхак", self.item()["overlays"][0]["text"])
        self.assertEqual("new.mp4", self.item()["name"])

    def test_the_new_duration_is_what_the_timings_are_checked_against(self):
        self.service.replace_source(self.item_id, self.new, duration=1.0)

        errors = self.service.store.validation_errors(
            self.service.get_transcript(self.item_id))

        self.assertTrue(any("конец видео" in error for error in errors))

    def test_the_file_is_ready_to_render_onto_the_new_video(self):
        self.service.replace_source(self.item_id, self.new)

        self.assertEqual("needs_review", self.item()["state"])
        self.assertIsNone(self.item()["output"], "старый результат больше не относится к делу")

    def test_a_video_that_is_already_in_the_list_is_refused(self):
        job = self.service.workspace()
        self.service.add_items(job["job_id"], [self.new])

        with self.assertRaises(ManualJobError):
            self.service.replace_source(self.item_id, self.new)

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(ManualJobError):
            self.service.replace_source(self.item_id, os.path.join(self.work, "нет.mp4"))


class DraftRenderTests(unittest.TestCase):
    def test_pixel_sizes_shrink_with_the_frame(self):
        style = copy.deepcopy(renderer.DEFAULT_STYLE)
        style.update(font_size=90, position_margin=190, box_padding_x=20,
                     shadow_offset=[4, 8], stroke_width=3)

        half = renderer.scale_style(style, 0.5)

        self.assertEqual(45, half["font_size"])
        self.assertEqual(95, half["position_margin"])
        self.assertEqual(10, half["box_padding_x"])
        self.assertEqual([2, 4], half["shadow_offset"])
        self.assertEqual(2, half["stroke_width"])

    def test_ratios_and_durations_stay_as_they_are(self):
        style = copy.deepcopy(renderer.DEFAULT_STYLE)

        half = renderer.scale_style(style, 0.5)

        self.assertEqual(style["max_width_ratio"], half["max_width_ratio"])
        self.assertEqual(style["line_spacing"], half["line_spacing"])
        self.assertEqual(style["line_count"], half["line_count"])
        self.assertEqual(style["word_animation_ms"], half["word_animation_ms"])
        self.assertEqual(style["shadow_opacity"], half["shadow_opacity"])

    def test_title_styles_shrink_too(self):
        style = {"preview_scale": 0.5,
                 "title_styles": [{"font_size": 96, "position_margin": 220, "offset_x": -300}]}

        title = renderer.title_style_for(style, 0)

        self.assertEqual(48, title["font_size"])
        self.assertEqual(110, title["position_margin"])
        self.assertEqual(-150, title["offset_x"])

    def test_a_title_left_at_its_defaults_shrinks_as_well(self):
        """Иначе заголовок по умолчанию выйдет вдвое крупнее, чем в чистовике."""
        full = renderer.title_style_for({}, 0)
        draft = renderer.title_style_for({"preview_scale": 0.5}, 0)

        self.assertEqual(full["font_size"] // 2, draft["font_size"])
        self.assertEqual(full["box_padding_x"] // 2, draft["box_padding_x"])

    def test_title_offsets_shrink_with_the_frame(self):
        draft = renderer.title_style_for(
            {"preview_scale": 0.5, "title_styles": [{"offset_x": -300, "offset_y": 640}]}, 0)

        self.assertEqual(-150, draft["offset_x"])
        self.assertEqual(320, draft["offset_y"])

    def test_the_default_is_a_full_size_render(self):
        self.assertEqual(1.0, renderer.DEFAULT_STYLE["preview_scale"])


class RenderQueueTests(unittest.TestCase):
    """Второй рендер того же файла — со своими заголовками, снятыми заранее."""

    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.video = os.path.join(self.work, "clip.mp4")
        Path(self.video).write_bytes(b"video")
        self.rendered = []

        def render_fn(path, output, segments, overlays=None, style=None, **kw):
            self.rendered.append(list(overlays or []))
            Path(output).write_bytes(b"out")
            return {"output": str(output)}

        self.service = ManualJobService(os.path.join(self.work, "rev"),
                                        transcriber, render_fn)
        self.job_id = self.service.workspace()["job_id"]
        self.service.add_items(self.job_id, [self.video])
        self.item_id = self.service.workspace()["items"][0]["item_id"]
        self.service.run_transcription(self.job_id)

    def render(self, overlays):
        self.service.set_overlays(self.item_id, overlays)
        captured = {self.item_id: copy.deepcopy(
            self.service.workspace()["items"][0]["overlays"])}
        return self.service.run_render(self.job_id, {}, os.path.join(self.work, "out"),
                                       selected_ids=[self.item_id],
                                       overlays_by_item=captured)

    def test_each_pass_renders_the_titles_it_was_queued_with(self):
        self.render([{"text": "С заголовком", "start": 0.0, "end": 1.0}])
        self.render([])

        self.assertEqual("С заголовком", self.rendered[0][0]["text"])
        self.assertEqual([], self.rendered[1])

    def test_the_two_passes_do_not_overwrite_each_other(self):
        self.render([{"text": "С заголовком", "start": 0.0, "end": 1.0}])
        first = self.service.workspace()["items"][0]["output"]
        self.render([])
        second = self.service.workspace()["items"][0]["output"]

        self.assertNotEqual(first, second)

    def test_titles_changed_during_a_pass_leave_the_file_marked_unrendered(self):
        captured = {self.item_id: []}
        self.service.set_overlays(self.item_id, [{"text": "Новый", "start": 0.0, "end": 1.0}])

        self.service.run_render(self.job_id, {}, os.path.join(self.work, "out"),
                                selected_ids=[self.item_id], overlays_by_item=captured)

        self.assertEqual("needs_review", self.service.workspace()["items"][0]["state"])

    def test_a_draft_render_gets_its_own_name(self):
        self.service.run_render(self.job_id, {"preview_scale": 0.5},
                                os.path.join(self.work, "out"), selected_ids=[self.item_id])

        output = self.service.workspace()["items"][0]["output"]

        self.assertTrue(output.endswith("_captioned_preview.mp4"), output)


if __name__ == "__main__":
    unittest.main()
