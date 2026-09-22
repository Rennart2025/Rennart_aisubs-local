// value -> [css font-family, css font-weight]
const FONT_FAMILY_MAP = {
  "fonts/Montserrat-var.ttf#ExtraBold": ["Montserrat", 800],
  "fonts/Montserrat-var.ttf#Bold": ["Montserrat", 700],
  "fonts/FiraSans-ExtraBold.ttf": ["Fira Sans ExtraBold", 400],
  "fonts/FiraSans-Black.ttf": ["Fira Sans Black", 400],
  "fonts/FiraSans-Medium.ttf": ["Fira Sans Medium", 400],
  "fonts/Oswald-var.ttf#Bold": ["Oswald", 700],
  "fonts/Rubik-var.ttf#ExtraBold": ["Rubik", 800],
  "fonts/PTSans-Bold.ttf": ["PT Sans Bold", 400],
  "fonts/BebasNeue-Regular.ttf": ["Bebas Neue", 400],
  "fonts/Poppins-ExtraBold.ttf": ["Poppins ExtraBold", 400],
  "fonts/Poppins-Black.ttf": ["Poppins Black", 400],
  "fonts/Anton-Regular.ttf": ["Anton", 400],
  "fonts/ArchivoBlack-Regular.ttf": ["Archivo Black", 400],
  "fonts/Bangers-Regular.ttf": ["Bangers", 400],
};

// Filled from Python with every bundled + system face.
let fontCatalog = [];
const fontByValue = new Map();

// Presets saved before text_case existed carry a boolean `uppercase`.
function textCaseOf(s) {
  if (s.text_case) return s.text_case;
  return s.uppercase ? "upper" : "none";
}

// Fonts loaded straight from their file, keyed by the style value.
const loadedFontFaces = new Map();
let fontFaceSeq = 0;

// Chromium ignores fonts installed for the current user only, so naming them
// in CSS silently renders a substitute. Loading the file itself is the only
// way the preview can be trusted to show the real typeface.
function ensureFontFace(value) {
  if (!value) return null;
  if (loadedFontFaces.has(value)) return loadedFontFaces.get(value);

  const alias = `aisubs-face-${++fontFaceSeq}`;
  loadedFontFaces.set(value, alias);

  (async () => {
    try {
      const url = await api().font_url(value);
      if (!url) return;
      const style = document.createElement("style");
      style.textContent = `@font-face{font-family:"${alias}";src:url("${url}");font-display:block;}`;
      document.head.appendChild(style);
      // Nudge a redraw once the file is in.
      if (document.fonts && document.fonts.load) {
        await document.fonts.load(`16px "${alias}"`);
        window.fontEpoch = (window.fontEpoch || 0) + 1;   // caption widths change
        updatePreview();
        renderPresetGrid();
      }
    } catch (e) { /* fall back to the system name below */ }
  })();

  return alias;
}

// Returns [css font-family list, weight, italic]. The loaded file comes first;
// system names stay as fallbacks while it is still downloading.
function fontCss(value) {
  const alias = ensureFontFace(value);
  const f = fontByValue.get(value);
  if (f) {
    const names = (f.css_stack && f.css_stack.length ? f.css_stack : [f.css_family])
      .map((n) => `"${n}"`);
    if (alias) names.unshift(`"${alias}"`);
    return [names.join(", "), f.css_weight, f.css_italic];
  }
  const legacy = FONT_FAMILY_MAP[value];
  const fallback = legacy ? `"${legacy[0]}"` : `"UI Sans"`;
  return [alias ? `"${alias}", ${fallback}` : fallback, legacy ? legacy[1] : 400, false];
}

const DEFAULT_STYLE = {
  font: "fonts/Montserrat-var.ttf#ExtraBold",
  font_size: 84,
  text_case: "upper",   // "upper" | "lower" | "none"
  // caption_mode: "phrases" | "sentences" | "words" - left unset here so a
  // preset that only has the older sentence_breaks flag keeps its meaning.
  text_color: "#FFFFFF",
  stroke_color: "#000000",
  stroke_width: 0,
  shadow_enabled: true,
  shadow_color: "#000000",
  shadow_opacity: 0.45,
  shadow_blur: 6,
  shadow_offset: [0, 3],
  shadow2_enabled: false,
  shadow2_color: "#000000",
  shadow2_opacity: 0.35,
  shadow2_blur: 18,
  shadow2_offset: [0, 10],
  highlight_style: "box",
  word_highlight_color: "#3FA9E8",
  active_text_color: "#FFFFFF",
  box_color: "#3FA9E8",
  box_opacity: 1.0,
  box_radius: 16,
  box_padding_x: 20,
  box_padding_y: 10,
  line_count: 1,
  max_width_ratio: 0.86,
  line_spacing: 1.18,
  position: "bottom",
  position_margin: 190,
  position_mode: "manual",
  position_safe_inset_ratio: null,
};

