# Adapted from captacity (MIT License) - https://github.com/unconv/captacity
# Groups word-level transcript segments into on-screen caption chunks.

import unicodedata
from typing import Callable

from typography import is_hanging

def has_partial_sentence(text):
    words = text.split()
    if len(words) >= 2:
        prev_word = words[-2].strip()
        if prev_word and prev_word[-1] == ".":
            return True
    return False

SENTENCE_END = (".", "!", "?", "…")


def split_sentences(segments):
    """Marks the last word of every sentence and drops its full stops.

    "кухни." becomes "кухни" with sentence_end=True, so the next sentence
    starts a new caption even though the period that used to signal it is
    gone. "!" and "?" stay visible but also end the sentence. Periods inside
    a word ("3.5", "т.е") are kept; only the trailing ones go.
    """
    for segment in segments:
        for word in segment["words"]:
            text = word["word"]
            core = text.rstrip()
            if core.endswith(SENTENCE_END):
                word["sentence_end"] = True
                stripped = core.rstrip(".…")
                # A word that was nothing but dots stays as it was rather than
                # turning into an empty caption word.
                if stripped.strip():
                    word["word"] = stripped + text[len(core):]
    return segments


def _is_punct(ch):
    return unicodedata.category(ch).startswith("P")


def clean_word(text):
    """Strips punctuation and quotes: "«Особые" -> "Особые", "кухни»." -> "кухни".

    Kept: a hyphen or apostrophe between letters ("какой-то", "don't") and a
    point or comma between digits ("3.5"). The leading space that separates
    words in whisper output is preserved.
    """
    lead = text[: len(text) - len(text.lstrip())]
    core = text.strip()
    out = []
    for i, ch in enumerate(core):
        if not _is_punct(ch):
            out.append(ch)
            continue
        before = core[i - 1] if i > 0 else ""
        after = core[i + 1] if i + 1 < len(core) else ""
        if ch in "-'’" and before.isalnum() and after.isalnum():
            out.append(ch)
        elif ch in ".," and before.isdigit() and after.isdigit():
            out.append(ch)
    return lead + "".join(out)


def caption_mode(style):
    """"phrases" | "sentences" | "words", accepting the older sentence_breaks flag."""
    mode = (style or {}).get("caption_mode")
    if mode in ("phrases", "sentences", "words"):
        return mode
    return "sentences" if (style or {}).get("sentence_breaks") else "phrases"


def one_word_captions(segments, hold_gap=0.7):
    """Every word is its own caption, stripped of punctuation.

    Each word stays up until the next one starts when the pause between them
    is short, so the screen does not blink empty between words.
    """
    words = []
    for segment in segments:
        for word in segment["words"]:
            text = clean_word(word["word"])
            if text.strip():
                words.append(dict(word, word=text))
    captions = []
    for i, word in enumerate(words):
        if i + 1 < len(words):
            next_start = words[i + 1]["start"]
            if 0 <= next_start - word["end"] <= hold_gap:
                word["end"] = next_start
        captions.append(_new_caption([word]))
    return captions


def parse(
    segments: list,
    fit_function: Callable,
    allow_partial_sentences: bool = False,
    sentence_breaks: bool = False,
    one_word: bool = False,
):
    captions = []
    caption = {
        "start": None,
        "end": 0,
        "words": [],
        "text": "",
    }

    # Merge words that are not separated by spaces
    for s, segment in enumerate(segments):
        for w, word in enumerate(segment["words"]):
            if w > 0 and word["word"][0] != " ":
                segments[s]["words"][w-1]["word"] += word["word"]
                segments[s]["words"][w-1]["end"] = word["end"]
                del segments[s]["words"][w]

    if one_word:
        return one_word_captions(segments)

    if sentence_breaks:
        split_sentences(segments)

    for segment in segments:
        for word in segment["words"]:
            if caption["start"] is None:
                caption["start"] = word["start"]

            text = caption["text"] + word["word"]

            caption_fits = allow_partial_sentences or not has_partial_sentence(text)
            caption_fits = caption_fits and fit_function(text)

            # A caption holding nothing but prepositions/conjunctions must never
            # be shown on its own, so it takes the next word even if that
            # overflows slightly - the renderer shrinks such a line to fit.
            if caption_fits or _only_hanging(caption):
                caption["words"].append(word)
                caption["end"] = word["end"]
                caption["text"] = text
            else:
                carried = _carry_hanging_words(caption, fit_function, word)
                captions.append(caption)
                caption = _new_caption(carried + [word])

            # A finished sentence closes the caption: the next one starts fresh.
            if word.get("sentence_end") and caption["words"]:
                captions.append(caption)
                caption = {"start": None, "end": 0, "words": [], "text": ""}

    if caption["words"]:
        captions.append(caption)

    return captions

def _only_hanging(caption):
    words = caption.get("words") or []
    return bool(words) and all(is_hanging(w["word"]) for w in words)

def _new_caption(words):
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "words": list(words),
        "text": "".join(w["word"] for w in words),
    }

def _carry_hanging_words(caption, fit_function, next_word):
    """Moves trailing prepositions/conjunctions out of a finished caption so
    they appear together with the word they belong to, never stranded at the
    end. Stops as soon as the next caption would no longer fit."""
    carried = []
    while len(caption["words"]) > 1 and is_hanging(caption["words"][-1]["word"]):
        candidate = [caption["words"][-1]] + carried + [next_word]
        if not fit_function("".join(w["word"] for w in candidate)):
            break
        carried.insert(0, caption["words"].pop())

    if carried:
        caption["text"] = "".join(w["word"] for w in caption["words"])
        caption["end"] = caption["words"][-1]["end"]
    return carried
