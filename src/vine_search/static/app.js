"use strict";
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [
    ...root.querySelectorAll(selector),
  ];
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const icons = {
    search:
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>',
    plus: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
    refresh:
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10a8 8 0 1 0-2 8M20 4v6h-6"/></svg>',
    filter:
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M7 12h10M10 17h4"/></svg>',
    image:
      '<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="4" y="5" width="24" height="22" rx="2"/><circle cx="11" cy="12" r="2"/><path d="m4 23 8-7 5 4 4-5 7 8"/></svg>',
  };
  const state = {
    csrf: "",
    settings: {},
    connection: { state: "disconnected" },
    trackers: [],
    route: "discover",
    mode: "history",
    query: "",
    source: "",
    tracker: "",
    sort: "rank",
    minScore: "",
    freshness: "",
    offset: 0,
    limit: 24,
    reviewOffset: 0,
    reviewLimit: 100,
    products: null,
    jobs: [],
    liveJob: null,
    login: null,
    viewEpoch: 0,
    reviewFilters: {
      query: "",
      status: "",
      local_progress: "",
      source: "",
      sort: "oldest",
    },
    importRecords: null,
    importPreview: null,
  };
  let pollTimer,
    toastTimer,
    pollBusy = false;
  function toast(message, error = false) {
    const node = $("#toast");
    node.textContent = message;
    node.classList.toggle("error", error);
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (node.hidden = true), error ? 9000 : 4500);
  }
  async function api(path, options = {}) {
    const headers = { Accept: "application/json", ...options.headers };
    if (options.method && options.method !== "GET") {
      headers["X-CSRF-Token"] = state.csrf;
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(`/api${path}`, {
      ...options,
      headers,
      credentials: "same-origin",
    });
    let data;
    try {
      data = await response.json();
    } catch {
      data = { detail: response.statusText };
    }
    if (!response.ok) {
      let message =
        data.detail || data.message || "The request failed. Try again.";
      if (Array.isArray(message))
        message = message.map((x) => x.msg).join("; ");
      throw new Error(
        typeof message === "string" ? message : JSON.stringify(message),
      );
    }
    return data;
  }
  const write = (path, body = {}, method = "POST") =>
    api(path, { method, body: JSON.stringify(body) });
  const items = (value) => (Array.isArray(value) ? value : value?.items || []);
  function date(value, options = {}) {
    if (!value) return "Not captured";
    const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
    const d = new Date(value);
    return Number.isNaN(d.getTime())
      ? "Unknown date"
      : d.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          ...options,
          ...(dateOnly ? { timeZone: "UTC" } : {}),
        });
  }
  function relative(value) {
    if (!value) return "Not yet";
    const age = Math.max(0, Date.now() - new Date(value).getTime());
    if (!Number.isFinite(age)) return "Unknown";
    if (age < 60000) return "just now";
    if (age < 3600000) return `${Math.floor(age / 60000)}m ago`;
    if (age < 86400000) return `${Math.floor(age / 3600000)}h ago`;
    return `${Math.floor(age / 86400000)}d ago`;
  }
  const pretty = (value) =>
    String(value || "unknown")
      .replace(/_/g, " ")
      .replace(/^./, (c) => c.toUpperCase());
  const sourceName = (value) =>
    ({
      rfy: "For you",
      afa: "Available for all",
      search: "Additional items",
      amazon: "Amazon",
      import: "Imported",
      manual: "Manual",
    })[value] || pretty(value);
  function safeAmazon(value) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" &&
        ["amazon.com", "www.amazon.com"].includes(url.hostname) &&
        !url.username &&
        !url.password
        ? url.href
        : "";
    } catch {
      return "";
    }
  }
  function safeImage(value) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" &&
        [
          "m.media-amazon.com",
          "images-na.ssl-images-amazon.com",
          "images-eu.ssl-images-amazon.com",
          "images.amazon.com",
        ].includes(url.hostname)
        ? url.href
        : "";
    } catch {
      return "";
    }
  }
  const external = (url, label, cls = "") =>
    safeAmazon(url)
      ? `<a class="${esc(cls)}" href="${esc(safeAmazon(url))}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`
      : "";
  const statusLabel = (value) =>
    `<span class="status-label ${esc(value)}">${esc(pretty(value))}</span>`;
  function skeleton() {
    $("#main").innerHTML =
      '<div class="skeleton" aria-label="Loading"><div></div><div></div><div></div></div>';
    $("#main").setAttribute("aria-busy", "true");
  }
  function page(title, description, actions = "") {
    return `<div class="page-heading"><div><h1>${esc(title)}</h1><p>${esc(description)}</p></div>${actions ? `<div class="actions">${actions}</div>` : ""}</div>`;
  }
  function empty(title, description, actions = "") {
    return `<div class="empty-state"><h2>${esc(title)}</h2><p>${esc(description)}</p>${actions ? `<div class="actions">${actions}</div>` : ""}</div>`;
  }
  function selectOptions(options, value) {
    return options
      .map(
        ([v, l]) =>
          `<option value="${esc(v)}"${String(v) === String(value) ? " selected" : ""}>${esc(l)}</option>`,
      )
      .join("");
  }
  function field(name, label, value, type = "text", help = "", attrs = "") {
    return `<label class="field">${esc(label)}<input name="${esc(name)}" type="${type}" value="${esc(value)}" ${attrs}>${help ? `<small>${esc(help)}</small>` : ""}</label>`;
  }
  function selectField(name, label, value, options, help = "") {
    return `<label class="field">${esc(label)}<select name="${esc(name)}">${selectOptions(options, value)}</select>${help ? `<small>${esc(help)}</small>` : ""}</label>`;
  }
  function check(name, label, value, help = "") {
    return `<label class="check-field wide"><input name="${esc(name)}" type="checkbox"${value ? " checked" : ""}><span class="label-text">${esc(label)}${help ? `<small>${esc(help)}</small>` : ""}</span></label>`;
  }
  function errorIn(form, error) {
    let node = $(".form-error", form);
    if (!node) {
      node = document.createElement("p");
      node.className = "form-error";
      node.setAttribute("role", "alert");
      form.append(node);
    }
    node.textContent = error.message;
  }
  async function busy(button, action) {
    if (button) button.disabled = true;
    try {
      return await action();
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (button) button.disabled = false;
    }
  }
  function confirmed(title, message, phrase = "") {
    return new Promise((resolve) => {
      const dialog = $("#confirmation-dialog");
      $("#confirmation-title").textContent = title;
      $("#confirmation-message").textContent = message;
      $("#confirmation-label").hidden = !phrase;
      $("#confirmation-label").firstChild.textContent = phrase
        ? `Type ${phrase} to continue`
        : "";
      $("#confirmation-input").value = "";
      $("#confirmation-commit").disabled = !!phrase;
      $("#confirmation-input").oninput = () =>
        ($("#confirmation-commit").disabled =
          $("#confirmation-input").value !== phrase);
      dialog.addEventListener(
        "close",
        () => resolve(dialog.returnValue === "confirm"),
        { once: true },
      );
      dialog.showModal();
    });
  }
  function coverageText(coverage, singleRun = false) {
    if (!coverage)
      return "Only observed pages are included. Amazon determines current availability.";
    const runs = Array.isArray(coverage)
      ? coverage
      : coverage.runs || coverage.recent_runs || [];
    if (runs.length) {
      const describe = (run) =>
        `${sourceName(run.kind || run.source)}${run.query ? ` “${run.query}”` : ""}: ${pretty(run.status).toLowerCase()}, ${run.pages ?? "?"} page${run.pages === 1 ? "" : "s"} · ${relative(run.finished_at || run.last_seen)}`;
      if (singleRun)
        return `${describe(runs[0])}. Results are limited to this run's captured pages.`;
      const scopes = new Map();
      for (const run of runs) {
        const key = run.scope || `${run.kind || run.source}:${run.query || ""}`;
        if (!scopes.has(key)) scopes.set(key, run);
      }
      const recent = [...scopes.values()];
      return `Recent captures — ${recent.slice(0, 4).map(describe).join("; ")}${recent.length > 4 ? `; ${recent.length - 4} other scopes` : ""}. Results may span historical runs. These captures do not establish full-catalog coverage.`;
    }
    if (typeof coverage === "string") return coverage;
    return (
      coverage.message ||
      `History reflects captured pages${coverage.last_seen ? `, last observed ${relative(coverage.last_seen)}` : ""}. No full-catalog coverage is implied.`
    );
  }
  function updateConnection(connection) {
    const changed =
      state.connection.state !== connection?.state ||
      state.connection.message !== connection?.message;
    state.connection = connection || { state: "disconnected" };
    const status = state.connection.state || "disconnected";
    $("#connection-dot").className = `status-dot ${status}`;
    $("#connection-label").textContent =
      {
        connected: "Amazon connected",
        connecting: "Connecting Amazon",
        needs_login: "Reconnect Amazon",
        challenge: "Amazon needs attention",
        failed: "Connection failed",
        disconnected: "Connect Amazon",
      }[status] || pretty(status);
    const notice = $("#global-notice");
    if (["needs_login", "challenge", "failed"].includes(status)) {
      notice.hidden = false;
      notice.innerHTML = `<p>${esc(state.connection.message || "Amazon needs your attention. Your saved history is still available.")}</p><button class="button compact" data-action="connect">Reconnect</button>`;
    } else notice.hidden = true;
    if (changed && !$("#connection-panel").hidden) renderConnection();
  }
  function renderConnection() {
    const c = state.connection;
    const panel = $("#connection-panel");
    const active =
      state.login &&
      [
        "queued",
        "starting",
        "connecting",
        "active",
        "waiting",
        "ready",
        "challenge",
      ].includes(state.login.state);
    const connected = c.state === "connected";
    panel.innerHTML = `<div class="connection-top"><div><h2 id="connection-title">${connected ? "Amazon is connected" : active ? "Sign in to Amazon" : "Connect your Amazon account"}</h2><p>${active ? "Sign in on Amazon in the dedicated browser below, including any verification Amazon requests. This window closes when Vine access is verified." : connected ? "The dedicated browser can collect products and review status. Your everyday browser can remain closed." : "Open the installation’s private browser and sign in directly on Amazon. VineSearch never asks you to type your Amazon password into this dashboard."}</p><div class="connection-details"><span>State: ${esc(pretty(c.state))}</span><span>Last successful access: ${esc(c.last_success ? date(c.last_success, { hour: "numeric", minute: "2-digit" }) : "Not yet verified")}</span>${state.login?.expires_at ? `<span>Login window expires ${esc(new Date(state.login.expires_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }))}</span>` : ""}</div>${c.message ? `<p class="small">${esc(c.message)}</p>` : ""}</div><div class="actions">${active ? '<button class="button" data-action="cancel-login">Cancel login</button>' : `<button class="button primary" data-action="start-login">${connected ? "Reconnect" : "Open login browser"}</button>`}${connected ? '<button class="button" data-action="disconnect">Disconnect</button>' : ""}<button class="button subtle" data-action="close-connection">Close</button></div></div>${active && ["ready", "challenge"].includes(state.login.state) && state.login.viewer_path ? `<p class="small"><a href="${esc(viewerURL())}" target="_blank" rel="noopener">Open login browser in a separate tab</a> if the embedded view is too small.</p><iframe class="login-frame" title="Private Amazon login browser" src="${esc(viewerURL())}" allow="clipboard-read; clipboard-write"></iframe>` : active ? '<p role="status">The dedicated browser is starting. Collection waits until login finishes.</p>' : ""}`;
  }
  function viewerURL() {
    const raw = (state.login?.viewer_path || "").replace(
      /^\/viewer\//,
      "/login-viewer/",
    );
    try {
      const url = new URL(raw, location.origin);
      if (url.origin !== location.origin) return "";
      if (state.login.capability && !url.searchParams.has("capability"))
        url.searchParams.set("capability", state.login.capability);
      return url.pathname + url.search;
    } catch {
      return "";
    }
  }
  async function startLogin(button) {
    await busy(button, async () => {
      state.login = await write("/connection/login");
      $("#connection-panel").hidden = false;
      state.connection = { ...state.connection, state: "connecting" };
      updateConnection(state.connection);
      renderConnection();
    });
  }
  async function loadTrackers() {
    state.trackers = items(await api("/trackers"));
    return state.trackers;
  }
  async function navigate() {
    const route = location.hash.slice(1).split("?")[0] || "discover";
    state.route = [
      "discover",
      "trackers",
      "reviews",
      "activity",
      "settings",
    ].includes(route)
      ? route
      : "discover";
    const epoch = ++state.viewEpoch;
    $$("[data-nav]").forEach((a) =>
      a.setAttribute(
        "aria-current",
        a.dataset.nav === state.route ? "page" : "false",
      ),
    );
    document.title = `VineSearch · ${pretty(state.route)}`;
    skeleton();
    try {
      await {
        discover: renderDiscover,
        trackers: renderTrackers,
        reviews: renderReviews,
        activity: renderActivity,
        settings: renderSettings,
      }[state.route](epoch);
    } catch (error) {
      if (epoch === state.viewEpoch) {
        $("#main").innerHTML = empty(
          "This view could not load",
          error.message,
          '<button class="button" data-action="retry-view">Try again</button>',
        );
      }
    } finally {
      $("#main").setAttribute("aria-busy", "false");
    }
  }

  async function renderDiscover(epoch = state.viewEpoch) {
    if (!state.trackers.length) await loadTrackers();
    if (epoch !== state.viewEpoch) return;
    $("#main").innerHTML =
      page(
        "Discover",
        "Find what fits. Keep a record of what you find.",
        '<button class="button" data-action="collect">' +
          icons.refresh +
          "Collect now</button>",
      ) +
      `<section class="search-area" aria-label="Product search"><div class="search-tabs" role="tablist" aria-label="Search scope"><button type="button" role="tab" data-search-mode="history" aria-selected="${state.mode === "history"}">Collected history</button><button type="button" role="tab" data-search-mode="live" aria-selected="${state.mode === "live"}">Live Amazon search</button></div><form id="search-form"><div class="search-line"><label class="search-field"><span class="screen-reader">${state.mode === "live" ? "Search the live Additional Items catalog" : "Search collected product history"}</span>${icons.search}<input name="query" type="search" placeholder="${state.mode === "live" ? "Search Additional Items on Amazon" : "Search titles in your collected history"}" value="${esc(state.query)}" maxlength="200"${state.mode === "live" ? " required" : ""}></label><button class="button primary" type="submit">${state.mode === "live" ? "Search live" : "Search"}</button></div><p class="search-hint">${state.mode === "live" ? "Queues a fresh search of Additional Items. Results are limited to the pages Amazon exposes and your collection budget." : "Searches products this installation has already observed. Live Amazon search can discover products outside this history."}</p></form></section><div id="live-job" role="status" aria-live="polite"></div><div class="discovery-layout"><aside class="filters" id="filters" aria-label="Product filters"><div class="filter-heading"><h2>Refine results</h2><button class="button subtle compact" data-action="clear-filters">Reset</button></div><div class="filter-group"><span class="filter-label">Observed in</span><div class="filter-list">${[
        ["", "All sources"],
        ["rfy", "For you"],
        ["afa", "Available for all"],
        ["search", "Additional items"],
      ]
        .map(
          ([v, l]) =>
            `<button class="filter-option" data-source="${v}" aria-pressed="${state.source === v}">${l}</button>`,
        )
        .join(
          "",
        )}</div></div><div class="filter-group"><label for="tracker-filter">Interest tracker</label><select id="tracker-filter">${selectOptions([["", "All products"], ...state.trackers.map((t) => [t.id, t.name])], state.tracker)}</select></div><div class="filter-group"><label for="freshness-filter">Last observed</label><select id="freshness-filter">${selectOptions(
        [
          ["", "Any time"],
          ["24", "Past 24 hours"],
          ["168", "Past 7 days"],
          ["720", "Past 30 days"],
        ],
        state.freshness,
      )}</select></div><div class="filter-group"><label for="score-filter">Minimum match score</label><input id="score-filter" type="number" min="0" max="1000" value="${esc(state.minScore)}" placeholder="Any score"></div><p class="filter-note">A match score comes from your tracker rules. Availability is checked on Amazon when you open an item.</p><a class="small" href="#trackers">Edit your interests</a></aside><section aria-label="Product results"><div class="results-toolbar"><div class="results-count" id="results-count">Loading observations…</div><button class="button compact mobile-filters" aria-expanded="false" aria-controls="filters" data-action="toggle-filters">${icons.filter}Filters</button><label class="sort-control results-sort">Sort<select id="sort-filter">${selectOptions(
        [
          ["rank", "Best match"],
          ["newest", "First seen: newest"],
          ["recent", "Last seen: newest"],
          ["title", "Title A–Z"],
        ],
        state.sort,
      )}</select></label></div><div id="product-results" class="results-grid" aria-live="polite"></div><div id="product-pagination"></div><p class="coverage" id="product-coverage"></p></section></div>`;
    $("#search-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      state.query = new FormData(event.currentTarget).get("query").trim();
      state.offset = 0;
      if (state.mode === "live") {
        await busy(
          $('button[type="submit"]', event.currentTarget),
          async () => {
            state.liveJob = await write("/jobs", {
              kind: "search",
              query: state.query,
            });
            renderLiveJob();
            toast("Live search queued. You can leave this page and return.");
          },
        );
      }
      await loadProducts();
    });
    $$("[data-search-mode]").forEach(
      (button) =>
        (button.onclick = () => {
          state.mode = button.dataset.searchMode;
          renderDiscover();
        }),
    );
    $$("[data-source]").forEach(
      (button) =>
        (button.onclick = () => {
          state.source = button.dataset.source;
          state.offset = 0;
          $$("[data-source]").forEach((b) =>
            b.setAttribute("aria-pressed", b === button ? "true" : "false"),
          );
          loadProducts().catch((e) => toast(e.message, true));
        }),
    );
    for (const [id, key] of [
      ["tracker-filter", "tracker"],
      ["freshness-filter", "freshness"],
      ["score-filter", "minScore"],
      ["sort-filter", "sort"],
    ])
      $("#" + id).onchange = (event) => {
        state[key] = event.target.value;
        state.offset = 0;
        loadProducts().catch((e) => toast(e.message, true));
      };
    renderLiveJob();
    await loadProducts();
  }
  async function loadProducts() {
    const params = new URLSearchParams({
      query: state.mode === "live" && state.liveJob ? "" : state.query,
      source: state.source,
      sort: state.sort,
      limit: state.limit,
      offset: state.offset,
    });
    if (state.mode === "live" && state.liveJob)
      params.set("job_id", state.liveJob.id);
    if (state.tracker) params.set("tracker_id", state.tracker);
    if (state.minScore !== "") params.set("min_score", state.minScore);
    if (state.freshness) params.set("freshness_hours", state.freshness);
    const data = await api("/products?" + params);
    state.products = data;
    if (state.route !== "discover" || !$("#product-results")) return;
    const products = items(data);
    $("#results-count").innerHTML =
      `<strong>${esc(data.total ?? products.length)}</strong> ${state.mode === "live" && state.liveJob ? "observed in this live search" : "products in history"}${state.tracker ? " · filtered by tracker" : ""}`;
    const grid = $("#product-results");
    grid.classList.toggle("results-grid", !!products.length);
    grid.innerHTML = products.length
      ? products.map(productCard).join("")
      : empty(
          state.mode === "live" &&
            state.liveJob &&
            ["queued", "running"].includes(state.liveJob.status)
            ? "Live search is in progress"
            : state.query
              ? "No observed products match"
              : "Your discovery history starts here",
          state.mode === "live" &&
            state.liveJob &&
            ["queued", "running"].includes(state.liveJob.status)
            ? "Results will appear when this run saves its observations. The job and its progress are preserved if you leave."
            : state.query
              ? "Try a broader phrase, clear the filters, or search the live Additional Items catalog."
              : "Connect Amazon, then collect your queues or run a live search. Observations and match reasons will appear here.",
          `<button class="button" data-action="${state.connection.state === "connected" ? "collect" : "connect"}">${state.connection.state === "connected" ? "Collect products" : "Connect Amazon"}</button>`,
        );
    $$("img", grid).forEach((image) =>
      image.addEventListener(
        "error",
        () => {
          image.replaceWith(imageFallback());
        },
        { once: true },
      ),
    );
    $("#product-coverage").textContent = coverageText(
      data.coverage,
      state.mode === "live" && !!state.liveJob,
    );
    $("#product-pagination").innerHTML =
      (data.total || 0) > state.limit
        ? `<div class="pagination"><button class="button compact" data-page="prev" ${state.offset === 0 ? "disabled" : ""}>Previous</button><span>${state.offset + 1}–${Math.min(state.offset + state.limit, data.total)} of ${data.total}</span><button class="button compact" data-page="next" ${state.offset + state.limit >= data.total ? "disabled" : ""}>Next</button></div>`
        : "";
    $$("[data-page]").forEach(
      (b) =>
        (b.onclick = () => {
          state.offset = Math.max(
            0,
            state.offset +
              (b.dataset.page === "next" ? state.limit : -state.limit),
          );
          loadProducts().catch((e) => toast(e.message, true));
        }),
    );
  }
  function imageFallback() {
    const node = document.createElement("span");
    node.className = "image-empty";
    node.innerHTML = icons.image + "<span>Image unavailable</span>";
    return node;
  }
  function demoImage(title) {
    const t = title.toLowerCase();
    if (t.includes("switch")) return 0;
    if (t.includes("hub")) return 1;
    if (t.includes("drill")) return 2;
    if (t.includes("solder")) return 3;
    if (t.includes("magnetic building")) return 4;
    if (t.includes("desk lamp")) return 5;
    return -1;
  }
  function productCard(product) {
    const sources = (product.sources || []).map((s) =>
      typeof s === "string"
        ? s
        : s.kind || s.source || (s.scope || "").split(":")[0],
    );
    const href =
      safeAmazon(product.vine_url) || safeAmazon(product.product_url);
    const demoCell = state.demo ? demoImage(product.title) : -1;
    const image =
      state.settings.image_mode === "hidden"
        ? ""
        : state.settings.image_mode === "direct"
          ? safeImage(product.image_url)
          : product.image_url
            ? `/api/products/${encodeURIComponent(product.id)}/image`
            : "";
    const reasons = (product.reasons || []).map((r) =>
      typeof r === "string" ? r : r.reason || r.label || JSON.stringify(r),
    );
    const matched = product.matches?.length;
    return `<article class="product-card"><div class="product-image">${demoCell >= 0 && state.settings.image_mode !== "hidden" ? `<span class="demo-product-image demo-cell-${demoCell}" role="img" aria-label="Synthetic illustration: ${esc(product.title)}"></span>` : image ? `<img src="${esc(image)}" alt="${esc(product.title)}" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : `<span class="image-empty">${icons.image}<span>${state.settings.image_mode === "hidden" ? "Images hidden" : "Image unavailable"}</span></span>`}</div><div class="product-body"><div class="product-source"><span>${esc(sources.map(sourceName).join(" / ") || "Observed product")}</span></div><h2 class="product-title">${href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(product.title)}</a>` : esc(product.title)}</h2><p class="product-category">${esc(product.category || "Category not observed")}</p><div class="match-line"><strong>${esc(product.score ?? 0)}</strong><span>match score${matched ? ` · ${matched} tracker${matched === 1 ? "" : "s"}` : ""}</span></div><p class="product-reasons">${esc(reasons.slice(0, 3).join(" · ") || "No active tracker match")}</p><div class="product-meta"><span title="${esc(product.last_seen)}">Seen ${esc(relative(product.last_seen))}</span>${external(href, "Open on Amazon")}</div></div></article>`;
  }
  function renderLiveJob() {
    const node = $("#live-job");
    if (!node || !state.liveJob) return;
    const j = state.liveJob;
    const terminal = [
      "complete",
      "partial",
      "truncated",
      "failed",
      "needs_login",
      "cancelled",
    ].includes(j.status);
    node.innerHTML = `<div class="job-progress"><div><strong>Live search: ${esc(j.query)}</strong> · ${statusLabel(j.status)}<p>${esc(j.error || progressText(j.progress) || (terminal ? "This search is saved in Activity. Its observed results are included below." : "Waiting for the dedicated browser. Progress is saved if you leave."))}</p></div>${terminal ? '<button class="button subtle compact" data-action="dismiss-live">Dismiss</button>' : `<button class="button compact" data-cancel-job="${esc(j.id)}">Cancel</button>`}</div>`;
  }
  function progressText(progress) {
    if (!progress) return "";
    if (typeof progress === "string") return progress;
    return (
      progress.message ||
      Object.entries(progress)
        .map(([k, v]) => `${pretty(k)}: ${v}`)
        .join(" · ")
    );
  }

  async function renderTrackers(epoch = state.viewEpoch) {
    await loadTrackers();
    if (epoch !== state.viewEpoch) return;
    $("#main").innerHTML =
      page(
        "Interest trackers",
        "Choose what matters, and see exactly why each product matches.",
        `<button class="button primary" data-action="new-tracker">${icons.plus}New tracker</button>`,
      ) +
      `<div class="tracker-layout"><section aria-label="Saved interest trackers"><div class="tracker-list">${state.trackers.map(trackerRow).join("")}</div>${!state.trackers.length ? empty("Track an interest", "Give an interest a name, add phrases and exclusions, then choose whether to search for it on a schedule.") : ""}<p class="coverage">Pausing a tracker removes it from ranking and scheduled searches. Existing products stay in your history. Editing rules does not replay old notifications.</p></section><aside class="tracker-editor" id="tracker-editor" aria-labelledby="editor-heading"></aside></div>`;
    renderTrackerEditor();
  }
  function trackerRow(t) {
    return `<article class="tracker-row"><div><h2>${esc(t.name)}</h2><p>${t.query ? `Live query: ${esc(t.query)}` : "History matching only"}${t.schedule_enabled ? ` · every ${t.interval_minutes} min` : ""}</p><div class="tags">${!t.enabled ? '<span class="tag paused">Paused</span>' : ""}${t.phrases.map((p) => `<span class="tag">${esc(p)}</span>`).join("")}${t.notify ? '<span class="tag">Alerts enabled</span>' : ""}</div><p class="muted small" style="margin-top:10px">${esc(t.phrase_mode === "all" ? "All phrases required" : "Any phrase may match")}${t.exclusions.length ? ` · ${t.exclusions.length} exclusion${t.exclusions.length === 1 ? "" : "s"}` : ""} · minimum score ${t.min_score}</p></div><div class="tracker-actions"><button class="button compact" data-edit-tracker="${t.id}">Edit</button><button class="button subtle compact" data-toggle-tracker="${t.id}">${t.enabled ? "Pause" : "Resume"}</button></div></article>`;
  }
  function renderTrackerEditor(tracker = null) {
    const t = tracker || {
      name: "",
      enabled: true,
      query: "",
      phrases: [],
      phrase_mode: "any",
      exclusions: [],
      categories: [],
      phrase_weight: 30,
      category_weight: 20,
      freshness_weight: 10,
      min_score: 1,
      freshness_hours: 168,
      notify: false,
      schedule_enabled: false,
      interval_minutes: 15,
      page_budget: 5,
    };
    $("#tracker-editor").innerHTML =
      `<h2 id="editor-heading">${tracker ? "Edit tracker" : "New tracker"}</h2><p>Matching is deterministic. Exclusions always remove a product from this tracker.</p><form id="tracker-form" data-id="${tracker?.id || ""}"><div class="form-grid">${field("name", "Tracker name", t.name, "text", "", 'required maxlength="120"')}${field("query", "Live Amazon query", t.query, "text", "Amazon searches Additional Items.", 'maxlength="200"')}<label class="field wide">Positive phrases<textarea name="phrases" placeholder="One phrase per line">${esc(t.phrases.join("\n"))}</textarea><small>Use one phrase per line. No phrases means all titles can match.</small></label>${selectField(
        "phrase_mode",
        "Phrase matching",
        t.phrase_mode,
        [
          ["any", "Any phrase"],
          ["all", "Every phrase"],
        ],
      )}${field("min_score", "Minimum score", t.min_score, "number", "Required to count as a match.", 'min="0" max="1000" required')}<label class="field wide">Excluded phrases<textarea name="exclusions" placeholder="One exclusion per line">${esc(t.exclusions.join("\n"))}</textarea></label><label class="field wide">Observed categories<input name="categories" value="${esc(t.categories.join(", "))}" placeholder="Any category"><small>Optional, comma-separated exact categories. Unknown categories do not satisfy a restriction.</small></label>${check("enabled", "Enable this tracker", t.enabled)}${check("schedule_enabled", "Search Amazon on a schedule", t.schedule_enabled, "A live query is required. Global collection pause also pauses this schedule.")}${field("interval_minutes", "Search interval (minutes)", t.interval_minutes, "number", "", 'min="5" max="10080" required')}${field("page_budget", "Maximum search pages", t.page_budget, "number", "", 'min="1" max="100" required')}${check("notify", "Alert on new eligible matches", t.notify, "Requires an enabled destination in Settings. Existing history is baselined.")}
      <details class="inline-disclosure"><summary>Ranking weights and freshness</summary><div class="form-grid">${field("phrase_weight", "Per matching phrase", t.phrase_weight, "number", "", 'min="0" max="1000" required')}${field("category_weight", "Category match", t.category_weight, "number", "", 'min="0" max="1000" required')}${field("freshness_weight", "Freshness bonus", t.freshness_weight, "number", "", 'min="0" max="1000" required')}${field("freshness_hours", "Freshness window (hours)", t.freshness_hours, "number", "Only products inside this window qualify.", 'min="1" max="8760" required')}</div></details></div><div class="form-actions"><button class="button primary" type="submit">Save tracker</button>${tracker ? `<button class="button subtle danger" type="button" data-delete-tracker="${tracker.id}">Delete tracker</button>` : ""}</div><p class="form-error" role="alert"></p></form>`;
    $("#tracker-form").onsubmit = async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const data = new FormData(form);
      const payload = {};
      for (const key of ["name", "query", "phrase_mode"])
        payload[key] = data.get(key).trim();
      for (const key of ["phrases", "exclusions"])
        payload[key] = data
          .get(key)
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean);
      payload.categories = data
        .get("categories")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
      for (const key of ["enabled", "schedule_enabled", "notify"])
        payload[key] = data.has(key);
      for (const key of [
        "phrase_weight",
        "category_weight",
        "freshness_weight",
        "min_score",
        "freshness_hours",
        "interval_minutes",
        "page_budget",
      ])
        payload[key] = Number(data.get(key));
      const button = $('[type="submit"]', form);
      button.disabled = true;
      try {
        const id = form.dataset.id;
        await write(
          "/trackers" + (id ? `/${id}` : ""),
          payload,
          id ? "PATCH" : "POST",
        );
        toast("Tracker saved. Ranking uses these rules now.");
        await renderTrackers();
      } catch (error) {
        errorIn(form, error);
      } finally {
        button.disabled = false;
      }
    };
  }

  async function renderReviews(epoch = state.viewEpoch) {
    const params = new URLSearchParams({
      ...state.reviewFilters,
      offset: state.reviewOffset,
      limit: state.reviewLimit,
    });
    const data = await api("/reviews?" + params);
    if (epoch !== state.viewEpoch) return;
    const records = items(data);
    const counts = {};
    $("#main").innerHTML =
      page(
        "Review progress",
        "Amazon’s observed status and your local progress, kept separate.",
        '<button class="button" data-action="sync-reviews">' +
          icons.refresh +
          'Sync reviews</button><button class="button" data-action="toggle-import">Import / export</button>',
      ) +
      `<section id="review-import" class="import-panel" hidden><h2>Import review metadata</h2><p>Choose a JSON export containing a list of records. The preview keeps identity, variant, dates, statuses, links and optional rating. Review bodies, drafts, notes, photos and credentials are excluded.</p><div class="actions"><label class="field">Metadata file<input id="review-file" type="file" accept="application/json,.json"></label><button class="button" data-action="export-reviews">Export review metadata</button></div><div id="import-preview"></div></section><div class="review-summary"><div class="summary-item"><strong>${esc(records.length)}</strong>shown of ${esc(data.total ?? records.length)}</div><div class="summary-item"><strong>${esc(counts.not_started ?? records.filter((r) => r.local_progress === "not_started").length)}</strong>not started locally</div><div class="summary-item"><strong>${esc(counts.in_progress ?? records.filter((r) => r.local_progress === "in_progress").length)}</strong>in progress locally</div><div class="summary-item"><strong>${esc(counts.submitted ?? records.filter((r) => r.local_progress === "submitted").length)}</strong>marked submitted</div></div><form id="review-filter-form" class="review-filters"><label class="screen-reader" for="review-query">Search review records</label><input id="review-query" type="search" name="query" placeholder="Search product titles" value="${esc(state.reviewFilters.query)}"><label class="screen-reader" for="review-status">Amazon observed status</label><select id="review-status" name="status">${selectOptions([["", "All observed statuses"], ...Array.from(new Set([...Object.keys(data.counts || {}), "Awaiting review", "Reviewed", "Approved", "Rejected", "Unknown", "Unavailable"])).map((value) => [value, value])], state.reviewFilters.status)}</select><label class="screen-reader" for="review-local">Local progress</label><select id="review-local" name="local_progress">${selectOptions(
        [
          ["", "All local progress"],
          ["not_started", "Not started"],
          ["in_progress", "In progress"],
          ["submitted", "Marked submitted"],
        ],
        state.reviewFilters.local_progress,
      )}</select><label class="screen-reader" for="review-source">Review source</label><select id="review-source" name="source">${selectOptions(
        [
          ["", "All sources"],
          ["amazon", "Amazon sync"],
          ["import", "Imported"],
        ],
        state.reviewFilters.source,
      )}</select><label class="screen-reader" for="review-sort">Sort reviews</label><select id="review-sort" name="sort">${selectOptions(
        [
          ["oldest", "Oldest order first"],
          ["newest", "Newest order first"],
          ["title", "Title A–Z"],
        ],
        state.reviewFilters.sort,
      )}</select><button class="button compact" type="submit">Apply</button></form>${records.length ? `<table class="data-table"><thead><tr><th class="title-cell">Product / variant</th><th>Order</th><th>Amazon observed</th><th>Local progress</th><th>Links</th></tr></thead><tbody>${records.map(reviewRow).join("")}</tbody></table>` : empty("No review records in this view", "Sync your Awaiting Review and Reviewed pages, import metadata, or clear the filters. Local progress never submits a review to Amazon.", '<button class="button" data-action="sync-reviews">Sync reviews</button>')}${(data.total || 0) > state.reviewLimit ? `<div class="pagination"><button class="button compact" data-review-page="prev" ${state.reviewOffset === 0 ? "disabled" : ""}>Previous</button><span>${state.reviewOffset + 1}–${Math.min(state.reviewOffset + state.reviewLimit, data.total)} of ${data.total}</span><button class="button compact" data-review-page="next" ${state.reviewOffset + state.reviewLimit >= data.total ? "disabled" : ""}>Next</button></div>` : ""}<p class="coverage">${esc(coverageText(data.coverage))} Local progress counts describe the displayed page. Counts describe saved records, not your account’s official review percentage. A partial scan never marks a missing item completed.</p>`;
    $("#review-filter-form").onsubmit = (event) => {
      event.preventDefault();
      state.reviewFilters = Object.fromEntries(
        new FormData(event.currentTarget),
      );
      state.reviewOffset = 0;
      renderReviews().catch((e) => toast(e.message, true));
    };
    $$("[data-review-progress]").forEach(
      (select) =>
        (select.onchange = async () => {
          const old = select.dataset.previous;
          try {
            await write(
              "/reviews/" + select.dataset.reviewProgress,
              { local_progress: select.value },
              "PATCH",
            );
            select.dataset.previous = select.value;
            if (state.reviewFilters.local_progress) {
              await renderReviews();
              $("#review-local")?.focus({ preventScroll: true });
            } else {
              const record = records.find(
                (r) => String(r.id) === select.dataset.reviewProgress,
              );
              if (record) record.local_progress = select.value;
              const counters = $$(".review-summary .summary-item strong");
              ["not_started", "in_progress", "submitted"].forEach(
                (progress, index) => {
                  counters[index + 1].textContent = String(
                    records.filter((r) => r.local_progress === progress).length,
                  );
                },
              );
            }
            toast("Local progress saved. Amazon status is unchanged.");
          } catch (e) {
            select.value = old;
            toast(e.message, true);
          }
        }),
    );
    $("#review-file").onchange = previewImport;
    $$("[data-review-page]").forEach(
      (b) =>
        (b.onclick = () => {
          state.reviewOffset = Math.max(
            0,
            state.reviewOffset +
              (b.dataset.reviewPage === "next"
                ? state.reviewLimit
                : -state.reviewLimit),
          );
          renderReviews().catch((e) => toast(e.message, true));
        }),
    );
  }
  function reviewRow(r) {
    return `<tr><td class="title-cell" data-label="Product"><h3>${esc(r.title)}</h3>${r.variant ? `<p>${esc(r.variant)}</p>` : ""}<p class="mono">${esc(r.asin || "ASIN not observed")}</p>${r.identity_quality === "provisional" ? "<p>Provisional identity</p>" : ""}</td><td data-label="Order"><span>${esc(r.order_date ? date(r.order_date) : "Date unavailable")}</span><p>${r.age_days != null ? `${esc(r.age_days)} days old` : "Age unavailable"}</p>${r.target_date ? `<p>${esc(r.target_kind === "personal" ? "Personal target" : "Observed deadline")}: ${esc(date(r.target_date))}${r.overdue ? " · past target" : ""}</p>` : ""}</td><td data-label="Amazon observed"><span>${esc(r.observed_status || "Unknown")}</span><p>${esc(sourceName(r.source))} · ${esc(relative(r.last_seen))}</p></td><td data-label="Local progress"><label class="screen-reader" for="progress-${r.id}">Local progress for ${esc(r.title)}</label><select id="progress-${r.id}" data-review-progress="${r.id}" data-previous="${esc(r.local_progress)}">${selectOptions(
      [
        ["not_started", "Not started"],
        ["in_progress", "In progress"],
        ["submitted", "Marked submitted"],
      ],
      r.local_progress,
    )}</select></td><td data-label="Links">${external(r.product_url, "Product")}<p>${external(r.review_url, "Review on Amazon")}</p></td></tr>`;
  }
  async function previewImport(event) {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      toast("Choose a metadata file smaller than 5 MB.", true);
      return;
    }
    try {
      const raw = JSON.parse(await file.text());
      state.importRecords = Array.isArray(raw)
        ? raw
        : raw.records || raw.reviews;
      if (!Array.isArray(state.importRecords))
        throw new Error("The JSON must contain an array of review records.");
      state.importPreview = await write("/reviews/import/preview", {
        records: state.importRecords,
      });
      const p = state.importPreview;
      $("#import-preview").innerHTML =
        `<div class="import-preview"><h3>Check the import</h3><dl><div><dt>Accepted</dt><dd>${esc(p.accepted)}</dd></div><div><dt>Existing identities</dt><dd>${esc(p.duplicates)}</dd></div><div><dt>Rejected</dt><dd>${esc(Array.isArray(p.rejected) ? p.rejected.length : p.rejected)}</dd></div></dl><p>Existing identities are updated; new identities become separate records. The source file is never modified.</p><p>Excluded fields: ${esc((p.ignored_fields || []).join(", ") || "None")}</p>${
          Array.isArray(p.rejected) && p.rejected.length
            ? `<p>${esc(
                p.rejected
                  .slice(0, 5)
                  .map((x) =>
                    typeof x === "string" ? x : x.error || JSON.stringify(x),
                  )
                  .join("; "),
              )}</p>`
            : ""
        }${
          (p.records || []).length
            ? `<div class="import-identities"><h3>Identity preview${p.records.length > 10 ? " · first 10 records" : ""}</h3>${p.records
                .slice(0, 10)
                .map(
                  (r) =>
                    `<div class="import-identity"><span>${esc(r.title)}<small>${esc(r.asin || "No ASIN")} · ${esc(r.order_date || "No order date")} · ${esc(r.variant || "No variant")}</small></span><span class="tag">${esc(pretty(r.action))}</span></div>`,
                )
                .join("")}</div>`
            : ""
        }<button class="button primary" data-action="commit-import" ${!p.accepted ? "disabled" : ""}>Import accepted metadata</button></div>`;
    } catch (e) {
      toast(e.message, true);
    }
  }

  async function renderSettings(epoch = state.viewEpoch) {
    state.settings = await api("/settings");
    if (epoch !== state.viewEpoch) return;
    const s = state.settings;
    $("#main").innerHTML =
      page(
        "Settings",
        "Control collection, delivery and the data this installation keeps.",
      ) +
      `<div class="settings-layout"><nav class="settings-nav" aria-label="Settings sections"><a href="#settings" data-scroll="collection-settings">Collection</a><a href="#settings" data-scroll="review-settings">Reviews</a><a href="#settings" data-scroll="notification-settings">Notifications</a><a href="#settings" data-scroll="privacy-settings">Privacy & history</a><a href="#settings" data-scroll="connection-settings">Amazon connection</a></nav><div><form id="settings-form"><section class="settings-section" id="collection-settings"><h2>Collection</h2><p>New jobs use saved settings. Pausing stops scheduled work; already-running work may finish. All browser jobs run one at a time.</p><div class="form-grid">${check("collection_enabled", "Enable scheduled collection", s.collection_enabled, "This is the master pause for queue polling and saved live searches.")}${check("rfy_enabled", "Collect Recommended for You", s.rfy_enabled)}${check("afa_enabled", "Collect Available for All", s.afa_enabled)}${field("collection_interval_minutes", "Queue polling interval (minutes)", s.collection_interval_minutes, "number", "Default: 15 minutes.", 'min="5" max="1440" required')}${field("page_budget", "Maximum pages per catalog job", s.page_budget, "number", "Runs reaching this budget report truncated coverage.", 'min="1" max="100" required')}${field("runtime_budget_seconds", "Maximum job duration (seconds)", s.runtime_budget_seconds, "number", "Bounds how long a catalog job occupies the browser.", 'min="15" max="1800" required')}<p class="small">Each interest tracker has its own saved query, search schedule, page budget and ranking rules. <a href="#trackers">Edit trackers</a>.</p></div></section>
    <section class="settings-section" id="review-settings"><h2>Review sync and reminders</h2><p>Sync reads Amazon’s Awaiting Review and Reviewed pages. Reminders and personal targets do not change Amazon’s requirements or submit reviews.</p><div class="form-grid">${check("review_sync_enabled", "Sync review status on a schedule", s.review_sync_enabled)}${field("review_sync_interval_minutes", "Sync interval (minutes)", s.review_sync_interval_minutes, "number", "", 'min="15" max="10080" required')}${field("review_page_budget", "Maximum review pages", s.review_page_budget, "number", "Partial scans preserve previously observed statuses.", 'min="1" max="100" required')}${check("review_reminders_enabled", "Send review reminders", s.review_reminders_enabled, "Uses your configured notification destination. No reminders are sent by default.")}${field("review_reminder_age_days", "Remind after order age (days)", s.review_reminder_age_days, "number", "", 'min="1" max="365" required')}${field("review_reminder_repeat_days", "Repeat reminder every (days)", s.review_reminder_repeat_days, "number", "", 'min="1" max="90" required')}${field("review_personal_target_days", "Personal target after order (days)", s.review_personal_target_days, "number", "Use 0 for no personal target. Observed deadlines remain distinct.", 'min="0" max="365" required')}</div></section>
    <section class="settings-section" id="notification-settings"><h2>Notifications</h2><p>Optional delivery sends product titles, matching details and Amazon links to the destination you choose. Webhooks receive JSON; ntfy receives push messages. Self-hosted ntfy on iOS may use an external wake-up relay.</p><div class="form-grid">${check("notifications_enabled", "Enable external notifications", s.notifications_enabled, "Enabling starts with a baseline of existing history, so old matches do not flood your destination.")}${selectField(
      "notification_adapter",
      "Delivery method",
      s.notification_adapter,
      [
        ["webhook", "Webhook (JSON)"],
        ["ntfy", "ntfy topic"],
      ],
    )}${field("notification_url", "Destination URL", "", "url", s.notification_url_configured ? "Destination configured. Leave blank to keep it; enter a URL to replace." : "For ntfy, include the topic path. HTTP is supported for a trusted private receiver.", 'placeholder="https://notify.example/topic"')}${check("clear_notification_url", "Remove saved destination", false, "Disable notifications before removing the destination.")}<label class="field">Destination secret<input name="notification_secret" type="password" autocomplete="new-password" placeholder="${s.notification_secret_configured ? "Secret configured — leave blank to keep" : "Optional bearer token"}"><small>Write-only. Leave blank to keep the stored secret.</small></label>${check("clear_notification_secret", "Remove stored secret", false, "Only select this when the destination no longer needs authentication.")}${selectField(
      "notification_cadence",
      "Delivery cadence",
      s.notification_cadence,
      [
        ["immediate", "Immediate"],
        ["digest", "Digest"],
      ],
    )}${field("digest_minutes", "Digest interval (minutes)", s.digest_minutes, "number", "Applies when Digest is selected.", 'min="5" max="1440" required')}${field("quiet_start", "Quiet hours start", s.quiet_start, "time", "Leave both quiet-hour fields empty for no quiet hours.")}${field("quiet_end", "Quiet hours end", s.quiet_end, "time", "Equal start and end also disables quiet hours.")}${field("timezone", "Timezone", s.timezone, "text", "An IANA name, such as America/New_York or Europe/London.", "required")}${check("notify_relists", "Alert again when a product returns", s.notify_relists, "Off by default. A relist requires a complete comparable scan to have recorded absence.")}</div><div class="form-actions"><button class="button" type="button" data-action="test-notification">Send test to saved destination</button><a href="#activity" class="small">View delivery status</a></div><p class="small muted" style="margin:12px 0 0">Save changes before testing. Tests contact only your explicitly configured destination.</p></section>
    <section class="settings-section" id="privacy-settings"><h2>Privacy and history</h2><p>There is no telemetry, third-party analytics or shared inventory service. Collection contacts Amazon. Image handling and optional notification delivery determine the additional network paths.</p><div class="form-grid">${selectField(
      "image_mode",
      "Product image handling",
      s.image_mode,
      [
        ["proxy", "Local proxy and cache"],
        ["direct", "Direct Amazon / CDN requests"],
        ["hidden", "Hide product images"],
      ],
      "Proxy keeps the phone’s image requests on this installation; the server still contacts Amazon’s image CDN. Direct mode exposes the viewing device to that CDN.",
    )}${field("retention_days", "History retention window (days)", s.retention_days, "number", "Saving does not delete history. Preview and explicitly apply cleanup below.", 'min="7" max="3650" required')}</div><div class="form-actions"><button class="button" type="button" data-action="export-data">Export application data</button><button class="button" type="button" data-action="preview-retention">Preview cleanup</button></div><div id="retention-preview"></div><details class="inline-disclosure" style="margin-top:20px"><summary>Reset and delete</summary><p class="small">Reset restores settings defaults. Delete removes product history, review records, jobs and delivery history; tracker rules and settings are preserved. Disconnect and forget Amazon separately to remove the private session.</p><div class="actions"><button type="button" class="button" data-action="reset-settings">Reset settings</button><button type="button" class="button danger" data-action="delete-data">Delete application data</button></div></details></section><div class="settings-actions"><p>Changes apply after saving.<br>Existing history is not replayed as new alerts.</p><button class="button primary" type="submit">Save settings</button></div><p class="form-error" role="alert"></p></form><section class="settings-section" id="connection-settings" style="margin-top:22px"><h2>Amazon connection</h2><p>Your session stays in the collector’s private storage. Reconnecting preserves history and local review progress.</p><div class="actions"><button class="button" data-action="connect">Open connection controls</button><button class="button danger" data-action="forget-session">Disconnect and forget session</button></div></section></div></div>`;
    $("#settings-form").onsubmit = async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const data = new FormData(form);
      const payload = {};
      for (const [key, value] of Object.entries(state.settings)) {
        if (
          !(key in s) ||
          key === "notification_secret" ||
          key === "notification_url" ||
          key.endsWith("_configured")
        )
          continue;
        if (typeof value === "boolean") payload[key] = data.has(key);
        else if (typeof value === "number")
          payload[key] = Number(data.get(key));
        else if (data.has(key)) payload[key] = data.get(key).trim();
      }
      if (data.has("clear_notification_url")) payload.notification_url = "";
      else if (data.get("notification_url"))
        payload.notification_url = data.get("notification_url").trim();
      if (data.has("clear_notification_secret"))
        payload.notification_secret = "";
      else if (data.get("notification_secret"))
        payload.notification_secret = data.get("notification_secret");
      const button = $('[type="submit"]', form);
      button.disabled = true;
      try {
        state.settings = await write("/settings", payload, "PATCH");
        toast("Settings saved. Newly queued jobs use these settings.");
        $(".form-error", form).textContent = "";
        $('input[name="notification_url"]', form).value = "";
        $('input[name="clear_notification_url"]', form).checked = false;
        $('input[name="notification_secret"]', form).value = "";
        $('input[name="clear_notification_secret"]', form).checked = false;
      } catch (error) {
        errorIn(form, error);
      } finally {
        button.disabled = false;
      }
    };
  }
  async function renderActivity(epoch = state.viewEpoch) {
    const [jobs, notifications, bootstrap] = await Promise.all([
      api("/jobs"),
      api("/notifications"),
      api("/bootstrap"),
    ]);
    if (epoch !== state.viewEpoch) return;
    state.jobs = items(jobs);
    const outbox = items(notifications);
    const dashboard = bootstrap.dashboard || bootstrap.health || {};
    $("#main").innerHTML =
      page(
        "Activity",
        "Collection coverage, queued work and notification delivery.",
        `<button class="button" data-action="retry-view">${icons.refresh}Refresh</button>`,
      ) +
      `<div class="activity-layout"><section><h2>Browser jobs</h2><p class="small muted">One job owns the browser at a time. Login takes priority; pending collection resumes afterward.</p><div class="activity-list">${state.jobs.map(jobRow).join("") || empty("No collection jobs yet", "Connect Amazon, then collect your queues or search Additional Items.")}</div></section><aside><section class="health-block"><h2>Installation health</h2><dl class="health-grid"><dt>Amazon</dt><dd>${esc(pretty(state.connection.state))}</dd><dt>Collection schedule</dt><dd>${state.settings.collection_enabled ? "Enabled" : "Paused"}</dd><dt>Queued jobs</dt><dd>${state.jobs.filter((j) => j.status === "queued").length}</dd><dt>Running jobs</dt><dd>${state.jobs.filter((j) => j.status === "running").length}</dd><dt>Last successful access</dt><dd>${esc(relative(state.connection.last_success))}</dd></dl><div class="form-actions"><button class="button compact" data-action="toggle-collection">${state.settings.collection_enabled ? "Pause schedules" : "Resume schedules"}</button><button class="button subtle compact" data-action="connect">Connection</button></div>${dashboard.message ? `<p>${esc(dashboard.message)}</p>` : ""}</section><section class="health-block"><h2>Notification delivery</h2><p>${state.settings.notifications_enabled ? "Delivery is enabled for your configured destination." : "Delivery is off. Enable and configure a destination in Settings."}</p><div class="actions"><button class="button compact" data-action="test-notification">Send test</button><a class="small" href="#settings">Settings</a></div><div class="activity-list" style="margin-top:16px">${
        outbox
          .slice(0, 12)
          .map(
            (n) =>
              `<article class="activity-row"><h3>${esc(n.kind === "test" ? "Destination test" : n.kind === "review_reminder" ? "Review reminder" : n.title || "Product match")}</h3><p>${esc(n.error || n.last_error || `Attempts: ${n.attempts || 0}`)}</p><div class="activity-end">${statusLabel(n.status)}<span class="mono">${esc(relative(n.sent_at || n.created_at))}</span></div></article>`,
          )
          .join("") ||
        '<p class="small muted" style="padding-top:14px">No delivery attempts recorded.</p>'
      }</div></section></aside></div>`;
  }
  function jobRow(j) {
    const terminal = [
      "complete",
      "partial",
      "truncated",
      "failed",
      "needs_login",
      "cancelled",
    ].includes(j.status);
    const result = j.result || {};
    return `<article class="activity-row"><h3>${esc(j.kind === "search" ? `Search: ${j.query}` : j.kind === "reviews" ? "Review status sync" : j.kind === "login" ? "Amazon login" : sourceName(j.kind))}</h3><p>${esc(j.error || progressText(j.progress) || `${result.pages ?? "?"} pages · ${result.observed_count ?? "?"} observations`)}</p><p class="mono">${esc(date(j.created_at, { hour: "numeric", minute: "2-digit" }))} · ${esc(j.source || "manual")}</p><div class="activity-end">${statusLabel(j.status)}${j.kind === "search" && ["complete", "partial", "truncated"].includes(j.status) ? `<button class="button subtle compact" data-view-job="${j.id}">View results</button>` : ""}${!terminal ? `<button class="button subtle compact" data-cancel-job="${j.id}">Cancel</button>` : ["failed", "partial", "truncated"].includes(j.status) ? `<button class="button subtle compact" data-retry-job="${j.id}">Run again</button>` : ""}</div></article>`;
  }
  async function download(path, name) {
    const response = await fetch("/api" + path, { credentials: "same-origin" });
    if (!response.ok)
      throw new Error("Export could not be created. Try again.");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Export downloaded. Store it privately.");
  }
  async function collect(button) {
    await busy(button, async () => {
      const kinds = [
        ...(state.settings.rfy_enabled ? ["rfy"] : []),
        ...(state.settings.afa_enabled ? ["afa"] : []),
      ];
      if (!kinds.length)
        throw new Error(
          "Enable at least one queue in Settings before collecting.",
        );
      for (const kind of kinds) await write("/jobs", { kind });
      toast("Collection queued. Follow progress in Activity.");
    });
  }
  async function poll() {
    if (pollBusy || document.hidden) return;
    pollBusy = true;
    try {
      const connection = await api("/connection");
      updateConnection(connection);
      if (state.login) {
        const login = await api("/connection/login/" + state.login.id);
        const previous = state.login.state;
        state.login = { ...state.login, ...login };
        if (login.state !== previous) {
          renderConnection();
          if (["connected", "complete"].includes(login.state)) {
            state.login = null;
            $("#connection-panel").hidden = true;
            toast("Amazon Vine access verified. Collection can resume.");
            updateConnection(await api("/connection"));
          } else if (
            ["cancelled", "expired", "failed", "timeout"].includes(login.state)
          ) {
            state.login = null;
            renderConnection();
            toast(
              login.message ||
                "Login ended. Open the login browser to try again.",
              login.state !== "cancelled",
            );
          }
        }
      }
      if (state.liveJob) {
        const jobs = items(await api("/jobs"));
        const job = jobs.find((j) => j.id === state.liveJob.id);
        if (job) {
          const changed = state.liveJob.status !== job.status;
          state.liveJob = job;
          renderLiveJob();
          if (
            changed &&
            ["complete", "partial", "truncated"].includes(job.status) &&
            state.route === "discover"
          )
            await loadProducts();
        }
      }
    } catch {
      /* Keep the last known view usable; foreground actions surface errors. */
    } finally {
      pollBusy = false;
    }
  }
  document.addEventListener("click", async (event) => {
    const button = event.target.closest(
      "[data-action],[data-edit-tracker],[data-toggle-tracker],[data-delete-tracker],[data-cancel-job],[data-retry-job],[data-view-job],[data-scroll]",
    );
    if (!button) return;
    const action = button.dataset.action;
    try {
      if (button.dataset.scroll) {
        event.preventDefault();
        document
          .getElementById(button.dataset.scroll)
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if (button.dataset.editTracker) {
        const t = state.trackers.find(
          (t) => String(t.id) === button.dataset.editTracker,
        );
        renderTrackerEditor(t);
        $("#tracker-editor").scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
        return;
      }
      if (button.dataset.toggleTracker) {
        const t = state.trackers.find(
          (t) => String(t.id) === button.dataset.toggleTracker,
        );
        await write("/trackers/" + t.id, { enabled: !t.enabled }, "PATCH");
        toast(t.enabled ? "Tracker paused." : "Tracker resumed.");
        await renderTrackers();
        return;
      }
      if (button.dataset.deleteTracker) {
        if (
          await confirmed(
            "Delete this tracker?",
            "Its rules and schedule will be removed. Observed products remain in history.",
          )
        ) {
          await api("/trackers/" + button.dataset.deleteTracker, {
            method: "DELETE",
          });
          toast("Tracker deleted.");
          await renderTrackers();
        }
        return;
      }
      if (button.dataset.cancelJob) {
        await write("/jobs/" + button.dataset.cancelJob + "/cancel");
        toast("Cancellation requested.");
        if (state.route === "activity") await renderActivity();
        else await poll();
        return;
      }
      if (button.dataset.viewJob) {
        const j = state.jobs.find(
          (j) => String(j.id) === button.dataset.viewJob,
        );
        state.liveJob = j;
        state.mode = "live";
        state.query = j.query;
        state.offset = 0;
        location.hash = "discover";
        return;
      }
      if (button.dataset.retryJob) {
        const j = state.jobs.find(
          (j) => String(j.id) === button.dataset.retryJob,
        );
        await write("/jobs", {
          kind: j.kind,
          query: j.query,
          tracker_id: j.tracker_id,
        });
        toast("A new collection job is queued.");
        await renderActivity();
        return;
      }
      switch (action) {
        case "connect":
          $("#connection-panel").hidden = false;
          renderConnection();
          $("#connection-panel").scrollIntoView({ behavior: "smooth" });
          break;
        case "start-login":
          await startLogin(button);
          break;
        case "close-connection":
          $("#connection-panel").hidden = true;
          break;
        case "cancel-login":
          if (state.login) {
            await write("/connection/login/" + state.login.id + "/cancel");
            state.login = null;
            updateConnection(await api("/connection"));
            renderConnection();
            toast("Login cancelled.");
          }
          break;
        case "disconnect":
          await write("/connection/disconnect", { forget: false });
          toast("Disconnect queued. Saved history remains available.");
          updateConnection(await api("/connection"));
          break;
        case "forget-session":
          if (
            await confirmed(
              "Forget the Amazon session?",
              "The saved login will be removed from the collector. You will need to sign in again. Your product and review history stays here.",
            )
          ) {
            await write("/connection/disconnect", { forget: true });
            toast("Session removal queued.");
            updateConnection(await api("/connection"));
          }
          break;
        case "retry-view":
          await navigate();
          break;
        case "retry-startup":
          await busy(button, init);
          break;
        case "collect":
          await collect(button);
          break;
        case "toggle-filters": {
          const open = $("#filters").classList.toggle("open");
          button.setAttribute("aria-expanded", String(open));
          break;
        }
        case "clear-filters":
          state.source = "";
          state.tracker = "";
          state.freshness = "";
          state.minScore = "";
          state.offset = 0;
          await renderDiscover();
          break;
        case "dismiss-live":
          state.liveJob = null;
          $("#live-job").innerHTML = "";
          break;
        case "new-tracker":
          renderTrackerEditor();
          $("#tracker-editor").scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
          $('input[name="name"]', $("#tracker-editor")).focus();
          break;
        case "sync-reviews":
          await busy(button, async () => {
            await write("/jobs", { kind: "reviews" });
            toast("Review sync queued. Follow progress in Activity.");
          });
          break;
        case "toggle-import":
          $("#review-import").hidden = !$("#review-import").hidden;
          break;
        case "commit-import":
          await busy(button, async () => {
            const result = await write("/reviews/import", {
              records: state.importRecords,
              preview_hash: state.importPreview.preview_hash,
            });
            toast(
              `${result.imported || 0} records imported, ${result.updated || 0} updated.`,
            );
            state.importRecords = null;
            state.importPreview = null;
            await renderReviews();
          });
          break;
        case "export-reviews":
          await download("/reviews/export", "vine-search-review-metadata.json");
          break;
        case "export-data":
          await download("/export", "vine-search-data.json");
          break;
        case "test-notification":
          await busy(button, async () => {
            await write("/notifications/test");
            toast(
              "Test queued for the saved destination. Check delivery in Activity.",
            );
          });
          break;
        case "toggle-collection":
          state.settings = await write(
            "/settings",
            { collection_enabled: !state.settings.collection_enabled },
            "PATCH",
          );
          toast(
            state.settings.collection_enabled
              ? "Schedules resumed."
              : "Schedules paused.",
          );
          await renderActivity();
          break;
        case "preview-retention": {
          const days = Number($('[name="retention_days"]').value);
          const preview = await write("/retention/preview", { days });
          $("#retention-preview").innerHTML =
            `<div class="import-preview"><h3>Cleanup preview</h3><p>Window: ${days} days. ${esc(
              Object.entries(preview)
                .filter(([k, v]) => typeof v !== "object")
                .map(([k, v]) => `${pretty(k)}: ${v}`)
                .join(" · "),
            )}</p><p>Cleanup only runs after explicit confirmation. Export data first if you need a permanent record.</p><button type="button" class="button danger" data-action="apply-retention" data-days="${days}">Apply this cleanup</button></div>`;
          break;
        }
        case "apply-retention":
          if (
            await confirmed(
              "Delete history outside this window?",
              "This cleanup permanently removes eligible historical records. The displayed retention window will be used.",
              "DELETE HISTORY",
            )
          ) {
            const result = await write("/retention/apply", {
              days: Number(button.dataset.days),
              confirm: "DELETE HISTORY",
            });
            toast("History cleanup completed.");
            $("#retention-preview").textContent = Object.entries(result)
              .map(([k, v]) => `${pretty(k)}: ${v}`)
              .join(" · ");
          }
          break;
        case "reset-settings":
          if (
            await confirmed(
              "Reset settings to defaults?",
              "Schedules return to their defaults and notifications are disabled. Existing history and tracker rules are preserved.",
            )
          ) {
            state.settings = await write("/settings/reset");
            toast("Default settings restored.");
            await renderSettings();
          }
          break;
        case "delete-data":
          if (
            await confirmed(
              "Delete application data?",
              "Product history, review records, local progress, jobs and delivery history will be removed. Tracker rules and settings are preserved. Export first if you need a copy. The private Amazon session is not removed.",
              "DELETE ALL DATA",
            )
          ) {
            await write("/data/delete", { confirm: "DELETE ALL DATA" });
            state.trackers = [];
            state.liveJob = null;
            toast("Application data deleted.");
            await navigate();
          }
          break;
      }
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("#connection-toggle").onclick = () => {
    $("#connection-panel").hidden = !$("#connection-panel").hidden;
    if (!$("#connection-panel").hidden) renderConnection();
  };
  window.addEventListener("hashchange", navigate);
  async function init() {
    clearInterval(pollTimer);
    try {
      const data = await api("/bootstrap");
      state.csrf = data.csrf_token || data.csrf || "";
      state.demo = !!data.demo;
      if (state.demo && !$(".demo-banner")) {
        const banner = document.createElement("div");
        banner.className = "demo-banner";
        banner.textContent =
          "Demonstration installation · synthetic products, images and review records";
        $(".app-frame").prepend(banner);
      }
      state.settings = data.settings || (await api("/settings"));
      const connection = data.connection || (await api("/connection"));
      state.login =
        connection.login &&
        ["waiting", "starting", "ready", "challenge"].includes(
          connection.login.state,
        )
          ? connection.login
          : null;
      updateConnection(connection);
      const jobs = items(await api("/jobs"));
      state.jobs = jobs;
      state.liveJob =
        jobs.find(
          (j) =>
            j.kind === "search" && ["queued", "running"].includes(j.status),
        ) || null;
      if (state.liveJob) {
        state.query = state.liveJob.query;
        state.mode = "live";
      }
      await navigate();
      pollTimer = setInterval(poll, 5000);
    } catch (error) {
      $("#main").setAttribute("aria-busy", "false");
      $("#main").innerHTML = empty(
        "VineSearch could not connect",
        error.message,
        '<button class="button" data-action="retry-startup">Try again</button>',
      );
    }
  }
  init();
})();