let style = Object.assign({}, DEFAULT_STYLE);
let previewVideo = null;  // {width, height, duration} of the selected file, for 1:1 preview scaling
let lastOutputPath = null;
let presets = [];
let isRunning = false;
let safeZoneState = SafeZones.createState();

const $ = (id) => document.getElementById(id);

function api() {
  return window.pywebview && window.pywebview.api;
}

// ---------------- control <-> state binding ----------------

function bindRange(id, valId, key, fmt) {
  const el = $(id);
  el.addEventListener("input", () => {
    const raw = parseFloat(el.value);
    style[key] = fmt ? fmt(raw) : raw;
    $(valId).textContent = fmt ? Math.round(raw) : raw;
    updatePreview();
    renderSafeZones();
  });
}

// One axis of an [x, y] offset pair.
function bindOffset(id, valId, key, axis) {
  const el = $(id);
  el.addEventListener("input", () => {
    const pair = offsetPair(style[key]);
    pair[axis] = parseFloat(el.value);
    style[key] = pair;
    $(valId).textContent = pair[axis];
    updatePreview();
    renderSafeZones();
  });
}

function offsetPair(value) {
  return Array.isArray(value) ? [Number(value[0]) || 0, Number(value[1]) || 0] : [0, 0];
}

function bindColor(colorId, hexId, key, alsoKey) {
  const colorEl = $(colorId), hexEl = $(hexId);
  colorEl.addEventListener("input", () => {
    hexEl.value = colorEl.value.toUpperCase();
    style[key] = colorEl.value.toUpperCase();
    if (alsoKey) style[alsoKey] = style[key];
    updatePreview();
  });
  hexEl.addEventListener("change", () => {
    let v = hexEl.value.trim();
    if (!v.startsWith("#")) v = "#" + v;
    if (/^#[0-9A-Fa-f]{6}$/.test(v)) {
      colorEl.value = v;
      style[key] = v.toUpperCase();
      if (alsoKey) style[alsoKey] = style[key];
      updatePreview();
    }
  });
}

