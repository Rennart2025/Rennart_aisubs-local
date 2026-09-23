(function (root, factory) {
  const creatorChannel = factory();
  if (typeof module === "object" && module.exports) module.exports = creatorChannel;
  root.CreatorChannel = creatorChannel;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  // Under Node (the tests) there is no interface and no dictionary: the
  // Russian source text is then the answer.
  function tr(text, vars) {
    const i18n = typeof globalThis !== "undefined" && globalThis.I18n;
    if (i18n) return i18n.t(text, vars);
    return vars ? text.replace(/\{(\w+)\}/g, (whole, key) =>
      (key in vars ? String(vars[key]) : whole)) : text;
  }

  async function openCreatorChannel(api, notify) {
    try {
      const result = await api.open_creator_channel();
      if (!result || !result.ok) {
        const error = tr((result && result.error) || "неизвестная ошибка");
        notify(tr("Не удалось открыть {what}: {why}", { what: "@daipotestit", why: error }));
      }
      return result;
    } catch (error) {
      const message = String(error);
      notify(tr("Не удалось открыть {what}: {why}", { what: "@daipotestit", why: message }));
      return { ok: false, error: message };
    }
  }

  const LABELS = {
    author: "@daipotestit",
    fork_author: "@rinatmaksutov",
    repo: "репозиторий проекта",
    page: "страницу программы",
  };

  // Header links other than the original author's channel. The page sends a
  // key, never a URL: app.py owns the list of addresses it may open.
  async function openProjectLink(api, key, notify) {
    const label = tr(LABELS[key] || "ссылку");
    try {
      const result = await api.open_link(key);
      if (!result || !result.ok) {
        const error = tr((result && result.error) || "неизвестная ошибка");
        notify(tr("Не удалось открыть {what}: {why}", { what: label, why: error }));
      }
      return result;
    } catch (error) {
      const message = String(error);
      notify(tr("Не удалось открыть {what}: {why}", { what: label, why: message }));
      return { ok: false, error: message };
    }
  }

  return { openCreatorChannel, openProjectLink };
});
