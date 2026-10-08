// Screenshot Findr: browser demo.
// The data in demo/data.json was produced by the real app's pipeline (scripts/build_demo.py).
// Search, tags, duplicates and the viewer are re-implemented here so the demo needs no server.
"use strict";

const TESS = {
  script: "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js",
  workerPath: "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/worker.min.js",
  corePath: "https://cdn.jsdelivr.net/npm/tesseract.js-core@5.1.1",
  langPath: "https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng@1.0.0/4.0.0_best_int",
};
const FORGOTTEN_AFTER_DAYS = 3;

// The app ranks "related" results with a local embedding model. The demo approximates it
// with groups of words that mean roughly the same thing.
const CONCEPTS = [
  ["shoe", "shoes", "sneaker", "sneakers", "trainers", "footwear", "trailrunner", "running shoes"],
  ["trip", "travel", "flight", "flights", "plane", "holiday", "vacation", "boarding", "airline", "train", "pnr", "hotel", "reservation", "check-in", "journey", "ticket"],
  ["food", "dinner", "lunch", "eat", "hungry", "meal", "pizza", "pasta", "recipe", "garlic", "spaghetti", "coffee", "cafe", "order summary"],
  ["money", "spent", "spend", "bill", "bills", "paid", "payment", "invoice", "amount", "budget", "rent", "debited", "expense", "total"],
  ["bug", "crash", "crashed", "broken", "programming", "code", "traceback", "error", "build failed", "typeerror", "valueerror", "npm", "python"],
  ["login", "secret", "otp", "verification code", "password", "wifi", "wi-fi", "network"],
  ["song", "songs", "music", "playlist", "playing", "listen"],
  ["exercise", "workout", "gym", "run", "running", "pace", "calories", "fitness"],
  ["doctor", "hospital", "health", "clinic", "dr."],
  ["weather", "rain", "cloudy", "forecast", "temperature"],
  ["gift", "gifts", "present", "birthday", "mom", "ideas"],
  ["shopping", "buy", "wishlist", "cart", "keyboard", "price", "deal", "store", "shop"],
  ["work", "meeting", "sprint", "goals", "notes", "agenda", "review", "launch"],
];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString();
const WORD = /[\p{L}\p{N}_]+/gu;
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
  set(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} },
};

const S = { all: [], query: "", tag: null, view: "library", list: [], dupGroups: [], rules: [], opened: new Set(), reading: null };
try { JSON.parse(store.get("sf-demo-opened", "[]")).forEach((id) => S.opened.add(id)); } catch (e) {}