function setupBindings() {
  $("s_font").addEventListener("change", () => { style.font = $("s_font").value; updatePreview(); });
  $("fontSearch").addEventListener("input", renderFontOptions);
  $("fontCyrillicOnly").addEventListener("change", renderFontOptions);
  bindRange("s_font_size", "v_font_size", "font_size");
  setupToggleGroup("textCaseGroup", (val) => { style.text_case = val; updatePreview(); });
  setupToggleGroup("captionModeGroup", (val) => {
    style.caption_mode = val;
    style.sentence_breaks = val === "sentences";   // what older builds read
    updateCaptionModeHint();
    updatePreview();
  });
  bindColor("s_text_color", "s_text_color_hex", "text_color");

  bindRange("s_stroke_width", "v_stroke_width", "stroke_width");
  bindColor("s_stroke_color", "s_stroke_color_hex", "stroke_color");

  $("s_shadow_enabled").addEventListener("change", () => {
    style.shadow_enabled = $("s_shadow_enabled").checked;
    $("shadowParams").classList.toggle("hidden", !style.shadow_enabled);
    updatePreview();
    renderSafeZones();
  });
  bindRange("s_shadow_blur", "v_shadow_blur", "shadow_blur");
  bindRange("s_shadow_opacity", "v_shadow_opacity", "shadow_opacity", (v) => v / 100);
  bindOffset("s_shadow_offset_x", "v_shadow_offset_x", "shadow_offset", 0);
  bindOffset("s_shadow_offset_y", "v_shadow_offset_y", "shadow_offset", 1);

  $("s_shadow2_enabled").addEventListener("change", () => {
    style.shadow2_enabled = $("s_shadow2_enabled").checked;
    $("shadow2Params").classList.toggle("hidden", !style.shadow2_enabled);
    updatePreview();
    renderSafeZones();
  });
  bindRange("s_shadow2_blur", "v_shadow2_blur", "shadow2_blur");
  bindRange("s_shadow2_opacity", "v_shadow2_opacity", "shadow2_opacity", (v) => v / 100);
  bindOffset("s_shadow2_offset_x", "v_shadow2_offset_x", "shadow2_offset", 0);
  bindOffset("s_shadow2_offset_y", "v_shadow2_offset_y", "shadow2_offset", 1);

  bindColor("s_box_color", "s_box_color_hex", "box_color");
  bindColor("s_active_text_color", "s_active_text_color_hex", "active_text_color");
  bindRange("s_box_radius", "v_box_radius", "box_radius");
  bindRange("s_box_padding_x", "v_box_padding_x", "box_padding_x");
  bindRange("s_box_padding_y", "v_box_padding_y", "box_padding_y");

  bindColor("s_word_highlight_color", "s_word_highlight_color_hex", "word_highlight_color");

  $("s_position_margin").addEventListener("input", () => {
    style = SafeZones.activateManualPosition(style, parseFloat($("s_position_margin").value));
    $("v_position_margin").textContent = style.position_margin;
    updatePreview();
    renderSafeZones();
  });
  bindRange("s_line_count", "v_line_count", "line_count");
  bindRange("s_max_width_ratio", "v_max_width_ratio", "max_width_ratio", (v) => v / 100);

  setupToggleGroup("highlightStyleGroup", (val) => {
    style.highlight_style = val;
    $("boxParams").classList.toggle("hidden", val !== "box");
    $("colorParams").classList.toggle("hidden", val !== "color");
    updatePreview();
    renderSafeZones();
  });

  setupToggleGroup("positionGroup", (val) => {
    const sourceHeight = previewVideo && previewVideo.height;
    style = SafeZones.activateManualPosition(style, SafeZones.effectiveMargin(style, sourceHeight));
    style.position = val;
    updatePreview();
    renderSafeZones();
  });

  $("snapSafeZoneMargin").addEventListener("click", () => {
    if (!previewVideo || !SafeZones.canSnapMargin(
      safeZoneState,
      style.position,
      previewVideo.width,
      previewVideo.height,
    )) return;

    const insetRatio = SafeZones.strictestInsetRatio(safeZoneState, style.position);
    if (insetRatio === null) return;
    style = SafeZones.activateSafePosition(style, insetRatio, previewVideo.height);
    updatePreview();
    renderSafeZones();
  });

  document.querySelectorAll(".safe-zone-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const platform = button.dataset.platform;
      safeZoneState = SafeZones.setEnabled(safeZoneState, platform, !safeZoneState[platform]);
      renderSafeZones();
    });
  });

}

function setupToggleGroup(groupId, onChange) {
  const group = $(groupId);
  group.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      group.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      onChange(btn.dataset.val);
    });
  });
}

