// One working list: pick a file on the left, fix its text in the middle,
// Transcribe and Render from the footer. The list lives in Python
// (lib/manual_jobs.py) and survives restarts; this file only mirrors it.

let ws = null;                    // latest snapshot {job_id, items, busy, ...}
let selectedId = null;
const transcripts = new Map();    // item_id -> transcript revision
let activeWordId = null;          // word under the playhead or in focus
let showingOutput = false;        // stage plays the rendered file instead of the source
let wasBusy = false;
let lastMessage = "";

let pendingPatches = new Map();
let pendingItemId = null;
let patchTimer = null;
let saveChain = Promise.resolve();
let savesInFlight = 0;
let editorLocked = false;         // word list drawn read-only (file is being rendered)
let seekingToWord = false;        // a click on a word is moving the playhead

const FILE_STATUS = {
  pending:       ["○", "Текст не распознан", ""],
  queued:        ["◌", "В очереди", "running"],
  transcribing:  ["◐", "Распознаётся", "running"],
  transcribed:   ["●", "Текст готов — проверьте", "ready"],
  approved:      ["●", "Текст готов", "ready"],
  needs_review:  ["●", "Есть правки, не отрендерено", "ready"],
  rendering:     ["◐", "Рендер", "running"],
  completed:     ["✓", "Готово", "done"],
  failed:        ["✕", "Ошибка распознавания", "failed"],
  render_failed: ["✕", "Ошибка рендера", "failed"],
  no_speech:     ["!", "Речь не найдена", "failed"],
  cancelled:     ["■", "Остановлено", ""],
};
const RUNNING = new Set(["queued", "transcribing", "rendering"]);

function video() { return $("stageVideo"); }
function selectedItem() {
  return ws && ws.items.find((item) => item.item_id === selectedId) || null;
}
function recognitionArgs() {
  return { model: $("modelSize").value, language: $("language").value, device: $("device").value };
}

// ---------------- setup ----------------

async function initWorkspace() {
  $("dropzone").addEventListener("click", pickVideos);
  $("clearListBtn").addEventListener("click", clearList);
  $("retranscribeBtn").addEventListener("click", () => retranscribe(selectedId));
  $("openResultBtn").addEventListener("click", () => {
    const item = selectedItem();
    if (item && item.output) api().open_output_folder(item.output);
  });
  $("editorEmptyAction").addEventListener("click", () => {
    const action = $("editorEmptyAction").dataset.action;
    if (action === "transcribe") transcribeOnly(selectedId);
    if (action === "retranscribe") retranscribe(selectedId);
  });
  setupPlayer();
  setupDropHighlight();
  loadTypography();

  try {
    const result = await api().workspace();
    if (result && result.ok) applySnapshot(result.job);
  } catch (e) { /* bridge not ready: the first update will fill the list */ }
  if (ws && ws.items.length && !selectedId) selectItem(ws.items[0].item_id);
  updateActionButtons();
}

// Files dropped on the window reach Python through pywebview's DOM events
// (app.py: enable_file_drop), which answers with window.onVideosPicked. The
// page only draws the highlight and keeps WebView2 from opening the file.
// Capture phase: pywebview's own drop listener stops propagation.
function setupDropHighlight() {
  let depth = 0;
  const hasFiles = (event) => Boolean(event.dataTransfer)
    && Array.from(event.dataTransfer.types || []).includes("Files");
  const off = () => { depth = 0; document.body.classList.remove("dragging"); };
  window.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    depth++;
    document.body.classList.add("dragging");
  }, true);
  window.addEventListener("dragleave", (event) => {
    if (!hasFiles(event)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) off();
  }, true);
  window.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, true);
  window.addEventListener("drop", (event) => {
    if (hasFiles(event)) event.preventDefault();
    off();
  }, true);
}

// The dialog runs on the UI thread and answers via window.onVideosPicked.
function pickVideos() {
  api().pick_videos();
}

window.onVideosPicked = async function (paths) {
  if (!paths || !paths.length) return;
  const result = await api().add_videos(paths);
  if (!result || !result.ok) return showToast("Не удалось добавить: " + ((result && result.error) || "ошибка"));
  applySnapshot(result.job);
  if (result.added && result.added.length) {
    selectItem(result.added[0]);
  } else {
    showToast("Эти файлы уже в списке", "ok");
  }
};