/* ---------- helpers ---------- */
let toastTimer;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hide");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hide"), 2600);
}
const dayStart = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
const daysAgo = (ts) => Math.round((dayStart(new Date()) - dayStart(new Date(ts))) / 86400000);
function when(ts) {
  const d = new Date(ts), n = daysAgo(ts);
  if (n <= 0) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (n === 1) return "yesterday";
  if (n < 7) return d.toLocaleDateString([], { weekday: "short" }).toLowerCase();
  return d.toLocaleDateString([], { day: "2-digit", month: "short", year: d.getFullYear() === new Date().getFullYear() ? undefined : "2-digit" }).toLowerCase();
}
function dateSection(ts) {
  const d = new Date(ts), n = daysAgo(ts), now = new Date();
  if (n <= 0) return "Today";
  if (n === 1) return "Yesterday";
  if (n < 7) return "Earlier this week";
  if (d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()) return "Earlier this month";
  return d.toLocaleDateString([], { month: "long", year: "numeric" });
}
const reEsc = (w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
function termRegex(words) {
  return new RegExp(`(?<![\\p{L}\\p{N}_])(?:${words.map(reEsc).join("|")})[\\p{L}\\p{N}_]*`, "giu");
}
function highlight(text, words) {
  if (!words.length) return esc(text);
  let out = "", last = 0;
  for (const m of text.matchAll(termRegex(words))) { out += esc(text.slice(last, m.index)) + "<mark>" + esc(m[0]) + "</mark>"; last = m.index + m[0].length; }
  return out + esc(text.slice(last));
}

/* ---------- same rules as the app (tags.py / web.py) ---------- */
function classify(text, filename, w, h) {
  const hay = `${filename}\n${text}`;
  const scores = {};
  for (const { tag, threshold, rules } of S.rules) {
    let score = 0;
    for (const [rx, weight, cap] of rules) score += weight * Math.min((hay.match(rx) || []).length, cap);
    if (score >= threshold) scores[tag] = score;
  }
  if (w && h && h > w * 1.6 && !scores.phone) scores.phone = 2;
  return Object.keys(scores).sort((a, b) => scores[b] - scores[a]);
}
function titleOf(text, filename) {
  for (let line of text.split("\n").slice(0, 12)) {
    line = line.split(/\s+/).join(" ").trim();
    const words = (line.match(/[\p{L}]{2,}/gu) || []).length;
    const letters = (line.match(/\p{L}/gu) || []).length;
    if (words >= 2 && letters >= 8) return line.slice(0, 90);
  }
  return filename.replace(/\.[^.]+$/, "");
}
function compileRules(rules) {
  // Python's re.IGNORECASE | re.MULTILINE  ->  JS "gim" (patterns are plain enough to share)
  return rules.map((r) => ({ tag: r.tag, threshold: r.threshold, rules: r.rules.map(([src, w, cap]) => [new RegExp(src, "gim"), w, cap]) }));
}

/* ---------- search ---------- */
function prepare(item) {
  item.lower = `${item.filename}\n${item.text}`.toLowerCase();
  // Also index hyphenated words joined up, so "wifi" finds "Wi-Fi".
  const joined = item.lower.replace(/(\p{L})-(?=\p{L})/gu, "$1");
  item.tokens = [...new Set([...(item.lower.match(WORD) || []), ...(joined.match(WORD) || [])])];
}
function search(query, tag) {
  const words = (query.toLowerCase().match(WORD) || []);
  let pool = tag ? S.all.filter((s) => s.tags.includes(tag)) : S.all.slice();
  if (!words.length) return { words, matches: pool.sort((a, b) => b.ts - a.ts), related: [] };
  const matches = [];
  for (const s of pool) {
    let score = 0, ok = true;
    for (const w of words) {
      const hits = s.tokens.filter((t) => t.startsWith(w)).length;
      if (!hits) { ok = false; break; }
      score += hits + (s.title.toLowerCase().includes(w) ? 2 : 0);
    }
    if (ok) matches.push({ s, score });
  }
  matches.sort((a, b) => b.score - a.score || b.s.ts - a.s.ts);
  // "Related": concepts the query touches, then screenshots that mention any word of those concepts.
  const q = query.toLowerCase();
  const concepts = CONCEPTS.filter((c) => c.some((term) => words.some((w) => term.startsWith(w) && w.length >= 3) || q.includes(term)));
  const exact = new Set(matches.map((m) => m.s.id));
  const related = concepts.length ? pool.filter((s) => !exact.has(s.id) && concepts.some((c) => c.some((term) => termRegex([term]).test(s.lower)))) : [];
  return { words, matches: matches.map((m) => m.s), related };
}
function snippet(text, words) {
  const flat = text.replace(/\s+/g, " ").trim();
  if (!words.length) return "";
  const m = termRegex(words).exec(flat);
  const start = m ? Math.max(0, m.index - 40) : 0;
  const piece = (start > 0 ? "… " : "") + flat.slice(start, start + 150) + (flat.length > start + 150 ? " …" : "");
  return highlight(piece, words);
}

/* ---------- rendering ---------- */
function cell(s, list, index, opts = {}) {
  const el = document.createElement("div");
  el.className = "shot";
  el.tabIndex = 0;
  el.setAttribute("role", "button");
  el.setAttribute("aria-label", s.title);
  const corner = opts.keep ? '<span class="corner keep">keep</span>' : opts.related ? '<span class="corner">related</span>' : s.yours ? '<span class="corner yours">yours</span>' : "";
  const snip = opts.words?.length && !opts.related ? snippet(s.text, opts.words) : "";
  el.innerHTML = `
    <div class="frame">${corner}<img loading="lazy" decoding="async" alt="" src="${esc(s.thumb)}"></div>
    <div class="cap"><span class="name" title="${esc(s.title)}">${esc(s.title)}</span><span class="when">${when(s.ts)}</span></div>
    ${snip ? `<div class="snip">${snip}</div>` : s.tags.length ? `<div class="tagline">${s.tags.map(esc).join(" · ")}</div>` : ""}`;
  const img = el.querySelector("img");
  const ok = () => img.classList.add("ok");
  if (img.complete) ok(); else { img.addEventListener("load", ok); img.addEventListener("error", ok); }
  el.addEventListener("click", () => openViewer(list, index, opts));
  el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openViewer(list, index, opts); } });
  return el;
}
function section(title, items, opts = {}, note = "") {
  const sec = document.createElement("section");
  sec.className = "sec";
  sec.innerHTML = `<div class="rule">${esc(title)}${note ? ` <span class="note">${esc(note)}</span>` : ""}<span class="count">${fmt(items.length)}</span></div><div class="grid"></div>`;
  const grid = sec.querySelector(".grid");
  items.forEach((s, i) => grid.appendChild(cell(s, items, i, opts)));
  return sec;
}