function applyStyleToControls() {
  // rebuild rather than assign: a preset may use a face the filter hides
  if (fontCatalog.length) renderFontOptions(); else $("s_font").value = style.font;
  $("s_font_size").value = style.font_size; $("v_font_size").textContent = style.font_size;
  setActiveToggle("textCaseGroup", textCaseOf(style));
  setActiveToggle("captionModeGroup", ManualState.captionModeOf(style));
  updateCaptionModeHint();
  $("s_text_color").value = style.text_color; $("s_text_color_hex").value = style.text_color.toUpperCase();

  $("s_stroke_width").value = style.stroke_width; $("v_stroke_width").textContent = style.stroke_width;
  $("s_stroke_color").value = style.stroke_color; $("s_stroke_color_hex").value = style.stroke_color.toUpperCase();

  $("s_shadow_enabled").checked = style.shadow_enabled;
  $("shadowParams").classList.toggle("hidden", !style.shadow_enabled);
  $("s_shadow_blur").value = style.shadow_blur; $("v_shadow_blur").textContent = style.shadow_blur;
  const shadowPct = Math.round(style.shadow_opacity * 100);
  $("s_shadow_opacity").value = shadowPct; $("v_shadow_opacity").textContent = shadowPct;
  const [sx, sy] = offsetPair(style.shadow_offset);
  $("s_shadow_offset_x").value = sx; $("v_shadow_offset_x").textContent = sx;
  $("s_shadow_offset_y").value = sy; $("v_shadow_offset_y").textContent = sy;

  $("s_shadow2_enabled").checked = Boolean(style.shadow2_enabled);
  $("shadow2Params").classList.toggle("hidden", !style.shadow2_enabled);
  $("s_shadow2_blur").value = style.shadow2_blur; $("v_shadow2_blur").textContent = style.shadow2_blur;
  const shadow2Pct = Math.round(style.shadow2_opacity * 100);
  $("s_shadow2_opacity").value = shadow2Pct; $("v_shadow2_opacity").textContent = shadow2Pct;
  const [s2x, s2y] = offsetPair(style.shadow2_offset);
  $("s_shadow2_offset_x").value = s2x; $("v_shadow2_offset_x").textContent = s2x;
  $("s_shadow2_offset_y").value = s2y; $("v_shadow2_offset_y").textContent = s2y;

  $("s_box_color").value = style.box_color; $("s_box_color_hex").value = style.box_color.toUpperCase();
  $("s_active_text_color").value = style.active_text_color; $("s_active_text_color_hex").value = style.active_text_color.toUpperCase();
  $("s_box_radius").value = style.box_radius; $("v_box_radius").textContent = style.box_radius;
  $("s_box_padding_x").value = style.box_padding_x; $("v_box_padding_x").textContent = style.box_padding_x;
  $("s_box_padding_y").value = style.box_padding_y; $("v_box_padding_y").textContent = style.box_padding_y;

  $("s_word_highlight_color").value = style.word_highlight_color; $("s_word_highlight_color_hex").value = style.word_highlight_color.toUpperCase();

  const sourceHeight = previewVideo && previewVideo.height;
  const effectiveMargin = SafeZones.effectiveMargin(style, sourceHeight);
  $("s_position_margin").value = effectiveMargin; $("v_position_margin").textContent = effectiveMargin;
  $("s_line_count").value = style.line_count; $("v_line_count").textContent = style.line_count;
  const mwr = Math.round(style.max_width_ratio * 100);
  $("s_max_width_ratio").value = mwr; $("v_max_width_ratio").textContent = mwr;

  setActiveToggle("highlightStyleGroup", style.highlight_style);
  setActiveToggle("positionGroup", style.position);
  $("boxParams").classList.toggle("hidden", style.highlight_style !== "box");
  $("colorParams").classList.toggle("hidden", style.highlight_style !== "color");
  renderSafeZones();
}

const CAPTION_MODE_HINTS = {
  phrases: "Слова собираются во фразы по ширине блока, знаки препинания как в тексте.",
  sentences: "Без точек; каждое новое предложение начинается с новой строки.",
  words: "По одному слову, без знаков препинания и кавычек. Слово держится до следующего.",
};

function updateCaptionModeHint() {
  $("captionModeHint").textContent = CAPTION_MODE_HINTS[ManualState.captionModeOf(style)];
}

function setActiveToggle(groupId, val) {
  const group = $(groupId);
  group.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.val === val));
}

// ---------------- live CSS preview ----------------

function updatePreview() {
  const stage = $("previewStage");
  const line = $("previewLine");

  // Scale against the real frame width so what you see matches the render.
  const videoWidth = (previewVideo && previewVideo.width) || 1080;
  const scale = stage.clientWidth / videoWidth;

  // Real words of the selected transcript around the playhead when there is
  // one, the sample line otherwise.
  const sample = typeof previewSample === "function" ? previewSample() : null;
  const words = sample ? sample.words : PREVIEW_SAMPLE;
  const activeIdx = sample ? sample.active : 1;
  line.style.visibility = sample && sample.hidden ? "hidden" : "visible";
  const [family, weight, italic] = fontCss(style.font);

  line.style.fontFamily = family;
  line.style.fontWeight = weight;
  line.style.fontStyle = italic ? "italic" : "normal";
  line.style.fontSize = Math.max(10, style.font_size * scale) + "px";
  line.style.color = style.text_color;
  const textCase = textCaseOf(style);
  line.style.textTransform = textCase === "upper" ? "uppercase" : textCase === "lower" ? "lowercase" : "none";
  line.style.textShadow = previewShadows(scale);
  line.style.setProperty("-webkit-text-stroke", style.stroke_width > 0 ? `${style.stroke_width*scale}px ${style.stroke_color}` : "0px transparent");

  // Manual margins are source pixels; safe margins are resolved for this frame.
  const effectiveMargin = SafeZones.effectiveMargin(style, previewVideo && previewVideo.height);
  stage.style.alignItems = style.position === "top" ? "flex-start" : style.position === "center" ? "center" : "flex-end";
  line.style.marginBottom = style.position === "bottom" ? (effectiveMargin * scale) + "px" : "0px";
  line.style.marginTop = style.position === "top" ? (effectiveMargin * scale) + "px" : "0px";
  line.style.maxWidth = (style.max_width_ratio * 100) + "%";

  updateTextBox(stage, line, scale, videoWidth, effectiveMargin);

  line.innerHTML = "";
  words.forEach((w, i) => {
    const span = document.createElement("span");
    span.className = "preview-word";
    span.textContent = w;
    if (i === activeIdx) {
      if (style.highlight_style === "box") {
        const padX = style.box_padding_x * scale;
        const padY = style.box_padding_y * scale;
        span.style.background = style.box_color;
        span.style.color = style.active_text_color;
        span.style.borderRadius = (style.box_radius*scale) + "px";
        span.style.padding = `${padY}px ${padX}px`;
        // Cancel the padding in layout: the renderer paints the pill around the
        // word without widening the line, and the preview must wrap at the same
        // point or it under-reports how many words fit.
        span.style.margin = `-${padY}px -${padX}px`;
        span.style.webkitTextStroke = "0px transparent";
      } else if (style.highlight_style === "color") {
        span.style.color = style.word_highlight_color;
      }
    }
    line.appendChild(span);
  });

  trimToLineCount(line, activeIdx);
}

