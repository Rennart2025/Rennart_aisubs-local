"""One working list of videos: transcribe, edit the words, render.

The GUI keeps a single persistent "workspace" job. Files can be added to it
and removed from it at any time; each one moves through its own states
independently, so adding a video after another has been rendered simply
gives the list one more file waiting for transcription.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from pathlib import Path

from lib import project_file
from lib.cancellation import Cancelled
from lib.transcript_revisions import TranscriptStore


# Waiting for, or in, a transcription run.
TRANSCRIPTION_ACTIVE = {"queued", "transcribing"}
# Anything a worker thread is touching right now.
ACTIVE = TRANSCRIPTION_ACTIVE | {"rendering"}
# Picked up by a transcription run. "pending" = added but never started.
TRANSCRIBABLE = {"pending", "queued", "failed", "no_speech", "cancelled"}
# Has a transcript that has not been rendered since it was last edited.
RENDER_READY = {"transcribed", "needs_review", "approved", "render_failed"}
# May be rendered when asked for explicitly (re-render after a style change).
RENDERABLE = RENDER_READY | {"completed"}


class ManualJobError(RuntimeError):
    pass


class ManualJobService:
    def __init__(self, revisions_dir, transcribe_fn, render_fn, event_cb=None):
        self.store = TranscriptStore(revisions_dir)
        self.transcribe_fn = transcribe_fn
        self.render_fn = render_fn
        self.event_cb = event_cb
        self.jobs = {}
        self.item_to_job = {}
        self.lock = threading.RLock()
        self.jobs_path = Path(revisions_dir) / "manual_jobs.json"
        self._load_jobs()

    # ---------- persistence ----------

    def _load_jobs(self):
        if not self.jobs_path.exists():
            return
        try:
            with self.jobs_path.open("r", encoding="utf-8") as handle:
                saved = json.load(handle)
            for job in saved.get("jobs", []):
                for item in job.get("items", []):
                    state = item.get("state")
                    if state == "rendering" and item.get("revision"):
                        # The transcript is intact; only the render was cut off.
                        item.update(
                            state="render_failed", stage="render_failed",
                            error="Рендер был прерван при закрытии приложения",
                        )
                    elif state in ACTIVE:
                        item.update(
                            state="cancelled", stage="cancelled",
                            error="Работа была прервана при закрытии приложения",
                        )
                    self.item_to_job[item["item_id"]] = job["job_id"]
                self.jobs[job["job_id"]] = job
        except (OSError, ValueError, KeyError):
            self.jobs = {}
            self.item_to_job = {}

    def _persist_jobs(self):
        with self.lock:
            temp = self.jobs_path.with_suffix(".json.tmp")
            with temp.open("w", encoding="utf-8") as handle:
                json.dump({"jobs": list(self.jobs.values())}, handle, ensure_ascii=False, indent=2)
            os.replace(temp, self.jobs_path)

    def _emit(self, job, item=None, persist=True):
        if persist:
            self._persist_jobs()
        if self.event_cb:
            with self.lock:
                snapshot = self._snapshot_unlocked(job)
                item_copy = copy.deepcopy(item) if item else None
            self.event_cb(snapshot, item_copy)

    # ---------- building the list ----------

    @staticmethod
    def _new_item(path, index, state):
        return {
            "item_id": "item-" + uuid.uuid4().hex[:12],
            "index": index,
            "path": os.path.abspath(os.fspath(path)),
            "name": os.path.basename(os.fspath(path)),
            "state": state,
            "progress": 0,
            "stage": state,
            "error": None,
            "revision": None,
            "output": None,
            "overlays": [],
        }

    def create_job(self, videos, params, initial_state="queued"):
        with self.lock:
            job_id = "manual-" + uuid.uuid4().hex[:12]
            items = []
            for index, path in enumerate(videos):
                item = self._new_item(path, index, initial_state)
                items.append(item)
                self.item_to_job[item["item_id"]] = job_id
            job = {"job_id": job_id, "params": copy.deepcopy(params), "items": items}
            self.jobs[job_id] = job
            self._persist_jobs()
            return self._snapshot_unlocked(job)

    def workspace(self):
        """The list the GUI works with: the latest job, or a new empty one."""
        with self.lock:
            if self.jobs:
                return self._snapshot_unlocked(list(self.jobs.values())[-1])
        return self.create_job([], {}, initial_state="pending")

    def add_items(self, job_id, videos):
        """Appends files that are not in the list yet; they wait for Transcribe."""
        with self.lock:
            job = self._job(job_id)
            known = {os.path.normcase(item["path"]) for item in job["items"]}
            added = []
            for path in videos:
                full = os.path.abspath(os.fspath(path))
                if os.path.normcase(full) in known:
                    continue
                known.add(os.path.normcase(full))
                item = self._new_item(full, len(job["items"]), "pending")
                job["items"].append(item)
                self.item_to_job[item["item_id"]] = job_id
                added.append(item["item_id"])
            self._persist_jobs()
            snapshot = self._snapshot_unlocked(job)
        return snapshot, added

    def remove_items(self, job_id, item_ids):
        with self.lock:
            job = self._job(job_id)
            doomed = set(item_ids)
            busy = [item["name"] for item in job["items"]
                    if item["item_id"] in doomed and item["state"] in ACTIVE]
            if busy:
                raise ManualJobError("файл сейчас обрабатывается: " + ", ".join(busy))
            job["items"] = [item for item in job["items"] if item["item_id"] not in doomed]
            for index, item in enumerate(job["items"]):
                item["index"] = index
            for item_id in doomed:
                self.item_to_job.pop(item_id, None)
                self.store.discard(item_id)
            self._persist_jobs()
            return self._snapshot_unlocked(job)

    def replace_source(self, item_id, new_path, duration=None):
        """Swaps the video under a file, keeping its text and titles.

        For the same clip re-exported at another quality: the audio is
        untouched, so every word still lands where it did. Only the path
        changes - the transcript, the manual edits and the titles stay.
        """
        job, item = self._item(item_id)
        if item["state"] in ACTIVE:
            raise ManualJobError("файл сейчас обрабатывается")
        full = os.path.abspath(os.fspath(new_path))
        if not os.path.exists(full):
            raise ManualJobError("файл не найден: " + full)
        clash = os.path.normcase(full)
        for other in job["items"]:
            if other is not item and os.path.normcase(other["path"]) == clash:
                raise ManualJobError("это видео уже есть в списке")

        item["path"] = full
        item["name"] = os.path.basename(full)
        item["output"] = None
        if item.get("revision"):
            self.store.retarget(item_id, full, duration)
            # The text is untouched, but it has never been rendered onto this
            # file, so the list says so.
            item.update(state="needs_review", stage="needs_review", error=None)
        self._emit(job, item)
        return self.snapshot(job["job_id"])

    # ---------- the work as a file ----------

    def export_project(self, style, app_version=""):
        """Everything the current list holds, ready to be written to disk."""
        with self.lock:
            job = list(self.jobs.values())[-1] if self.jobs else None
            items = copy.deepcopy(job["items"]) if job else []
            params = copy.deepcopy(job["params"]) if job else {}
        entries = []
        for item in items:
            transcript = None
            if item.get("revision"):
                try:
                    transcript = self.store.latest(item["item_id"])
                except Exception:
                    transcript = None
            entries.append(project_file.item_entry(item, transcript))
        return project_file.build(entries, style, params, app_version)

    def import_project(self, data, project_dir=""):
        """Replaces the list with the one saved in the project.

        The text comes back as revision 1 of each file: the edits are in it,
        the history behind them stays where it was made.
        """
        project_file.validate(data)
        entries = data.get("items") or []
        paths = [project_file.resolve_path(entry, project_dir) for entry in entries]

        with self.lock:
            for job in list(self.jobs.values()):
                for item in job["items"]:
                    self.item_to_job.pop(item["item_id"], None)
            self.jobs = {}

        snapshot = self.create_job(paths, data.get("params") or {}, initial_state="pending")
        job = self._job(snapshot["job_id"])
        missing = []
        for item, entry in zip(job["items"], entries):
            item["overlays"] = [dict(overlay) for overlay in entry.get("overlays") or []]
            if not os.path.exists(item["path"]):
                missing.append(item["name"])
            if not entry.get("words"):
                continue
            revision = self.store.create(
                item["item_id"], item["path"],
                project_file.transcription_of(entry), data.get("params") or {},
                lead_in=False,
            )
            item.update(state="needs_review", stage="needs_review",
                        revision=revision["revision"], progress=0, error=None)
        self._persist_jobs()
        return {"job": self.snapshot(job["job_id"]), "missing": missing,
                "style": data.get("style") or {}}

    # ---------- lookups ----------

    def _job(self, job_id):
        try:
            return self.jobs[job_id]
        except KeyError as exc:
            raise ManualJobError("job not found") from exc

    def _item(self, item_id):
        job = self._job(self.item_to_job.get(item_id))
        for item in job["items"]:
            if item["item_id"] == item_id:
                return job, item
        raise ManualJobError("item not found")

    def _snapshot_unlocked(self, job):
        items = copy.deepcopy(job["items"])
        settled = all(item["state"] not in TRANSCRIPTION_ACTIVE for item in items)
        approved = sum(item["state"] == "approved" for item in items)
        ready = sum(item["state"] in RENDER_READY and bool(item.get("revision")) for item in items)
        return {
            "job_id": job["job_id"],
            "items": items,
            "transcription_settled": settled,
            "busy": any(item["state"] in ACTIVE for item in items),
            "approved_count": approved,
            "ready_count": ready,
            "render_ready": settled and ready > 0,
        }

    def snapshot(self, job_id):
        with self.lock:
            return self._snapshot_unlocked(self._job(job_id))

    def latest_snapshot(self):
        with self.lock:
            if not self.jobs:
                return None
            return self._snapshot_unlocked(list(self.jobs.values())[-1])

    # ---------- transcription ----------

    def run_transcription(self, job_id, cancelled=None, selected_ids=None, params=None,
                          abort=None):
        job = self._job(job_id)
        if params:
            with self.lock:
                job["params"] = copy.deepcopy(params)
        selected = set(selected_ids) if selected_ids is not None else None

        with self.lock:
            targets = [
                item for item in job["items"]
                if (selected is None or item["item_id"] in selected)
                and item["state"] in TRANSCRIBABLE
            ]
            # Mark the whole run up front, so the list shows what is coming.
            for item in targets:
                item.update(state="queued", stage="queued", progress=0, error=None)
        if targets:
            self._emit(job)

        for item in targets:
            if item["state"] != "queued":
                continue  # removed or changed meanwhile
            if cancelled and cancelled():
                item.update(state="cancelled", stage="cancelled")
                self._emit(job, item)
                continue
            item.update(state="transcribing", stage="loading_model", progress=0, error=None)
            self._emit(job, item)

            def progress(stage, pct, current=item):
                current.update(stage=stage, progress=int(pct))
                self._emit(job, current, persist=False)

            try:
                effective_params = dict(job["params"])
                effective_params.update(item.pop("params_override", {}))
                if not os.path.exists(item["path"]):
                    raise FileNotFoundError("исходный файл не найден: " + item["path"])
                artifact = self.transcribe_fn(
                    item["path"], progress_cb=progress, abort=abort, **effective_params
                )
                transcript = artifact["transcript"]
                revision = self.store.create(
                    item["item_id"], item["path"], transcript, effective_params
                )
                state = "transcribed" if revision["words"] else "no_speech"
                item.update(
                    state=state, stage=state, progress=100,
                    revision=revision["revision"], error=None,
                )
            except Cancelled:
                # Stopped by hand: not a failure, and the file is ready to be
                # picked up again by the next Transcribe.
                item.update(state="cancelled", stage="cancelled", error=None)
                self._emit(job, item)
                break
            except Exception as exc:
                item.update(state="failed", stage="failed", error=str(exc))
            self._emit(job, item)
        return self.snapshot(job_id)

    def retranscribe(self, item_id, params=None, cancelled=None, abort=None):
        job, item = self._item(item_id)
        if item["state"] in ACTIVE:
            raise ManualJobError("файл сейчас обрабатывается")
        item.update(state="queued", stage="queued", progress=0, error=None, output=None)
        if params:
            item["params_override"] = copy.deepcopy(params)
        self._emit(job, item)
        return self.run_transcription(
            job["job_id"], selected_ids=[item_id], cancelled=cancelled, abort=abort
        )

    # ---------- editing ----------

    def get_transcript(self, item_id):
        self._item(item_id)
        return self.store.latest(item_id)

    def set_overlays(self, item_id, overlays):
        """Manual titles for one file: [{text, start, end, enabled}, ...].

        A title switched off keeps its text and timings - it is simply not
        drawn, so it can be brought back without retyping it.
        """
        job, item = self._item(item_id)
        cleaned = []
        for overlay in overlays or []:
            try:
                start = max(0.0, float((overlay or {}).get("start") or 0))
                end = max(0.0, float((overlay or {}).get("end") or 0))
            except (TypeError, ValueError):
                start = end = 0.0
            enabled = (overlay or {}).get("enabled")
            cleaned.append({"text": str((overlay or {}).get("text") or ""),
                            "start": start, "end": end,
                            "enabled": True if enabled is None else bool(enabled)})
        item["overlays"] = cleaned
        # A title change is a change to the output, like editing the text. A
        # file being rendered right now keeps its state: that pass carries its
        # own copy of the titles, and run_render settles the state when it is
        # done.
        if item["state"] == "completed" and item.get("revision"):
            item.update(state="needs_review", stage="needs_review")
        self._emit(job, item)
        return self._snapshot_unlocked(job)

    def apply_patch(self, item_id, base_revision, operations):
        job, item = self._item(item_id)
        if item["state"] in ACTIVE:
            raise ManualJobError("файл сейчас обрабатывается")
        revision = self.store.apply_patch(item_id, base_revision, operations)
        # An edit after a render makes the file ready to be rendered again.
        item.update(state="needs_review", revision=revision["revision"], error=None)
        self._emit(job, item)
        return revision

    def approve(self, item_id, revision):
        job, item = self._item(item_id)
        approved = self.store.approve(item_id, revision)
        item.update(state="approved", revision=approved["revision"], error=None)
        self._emit(job, item)
        return approved

    # ---------- rendering ----------

    def run_render(self, job_id, style, output_dir, selected_ids=None, cancelled=None,
                   abort=None, overlays_by_item=None):
        job = self._job(job_id)
        if not self._snapshot_unlocked(job)["transcription_settled"]:
            raise ManualJobError("transcription is still running")
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if selected_ids:
            selected, allowed = set(selected_ids), RENDERABLE
        else:
            selected, allowed = {item["item_id"] for item in job["items"]}, RENDER_READY
        completed = failed = skipped = 0
        used_names = set()
        for item in list(job["items"]):
            if (item["item_id"] not in selected or item["state"] not in allowed
                    or not item.get("revision")):
                skipped += 1
                continue
            if cancelled and cancelled():
                # Leave the file as it was: its transcript is still good.
                skipped += 1
                continue
            # A draft render says so in its name, so the two never get mixed up.
            draft = 0.1 <= float((style or {}).get("preview_scale") or 1.0) < 1.0
            stem = Path(item["path"]).stem + "_captioned" + ("_preview" if draft else "")
            candidate = stem
            suffix = 2
            while candidate.lower() in used_names or (output_dir / f"{candidate}.mp4").exists():
                candidate = f"{stem}_{suffix}"
                suffix += 1
            used_names.add(candidate.lower())
            output = output_dir / f"{candidate}.mp4"
            previous_state = item["state"]
            item.update(state="rendering", stage="preparing", progress=0, error=None)
            self._emit(job, item)

            def progress(stage, pct, current=item):
                current.update(stage=stage, progress=int(pct))
                self._emit(job, current, persist=False)

            try:
                if not os.path.exists(item["path"]):
                    raise FileNotFoundError("исходный файл не найден: " + item["path"])
                segments = self.store.render_segments(item["item_id"], item["revision"])
                # Titles as they were when this pass was queued: a second
                # render lined up behind it carries its own set, which is how
                # one clip can be made with a title and without one.
                used_overlays = (overlays_by_item or {}).get(item["item_id"])
                if used_overlays is None:
                    used_overlays = item.get("overlays") or []
                result = self.render_fn(
                    item["path"], output, segments, style=copy.deepcopy(style),
                    progress_cb=progress, overlays=copy.deepcopy(used_overlays),
                    abort=abort,
                )
                # If the titles moved on while this was rendering, the file on
                # disk is already one version behind - the list should say so.
                current = item.get("overlays") or []
                settled = "completed" if current == used_overlays else "needs_review"
                item.update(
                    state=settled, stage=settled, progress=100,
                    output=result["output"], error=None,
                )
                completed += 1
            except Cancelled:
                # The half-written file is already gone; the item goes back to
                # what it was, so Render can simply be pressed again.
                item.update(state=previous_state, stage="cancelled", progress=0, error=None)
                self._emit(job, item)
                skipped += 1
                break
            except Exception as exc:
                item.update(state="render_failed", stage="render_failed", error=str(exc))
                failed += 1
            self._emit(job, item)
        return {"completed": completed, "failed": failed, "skipped": skipped}