window.onWorkspaceUpdated = function (snapshot) {
  if (snapshot) applySnapshot(snapshot);
};

window.onRenderDone = function (result) {
  const text = `Рендер: готово ${result.completed}` + (result.failed ? `, ошибок ${result.failed}` : "");
  lastMessage = text;
  showToast(text, result.failed ? undefined : "ok");
  const done = ws && ws.items.filter((item) => item.output);
  if (done && done.length) lastOutputPath = done[done.length - 1].output;
};

// ---------------- snapshot -> UI ----------------

function applySnapshot(snapshot) {
  ws = snapshot;
  isRunning = Boolean(snapshot.busy);
  if (selectedId && !selectedItem()) {
    selectedId = null;
    if (ws.items.length) selectItem(ws.items[0].item_id);
    else showNothingSelected();
  }
  renderFileList();
  updateActionButtons();
  updateProgress();
  hydrateTranscripts();
  const item = selectedItem();
  if (!item || !transcripts.has(selectedId) || RUNNING.has(item.state) !== editorLocked
      || $("editorBody").classList.contains("hidden")) {
    renderEditor();
  } else {
    updateEditorChrome();
  }
  const outputs = ws.items.filter((candidate) => candidate.output);
  if (outputs.length) lastOutputPath = outputs[outputs.length - 1].output;

  if (wasBusy && !isRunning) refreshModelHint();   // a model may have just been downloaded
  wasBusy = isRunning;
}

async function hydrateTranscripts() {
  if (!ws) return;
  for (const item of ws.items) {
    if (!item.revision || RUNNING.has(item.state) || item.state === "no_speech") continue;
    const cached = transcripts.get(item.item_id);
    // A snapshot can be older than a save that already came back; never
    // step the editor back to an earlier revision.
    if (cached && cached.revision >= item.revision) continue;
    // Our own edit is on its way back; re-reading now would reset the editor.
    if (item.item_id === selectedId && (savesInFlight || pendingPatches.size)) continue;
    const result = await api().get_transcript(item.item_id);
    if (!result || !result.ok) continue;
    transcripts.set(item.item_id, result.transcript);
    if (item.item_id === selectedId) {
      renderEditor();
      updatePreview();
    }
  }
}

function renderFileList() {
  const items = (ws && ws.items) || [];
  $("dropzone").classList.toggle("hidden", items.length > 0);
  $("fileListWrap").classList.toggle("hidden", items.length === 0);
  $("queueCount").textContent = items.length ? `— ${items.length}` : "";

  const list = $("fileList");
  list.innerHTML = "";
  items.forEach((item) => {
    const [icon, label, tone] = FILE_STATUS[item.state] || ["•", item.state, ""];
    const row = document.createElement("div");
    row.className = `file-row ${tone}` + (item.item_id === selectedId ? " selected" : "");
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", item.item_id === selectedId ? "true" : "false");
    row.tabIndex = 0;
    row.title = item.path;

    const status = document.createElement("span");
    status.className = "status";
    status.textContent = icon;

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = item.name;
    const small = document.createElement("small");
    if (item.error) {
      small.textContent = item.error;
      small.className = "error";
    } else if (RUNNING.has(item.state) && item.state !== "queued") {
      small.textContent = `${STAGE_LABELS[item.stage] || label} ${item.progress || 0}%`;
    } else {
      small.textContent = label;
    }
    name.appendChild(small);
    row.append(status, name);

    if (RUNNING.has(item.state) && item.state !== "queued") {
      const bar = document.createElement("span");
      bar.className = "mini-bar";
      const fill = document.createElement("span");
      fill.className = "mini-fill";
      fill.style.width = (item.progress || 0) + "%";
      bar.appendChild(fill);
      row.appendChild(bar);
    } else if (!RUNNING.has(item.state)) {
      const remove = document.createElement("button");
      remove.className = "remove";
      remove.type = "button";
      remove.title = "Убрать из списка (файл на диске останется)";
      remove.textContent = "×";
      remove.addEventListener("click", (event) => {
        event.stopPropagation();
        removeItems([item.item_id]);
      });
      row.appendChild(remove);
    }

    row.addEventListener("click", () => selectItem(item.item_id));
    row.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const next = ws.items[item.index + (event.key === "ArrowDown" ? 1 : -1)];
        if (next) selectItem(next.item_id).then(() => focusSelectedRow());
      }
    });
    list.appendChild(row);
  });
}