// CSS paints the first shadow on top, the renderer draws "Тень 2" first and
// the main shadow over it - so the main one is listed first here.
function previewShadows(scale) {
  const layer = (enabled, color, opacity, blur, offset) => {
    if (!enabled) return null;
    const [dx, dy] = offsetPair(offset);
    const hex = /^#[0-9a-f]{6}$/i.test(color || "") ? color : "#000000";
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    return `${dx * scale}px ${dy * scale}px ${(Number(blur) || 0) * scale}px rgba(${r},${g},${b},${opacity})`;
  };
  const layers = [
    layer(style.shadow_enabled, style.shadow_color, style.shadow_opacity, style.shadow_blur, style.shadow_offset),
    layer(style.shadow2_enabled, style.shadow2_color, style.shadow2_opacity, style.shadow2_blur, style.shadow2_offset),
  ].filter(Boolean);
  return layers.length ? layers.join(", ") : "none";
}

function renderSafeZones() {
  const layer = $("safeZoneLayer");
  layer.innerHTML = "";

  SafeZones.overlayDefinitions(safeZoneState).forEach((guide) => {
    const frame = document.createElement("div");
    frame.className = "safe-zone-frame";
    frame.dataset.platform = guide.id;
    frame.style.inset = `${guide.inset.top}% ${guide.inset.right}% ${guide.inset.bottom}% ${guide.inset.left}%`;

    const label = document.createElement("span");
    label.className = "safe-zone-label";
    label.textContent = guide.label;
    frame.appendChild(label);
    layer.appendChild(frame);
  });

  document.querySelectorAll(".safe-zone-toggle").forEach((button) => {
    button.setAttribute("aria-pressed", safeZoneState[button.dataset.platform] ? "true" : "false");
  });

  const hasActiveGuide = SafeZones.activePlatforms(safeZoneState).length > 0;
  const wrongFormat = previewVideo && !SafeZones.isVerticalFormat(previewVideo.width, previewVideo.height);
  $("safeZoneFormatHint").classList.toggle("hidden", !(hasActiveGuide && wrongFormat));

  const range = $("s_position_margin");
  const sourceHeight = previewVideo && previewVideo.height;
  const effectiveMargin = SafeZones.effectiveMargin(style, sourceHeight);
  range.max = SafeZones.marginRangeMax(sourceHeight, effectiveMargin);
  range.value = effectiveMargin;
  $("v_position_margin").textContent = effectiveMargin;

  const snapButton = $("snapSafeZoneMargin");
  const canSnap = Boolean(previewVideo) && SafeZones.canSnapMargin(
    safeZoneState,
    style.position,
    previewVideo && previewVideo.width,
    sourceHeight,
  );
  snapButton.disabled = !canSnap;
  const safeActive = SafeZones.isSafePosition(style);
  snapButton.setAttribute("aria-pressed", safeActive ? "true" : "false");

  let snapHint = "Включите безопасную зону под предпросмотром";
  if (!previewVideo) snapHint = safeActive
    ? "Безопасный режим сохранён; загрузите видео для расчёта"
    : "Загрузите вертикальное видео 9:16";
  else if (!hasActiveGuide) snapHint = safeActive
    ? `Безопасный отступ ${effectiveMargin} px; включите зону для проверки`
    : "Включите безопасную зону под предпросмотром";
  else if (style.position === "center") snapHint = "Для позиции «Центр» отступ не применяется";
  else if (wrongFormat) snapHint = "Привязка доступна для видео 9:16";
  else if (safeActive) snapHint = `Безопасный отступ ${effectiveMargin} px; пересчитывается для каждого файла`;
  else snapHint = "Учтёт плашку, обводку и тень";
  $("safeZoneSnapHint").textContent = snapHint;
}