function renderLibrary() {
  const { words, matches, related } = search(S.query, S.tag);
  const box = $("results");
  box.innerHTML = "";
  if (S.query) {
    if (matches.length) box.appendChild(section("Matches", matches, { words }, "contains the words"));
    if (related.length) box.appendChild(section("Related", related, { related: true }, "similar meaning, different words"));
    if (!matches.length && !related.length) box.innerHTML = '<div class="empty"><h3>No matches</h3><div>Try fewer words, or one of the suggestions above.</div></div>';
  } else {
    const forgotten = S.tag ? [] : forgottenList().slice(0, 5);
    if (forgotten.length) {
      const sec = section("Never opened", forgotten, {}, "a few you saved and didn't come back to");
      sec.querySelector(".count").textContent = fmt(forgottenList().length);
      const more = document.createElement("button");
      more.className = "more"; more.textContent = "see all →"; more.onclick = () => showView("forgotten");
      sec.querySelector(".rule").appendChild(more);
      box.appendChild(sec);
    }
    const groups = new Map();
    matches.forEach((s) => { const k = dateSection(s.ts); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(s); });
    groups.forEach((items, k) => box.appendChild(section(k, items)));
    if (!matches.length) box.innerHTML = '<div class="empty"><h3>Nothing with this tag</h3></div>';
  }
  S.list = matches.concat(related);
  renderStatus(matches.length, related.length);
}
function forgottenList() {
  return S.all.filter((s) => !S.opened.has(s.id) && daysAgo(s.ts) >= FORGOTTEN_AFTER_DAYS).sort((a, b) => a.ts - b.ts);
}
function renderStatus(nMatch, nRelated) {
  const parts = [];
  if (S.query) parts.push(`<span><b>${fmt(nMatch)}</b> matching “${esc(S.query)}”${nRelated ? ` · ${nRelated} related` : ""}</span>`);
  else {
    const week = S.all.filter((s) => daysAgo(s.ts) < 7).length;
    parts.push(`<span><b>${fmt(S.all.length)}</b> screenshots</span>`, `<span><b>${fmt(week)}</b> this week</span>`);
    const f = forgottenList().length, d = dupExtras();
    if (f) parts.push(`<a data-goto="forgotten"><b>${fmt(f)}</b> never opened</a>`);
    if (d) parts.push(`<a data-goto="dupes"><b>${fmt(d)}</b> duplicates</a>`);
  }
  if (S.reading) parts.push(`<span class="live">${esc(S.reading)}</span>`);
  $("status").innerHTML = parts.join("");
  $("status").querySelectorAll("[data-goto]").forEach((a) => a.onclick = () => showView(a.dataset.goto));
  $("nav-forgotten").textContent = forgottenList().length || "";
  $("nav-dupes").textContent = dupExtras() || "";
}
function renderFilters() {
  const counts = {};
  S.all.forEach((s) => s.tags.forEach((t) => counts[t] = (counts[t] || 0) + 1));
  const box = $("filters");
  box.innerHTML = "";
  [[null, S.all.length], ...Object.entries(counts).sort((a, b) => b[1] - a[1])].forEach(([tag, n]) => {
    const b = document.createElement("button");
    b.className = "filter" + (tag === S.tag ? " on" : "");
    b.innerHTML = `${tag ? esc(tag) : "all"}<span class="n">${fmt(n)}</span>`;
    b.onclick = () => { S.tag = S.tag === tag ? null : tag; renderFilters(); renderLibrary(); };
    box.appendChild(b);
  });
}
function renderForgotten() {
  const list = forgottenList();
  const box = $("forgotten");
  box.innerHTML = "";
  if (!list.length) { box.innerHTML = '<div class="empty"><h3>Nothing here</h3><div>You\'ve opened every older screenshot.</div></div>'; return; }
  box.appendChild(section("Oldest first", list));
}
function dupGroups() {
  const byId = new Map(S.all.map((s) => [s.id, s]));
  return S.dupGroups.map((g) => g.map((id) => byId.get(id)).filter(Boolean)).filter((g) => g.length > 1)
    .map((g) => g.sort((a, b) => b.width * b.height - a.width * a.height || a.ts - b.ts));
}
const dupExtras = () => dupGroups().reduce((n, g) => n + g.length - 1, 0);
function renderDupes() {
  const groups = dupGroups();
  $("dupes-sub").textContent = groups.length
    ? `${groups.length} group${groups.length > 1 ? "s" : ""} of screenshots that look the same (perceptual hash + matching text). The first in each group is kept.`
    : "No look-alike screenshots left.";
  const box = $("dupes");
  box.innerHTML = "";
  groups.forEach((g, gi) => {
    const sec = document.createElement("section");
    sec.className = "group";
    sec.innerHTML = `<div class="rule">Group ${gi + 1}<span class="note">${g.length} copies</span><span class="count"></span><button class="more">delete ${g.length - 1} →</button></div><div class="grid"></div>`;
    sec.querySelector(".more").onclick = () => removeShots(g.slice(1).map((s) => s.id));
    const grid = sec.querySelector(".grid");
    g.forEach((s, i) => grid.appendChild(cell(s, g, i, { keep: i === 0 })));
    box.appendChild(sec);
  });
}
function removeShots(ids) {
  const set = new Set(ids);
  S.all = S.all.filter((s) => !set.has(s.id));
  toast(`removed ${ids.length} from the demo. In the app they go to the Recycle Bin.`);
  refresh();
}
function refresh() {
  renderFilters();
  if (S.view === "library") renderLibrary(); else renderStatus(0, 0);
  if (S.view === "forgotten") renderForgotten();
  if (S.view === "dupes") renderDupes();
}
function showView(name) {
  S.view = name;
  document.querySelectorAll("nav.views button").forEach((b) => b.classList.toggle("on", b.dataset.view === name));
  ["library", "forgotten", "dupes"].forEach((v) => $(`view-${v}`).hidden = v !== name);
  $("app").scrollTop = 0;
  refresh();
}