function focusSelectedRow() {
  const row = $("fileList").querySelector(".file-row.selected");
  if (row) row.focus();
}

function updateActionButtons() {
  const actions = ManualState.workspaceActions(ws, selectedId);
  const transcribe = $("transcribeBtn"), render = $("renderBtn");
  transcribe.querySelector(".label").textContent = actions.transcribe.label;
  transcribe.disabled = !actions.transcribe.enabled;
  transcribe.title = actions.transcribe.ids.length
    ? "Распознать речь во всех файлах, где текста ещё нет"
    : "Все файлы уже распознаны";
  render.querySelector(".label").textContent = actions.render.label;
  render.disabled = !actions.render.enabled;
  render.title = actions.render.again
    ? "Отрендерить выбранный файл ещё раз с текущим стилем"
    : "Вшить субтитры во все файлы с готовым текстом";
  // The step that makes sense next gets the bright button.
  const renderIsNext = !actions.transcribe.ids.length && actions.render.ids.length;
  transcribe.classList.toggle("secondary", Boolean(renderIsNext));
  render.classList.toggle("secondary", !renderIsNext);

  $("runSummary").textContent = actions.summary;
  $("cancelBtn").classList.toggle("hidden", !actions.busy);
  const anyOutput = ws && ws.items.some((item) => item.output);
  $("resultActions").classList.toggle("hidden", !anyOutput);
}

function updateProgress() {
  const items = (ws && ws.items) || [];
  const active = items.find((item) => item.state === "transcribing" || item.state === "rendering");
  if (active) {
    const waiting = items.filter((item) => item.state === "queued").length;
    const label = STAGE_LABELS[active.stage] || (active.state === "rendering" ? "Рендер" : "Распознавание");
    setProgress(`${active.name} · ${label}` + (waiting ? ` · ещё в очереди: ${waiting}` : ""), active.progress || 0);
    $("liveStatus").textContent = `${active.name}: ${label}`;
    return;
  }
  if (items.some((item) => item.state === "queued")) {
    setProgress("Подготовка…", 0);
    return;
  }
  if (!items.length) setProgress("Добавьте видео", null);
  else if (lastMessage) setProgress(lastMessage, 100);
  else setProgress("Готово к работе", null);
}

// ---------------- selecting a file ----------------

async function selectItem(itemId) {
  if (!itemId) return;
  if (selectedId && selectedId !== itemId) await flushPatches();
  const changed = selectedId !== itemId;
  selectedId = itemId;
  if (changed) {
    activeWordId = null;
    showingOutput = false;
    $("editorSaveState").textContent = "";
  }
  renderFileList();
  updateActionButtons();
  renderEditor();
  if (changed) await loadStageMedia();
  hydrateTranscripts();
}

function showNothingSelected() {
  const player = video();
  player.pause();
  player.removeAttribute("src");
  player.removeAttribute("poster");
  player.load();
  $("previewStage").classList.remove("showing-output");
  document.querySelector(".preview-empty").innerHTML =
    "Добавьте видео — здесь будет кадр<br>с субтитрами в выбранном стиле";
  clearStageFrame();
  updatePlayerBar();
  renderEditor();
}

async function loadStageMedia() {
  const item = selectedItem();
  const player = video();
  player.pause();
  $("previewStage").classList.toggle("showing-output", showingOutput);
  setActiveToggle("sourceToggle", showingOutput ? "output" : "source");
  if (!item) return showNothingSelected();

  let info = {};
  try { info = (await api().video_info(item.path)) || {}; } catch (e) { info = {}; }
  if (selectedId !== item.item_id) return;   // switched while waiting

  if (!info.media_url) {
    player.removeAttribute("src");
    player.removeAttribute("poster");
    player.load();
    document.querySelector(".preview-empty").textContent = "Исходный файл не найден: " + item.path;
    clearStageFrame();
    updatePlayerBar();
    return;
  }

  previewVideo = info.width ? info : null;
  applyStageGeometry();
  let src = info.media_url;
  if (showingOutput && item.output) {
    const out = await api().video_info(item.output);
    if (out && out.media_url) src = out.media_url;
  }
  player.src = src;
  player.load();
  updatePlayerBar();

  try {
    const frame = await api().frame_url(item.path, null);
    if (frame && selectedId === item.item_id) {
      player.poster = frame;
      setStageFrame(frame);
    }
  } catch (e) { /* the checkerboard stays */ }
}