// ---------------- fonts ----------------

async function loadFonts() {
  try {
    fontCatalog = await api().list_fonts();
  } catch (e) {
    fontCatalog = [];
  }
  fontByValue.clear();
  fontCatalog.forEach((f) => fontByValue.set(f.path, f));
  renderFontOptions();
}

function renderFontOptions() {
  const select = $("s_font");
  const query = ($("fontSearch").value || "").trim().toLowerCase();
  const cyrillicOnly = $("fontCyrillicOnly").checked;

  const matches = (f) =>
    (!cyrillicOnly || f.cyrillic) && (!query || f.label.toLowerCase().includes(query));

  // The face in use always stays selectable, even if filtered out.
  const visible = fontCatalog.filter((f) => matches(f) || f.path === style.font);

  const groups = [
    ["Из комплекта", visible.filter((f) => f.source === "bundled")],
    ["Системные", visible.filter((f) => f.source === "system")],
  ];

  select.innerHTML = "";
  groups.forEach(([name, items]) => {
    if (!items.length) return;
    const group = document.createElement("optgroup");
    group.label = `${name} — ${items.length}`;
    items.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.path;
      opt.textContent = f.cyrillic ? f.label : `${f.label} (без кириллицы)`;
      // System names only here - loading a file per option would fetch
      // hundreds of fonts just to draw the dropdown.
      opt.style.fontFamily = (f.css_stack && f.css_stack.length ? f.css_stack : [f.css_family])
        .map((n) => `"${n}"`).join(", ");
      opt.style.fontWeight = f.css_weight;
      opt.style.fontStyle = f.css_italic ? "italic" : "normal";
      group.appendChild(opt);
    });
    select.appendChild(group);
  });

  if (!visible.length) {
    const opt = document.createElement("option");
    opt.textContent = "ничего не найдено";
    opt.disabled = true;
    select.appendChild(opt);
  }

  select.value = style.font;
  $("fontCount").textContent = `— ${visible.length}`;
}

// ---------------- presets ----------------

async function loadPresets() {
  try {
    presets = await api().list_presets();
  } catch (e) {
    presets = [];
  }
  renderPresetGrid();
}

function renderPresetGrid() {
  const grid = $("presetGrid");
  grid.innerHTML = "";
  presets.forEach((p) => {
    const card = document.createElement("div");
    card.className = "preset-card";
    card.title = p.name || p.filename;
    const [family, weight] = fontCss(p.font);
    const thumbColor = p.highlight_style === "box" ? p.box_color : p.word_highlight_color;
    card.innerHTML = `
      <div class="preset-thumb"><span class="preset-sample">Аа</span></div>
      <div class="preset-name">${p.name || p.filename}</div>
      <button class="preset-del" title="Удалить пресет">×</button>
    `;

    // Styled through the DOM, not inside the markup: font stacks contain
    // quotes, and those terminate a style="..." attribute early, silently
    // dropping every declaration after the font name.
    const sample = card.querySelector(".preset-sample");
    sample.style.fontFamily = family;
    sample.style.fontWeight = weight;
    sample.style.fontSize = "15px";
    sample.style.textTransform = textCaseOf(p) === "upper" ? "uppercase"
      : textCaseOf(p) === "lower" ? "lowercase" : "none";
    if (p.highlight_style === "box") {
      sample.style.background = thumbColor;
      sample.style.color = p.active_text_color;
      sample.style.padding = "3px 8px";
      sample.style.borderRadius = Math.min(p.box_radius, 10) + "px";
    } else {
      sample.style.color = thumbColor;
    }
    card.addEventListener("click", () => {
      style = Object.assign({}, DEFAULT_STYLE, p);
      applyStyleToControls();
      updatePreview();
      document.querySelectorAll(".preset-card").forEach((c) => c.classList.remove("active"));
      card.classList.add("active");
    });
    card.querySelector(".preset-del").addEventListener("click", (e) => {
      e.stopPropagation();
      deletePreset(p, card);
    });
    grid.appendChild(card);
  });
}