/* ---------- viewer ---------- */
const V = { list: [], idx: 0, opts: {} };
function openViewer(list, idx, opts = {}) { V.list = list; V.idx = idx; V.opts = opts; $("viewer").hidden = false; document.body.classList.add("locked"); show(); }
function closeViewer() {
  $("viewer").hidden = true;
  document.body.classList.remove("locked");
  $("stage").classList.remove("zoom");
  refresh();
}
function show() {
  const s = V.list[V.idx];
  if (!s) return closeViewer();
  S.opened.add(s.id);
  if (!s.yours) store.set("sf-demo-opened", JSON.stringify([...S.opened].filter((x) => typeof x === "number")));
  $("stage").classList.remove("zoom");
  $("v-img").src = s.full;
  $("v-name").textContent = s.title;
  $("v-counter").textContent = `${V.idx + 1} / ${V.list.length}`;
  const words = (S.query.toLowerCase().match(WORD) || []);
  const rows = [
    ["file", s.filename],
    ["taken", new Date(s.ts).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })],
    ["size", `${s.width} × ${s.height}`],
    ["tags", s.tags.length ? s.tags.join(", ") : "–"],
  ];
  if (S.query && !words.every((w) => s.tokens.some((t) => t.startsWith(w)))) rows.push(["match", "related by meaning"]);
  $("v-meta").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
  $("v-text").innerHTML = s.text ? highlight(s.text, words) : '<span style="color:#6c6961">no text found</span>';
  $("v-prev").disabled = V.idx === 0;
  $("v-next").disabled = V.idx >= V.list.length - 1;
  [V.idx - 1, V.idx + 1].forEach((i) => { if (V.list[i]) new Image().src = V.list[i].full; });
}
function step(d) { const n = V.idx + d; if (n >= 0 && n < V.list.length) { V.idx = n; show(); } }
$("v-prev").onclick = () => step(-1);
$("v-next").onclick = () => step(1);
$("v-close").onclick = closeViewer;
$("stage").addEventListener("click", (e) => { if (e.target === $("stage")) closeViewer(); });
$("v-img").onclick = () => $("stage").classList.toggle("zoom");
$("v-open").onclick = () => window.open(V.list[V.idx].full, "_blank", "noopener");
$("v-copy").onclick = copyCurrent;
$("v-delete").onclick = () => { const s = V.list[V.idx]; closeViewer(); removeShots([s.id]); };
async function copyCurrent() {
  const s = V.list[V.idx];
  if (!s.text) return toast("no text in this screenshot");
  try { await navigator.clipboard.writeText(s.text); toast("text copied"); } catch (e) { toast("couldn't copy here"); }
}
document.addEventListener("keydown", (e) => {
  if (!$("viewer").hidden) {
    if (e.key === "Escape") closeViewer();
    else if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
    else if (e.key.toLowerCase() === "c" && !e.ctrlKey && !e.metaKey) copyCurrent();
    else return;
    e.preventDefault();
  } else if (e.key === "Escape" && document.activeElement === $("q") && $("q").value) {
    setQuery("");
  }
});