// ---------------- player ----------------

function setupPlayer() {
  const player = video();
  $("playBtn").addEventListener("click", () => {
    if (player.paused) player.play().catch(() => {}); else player.pause();
  });
  $("seekBar").addEventListener("input", () => {
    if (player.duration) player.currentTime = player.duration * $("seekBar").value / 1000;
  });
  ["play", "pause", "loadedmetadata", "emptied"].forEach((name) =>
    player.addEventListener(name, updatePlayerBar));
  player.addEventListener("loadeddata", () => $("previewStage").classList.remove("no-frame"));
  player.addEventListener("timeupdate", onTimeUpdate);
  player.addEventListener("seeked", () => { seekingToWord = false; updatePlayerBar(); });
  setupToggleGroup("sourceToggle", (value) => {
    showingOutput = value === "output";
    const time = player.currentTime;
    loadStageMedia().then(() => {
      player.addEventListener("loadedmetadata", () => { player.currentTime = time; }, { once: true });
    });
    updatePreview();
  });
}

function formatTime(seconds) {
  if (!isFinite(seconds)) seconds = 0;
  const m = Math.floor(seconds / 60), s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function updatePlayerBar() {
  const player = video();
  const hasMedia = Boolean(player.currentSrc);
  $("playBtn").disabled = !hasMedia;
  $("seekBar").disabled = !hasMedia;
  $("playBtn").textContent = player.paused ? "▶" : "❚❚";
  $("playBtn").setAttribute("aria-label", player.paused ? "Воспроизвести" : "Пауза");
  $("seekBar").value = player.duration ? Math.round(1000 * player.currentTime / player.duration) : 0;
  $("timeLabel").textContent = `${formatTime(player.currentTime)} / ${formatTime(player.duration)}`;
  const item = selectedItem();
  const outputButton = $("sourceToggle").querySelector('[data-val="output"]');
  outputButton.disabled = !(item && item.output);
}

function onTimeUpdate() {
  updatePlayerBar();
  const transcript = transcripts.get(selectedId);
  // While a clicked word is being sought to, the old playhead position would
  // otherwise briefly win and move the highlight back.
  if (!transcript || seekingToWord) return;
  const word = ManualState.wordAt(transcript, video().currentTime);
  const id = word ? word.id : null;
  if (id === activeWordId) return;
  activeWordId = id;
  markPlayingRow(!video().paused);
  updatePreview();
}

function markPlayingRow(scroll) {
  const list = $("wordList");
  list.querySelectorAll(".word-row.playing").forEach((row) => row.classList.remove("playing"));
  if (!activeWordId) return;
  const row = list.querySelector(`[data-word-id="${activeWordId}"]`);
  if (!row) return;
  row.classList.add("playing");
  // Follow playback, but never yank the list away from a field being edited.
  if (scroll && !list.contains(document.activeElement)) row.scrollIntoView({ block: "nearest" });
}

// ---------------- captions for the preview ----------------
//
// The renderer groups words into captions (lib/segment_parser.py) and keeps a
// caption on screen while its words are spoken. The preview shows exactly
// that caption, grouped by the same rules; word widths come from a canvas in
// the same font at source-pixel size, like the renderer's own measuring.

let isHangingWord = () => false;
let captionCache = { key: null, captions: [], byWord: new Map() };
const measureCtx = document.createElement("canvas").getContext("2d");

async function loadTypography() {
  try {
    const rules = await api().typography();
    isHangingWord = ManualState.makeIsHanging(rules && rules.hanging_words);
    captionCache.key = null;
    updatePreview();
  } catch (e) { /* no rule: prepositions may end a caption */ }
}

// fits(texts) for the current style, mirroring renderer._fit_function.
function captionFitter() {
  const videoW = (previewVideo && previewVideo.width) || 1080;
  const [family, weight, italic] = fontCss(style.font);
  measureCtx.font = `${italic ? "italic " : ""}${weight} ${style.font_size}px ${family}`;
  const textCase = textCaseOf(style);
  const shape = (text) => textCase === "upper" ? text.toUpperCase() : textCase === "lower" ? text.toLowerCase() : text;
  const box = style.highlight_style === "box";
  const gap = measureCtx.measureText(" ").width + (box ? style.box_padding_x * 1.6 : 0);
  const stroke = 2 * Math.max(0, Number(style.stroke_width) || 0);
  let maxWidth = videoW * style.max_width_ratio;
  if (box) maxWidth = Math.min(maxWidth, videoW - 2 * (style.box_padding_x + 4));
  maxWidth = Math.max(maxWidth, Math.min(style.font_size * 1.5, videoW - 4));
  const maxLines = Math.max(1, style.line_count);
  const widths = new Map();
  const widthOf = (text) => {
    if (!widths.has(text)) widths.set(text, measureCtx.measureText(shape(text)).width);
    return widths.get(text);
  };
  return (texts) => {
    let lines = 1, line = 0;
    for (const text of texts) {
      const w = widthOf(text.trim());
      if (line && line + gap + w + stroke > maxWidth) {
        lines++;
        line = w;
      } else {
        line = line ? line + gap + w : w;
      }
      if (lines > maxLines) return false;
    }
    return true;
  };
}

function previewCaptions(transcript) {
  const mode = ManualState.captionModeOf(style);
  const key = JSON.stringify([
    selectedId, transcript.revision, mode, style.font, style.font_size, textCaseOf(style),
    style.max_width_ratio, style.line_count, style.highlight_style, style.box_padding_x,
    style.stroke_width, previewVideo && previewVideo.width, window.fontEpoch || 0,
    transcript.words.map((w) => `${w.word}${w.deleted ? "~" : ""}${w.start}`).join("|"),
  ]);
  if (captionCache.key === key) return captionCache;
  const words = transcript.words.filter((word) => !word.deleted);
  const captions = ManualState.buildCaptions(words, mode, captionFitter(), isHangingWord);
  if (mode === "words") {
    // Same hold as segment_parser.one_word_captions: a word stays until the
    // next one when the pause is short.
    captions.forEach((caption, i) => {
      const next = captions[i + 1];
      const word = caption.words[0];
      if (next && next.words[0].start - word.end >= 0 && next.words[0].start - word.end <= 0.7) {
        word.end = next.words[0].start;
      }
    });
  }
  const byWord = new Map();
  captions.forEach((caption, index) => caption.words.forEach((word) => byWord.set(word.id, index)));
  captionCache = { key, captions, byWord };
  return captionCache;
}

// Called by updatePreview() in app.js: the caption the render will show.
function previewSample() {
  if (showingOutput) return { words: PREVIEW_SAMPLE, active: 0, hidden: true };
  const transcript = transcripts.get(selectedId);
  if (!transcript) return null;
  const { captions, byWord } = previewCaptions(transcript);
  if (!captions.length) return null;

  const player = video();
  const time = player.currentTime;
  let index = byWord.has(activeWordId) ? byWord.get(activeWordId) : -1;
  if (index < 0) {
    // The active word shows nothing of its own (a lone dash in word mode):
    // fall back to the caption on screen at the playhead.
    index = 0;
    captions.forEach((caption, i) => { if (caption.words[0].start <= time) index = i; });
  }
  const caption = captions[index];
  const active = Math.max(0, caption.words.findIndex((word) => word.id === activeWordId));
  const first = caption.words[0], last = caption.words[caption.words.length - 1];
  return {
    words: caption.words.map((word) => word.text.trim()),
    active,
    // While playing, the render shows nothing between captions.
    hidden: !player.paused && (time < first.start - 0.05 || time > last.end + 0.05),
  };
}

// ---------------- editor ----------------

function setEditorEmpty(html, action) {
  $("editorBody").classList.add("hidden");
  $("editorEmpty").classList.remove("hidden");
  $("editorEmptyText").innerHTML = html;
  const button = $("editorEmptyAction");
  button.classList.toggle("hidden", !action);
  if (action) {
    button.textContent = action.label;
    button.dataset.action = action.id;
    button.disabled = isRunning;
  }
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
}

function renderEditor() {
  const item = selectedItem();
  $("editorFileName").textContent = item ? item.name : "";
  if (!item) {
    return setEditorEmpty(ws && ws.items.length
      ? "Выберите видео в списке слева."
      : "Добавьте видео слева.<br>Потом нажмите <b>Transcribe</b> — здесь появится распознанный текст.");
  }
  const transcript = transcripts.get(item.item_id);
  if (item.state === "queued" || item.state === "transcribing") {
    const pct = item.state === "transcribing" ? ` ${item.progress || 0}%` : "";
    return setEditorEmpty(`Распознаём речь…${pct}<br><small>Текст появится здесь, как только файл будет готов.</small>`);
  }
  if (item.state === "pending" || (item.state === "cancelled" && !item.revision)) {
    return setEditorEmpty(
      "Текст для этого видео ещё не распознан.<br>Нажмите <b>Transcribe</b> внизу — распознаются все новые файлы.",
      { id: "transcribe", label: "Распознать только этот файл" });
  }
  if (item.state === "failed" && !item.revision) {
    return setEditorEmpty(`Не удалось распознать:<br><small>${escapeHtml(item.error || "")}</small>`,
      { id: "transcribe", label: "Попробовать ещё раз" });
  }
  if (item.state === "no_speech") {
    return setEditorEmpty("В этом видео речь не найдена.<br><small>Можно попробовать другую модель или указать язык.</small>",
      { id: "retranscribe", label: "Распознать заново" });
  }
  if (!transcript) return setEditorEmpty("Загружаем текст…");

  $("editorEmpty").classList.add("hidden");
  $("editorBody").classList.remove("hidden");
  renderWordList(transcript, item.state === "rendering");
  updateEditorChrome();
}

// The parts around the word list that follow the file's state.
function updateEditorChrome() {
  const item = selectedItem();
  const transcript = item && transcripts.get(item.item_id);
  if (!item || !transcript) return;
  const reasons = ManualState.attentionReasons(transcript);
  const bad = Object.keys(ManualState.timingProblems(transcript)).length;
  if (bad) reasons.unshift(`Проверьте тайминги: ${bad} (выделены красным) — с ними рендер не пройдёт`);
  const box = $("editorAttention");
  box.classList.toggle("hidden", !reasons.length);
  box.classList.toggle("bad", bad > 0);
  box.textContent = reasons.join(" · ");
  $("retranscribeBtn").disabled = isRunning;
  $("openResultBtn").classList.toggle("hidden", !item.output);
  if (!$("editorSaveState").textContent || item.state === "completed") {
    $("editorSaveState").textContent = item.state === "completed" ? "отрендерено" : "";
  }
  updatePlayerBar();
}

function renderWordList(transcript, locked) {
  editorLocked = Boolean(locked);
  const list = $("wordList");
  const scrollTop = list.scrollTop;
  list.innerHTML = "";
  const problems = ManualState.timingProblems(transcript);

  transcript.words.forEach((word) => {
    const row = document.createElement("div");
    row.className = "word-row";
    row.dataset.wordId = word.id;
    row.classList.toggle("deleted", Boolean(word.deleted));
    row.classList.toggle("low-confidence", word.probability != null && word.probability < ManualState.LOW_CONFIDENCE);
    row.classList.toggle("bad-timing", Boolean(problems[word.id]));
    row.classList.toggle("playing", word.id === activeWordId);
    if (problems[word.id]) row.title = problems[word.id];

    const text = document.createElement("input");
    text.type = "text";
    text.className = "word-text";
    text.value = String(word.word).trim();
    text.disabled = Boolean(word.deleted) || locked;
    text.setAttribute("aria-label", "Слово");
    text.addEventListener("focus", () => focusWord(word));
    text.addEventListener("input", () => {
      const value = text.value.trim();
      if (!value) return;   // an empty word is refused; delete it with × instead
      const lead = String(word.word).startsWith(" ") ? " " : "";
      word.word = lead + value;
      queuePatch(`text:${word.id}`, { op: "replace", word_id: word.id, text: word.word });
      updatePreview();
    });
    text.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      const rows = Array.from(list.querySelectorAll(".word-text:not(:disabled)"));
      const next = rows[rows.indexOf(text) + (event.shiftKey ? -1 : 1)];
      if (next) { next.focus(); next.select(); }
    });

    const start = timingInput(word.start, "Начало слова, секунды", locked || word.deleted);
    const end = timingInput(word.end, "Конец слова, секунды", locked || word.deleted);
    const timingChanged = () => {
      const s = Number(start.value), e = Number(end.value);
      if (!isFinite(s) || !isFinite(e)) return;
      word.start = s; word.end = e;
      queuePatch(`timing:${word.id}`, { op: "set_timing", word_id: word.id, start: s, end: e });
      refreshTimingMarks();
    };
    start.addEventListener("input", timingChanged);
    end.addEventListener("input", timingChanged);
    start.addEventListener("focus", () => focusWord(word));
    end.addEventListener("focus", () => focusWord(word));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "word-del";
    remove.textContent = word.deleted ? "↶" : "×";
    remove.title = word.deleted ? "Вернуть слово" : "Удалить слово";
    remove.disabled = locked;
    remove.addEventListener("click", () => saveNow([{ op: word.deleted ? "restore" : "delete", word_id: word.id }], true));

    const insert = document.createElement("button");
    insert.type = "button";
    insert.textContent = "+";
    insert.title = "Вставить слово после";
    insert.disabled = locked || word.deleted;
    insert.addEventListener("click", () => insertWordAfter(word));

    row.append(text, start, end, remove, insert);
    list.appendChild(row);
  });
  list.scrollTop = scrollTop;
}

