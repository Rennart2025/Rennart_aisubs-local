(function (root, factory) {
  const value = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = value;
  if (root) root.ManualState = value;
})(typeof window !== "undefined" ? window : globalThis, function () {
  const ACTIVE_TRANSCRIPTION = new Set(["queued", "transcribing"]);
  const ACTIVE = new Set(["queued", "transcribing", "rendering"]);
  // Files the Transcribe button picks up. "no_speech" is left out on purpose:
  // running it again gives the same empty result; "Распознать заново" is there
  // for a deliberate retry with other settings.
  const NEEDS_TRANSCRIPTION = new Set(["pending", "failed", "cancelled"]);
  const RENDER_READY = new Set(["transcribed", "needs_review", "approved", "render_failed"]);
  const LOW_CONFIDENCE = 0.65;

  function renderGate(snapshot) {
    const items = (snapshot && snapshot.items) || [];
    const approved = (snapshot && snapshot.approved_count) || 0;
    if (!snapshot || !snapshot.transcription_settled) {
      const active = items.filter((item) => ACTIVE_TRANSCRIPTION.has(item.state)).length;
      return { enabled: false, label: `Ждём транскрибацию: ${active}` };
    }
    if (!approved) return { enabled: false, label: "Одобрите хотя бы один файл" };
    return { enabled: true, label: `Рендер одобренных (${approved})` };
  }

  // What the two main buttons do right now.
  //
  // Transcribe: every file that has no text yet.
  // Render: every file whose text is ready and not rendered since its last
  // edit. When there is none, it re-renders the selected file, which is what
  // someone who just changed the style wants.
  function workspaceActions(snapshot, selectedId) {
    const items = (snapshot && snapshot.items) || [];
    const busy = items.some((item) => ACTIVE.has(item.state));
    const toTranscribe = items.filter((item) => NEEDS_TRANSCRIPTION.has(item.state));
    const ready = items.filter((item) => item.revision && RENDER_READY.has(item.state));
    const selected = items.find((item) => item.item_id === selectedId);

    let renderIds = ready.map((item) => item.item_id);
    let renderLabel = ready.length > 1 ? `Render (${ready.length})` : "Render";
    let renderAgain = false;
    if (!ready.length && selected && selected.state === "completed" && selected.revision) {
      renderIds = [selected.item_id];
      renderLabel = "Render again";
      renderAgain = true;
    }

    const parts = [];
    if (toTranscribe.length) parts.push(`ждут распознавания: ${toTranscribe.length}`);
    if (ready.length) parts.push(`готовы к рендеру: ${ready.length}`);
    const done = items.filter((item) => item.state === "completed").length;
    if (done) parts.push(`готово: ${done}`);

    return {
      busy,
      transcribe: {
        enabled: !busy && toTranscribe.length > 0,
        ids: toTranscribe.map((item) => item.item_id),
        label: toTranscribe.length > 1 ? `Transcribe (${toTranscribe.length})` : "Transcribe",
      },
      render: {
        enabled: !busy && renderIds.length > 0,
        ids: renderIds,
        label: renderLabel,
        again: renderAgain,
      },
      summary: parts.join(" · "),
    };
  }

  function wordsNoun(n) {
    const mod10 = n % 10, mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return "слово";
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "слова";
    return "слов";
  }

  function activeWords(transcript) {
    return ((transcript && transcript.words) || []).filter((word) => !word.deleted);
  }

  function attentionReasons(transcript) {
    const words = activeWords(transcript);
    const low = words.filter(
      (word) => word.probability !== null && word.probability !== undefined && word.probability < LOW_CONFIDENCE
    ).length;
    const reasons = [];
    if (low) reasons.push(`Низкая уверенность: ${low} ${wordsNoun(low)}`);
    if (!words.length) reasons.push("Речь не распознана");
    return reasons;
  }

  // Same rules the backend checks before rendering, so problems show while
  // editing instead of as a failed render. Returns {wordId: message}.
  function timingProblems(transcript) {
    const problems = {};
    const duration = Number((transcript && transcript.duration) || 0);
    let previous = null;
    activeWords(transcript).forEach((word) => {
      const start = Number(word.start), end = Number(word.end);
      if (!(start >= 0) || !(end > start)) problems[word.id] = "конец раньше начала";
      else if (duration && end > duration) problems[word.id] = "выходит за конец видео";
      else if (previous && start < Number(previous.end)) problems[word.id] = "наезжает на предыдущее слово";
      previous = word;
    });
    return problems;
  }

  // The word being spoken at `seconds`, or the last one before it.
  function wordAt(transcript, seconds) {
    let found = null;
    for (const word of activeWords(transcript)) {
      if (Number(word.start) > seconds) break;
      found = word;
    }
    return found;
  }

  const SENTENCE_END = /[.!?…]$/;

  // Mirrors lib/segment_parser.split_sentences for the preview.
  function displayWord(text, sentenceBreaks) {
    const word = String(text).trim();
    if (!sentenceBreaks) return word;
    const stripped = word.replace(/[.…]+$/, "");
    return stripped || word;
  }

  // A handful of real words around `wordId` for the style preview. With
  // sentence breaks on, the window never crosses a sentence boundary, the
  // same way the renderer starts a new caption there.
  function previewWindow(transcript, wordId, size, sentenceBreaks) {
    const words = activeWords(transcript);
    if (!words.length) return null;
    const count = size || 5;
    let index = words.findIndex((word) => word.id === wordId);
    if (index < 0) index = 0;

    let lo = 0, hi = words.length;   // allowed range [lo, hi)
    if (sentenceBreaks) {
      lo = index;
      while (lo > 0 && !SENTENCE_END.test(String(words[lo - 1].word).trim())) lo--;
      hi = index;
      while (hi < words.length - 1 && !SENTENCE_END.test(String(words[hi].word).trim())) hi++;
      hi += 1;
    }
    const from = Math.max(lo, Math.min(index - 1, hi - count));
    const slice = words.slice(from, Math.min(hi, from + count));
    return {
      words: slice.map((word) => displayWord(word.word, sentenceBreaks)),
      active: index - from,
    };
  }

  // ---------- captions, mirroring lib/segment_parser.py ----------

  function captionModeOf(style) {
    const mode = style && style.caption_mode;
    if (mode === "phrases" || mode === "sentences" || mode === "words") return mode;
    return style && style.sentence_breaks ? "sentences" : "phrases";
  }

  const PUNCT = /\p{P}/u;
  const LETTER_OR_DIGIT = /[\p{L}\p{N}]/u;
  const DIGIT = /\p{N}/u;

  // Same rule as segment_parser.clean_word: no punctuation or quotes, except
  // a hyphen/apostrophe inside a word and a point/comma inside a number.
  function cleanWord(text) {
    const chars = Array.from(String(text).trim());
    return chars.filter((ch, i) => {
      if (!PUNCT.test(ch)) return true;
      const before = chars[i - 1] || "", after = chars[i + 1] || "";
      if ("-'’".includes(ch)) return LETTER_OR_DIGIT.test(before) && LETTER_OR_DIGIT.test(after);
      if (".,".includes(ch)) return DIGIT.test(before) && DIGIT.test(after);
      return false;
    }).join("");
  }

  // What a word looks like on screen in the given caption mode.
  function captionText(text, mode) {
    if (mode === "words") return cleanWord(text);
    return displayWord(text, mode === "sentences");
  }

  const HANGING_STRIP = /^[.,!?;:—\-–«»"'()]+|[.,!?;:—\-–«»"'()]+$/g;
  function makeIsHanging(hangingWords) {
    const set = new Set(hangingWords || []);
    return (text) => {
      const bare = String(text || "").trim().replace(HANGING_STRIP, "").toLowerCase();
      return Boolean(bare) && set.has(bare);
    };
  }

  // Groups transcript words into captions the way the renderer does.
  //   words: [{id, word, start, end}] (active words only)
  //   fits(texts): true when these on-screen texts fit the caption box
  //   isHanging(text): prepositions that travel with the next word
  // Returns [{words: [{id, text, start, end}]}].
  function buildCaptions(words, mode, fits, isHanging) {
    const hanging = isHanging || (() => false);
    const items = words
      .map((word) => ({ id: word.id, raw: String(word.word), text: captionText(word.word, mode),
                        start: Number(word.start), end: Number(word.end) }))
      .filter((item) => item.text.trim());

    if (mode === "words") return items.map((item) => ({ words: [item] }));

    const texts = (list) => list.map((item) => item.text);
    const onlyHanging = (list) => list.length > 0 && list.every((item) => hanging(item.text));
    const captions = [];
    let current = [];
    items.forEach((item) => {
      if (!current.length) {
        current = [item];
      } else {
        // In phrase mode a caption never runs past a full stop.
        const partial = mode === "phrases" && /\.$/.test(current[current.length - 1].raw.trim());
        const candidate = current.concat([item]);
        if ((!partial && fits(texts(candidate))) || onlyHanging(current)) {
          current = candidate;
        } else {
          // Trailing prepositions move on with the word they belong to.
          const carried = [];
          while (current.length > 1 && hanging(current[current.length - 1].text)) {
            const next = [current[current.length - 1]].concat(carried, [item]);
            if (!fits(texts(next))) break;
            carried.unshift(current.pop());
          }
          captions.push({ words: current });
          current = carried.concat([item]);
        }
      }
      if (mode === "sentences" && SENTENCE_END.test(item.raw.trim())) {
        captions.push({ words: current });
        current = [];
      }
    });
    if (current.length) captions.push({ words: current });
    return captions;
  }

  function capturePatchBatch(itemId, operations) {
    return { itemId, operations: operations.slice() };
  }

  function pipelineProgress(previous, stage, percent) {
    const pct = Math.max(0, Math.min(100, Number(percent) || 0)) / 100;
    const ranges = {
      downloading_model: [0, 4], loading_model: [4, 5], transcribing: [5, 45],
      preparing: [45, 46], building: [46, 65], compositing: [65, 66],
      rendering: [66, 99], done: [100, 100], completed: [100, 100],
    };
    const range = ranges[stage];
    const mapped = range ? range[0] + (range[1] - range[0]) * pct : Number(percent) || 0;
    return Math.max(Number(previous) || 0, Math.round(mapped));
  }

  return {
    attentionReasons, buildCaptions, captionModeOf, captionText, capturePatchBatch, cleanWord,
    displayWord, makeIsHanging, pipelineProgress, previewWindow,
    renderGate, timingProblems, wordAt, workspaceActions, LOW_CONFIDENCE,
  };
});
