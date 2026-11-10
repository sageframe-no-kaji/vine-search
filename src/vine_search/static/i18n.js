"use strict";
/*
 * Interface translation.
 *
 * The application renders English. This layer translates the rendered text
 * through a catalog keyed by the English source text, so code changes never
 * need translation work: text missing from a catalog simply stays English.
 *
 * Catalog keys (static/locales/<lang>.js):
 *   "Sync reviews"            exact text of an element, an attribute
 *                             (placeholder, aria-label, title) or a toast
 *   "Seen {when}"             a pattern; each {name} matches text within one
 *                             sentence, itself translated when the catalog
 *                             knows it; {n} matches only a number
 * Text joined with " · " or written as several sentences is also translated
 * part by part. Elements marked translate="no" (product titles, tracker names)
 * are never changed. In a non-English interface, VINE_I18N.missing lists the
 * text the catalog does not cover yet.
 */
(() => {
  const STORAGE_KEY = "vine-language";
  const catalogs = window.VINE_LOCALES || {};
  const stored = () => {
    try {
      return localStorage.getItem(STORAGE_KEY) || "";
    } catch {
      return "";
    }
  };
  const supported = (tag) => {
    const base = String(tag || "")
      .slice(0, 2)
      .toLowerCase();
    return base === "en" || catalogs[base] ? base : "";
  };
  const lang =
    supported(stored()) ||
    [...(navigator.languages || []), navigator.language]
      .map(supported)
      .find(Boolean) ||
    "en";
  const catalog = (lang !== "en" && catalogs[lang]) || null;
  const missing = new Set();
  // Text already in the target language (translations, help titles) is not missing.
  const targets = new Set([
    ...Object.values(catalog?.strings || {}),
    ...Object.values(catalog?.help || {}).map((topic) => topic.title),
  ]);
  const exact = new Map();
  const patterns = [];
  for (const [source, target] of Object.entries(catalog?.strings || {})) {
    if (!/\{\w+\}/.test(source)) {
      exact.set(source, target);
      continue;
    }
    const names = [];
    const body = source
      .split(/(\{\w+\})/)
      .map((part) => {
        const name = /^\{(\w+)\}$/.exec(part)?.[1];
        if (!name) return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        names.push(name);
        return name === "n" ? "([\\d.,\\s]+?)" : "((?:(?![.!?]\\s).)+?)";
      })
      .join("");
    patterns.push({
      regex: new RegExp(`^${body}$`, "s"),
      names,
      target,
      weight: source.replace(/\{\w+\}/g, "").length,
    });
  }
  // Prefer the most specific pattern: the one with the most literal text.
  patterns.sort((a, b) => b.weight - a.weight);

  function translate(text, depth = 0) {
    if (exact.has(text)) return exact.get(text);
    if (depth > 6) return null;
    for (const pattern of patterns) {
      const match = pattern.regex.exec(text);
      if (!match) continue;
      const values = Object.fromEntries(
        pattern.names.map((name, index) => {
          const value = match[index + 1];
          return [name, translate(value, depth + 1) ?? value];
        }),
      );
      return pattern.target.replace(/\{(\w+)\}/g, (_, name) => values[name]);
    }
    // Composed text: sentences, then "; " lists, then " · " details.
    for (const [split, join] of [
      [/(?<=[.!?])\s+(?=\S)/, " "],
      ["; ", "; "],
      [" · ", " · "],
    ]) {
      const parts = text.split(split);
      if (parts.length < 2) continue;
      const translated = parts.map((part) => translate(part, depth + 1));
      if (translated.some((part) => part !== null))
        return translated.map((part, index) => part ?? parts[index]).join(join);
    }
    return null;
  }

  function translateValue(value) {
    const text = value.trim();
    if (!text || !/\p{L}/u.test(text)) return null;
    const result = translate(text);
    if (result === null) {
      if (!targets.has(text)) missing.add(text);
      return null;
    }
    const start = value.indexOf(text);
    return value.slice(0, start) + result + value.slice(start + text.length);
  }

  const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE"]);
  const ATTRIBUTES = ["placeholder", "aria-label", "title"];
  const done = new WeakMap();
  const excluded = (element) =>
    !element ||
    SKIP.has(element.tagName) ||
    !!element.closest('[translate="no"]');

  function translateText(node) {
    if (done.get(node) === node.data || excluded(node.parentElement)) return;
    const result = translateValue(node.data);
    if (result !== null && result !== node.data) node.data = result;
    done.set(node, node.data);
  }
  function translateAttributes(element) {
    if (excluded(element)) return;
    for (const name of ATTRIBUTES) {
      const value = element.getAttribute(name);
      const key = `${name}\u0000${value}`;
      if (value === null || done.get(element)?.[key]) continue;
      const result = translateValue(value);
      const translated = result ?? value;
      if (translated !== value) element.setAttribute(name, translated);
      done.set(element, {
        ...done.get(element),
        [`${name}\u0000${translated}`]: true,
      });
    }
  }
  function translateTree(root) {
    if (root.nodeType === Node.TEXT_NODE) return translateText(root);
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    if (excluded(root)) return;
    translateAttributes(root);
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
      {
        acceptNode: (node) =>
          node.nodeType === Node.ELEMENT_NODE &&
          (SKIP.has(node.tagName) || node.getAttribute("translate") === "no")
            ? NodeFilter.FILTER_REJECT
            : NodeFilter.FILTER_ACCEPT,
      },
    );
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeType === Node.TEXT_NODE) translateText(node);
      else translateAttributes(node);
    }
  }

  // Help topics: a translated topic replaces its English title and body;
  // topics without a translation stay English.
  const help = catalog?.help || {};
  if (Array.isArray(window.VINE_HELP_TOPICS) && Object.keys(help).length)
    window.VINE_HELP_TOPICS = Object.freeze(
      window.VINE_HELP_TOPICS.map((topic) =>
        help[topic.id]
          ? {
              ...topic,
              ...help[topic.id],
              html: `<div translate="no">${help[topic.id].html}</div>`,
            }
          : topic,
      ),
    );

  window.VINE_I18N = Object.freeze({
    lang,
    locale: catalog?.locale || (lang === "en" ? undefined : lang),
    missing,
    translate: (text) => translate(text) ?? text,
  });
  document.documentElement.lang = catalog?.locale || lang;

  const picker = document.getElementById("language-select");
  if (picker) {
    const choices = [
      ["", "Automatic"],
      ["en", "English"],
      ...Object.entries(catalogs).map(([code, value]) => [
        code,
        value.name || code,
      ]),
    ];
    for (const [value, label] of choices)
      picker.add(new Option(label, value, false, value === stored()));
    picker.onchange = () => {
      try {
        if (picker.value) localStorage.setItem(STORAGE_KEY, picker.value);
        else localStorage.removeItem(STORAGE_KEY);
      } catch {
        /* Without storage the browser language decides. */
      }
      location.reload();
    };
  }

  if (!catalog) return;
  translateTree(document.documentElement);
  new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === "characterData") translateText(record.target);
      else if (record.type === "attributes") translateAttributes(record.target);
      else record.addedNodes.forEach(translateTree);
    }
  }).observe(document.documentElement, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRIBUTES,
  });
})();