function timingInput(value, label, disabled) {
  const input = document.createElement("input");
  input.type = "number";
  input.step = "0.01";
  input.min = "0";
  input.className = "word-time";
  input.value = Number(value).toFixed(2);
  input.disabled = Boolean(disabled);
  input.setAttribute("aria-label", label);
  return input;
}

function refreshTimingMarks() {
  const transcript = transcripts.get(selectedId);
  if (!transcript) return;
  const problems = ManualState.timingProblems(transcript);
  $("wordList").querySelectorAll(".word-row").forEach((row) => {
    const problem = problems[row.dataset.wordId];
    row.classList.toggle("bad-timing", Boolean(problem));
    row.title = problem || "";
  });
  updateEditorChrome();
}

// Focusing a word shows it on the preview, both the frame and the caption.
function focusWord(word) {
  activeWordId = word.id;
  markPlayingRow(false);
  const player = video();
  if (!showingOutput && player.currentSrc) {
    player.pause();
    seekingToWord = true;
    player.currentTime = Math.max(0, Number(word.start) + 0.01);
  }
  updatePreview();
}

function insertWordAfter(word) {
  const text = window.prompt("Новое слово:", "");
  if (!text || !text.trim()) return;
  const transcript = transcripts.get(selectedId);
  const active = transcript.words.filter((candidate) => !candidate.deleted);
  const next = active[active.findIndex((candidate) => candidate.id === word.id) + 1];
  const start = Number(word.end);
  const limit = next ? Number(next.start) : Math.min(transcript.duration || start + 0.5, start + 0.5);
  const end = Math.max(start + 0.05, limit);
  saveNow([{ op: "insert_after", word_id: word.id, text: " " + text.trim(), start, end }], true);
}