/* ---------- search box ---------- */
let searchTimer;
function setQuery(v) {
  $("q").value = v;
  $("clear").hidden = !v;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    S.query = v.trim();
    if (S.view !== "library") showView("library"); else renderLibrary();
    $("app").scrollTop = 0;
  }, 120);
}
$("q").addEventListener("input", () => setQuery($("q").value));
$("clear").onclick = () => { setQuery(""); $("q").focus(); };
document.querySelectorAll("[data-q]").forEach((b) => b.onclick = () => {
  $("app").scrollIntoView({ behavior: "smooth", block: "center" });
  setQuery(b.dataset.q);
});
document.querySelectorAll("nav.views button").forEach((b) => b.onclick = () => showView(b.dataset.view));

/* ---------- add your own: OCR in the browser ---------- */
let worker = null;
function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src; s.onload = resolve; s.onerror = () => reject(new Error("couldn't load " + src));
    document.head.appendChild(s);
  });
}
async function getWorker() {
  if (worker) return worker;
  setReading("loading the text reader (about 5 MB, once)…");
  if (!window.Tesseract) await loadScript(TESS.script);
  worker = await Tesseract.createWorker("eng", 1, { workerPath: TESS.workerPath, corePath: TESS.corePath, langPath: TESS.langPath });
  return worker;
}
function setReading(msg) { S.reading = msg; renderStatus(0, 0); if (S.view === "library") renderLibrary(); }
function imageSize(url) {
  return new Promise((resolve) => { const i = new Image(); i.onload = () => resolve([i.naturalWidth, i.naturalHeight]); i.onerror = () => resolve([0, 0]); i.src = url; });
}
let nextId = 100000;
async function addFiles(files) {
  files = [...files].filter((f) => f.type.startsWith("image/"));
  if (!files.length) return;
  showView("library");
  try {
    const w = await getWorker();
    for (let i = 0; i < files.length; i++) {
      setReading(`reading ${i + 1}/${files.length} in your browser…`);
      const f = files[i];
      const url = URL.createObjectURL(f);
      const [width, height] = await imageSize(url);
      const { data } = await w.recognize(f);
      const text = (data.text || "").trim();
      const s = { id: nextId++, filename: f.name, text, width, height, ts: f.lastModified || Date.now(), thumb: url, full: url, yours: true };
      s.title = titleOf(text, f.name);
      s.tags = classify(text, f.name, width, height);
      prepare(s);
      S.all.push(s);
      refresh();
    }
    toast(`read ${files.length} screenshot${files.length > 1 ? "s" : ""}. Nothing was uploaded.`);
  } catch (e) {
    toast("couldn't load the text reader. Check your connection and try again.");
    console.error(e);
  } finally {
    S.reading = null;
    refresh();
  }
}
$("add").onclick = () => $("file").click();
$("file").onchange = (e) => { addFiles(e.target.files); e.target.value = ""; };
const app = $("app");
["dragenter", "dragover"].forEach((ev) => app.addEventListener(ev, (e) => { e.preventDefault(); app.classList.add("dragging"); }));
["dragleave", "drop"].forEach((ev) => app.addEventListener(ev, (e) => { e.preventDefault(); if (ev === "drop" || e.target === app) app.classList.remove("dragging"); }));
app.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
window.addEventListener("paste", (e) => { const files = [...(e.clipboardData?.files || [])]; if (files.length) addFiles(files); });

