"""Manual titles: text with its own timings drawn over the video."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer
from lib.manual_jobs import ManualJobService


def transcript_for(text):
    return {"language": "ru", "duration": 5.0, "segments": [{
        "start": 0.1, "end": 0.8, "text": " " + text,
        "words": [{"word": " " + text, "start": 0.1, "end": 0.8, "probability": 0.95}],
    }]}


class TitleRenderingTests(unittest.TestCase):
    def style(self, **changes):
        style = copy.deepcopy(renderer.TITLE_STYLE)
        style.update(changes)
        return style

    def ink_box(self, image):
        self.assertIsNotNone(image)
        return image.getbbox()

    def test_long_text_is_wrapped_and_shrunk_into_the_block(self):
        long_text = "Очень длинный заголовок из многих слов, который обязан поместиться в кадр целиком"
        image = renderer.render_title_image(1080, 1920, long_text, self.style(font_size=140))
        left, top, right, bottom = self.ink_box(image)

        self.assertLessEqual(right - left, 1080)
        self.assertLessEqual(bottom - top, 1920 * 0.42)
        self.assertGreaterEqual(left, 0)

    def test_position_moves_the_block(self):
        boxes = {}
        for position in ("top", "center", "bottom"):
            image = renderer.render_title_image(
                1080, 1920, "Заголовок", self.style(position=position, position_margin=150))
            boxes[position] = self.ink_box(image)

        self.assertLess(boxes["top"][1], boxes["center"][1])
        self.assertLess(boxes["center"][1], boxes["bottom"][1])
        self.assertGreaterEqual(boxes["top"][1], 100)

    def test_empty_text_draws_nothing(self):
        self.assertIsNone(renderer.render_title_image(1080, 1920, "   ", self.style()))

    def test_static_plate_is_drawn_under_the_text(self):
        plain = renderer.render_title_image(1080, 1920, "Заголовок", self.style(highlight_style="none"))
        plate = renderer.render_title_image(
            1080, 1920, "Заголовок", self.style(highlight_style="box", box_color="#FF0000"))
        reds = sum(1 for px in plate.getdata() if px[3] > 200 and px[0] > 200 and px[1] < 80)

        self.assertGreater(reds, 1000)
        self.assertEqual(0, sum(1 for px in plain.getdata() if px[3] > 200 and px[0] > 200 and px[1] < 80))

    def test_clips_skip_empty_titles_and_clamp_to_the_video(self):
        overlays = [
            {"text": "Первый", "start": 0.0, "end": 2.0},
            {"text": "   ", "start": 0.0, "end": 2.0},
            {"text": "Хвост за концом видео", "start": 4.0, "end": 99.0},
            {"text": "Без длительности", "start": 3.0, "end": 3.0},
        ]
        clips = renderer.title_clips(1080, 1920, 5.0, overlays, renderer.TITLE_STYLE)

        self.assertEqual(2, len(clips))
        self.assertAlmostEqual(2.0, clips[0].duration, places=2)
        self.assertAlmostEqual(1.0, clips[1].duration, places=2)   # clamped to 5.0


class TitleStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rendered = []

        def transcribe(path, **_p):
            return {"transcript": transcript_for("готово"), "cached": False}

        def render(path, output, segments, style=None, progress_cb=None, overlays=None):
            self.rendered.append(overlays)
            return {"output": str(output)}

        self.service = ManualJobService(self.root / "revisions", transcribe, render)
        video = self.root / "clip.mp4"
        video.write_bytes(b"video")
        job = self.service.workspace()
        _snapshot, (self.item_id,) = self.service.add_items(job["job_id"], [video])
        self.job_id = job["job_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_titles_reach_the_renderer_and_survive_a_restart(self):
        self.service.set_overlays(self.item_id, [{"text": "Заголовок", "start": 0, "end": 2.5}])
        self.service.run_transcription(self.job_id)
        self.service.run_render(self.job_id, {}, self.root / "out")

        self.assertEqual([[{"text": "Заголовок", "start": 0.0, "end": 2.5}]], self.rendered)
        restarted = ManualJobService(self.root / "revisions",
                                     self.service.transcribe_fn, self.service.render_fn)
        self.assertEqual("Заголовок",
                         restarted.workspace()["items"][0]["overlays"][0]["text"])

    def test_editing_a_title_after_a_render_makes_the_file_ready_again(self):
        self.service.run_transcription(self.job_id)
        self.service.run_render(self.job_id, {}, self.root / "out")
        self.assertEqual("completed", self.service.workspace()["items"][0]["state"])

        self.service.set_overlays(self.item_id, [{"text": "Новый", "start": 0, "end": 1}])

        self.assertEqual(1, self.service.workspace()["ready_count"])


if __name__ == "__main__":
    unittest.main()


class TitleAnimationTests(unittest.TestCase):
    """Each title arrives and leaves on its own terms."""

    def image(self):
        return renderer.render_title_image(1080, 1920, "Заголовок", renderer.TITLE_STYLE)

    def test_phase_reads_the_switch_the_kind_and_the_length(self):
        style = {"anim_in_enabled": True, "anim_in_kind": "zoom", "anim_in_ms": 500}
        self.assertEqual(("zoom", 0.5), renderer._title_phase(style, "in"))
        self.assertEqual((None, 0.0), renderer._title_phase(style, "out"))
        self.assertEqual((None, 0.0), renderer._title_phase(
            {"anim_in_enabled": False, "anim_in_kind": "zoom", "anim_in_ms": 500}, "in"))
        self.assertEqual((None, 0.0), renderer._title_phase(
            {"anim_in_enabled": True, "anim_in_kind": "нечто", "anim_in_ms": 500}, "in"))
        self.assertEqual((None, 0.0), renderer._title_phase(
            {"anim_in_enabled": True, "anim_in_kind": "fade", "anim_in_ms": 0}, "in"))

    def test_slide_starts_outside_the_frame_and_lands_in_place(self):
        clips = renderer._title_clips_for(
            self.image(), 0.0, 4.0, 1080, 1920, ("slide_left", 0.5), (None, 0.0))
        body = clips[-1]
        start_x, _ = body.pos(0.0)
        end_x, _ = body.pos(1.0)

        self.assertLess(start_x, 0)          # off the left edge
        self.assertGreater(end_x, start_x)
        self.assertAlmostEqual(end_x, body.pos(3.0)[0], places=3)

    def test_each_side_moves_along_its_own_axis(self):
        for kind, axis, outside in (("slide_right", 0, True), ("slide_up", 1, False),
                                    ("slide_down", 1, True)):
            clips = renderer._title_clips_for(
                self.image(), 0.0, 4.0, 1080, 1920, (kind, 0.5), (None, 0.0))
            begin, finish = clips[-1].pos(0.0), clips[-1].pos(1.0)
            moved = abs(begin[axis] - finish[axis])
            still = abs(begin[1 - axis] - finish[1 - axis])
            self.assertGreater(moved, 100, kind)
            self.assertAlmostEqual(0, still, places=3)
            if outside:
                self.assertGreater(begin[axis], finish[axis], kind)

    def test_zoom_grows_from_small_and_keeps_the_centre(self):
        clips = renderer._title_clips_for(
            self.image(), 0.0, 4.0, 1080, 1920, ("zoom", 0.5), (None, 0.0))
        body = clips[-1]
        small = body.get_frame(0.0).shape[1]
        full = body.get_frame(2.0).shape[1]

        self.assertLess(small, full)
        centre_at = lambda t: body.pos(t)[0] + body.get_frame(t).shape[1] / 2
        self.assertAlmostEqual(centre_at(0.0), centre_at(2.0), delta=2)

    def test_blur_is_a_stack_of_stills_that_covers_its_phase(self):
        clips = renderer._title_clips_for(
            self.image(), 1.0, 3.0, 1080, 1920, ("blur", 0.5), ("blur", 0.5))
        steps = [c for c in clips[:-1]]

        self.assertEqual(2 * renderer._BLUR_STEPS, len(steps))
        self.assertAlmostEqual(1.0, min(c.start for c in steps), places=3)
        self.assertAlmostEqual(4.0, max(c.start + c.duration for c in steps), places=2)
        body = clips[-1]
        self.assertAlmostEqual(1.5, body.start, places=3)
        self.assertAlmostEqual(3.5, body.start + body.duration, places=3)

    def test_animations_never_take_more_than_half_the_title(self):
        clips = renderer._title_clips_for(
            self.image(), 0.0, 1.0, 1080, 1920, ("blur", 5.0), ("blur", 5.0))
        body = clips[-1]

        self.assertAlmostEqual(0.5, body.start, places=3)
        self.assertLessEqual(body.start + body.duration, 1.01)

    def test_two_titles_keep_their_own_style(self):
        style = {"title_styles": [
            {"position": "top", "position_margin": 100, "anim_in_kind": "slide_left"},
            {"position": "bottom", "position_margin": 100},
        ]}
        overlays = [{"text": "Сверху", "start": 0, "end": 2},
                    {"text": "Снизу", "start": 0, "end": 2}]
        clips = renderer.title_clips(1080, 1920, 5.0, overlays, style)
        tops = [clip.pos(1.0)[1] for clip in clips]

        self.assertEqual(2, len(clips))
        self.assertLess(tops[0], 400)
        self.assertGreater(tops[1], 1400)

    def test_an_older_preset_with_one_shared_style_still_works(self):
        style = {"title_style": {"position": "top", "font_size": 50}}
        for index in (0, 1):
            self.assertEqual("top", renderer.title_style_for(style, index)["position"])
        self.assertEqual("center", renderer.title_style_for({}, 0)["position"])