async function deletePreset(preset, card) {
  // Two-step confirm inside the card, so no modal is needed.
  const button = card.querySelector(".preset-del");
  if (!card.classList.contains("confirm-delete")) {
    document.querySelectorAll(".preset-card.confirm-delete").forEach((c) => {
      c.classList.remove("confirm-delete");
      c.querySelector(".preset-del").textContent = "×";
    });
    card.classList.add("confirm-delete");
    button.textContent = "Удалить?";
    setTimeout(() => {
      card.classList.remove("confirm-delete");
      button.textContent = "×";
    }, 4000);
    return;
  }

  const result = await api().delete_preset(preset.filename);
  if (result && result.ok) {
    await loadPresets();
  } else {
    showToast("Не удалось удалить пресет: " + ((result && result.error) || "неизвестная ошибка"));
  }
}

async function savePreset() {
  const name = $("presetSaveName").value.trim();
  if (!name) return;
  const toSave = Object.assign({}, style, { name });
  await api().save_preset(name, toSave);
  await loadPresets();
}

function applyStageGeometry() {
  const holder = $("previewHolder");
  const stage = $("previewStage");
  const ratio = (previewVideo && previewVideo.width && previewVideo.height)
    ? previewVideo.width / previewVideo.height
    : 9 / 16;

  // Fit the frame inside the holder, like object-fit: contain. Doing this in JS
  // keeps the box exact, which matters because the caption overlay is scaled
  // from the stage width.
  const availW = holder.clientWidth;
  const availH = holder.clientHeight;
  if (availW > 0 && availH > 0) {
    let w = availW;
    let h = w / ratio;
    if (h > availH) { h = availH; w = h * ratio; }
    stage.style.width = Math.round(w) + "px";
    stage.style.height = Math.round(h) + "px";
  }
  updatePreview();
  renderSafeZones();
}

function setStageFrame(url) {
  const stage = $("previewStage");
  stage.style.backgroundImage = `url("${url}")`;
  stage.classList.remove("no-frame");
  updatePreview();
}

function clearStageFrame() {
  const stage = $("previewStage");
  stage.style.backgroundImage = "";
  stage.classList.add("no-frame");
  previewVideo = null;
  applyStageGeometry();
}

// Outlines the area text can occupy, and labels it in source pixels: as wide
// as max_width_ratio allows, as tall as line_count lines.
function updateTextBox(stage, line, scale, videoWidth, positionMargin) {
  const box = $("textBox");
  const stageW = stage.clientWidth;
  const stageH = stage.clientHeight;
  if (!stageW || !stageH) return;

  const boxW = stageW * style.max_width_ratio;
  const lineH = parseFloat(getComputedStyle(line).lineHeight) || style.font_size * scale;
  const boxH = lineH * Math.max(1, style.line_count);

  let top;
  if (style.position === "top") {
    top = positionMargin * scale;
  } else if (style.position === "center") {
    top = (stageH - boxH) / 2;
  } else {
    top = stageH - positionMargin * scale - boxH;
  }
  top = Math.max(0, Math.min(top, stageH - boxH));

  box.style.left = ((stageW - boxW) / 2) + "px";
  box.style.top = top + "px";
  box.style.width = boxW + "px";
  box.style.height = boxH + "px";

  const srcW = Math.round(videoWidth * style.max_width_ratio);
  const srcH = Math.round(boxH / scale);
  $("textBoxSize").textContent = `${srcW} × ${srcH}`;
}

const PREVIEW_SAMPLE = ["ЭТО", "ПРИМЕР", "СУБТИТРОВ", "НА", "ВИДЕО"];

// Drops trailing sample words until the block fits within line_count lines,
// mirroring how the renderer packs words into a caption instead of wrapping
// endlessly. Without this the preview shows more text than will ever appear.
function trimToLineCount(line, activeIdx) {
  const lineHeight = parseFloat(getComputedStyle(line).lineHeight) || 1;
  const allowed = Math.max(1, style.line_count);
  let active = activeIdx == null ? 0 : activeIdx;
  let guard = 12;
  while (guard-- > 0 && line.children.length > 1) {
    const lines = Math.round(line.scrollHeight / lineHeight);
    if (lines <= allowed) break;
    // Drop words from the side away from the highlighted one, so the word
    // being edited never disappears from its own preview.
    if (line.children.length - 1 > active) {
      line.removeChild(line.lastElementChild);
    } else {
      line.removeChild(line.firstElementChild);
      active--;
    }
  }
}

