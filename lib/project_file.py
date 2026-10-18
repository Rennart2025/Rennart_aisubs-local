"""The work, in one file you can keep, copy or hand over.

The program already remembers everything by itself in cache/, but that memory
belongs to this installation: clear the cache, reinstall, move to another
machine, and it is gone. A project file is the same work written out - the
list of videos, the text with every manual correction, the titles and the
style - so a job can be put away today and reopened next month.

The text is stored the way it stands after editing: deleted words are gone
rather than carried along as tombstones, and the revision history stays in the
cache. The point is a working file, not an archive of every keystroke.
"""

import os
import time

FORMAT = "aisubs-project"
VERSION = 1
SUFFIX = ".aisubs"


def build(items, style, params, app_version=""):
    """The project as a plain dict, ready for json.dump."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "app_version": str(app_version or ""),
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "style": style or {},
        "params": params or {},
        "items": list(items),
    }


def item_entry(item, transcript):
    """One video in the project: where it is, its titles and its text."""
    words = []
    for word in (transcript or {}).get("words") or []:
        if word.get("deleted"):
            continue
        words.append({
            "word": word.get("word", ""),
            "start": float(word.get("start") or 0),
            "end": float(word.get("end") or 0),
            "probability": word.get("probability"),
            "segment_index": int(word.get("segment_index") or 0),
        })
    return {
        "path": item.get("path", ""),
        "name": item.get("name") or os.path.basename(item.get("path", "")),
        "overlays": item.get("overlays") or [],
        "language": (transcript or {}).get("language"),
        "duration": float((transcript or {}).get("duration") or 0),
        "words": words,
    }


def validate(data):
    """Raises ValueError unless this really is one of our project files."""
    if not isinstance(data, dict):
        raise ValueError("файл проекта повреждён")
    if data.get("format") != FORMAT:
        raise ValueError("это не файл проекта AISubs")
    if int(data.get("version") or 0) > VERSION:
        raise ValueError("проект сохранён более новой версией программы")
    if not isinstance(data.get("items"), list):
        raise ValueError("в проекте нет списка видео")
    return data


def resolve_path(entry, project_dir):
    """Where the video actually is now.

    A project carries absolute paths, which break the moment the folder is
    renamed or the file travels to another machine. So a missing video is
    looked for next to the project file before giving up - which is where it
    usually sits.
    """
    path = entry.get("path") or ""
    if path and os.path.exists(path):
        return path
    name = entry.get("name") or os.path.basename(path)
    if name and project_dir:
        beside = os.path.join(project_dir, name)
        if os.path.exists(beside):
            return beside
    return path


def transcription_of(entry):
    """The stored words back in the shape a transcript is created from."""
    segments = {}
    for word in entry.get("words") or []:
        segments.setdefault(int(word.get("segment_index") or 0), []).append({
            "word": word.get("word", ""),
            "start": float(word.get("start") or 0),
            "end": float(word.get("end") or 0),
            "probability": word.get("probability"),
        })
    out = []
    for index in sorted(segments):
        words = segments[index]
        out.append({
            "start": words[0]["start"],
            "end": words[-1]["end"],
            "text": "".join(word["word"] for word in words),
            "words": words,
        })
    return {
        "language": entry.get("language"),
        "duration": float(entry.get("duration") or 0),
        "segments": out,
    }
