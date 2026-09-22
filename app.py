"""
AISubs desktop app: pywebview window hosting gui/index.html, backed by a small
js_api bridge that drives transcribe.py + renderer.py (pipeline.py).
"""

import os
import sys
import json
import glob
import queue
import threading
import traceback
import subprocess
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import webview
from webview import FileDialog

import pipeline as pipeline_mod
import transcribe as transcribe_mod
import mediaserver
import fontlist
from lib.manual_jobs import ManualJobService
from lib.transcript_revisions import RevisionConflict, TranscriptError

PRESETS_DIR = os.path.join(BASE_DIR, "presets")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
REVISIONS_DIR = os.path.join(BASE_DIR, "cache", "revisions")
APP_VERSION = "1.2.1"
CREATOR_CHANNEL_URL = "https://t.me/daipotestit"
CACHE_DIR = os.path.join(BASE_DIR, "cache")

# Every link the window can open, by key: the page never passes a URL.
LINKS = {
    "author": CREATOR_CHANNEL_URL,
    "fork_author": "https://t.me/rinatmaksutov",
    "repo": "https://github.com/Rennart2025/Rennart_aisubs-local",
}
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _human_size(num):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if num < 1024 or unit == "ГБ":
            return f"{num:.0f} {unit}" if unit in ("Б", "КБ") else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} ГБ"


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts"}