const STAGE_LABELS = {
  downloading_model: "Скачивание модели (разово)...",
  loading_model: "Загрузка модели распознавания...",
  transcribing: "Распознавание речи...",
  preparing: "Подготовка рендера...",
  building: "Построение субтитров...",
  compositing: "Сборка видео слоёв...",
  rendering: "Рендер видео...",
  done: "Готово",
};

function setProgress(label, pct) {
  $("progressStage").textContent = label;
  $("progressPct").textContent = pct != null ? pct + "%" : "";
  $("progressFill").style.width = (pct || 0) + "%";
}

// tone "ok" for plain notices; errors keep the red frame.
function showToast(message, tone) {
  document.querySelectorAll(".toast").forEach((old) => old.remove());
  const toast = document.createElement("div");
  toast.className = "toast" + (tone === "ok" ? " ok" : "");
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 6000);
}

async function openCreatorChannel() {
  return CreatorChannel.openCreatorChannel(api(), showToast);
}

window.onPipelineError = function (message) {
  setProgress("Ошибка", null);
  showToast("Ошибка: " + message);
};

async function openOutput() {
  await api().open_output_folder(lastOutputPath);
}

// Approximate download sizes, so the hint can warn before a long wait.
const MODEL_SIZES = {
  "large-v3": "~3 ГБ",
  "distil-large-v3": "~1.5 ГБ",
  "medium": "~1.5 ГБ",
  "small": "~500 МБ",
  "base": "~150 МБ",
};
let modelsCached = {};

// Best first: the dropdown falls back to the best model already on disk.
const MODEL_PREFERENCE = ["large-v3", "distil-large-v3", "medium", "small", "base", "tiny"];

async function refreshModelHint(selectDownloaded) {
  try {
    modelsCached = (await api().models_status()) || {};
  } catch (e) {
    modelsCached = {};
  }

  // On startup, don't leave a 3 GB download queued up behind the default when
  // the user already has a lighter model installed.
  if (selectDownloaded && !modelsCached[$("modelSize").value]) {
    const ready = MODEL_PREFERENCE.find((m) => modelsCached[m] &&
      $("modelSize").querySelector(`option[value="${m}"]`));
    if (ready) $("modelSize").value = ready;
  }

  updateModelHint();
}

function updateModelHint() {
  const size = $("modelSize").value;
  const hint = $("modelHint");
  if (modelsCached[size]) {
    hint.textContent = "Модель уже скачана — начнём сразу.";
    hint.style.color = "";
  } else {
    hint.textContent = `Модель ещё не скачана: при запуске загрузится ${MODEL_SIZES[size] || ""} (разово).`;
    hint.style.color = "var(--accent)";
  }
}

async function refreshGpuBadge() {
  const dot = $("gpuDot"), label = $("gpuLabel");
  const IDLE = "var(--text-dim)";
  const paint = (text, color, hint) => {
    label.textContent = text;
    label.title = hint || "";
    dot.style.background = color;
    dot.style.boxShadow = color === IDLE ? "none" : `0 0 8px ${color}`;
  };
  try {
    const info = await api().get_gpu_info();
    if (!info.name) return paint("CPU режим", IDLE);
    // A detected card is not a usable card: without the CUDA libraries, or on
    // a card whose compute types the model cannot use, the run lands on the
    // processor anyway. Green over CPU-speed work is what hid that.
    if (info.usable) return paint(`${info.name} · ${info.compute_type}`, "var(--good)");
    paint(`${info.name} — CPU режим`, "var(--warn)", info.reason);
  } catch (e) {
    paint("CPU режим", IDLE);
  }
}

// ---------------- init ----------------

function init() {
  setupBindings();
  if (typeof initWorkspace === "function") initWorkspace();
  applyStyleToControls();
  applyStageGeometry();
  renderSafeZones();
  loadPresets();
  loadFonts();
  refreshGpuBadge();
  refreshModelHint(true);
  $("modelSize").addEventListener("change", updateModelHint);
}

// Waits for the whole page (workspace.js loads after this file) and for the
// Python bridge, whichever comes last.
let booted = false;
function boot() {
  const start = () => { if (!booted) { booted = true; init(); } };
  if (window.pywebview && window.pywebview.api) start();
  else window.addEventListener("pywebviewready", start, { once: true });
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
// The preview takes whatever height the column has left, so refit the frame
// whenever that box changes (window resize, 4K scaling, panels wrapping).
if (window.ResizeObserver) {
  new ResizeObserver(() => applyStageGeometry()).observe(document.getElementById("previewHolder"));
} else {
  window.addEventListener("resize", applyStageGeometry);
}
