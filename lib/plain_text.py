"""The transcript as running text, for writing rather than for subtitles.

Subtitles are cut into chunks that fit a screen; an article needs whole
sentences with their punctuation. So this joins the words back the way they
were recognised, keeps the commas and full stops, and starts a new paragraph
where the speaker paused long enough for one.
"""

PARAGRAPH_GAP = 2.0      # seconds of silence that end a paragraph
SENTENCE_END = (".", "!", "?", "…")


def build(transcript, paragraph_gap=PARAGRAPH_GAP):
    """Returns the transcript as plain text, paragraphs separated by a blank line."""
    words = [word for word in (transcript or {}).get("words") or []
             if not word.get("deleted") and str(word.get("word") or "").strip()]
    paragraphs = []
    current = []
    previous_end = None
    for word in words:
        start = _number(word.get("start"))
        gap = None if previous_end is None or start is None else start - previous_end
        # A pause only breaks the paragraph where a sentence has just ended:
        # a speaker thinking mid-sentence should not split it in two.
        if current and gap is not None and gap >= paragraph_gap \
                and str(current[-1]).rstrip().endswith(SENTENCE_END):
            paragraphs.append(current)
            current = []
        current.append(str(word["word"]).strip())
        previous_end = _number(word.get("end")) or previous_end
    if current:
        paragraphs.append(current)
    return "\n\n".join(" ".join(part for part in group if part) for group in paragraphs)


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