// ---------------- saving edits ----------------

function queuePatch(key, operation) {
  if (!pendingItemId) pendingItemId = selectedId;
  pendingPatches.set(key, operation);
  $("editorSaveState").textContent = "есть несохранённые правки";
  clearTimeout(patchTimer);
  patchTimer = setTimeout(flushPatches, 650);
}

function flushPatches() {
  clearTimeout(patchTimer);
  if (!pendingPatches.size) return saveChain;
  const batch = ManualState.capturePatchBatch(pendingItemId, Array.from(pendingPatches.values()));
  pendingPatches.clear();
  pendingItemId = null;
  return saveNow(batch.operations, false, batch.itemId);
}

function saveNow(operations, rerender, targetItemId) {
  const itemId = targetItemId || selectedId;
  savesInFlight++;
  saveChain = saveChain.then(async () => {
    try {
      const base = transcripts.get(itemId);
      if (!base) return;
      if (itemId === selectedId) $("editorSaveState").textContent = "сохраняем…";
      const result = await api().apply_transcript_patch(itemId, base.revision, operations);
      if (!result || !result.ok) {
        if (itemId === selectedId) {
          $("editorSaveState").textContent = result && result.code === "revision_conflict"
            ? "текст изменился — перечитываем" : "не сохранено: " + ((result && result.error) || "ошибка");
        }
        if (result && result.code === "revision_conflict") transcripts.delete(itemId);
        return;
      }
      transcripts.set(itemId, result.transcript);
      if (itemId === selectedId) {
        $("editorSaveState").textContent = "сохранено";
        if (rerender) renderWordList(result.transcript, false);
        updateEditorChrome();
        updatePreview();
      }
    } finally {
      savesInFlight--;
      if (!savesInFlight) hydrateTranscripts();
    }
  });
  return saveChain;
}