/* ---------- theme ---------- */
const THEME_ICONS = {
  auto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17a8.5 8.5 0 0 0 0-17z" fill="currentColor"/></svg>',
  dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M20 13.5A8 8 0 1 1 10.5 4a6.5 6.5 0 0 0 9.5 9.5z"/></svg>',
  light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></svg>',
};
let theme = store.get("sf-theme", "auto") || "auto";
function applyTheme() {
  if (theme === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = theme;
  $("theme").innerHTML = THEME_ICONS[theme];
  $("theme").title = `Theme: ${theme}`;
}
applyTheme();
$("theme").onclick = () => { theme = { auto: "dark", dark: "light", light: "auto" }[theme]; store.set("sf-theme", theme === "auto" ? null : theme); applyTheme(); };

/* ---------- start ---------- */
fetch("demo/data.json").then((r) => r.json()).then((data) => {
  const now = Date.now();
  S.rules = compileRules(data.tag_rules);
  S.dupGroups = data.duplicates;
  S.all = data.items.map((it) => {
    const s = { ...it, ts: now - it.age_days * 86400000, thumb: `demo/thumb/${it.id}.jpg`, full: `demo/img/${it.id}.jpg` };
    prepare(s);
    return s;
  });
  refresh();
}).catch(() => { $("results").innerHTML = '<div class="empty"><h3>Couldn\'t load the demo data</h3><div>Open this page through a web server (not file://).</div></div>'; });
