// Interface language.
//
// The key of every string is the Russian original, the way gettext uses the
// source text as msgid. That buys two things: the markup and the code stay
// readable with no key catalogue to keep in sync, and a string with no
// translation yet simply stays Russian instead of showing "ui.header.title".
//
// Static chrome is translated by walking the DOM; anything JS builds goes
// through t() at the moment it is built, so language switching only has to
// redraw what is already redrawable.
(function (root, factory) {
  const i18n = factory();
  if (typeof module === "object" && module.exports) module.exports = i18n;
  root.I18n = i18n;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const SOURCE = "ru";
  const dicts = { ru: {} };          // ru is the source: nothing to look up
  const names = { ru: "Русский" };
  let lang = SOURCE;
  let onChange = null;

  // Originals live here, not in the markup: switching back to Russian needs
  // the text the node had before the first translation.
  const textSource = new WeakMap();
  const attrSource = new WeakMap();

  const ATTRS = ["title", "placeholder", "aria-label", "alt"];
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA"]);

  function register(code, name, dict) {
    dicts[code] = dict || {};
    names[code] = name;
  }

  function languages() {
    return Object.keys(dicts).map((code) => ({ code, name: names[code] || code }));
  }

  function current() { return lang; }

  function has(code) { return Object.prototype.hasOwnProperty.call(dicts, code); }

  // t("готово: {n}", {n: 3}) -> "done: 3"
  function t(text, vars) {
    if (typeof text !== "string" || !text) return text;
    const dict = dicts[lang] || {};
    let out = Object.prototype.hasOwnProperty.call(dict, text) ? dict[text] : text;
    if (vars) {
      out = out.replace(/\{(\w+)\}/g, (whole, key) =>
        Object.prototype.hasOwnProperty.call(vars, key) ? String(vars[key]) : whole);
    }
    return out;
  }

  function translatable(node) {
    const parent = node.parentElement;
    if (!parent || SKIP_TAGS.has(parent.tagName)) return false;
    // User data - file names, recognised words - never goes through the
    // dictionary: a video called "Готово" is not the word "Готово".
    return !parent.closest("[data-i18n-skip]");
  }

  function applyText(node) {
    const original = textSource.has(node) ? textSource.get(node) : node.nodeValue;
    const trimmed = original.trim();
    if (!trimmed) return;
    const translated = t(trimmed);
    if (translated === trimmed && !textSource.has(node)) return;
    if (!textSource.has(node)) textSource.set(node, original);
    node.nodeValue = original.replace(trimmed, translated);
  }

  function applyAttrs(el) {
    if (el.closest && el.closest("[data-i18n-skip]")) return;
    let saved = attrSource.get(el);
    for (const name of ATTRS) {
      if (!el.hasAttribute(name)) continue;
      const original = saved && name in saved ? saved[name] : el.getAttribute(name);
      const translated = t(original);
      if (translated === original && !(saved && name in saved)) continue;
      if (!saved) { saved = {}; attrSource.set(el, saved); }
      if (!(name in saved)) saved[name] = original;
      el.setAttribute(name, translated);
    }
  }

  // Translates everything under `root` that is not marked data-i18n-skip.
  function apply(root) {
    const scope = root || (typeof document !== "undefined" ? document.body : null);
    if (!scope) return;
    if (scope.nodeType === 1) applyAttrs(scope);
    scope.querySelectorAll("*").forEach(applyAttrs);
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) =>
        translatable(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(applyText);
  }

  // Returns true when the language actually changed.
  function setLang(code, options) {
    const next = has(code) ? code : SOURCE;
    if (next === lang) return false;
    lang = next;
    if (typeof document !== "undefined") {
      document.documentElement.lang = next;
      apply(document.body);
    }
    if (onChange && !(options && options.silent)) onChange(next);
    return true;
  }

  function onLanguageChange(handler) { onChange = handler; }

  return { register, languages, current, setLang, t, apply, onLanguageChange, SOURCE };
});