// ---------------- actions ----------------

async function runTranscribe() {
  await flushPatches();
  const actions = ManualState.workspaceActions(ws, selectedId);
  if (!actions.transcribe.enabled) {
    if (!ws || !ws.items.length) pickVideos();
    return;
  }
  lastMessage = "";
  const result = await api().transcribe(Object.assign({ item_ids: actions.transcribe.ids }, recognitionArgs()));
  if (!result || !result.ok) showToast((result && result.error) || "Распознавание не запущено");
}

async function transcribeOnly(itemId) {
  if (!itemId) return;
  lastMessage = "";
  const result = await api().transcribe(Object.assign({ item_ids: [itemId] }, recognitionArgs()));
  if (!result || !result.ok) showToast((result && result.error) || "Распознавание не запущено");
}

async function retranscribe(itemId) {
  if (!itemId) return;
  await flushPatches();
  const result = await api().retranscribe(itemId, recognitionArgs());
  if (!result || !result.ok) return showToast((result && result.error) || "Распознавание не запущено");
  transcripts.delete(itemId);
  showToast("Распознаём заново; прошлая версия текста сохранена в истории", "ok");
}

async function runRender() {
  await flushPatches();
  const actions = ManualState.workspaceActions(ws, selectedId);
  if (!actions.render.enabled) return;
  const transcriptProblems = actions.render.ids.filter((id) => {
    const transcript = transcripts.get(id);
    return transcript && Object.keys(ManualState.timingProblems(transcript)).length;
  });
  if (transcriptProblems.length) {
    const names = ws.items.filter((item) => transcriptProblems.includes(item.item_id)).map((item) => item.name);
    showToast("Есть ошибки в таймингах, эти файлы не отрендерятся: " + names.join(", "));
  }
  lastMessage = "";
  const result = await api().render({ item_ids: actions.render.ids, style });
  if (!result || !result.ok) showToast((result && result.error) || "Рендер не запущен");
}

