// The English interface is only as complete as its dictionary, and a missing
// line is invisible in Russian. So the test walks the window itself: every
// Russian string the interface can show must have an English one.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const GUI = path.join(ROOT, "gui");

require(path.join(GUI, "i18n", "en.js"));
const DICT = globalThis.I18N_EN;

const CYRILLIC = /[А-Яа-яЁё]/;
const ATTRS = ["title", "placeholder", "aria-label", "alt"];

const read = (...parts) => fs.readFileSync(path.join(...parts), "utf8");
const SCRIPTS = ["app.js", "workspace.js", "manual-state.js", "creator-channel.js"];

// The window is the page plus the panels app.js builds from template literals.
function markupSources() {
  const sources = [read(GUI, "index.html").split("<body>")[1]];
  for (const name of SCRIPTS) {
    for (const literal of read(GUI, name).match(/`[^`]*`/g) || []) {
      if (literal.includes("<")) sources.push(literal);
    }
  }
  return sources;
}

// Text between tags, minus <script>/<style> blocks and skipped containers.
function markupStrings() {
  const found = new Set();
  for (const source of markupSources()) {
    const body = source.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<style[\s\S]*?<\/style>/g, "");
    for (const chunk of body.split(/<[^>]*>/)) {
      const text = chunk.replace(/\s+/g, " ").trim();
      if (text && CYRILLIC.test(text) && !text.includes("${")) found.add(text);
    }
    for (const attr of ATTRS) {
      const re = new RegExp(`${attr}="([^"$]*)"`, "g");
      let m;
      while ((m = re.exec(body))) if (CYRILLIC.test(m[1])) found.add(m[1]);
    }
  }
  return found;
}

// Every Russian literal in the scripts. They are all meant for the screen:
// what the code writes itself goes through t(), and the label tables
// (FILE_STATUS, STAGE_LABELS and friends) are translated where they are used.
function codeStrings() {
  const found = new Set();
  for (const name of ["app.js", "workspace.js", "manual-state.js", "creator-channel.js"]) {
    const source = fs.readFileSync(path.join(GUI, name), "utf8");
    for (const line of source.split("\n")) {
      const trimmed = line.trim();
      if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) continue;
      const re = /"([^"\\]*)"|'([^'\\]*)'/g;
      let m;
      while ((m = re.exec(line))) {
        const text = m[1] !== undefined ? m[1] : m[2];
        if (text && CYRILLIC.test(text)) found.add(text);
      }
    }
  }
  return found;
}

const placeholders = (text) => (text.match(/\{(\w+)\}/g) || []).sort().join(",");

test("every Russian string in the markup has an English one", () => {
  const missing = [...markupStrings()].filter((text) => !(text in DICT));
  assert.deepEqual(missing, [], "нет перевода для строк разметки");
});

test("every string the code translates has an English one", () => {
  const missing = [...codeStrings()].filter((text) => !(text in DICT));
  assert.deepEqual(missing, [], "нет перевода для строк из кода");
});

test("the dictionary has no entries nobody asks for", () => {
  // A stale key means a typo on one side or the other: the interface would
  // quietly stay Russian there.
  // Python sends some of these straight to a toast, so its sources count too.
  const haystack = [read(GUI, "index.html"), ...SCRIPTS.map((n) => read(GUI, n)),
    read(ROOT, "app.py"), read(ROOT, "lib", "updates.py"),
    read(ROOT, "lib", "manual_jobs.py")].join("\n");
  const unused = Object.keys(DICT).filter((key) => !haystack.includes(key));
  assert.deepEqual(unused, [], "в словаре есть строки, которых нет в интерфейсе");
});

test("placeholders survive the translation", () => {
  const broken = Object.entries(DICT)
    .filter(([ru, en]) => placeholders(ru) !== placeholders(en))
    .map(([ru]) => ru);
  assert.deepEqual(broken, [], "подстановки {n} не совпадают");
});

test("no translation is left in Russian", () => {
  const untranslated = Object.entries(DICT)
    .filter(([, en]) => CYRILLIC.test(en))
    .map(([ru]) => ru);
  assert.deepEqual(untranslated, []);
});