class Api:
    """Methods here are exposed to JS by pywebview.

    Attributes must stay underscore-private: pywebview walks the public
    attributes of this object to expose them, and a pywebview Window leads into
    the WinForms object graph, which recurses until it blows the stack.
    """

    def __init__(self):
        self._window = None
        self._cancelled = False
        self._js_queue = queue.Queue()
        self._js_thread = threading.Thread(target=self._js_pump, daemon=True)
        self._js_thread.start()
        self._worker_lock = threading.Lock()
        self._manual = ManualJobService(
            REVISIONS_DIR,
            pipeline_mod.transcribe_phase,
            pipeline_mod.render_phase,
            event_cb=self._manual_event,
        )

    # ---------- presets ----------

    def list_presets(self):
        result = []
        for path in sorted(glob.glob(os.path.join(PRESETS_DIR, "*.json"))):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data.setdefault("name", os.path.splitext(os.path.basename(path))[0])
                data["filename"] = os.path.splitext(os.path.basename(path))[0]
                result.append(data)
            except Exception:
                continue
        return result

    def save_preset(self, name, style):
        safe = "".join(c for c in name if c.isalnum() or c in (" ", "_", "-")).strip() or "custom"
        path = os.path.join(PRESETS_DIR, safe.replace(" ", "_") + ".json")
        style = dict(style)
        style["name"] = name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(style, f, ensure_ascii=False, indent=2)
        return True

    # ---------- files ----------

    def pick_videos(self):
        """Opens the file dialog without blocking the js_api thread.

        WinForms' ShowDialog must run on the thread that owns the window; called
        straight from js_api it deadlocks and the window goes "not responding".
        So we hand it to the UI thread via BeginInvoke and deliver the result to
        JS through a callback instead of a return value.
        """
        form = getattr(self._window, "native", None)

        def show():
            try:
                result = self._window.create_file_dialog(
                    FileDialog.OPEN,
                    allow_multiple=True,
                    file_types=("Видео (*.mp4;*.mov;*.mkv;*.avi;*.webm)", "Все файлы (*.*)"),
                )
                self._push_files(list(result) if result else [])
            except Exception as e:
                traceback.print_exc()
                self._js("onPipelineError", f"Не удалось открыть диалог выбора файлов: {e}")

        if form is None:
            show()
        else:
            from System import Action
            form.BeginInvoke(Action(show))
        return True

    def _js_pump(self):
        """Serialises all JS calls onto one background thread.

        evaluate_js blocks until WebView2 answers, so calling it from the UI
        thread (drag & drop handlers run there) deadlocks the window. Queueing
        keeps callers non-blocking while preserving call order.
        """
        while True:
            script = self._js_queue.get()
            try:
                if self._window is not None:
                    self._window.evaluate_js(script)
            except Exception:
                pass

    def _js(self, fn, *js_args):
        payload = ", ".join(json.dumps(a, ensure_ascii=False) for a in js_args)
        self._js_queue.put(f"window.{fn}({payload})")

    def _push_files(self, paths):
        videos = [p for p in paths if os.path.splitext(p)[1].lower() in VIDEO_EXTS]
        if paths and not videos:
            self._js("showToast", "Это не видео: поддерживаются " + ", ".join(sorted(VIDEO_EXTS)))
            return
        self._js("onVideosPicked", videos)

    def _manual_event(self, snapshot, _item):
        self._js("onWorkspaceUpdated", snapshot)

    def delete_preset(self, filename):
        """Removes a preset by its file stem. Refuses anything that would
        escape the presets folder."""
        stem = os.path.basename(str(filename or "")).removesuffix(".json")
        if not stem or stem in (".", ".."):
            return {"ok": False, "error": "пустое имя"}

        path = os.path.join(PRESETS_DIR, stem + ".json")
        if os.path.dirname(os.path.abspath(path)) != os.path.abspath(PRESETS_DIR):
            return {"ok": False, "error": "недопустимый путь"}
        if not os.path.exists(path):
            return {"ok": False, "error": "пресет не найден"}

        try:
            os.remove(path)
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def typography(self):
        """Word rules the preview needs to group captions like the renderer."""
        from lib.typography import HANGING_WORDS
        return {"hanging_words": sorted(HANGING_WORDS)}

    def models_status(self):
        """Which models are already on disk, so the UI can say what needs a download."""
        try:
            import transcribe as t
            models_dir = os.path.join(BASE_DIR, "models", "whisper")
            return {size: t.is_model_cached(size, models_dir) for size in
                    ("large-v3", "distil-large-v3", "medium", "small", "base", "tiny")}
        except Exception:
            traceback.print_exc()
            return {}

    def list_fonts(self):
        """Bundled faces plus everything installed in Windows."""
        try:
            return fontlist.list_fonts()
        except Exception:
            traceback.print_exc()
            return []

    def font_url(self, path):
        """URL of a font file, so the preview can @font-face it directly."""
        try:
            file_path = str(path).partition("#")[0]
            if not os.path.isabs(file_path):
                file_path = os.path.join(BASE_DIR, file_path)
            if not os.path.exists(file_path):
                return None
            return mediaserver.font_url(file_path)
        except Exception:
            traceback.print_exc()
            return None

    def video_info(self, path):
        """Geometry plus http URLs the page can actually load (file:// cannot).

        Frame extraction is the slow part, so it is requested separately.
        """
        try:
            info = mediaserver.probe(path)
            info["media_url"] = mediaserver.media_url(path)
            info["name"] = os.path.basename(path)
            return info
        except Exception:
            traceback.print_exc()
            return {}

    def frame_url(self, path, at_seconds=None):
        try:
            return mediaserver.frame_url(path, at_seconds)
        except Exception:
            traceback.print_exc()
            return None

    def open_output_folder(self, path):
        target = os.path.dirname(path) if path and os.path.isfile(path) else OUTPUT_DIR
        os.startfile(target)
        return True

    def app_info(self):
        """Version and the links shown in the header."""
        return {"version": APP_VERSION, "links": dict(LINKS)}

    def open_link(self, key):
        """Opens one of the known links. A key, never a URL from the page."""
        url = LINKS.get(str(key))
        if not url:
            return {"ok": False, "error": "неизвестная ссылка"}
        try:
            if not webbrowser.open(url, new=2):
                return {"ok": False, "error": "Не удалось открыть браузер"}
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def cache_usage(self):
        """How much disk the cache takes, for the badge in the header."""
        total = files = 0
        for root, _dirs, names in os.walk(CACHE_DIR):
            for name in names:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                    files += 1
                except OSError:
                    pass
        return {"bytes": total, "files": files, "text": _human_size(total)}

    def open_cache_folder(self):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            os.startfile(CACHE_DIR)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_creator_channel(self):
        try:
            if not webbrowser.open(CREATOR_CHANNEL_URL, new=2):
                return {"ok": False, "error": "Не удалось открыть браузер"}
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---------- system info ----------

    def get_gpu_info(self):
        """The card, and whether transcription can actually use it.

        nvidia-smi only proves a driver is installed. A run also needs a CUDA
        build that sees the device, the cuBLAS/cuDNN libraries, and a compute
        type the card supports - and when any of those is missing the job
        quietly lands on the CPU. Reporting only the name put a green light
        over CPU-speed work and left the cause invisible.
        """
        name = None
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                name = out.stdout.strip().splitlines()[0]
        except Exception:
            name = None

        if not name:
            return {"available": False, "usable": False, "name": None,
                    "compute_type": None, "reason": None}

        compute_types = transcribe_mod.cuda_compute_types()
        missing = transcribe_mod.missing_cuda_libraries()
        if not compute_types:
            reason = "CUDA недоступна — распознавание пойдёт на процессоре"
        elif missing:
            reason = "нет " + " и ".join(missing) + " — запустите setup.bat"
        else:
            reason = None

        return {
            "available": True,
            "usable": reason is None,
            "name": name,
            "compute_type": compute_types[0] if compute_types else None,
            "reason": reason,
        }

    # ---------- pipeline ----------

    def cancel_queue(self):
        self._cancelled = True
        return True

    # ---------- workspace: one list of files, Transcribe -> edit -> Render ----------

    def _start_worker(self, target):
        """Runs one transcription or render pass at a time.

        Two passes over the same list would race on the same items, so a
        second request while one is running is refused instead of queued.
        """
        if not self._worker_lock.acquire(blocking=False):
            return False

        def run():
            try:
                target()
            except Exception as exc:
                traceback.print_exc()
                self._js("onPipelineError", str(exc))
            finally:
                self._worker_lock.release()
                try:
                    self._js("onWorkspaceUpdated", self._manual.workspace())
                except Exception:
                    traceback.print_exc()

        threading.Thread(target=run, daemon=True).start()
        return True

    def workspace(self):
        try:
            return {"ok": True, "job": self._manual.workspace()}
        except Exception as exc:
            traceback.print_exc()
            return {"ok": False, "error": str(exc)}

    def add_videos(self, paths):
        try:
            job = self._manual.workspace()
            videos = [p for p in (paths or []) if os.path.splitext(p)[1].lower() in VIDEO_EXTS]
            snapshot, added = self._manual.add_items(job["job_id"], videos)
            return {"ok": True, "job": snapshot, "added": added}
        except Exception as exc:
            traceback.print_exc()
            return {"ok": False, "error": str(exc)}

    def remove_videos(self, item_ids):
        try:
            job = self._manual.workspace()
            return {"ok": True, "job": self._manual.remove_items(job["job_id"], item_ids or [])}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def transcribe(self, args):
        """Transcribes the given files (default: every file that has no text yet)."""
        args = args or {}
        params = {
            "model_size": args.get("model") or "large-v3",
            "device": args.get("device") or "auto",
            "language": args.get("language") or None,
        }
        job_id = self._manual.workspace()["job_id"]
        item_ids = args.get("item_ids") or None
        self._cancelled = False
        started = self._start_worker(lambda: self._manual.run_transcription(
            job_id, selected_ids=item_ids, params=params,
            cancelled=lambda: self._cancelled,
        ))
        if not started:
            return {"ok": False, "error": "Дождитесь окончания текущей обработки"}
        return {"ok": True}

    def render(self, args):
        """Renders the given files with the current style (default: all ready files)."""
        args = args or {}
        style = args.get("style") or {}
        item_ids = args.get("item_ids") or None
        job_id = self._manual.workspace()["job_id"]
        self._cancelled = False

        def work():
            result = self._manual.run_render(
                job_id, style, OUTPUT_DIR, selected_ids=item_ids,
                cancelled=lambda: self._cancelled,
            )
            self._js("onRenderDone", result)

        if not self._start_worker(work):
            return {"ok": False, "error": "Дождитесь окончания текущей обработки"}
        return {"ok": True}

    def retranscribe(self, item_id, args=None):
        """New transcript for one file with the current model settings, bypassing the cache."""
        args = args or {}
        params = {
            "model_size": args.get("model") or "large-v3",
            "device": args.get("device") or "auto",
            "language": args.get("language") or None,
            "use_cached_transcript": False,
        }
        self._cancelled = False
        started = self._start_worker(lambda: self._manual.retranscribe(
            item_id, params=params, cancelled=lambda: self._cancelled
        ))
        if not started:
            return {"ok": False, "error": "Дождитесь окончания текущей обработки"}
        return {"ok": True}

    def set_overlays(self, item_id, overlays):
        """Manual titles for one file: [{text, start, end}, ...]."""
        try:
            return {"ok": True, "job": self._manual.set_overlays(item_id, overlays or [])}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_transcript(self, item_id):
        try:
            return {"ok": True, "transcript": self._manual.get_transcript(item_id)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def apply_transcript_patch(self, item_id, base_revision, operations):
        try:
            revision = self._manual.apply_patch(item_id, base_revision, operations or [])
            return {"ok": True, "transcript": revision}
        except RevisionConflict as exc:
            return {"ok": False, "code": "revision_conflict", "error": str(exc)}
        except TranscriptError as exc:
            return {"ok": False, "code": "invalid_patch", "error": str(exc)}
        except Exception as exc:
            traceback.print_exc()
            return {"ok": False, "code": "internal", "error": str(exc)}


def enable_file_drop(api, window):
    """Native drag & drop of video files.

    The page fills the whole window and WebView2 runs in its own process, so
    WinForms drag events on the form never fire. pywebview's DOM events do
    reach Python, and on WebView2 each dropped file carries its real path in
    `pywebviewFullPath` (the HTML5 File API alone never exposes it).
    The drag highlight itself is handled in the page (gui/workspace.js).
    """
    from webview.dom import DOMEventHandler

    def ignore(_event):
        pass

    def on_drop(event):
        try:
            files = (event.get("dataTransfer") or {}).get("files") or []
            paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if paths:
                api._push_files(paths)
        except Exception:
            traceback.print_exc()

    try:
        events = window.dom.document.events
        # preventDefault on dragover/drop keeps WebView2 from opening the file.
        events.dragenter += DOMEventHandler(ignore, True, True)
        events.dragover += DOMEventHandler(ignore, True, True, debounce=500)
        events.drop += DOMEventHandler(on_drop, True, True)
    except Exception:
        traceback.print_exc()


def main():
    mediaserver.start()
    api = Api()
    window = webview.create_window(
        "AISubs",
        os.path.join(BASE_DIR, "gui", "index.html"),
        js_api=api,
        width=1560,
        height=900,
        min_size=(1280, 720),
        background_color="#0c0e13",
    )
    # Must stay underscore-private: pywebview walks public attributes of js_api
    # to build the JS bridge, and a Window leads into the WinForms/.NET graph,
    # where a property read blocks on the UI thread and freezes the app.
    api._window = window
    window.events.loaded += lambda: enable_file_drop(api, window)
    webview.start()


if __name__ == "__main__":
    main()