async function cancelCurrentQueue() {
  $("cancelBtn").disabled = true;
  $("cancelBtn").textContent = "Останавливаем после файла…";
  await api().cancel_queue();
  showToast("Текущий файл доделается, остальные будут остановлены", "ok");
  setTimeout(() => {
    $("cancelBtn").disabled = false;
    $("cancelBtn").textContent = "Остановить после файла";
  }, 1500);
}

async function removeItems(itemIds) {
  if (!itemIds.length) return;
  await flushPatches();
  const result = await api().remove_videos(itemIds);
  if (!result || !result.ok) return showToast("Не удалось убрать: " + ((result && result.error) || "ошибка"));
  itemIds.forEach((id) => transcripts.delete(id));
  applySnapshot(result.job);
}

let clearArmed = null;
function clearList() {
  const button = $("clearListBtn");
  if (!ws || !ws.items.length) return;
  if (isRunning) return showToast("Дождитесь окончания обработки или остановите её");
  if (!clearArmed) {
    button.textContent = "Точно?";
    clearArmed = setTimeout(() => { clearArmed = null; button.textContent = "Очистить"; }, 3000);
    return;
  }
  clearTimeout(clearArmed);
  clearArmed = null;
  button.textContent = "Очистить";
  lastMessage = "";
  removeItems(ws.items.map((item) => item.item_id));
}
