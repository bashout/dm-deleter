"""Embedded viewer UI (HTML/CSS/JS), served from memory with no external files."""

INDEX_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Archive Viewer</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header id="topbar">
    <select id="archive-select" title="Choose archive"></select>
    <div id="chat-id">
      <span id="chat-name">...</span>
      <span id="chat-sub"></span>
    </div>
    <nav id="tabs">
      <button data-tab="chat" class="active">Chat</button>
      <button data-tab="gallery">Gallery</button>
      <button data-tab="stats">Stats</button>
    </nav>
    <div id="chat-tools">
      <input type="search" id="search" placeholder="Search messages..." autocomplete="off">
    </div>
  </header>

  <div id="filterbar">
    <label class="fb-item">From <input type="date" id="date-from"></label>
    <label class="fb-item">To <input type="date" id="date-to"></label>
    <label class="fb-item chk"><input type="checkbox" id="f-att"> Has attachment</label>
    <label class="fb-item chk"><input type="checkbox" id="f-link"> Has link</label>
    <button id="sort-dir" class="fb-item">Oldest first</button>
    <button id="f-clear" class="fb-item" hidden>Clear filters</button>
    <span id="f-status"></span>
  </div>

  <main id="main">
    <section id="view-chat" class="view active">
      <div id="load-top" class="load-more" hidden><button id="load-top-btn">Load older messages</button></div>
      <div id="messages"></div>
      <div id="load-bottom" class="load-more" hidden><button id="load-bottom-btn">Load older messages</button></div>
    </section>

    <section id="view-gallery" class="view">
      <div id="gallery"></div>
    </section>

    <section id="view-stats" class="view">
      <div id="stats"></div>
    </section>
  </main>

  <div id="search-results" hidden>
    <div id="search-head">
      <span id="search-summary"></span>
      <button id="search-close">Close</button>
    </div>
    <div id="search-list"></div>
  </div>

  <div id="lightbox" hidden>
    <button id="lightbox-close">Close</button>
    <div id="lightbox-body"></div>
  </div>

  <script src="/app.js"></script>
</body>
</html>
'''

STYLE_CSS = r''':root {
  --bg: #1a1d21;
  --bg-elev: #22252a;
  --bg-hover: #2a2e34;
  --fg: #dcddde;
  --fg-dim: #8e9297;
  --accent: #5865f2;
  --accent-soft: rgba(88, 101, 242, 0.25);
  --border: #303338;
  --radius: 8px;
  --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  height: 100%;
  background: var(--bg);
  color: var(--fg);
  font: 15px/1.4 "gg sans", "Segoe UI", Helvetica, Arial, sans-serif;
}

body { display: flex; flex-direction: column; }

/* Header */
#topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  background: var(--bg-elev);
  border-bottom: 1px solid var(--border);
  flex: 0 0 auto;
}

#chat-name { font-weight: 700; font-size: 16px; }
#chat-sub { color: var(--fg-dim); font-size: 12px; margin-left: 8px; }
#chat-id { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

#archive-select {
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 8px;
  font-size: 13px;
  max-width: 220px;
  color-scheme: dark;
}

#tabs { display: flex; gap: 4px; }
#tabs button {
  background: none;
  border: none;
  color: var(--fg-dim);
  padding: 6px 12px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border-radius: var(--radius);
}
#tabs button:hover { color: var(--fg); background: var(--bg-hover); }
#tabs button.active { color: var(--fg); background: var(--accent-soft); }

#chat-tools { display: flex; gap: 8px; margin-left: auto; }
#chat-tools input {
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 10px;
  font-size: 13px;
}
#chat-tools input:focus { outline: 1px solid var(--accent); }

/* Filter bar */
#filterbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 16px;
  background: var(--bg-elev);
  border-bottom: 1px solid var(--border);
  flex: 0 0 auto;
}
.fb-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--fg-dim);
  cursor: default;
}
.fb-item.chk { cursor: pointer; }
.fb-item input[type="date"] {
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px 8px;
  font-size: 12px;
  color-scheme: dark;
}
.fb-item input[type="checkbox"] { accent-color: var(--accent); cursor: pointer; }
#sort-dir, #f-clear {
  background: var(--bg);
  color: var(--fg-dim);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
#sort-dir:hover, #f-clear:hover { color: var(--fg); background: var(--bg-hover); }
#f-status { font-size: 12px; color: var(--fg-dim); margin-left: auto; }

/* Main / views */
#main { flex: 1 1 auto; min-height: 0; position: relative; }
.view { display: none; height: 100%; }
.view.active { display: block; }

/* Chat */
#view-chat { overflow-y: auto; }
#messages { padding: 16px 0 40px; max-width: 900px; margin: 0 auto; }

.msg { position: relative; padding: 2px 48px 2px 72px; }
.msg:hover { background: rgba(255, 255, 255, 0.015); }
.msg.first { margin-top: 12px; }
.msg.highlighted { background: var(--accent-soft); border-radius: var(--radius); }

.msg .avatar {
  position: absolute;
  left: 16px;
  top: 2px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: #fff;
}
.msg.compact { padding-top: 0; padding-bottom: 0; }
.msg.compact .avatar { display: none; }

.msg .hover-time {
  position: absolute;
  left: 0;
  width: 64px;
  text-align: right;
  font-size: 10px;
  color: var(--fg-dim);
  opacity: 0;
  top: 4px;
  font-family: var(--mono);
}
.msg.compact .hover-time { top: 1px; }
.msg:hover .hover-time { opacity: 1; }

.msg .head { display: flex; align-items: baseline; gap: 8px; }
.msg .author { font-weight: 600; }
.msg .time { color: var(--fg-dim); font-size: 11px; }
.msg .edited { color: var(--fg-dim); font-size: 10px; }

.msg .content { white-space: pre-wrap; overflow-wrap: anywhere; }
.msg .content a { color: #00a8fc; }
.msg.system .content { color: var(--fg-dim); font-style: italic; }

.reply-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--fg-dim);
  cursor: pointer;
  padding: 2px 0;
  max-width: 100%;
}
.reply-line:hover { color: var(--fg); }
.reply-line .reply-arrow { color: var(--fg-dim); }
.reply-line .reply-body {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.reply-line .reply-author { font-weight: 600; }

.attachments { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.attachments img.thumb {
  max-width: 380px;
  max-height: 280px;
  border-radius: var(--radius);
  cursor: zoom-in;
  display: block;
}
.attachments video { max-width: 420px; width: 100%; border-radius: var(--radius); display: block; }
.attachments audio { width: 100%; max-width: 420px; }
.file-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 12px;
  color: var(--fg);
  text-decoration: none;
  font-size: 13px;
}
.file-chip:hover { background: var(--bg-hover); }
.file-chip .size { color: var(--fg-dim); }

.day-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 20px 16px 4px;
  color: var(--fg-dim);
  font-size: 12px;
  font-weight: 600;
}
.day-divider::before, .day-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--border);
}

.load-more { display: flex; justify-content: center; padding: 12px; max-width: 900px; margin: 0 auto; }
.load-more button {
  background: var(--bg-elev);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 14px;
  cursor: pointer;
}
.load-more button:hover { background: var(--bg-hover); }

.empty { text-align: center; color: var(--fg-dim); padding: 80px 0; font-size: 14px; }

/* Search results panel */
#search-results {
  position: absolute;
  top: 56px;
  right: 16px;
  width: 420px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 80px);
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 30;
  display: flex;
  flex-direction: column;
}
#search-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  color: var(--fg-dim);
}
#search-head button { background: none; border: none; color: var(--fg-dim); cursor: pointer; font-size: 13px; }
#search-head button:hover { color: var(--fg); }
#search-list { overflow-y: auto; }
.search-hit { padding: 8px 12px; cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.04); }
.search-hit:hover { background: var(--bg-hover); }
.search-hit .meta { font-size: 12px; color: var(--fg-dim); display: flex; gap: 8px; }
.search-hit .meta .author { font-weight: 600; color: var(--fg); }
.search-hit .snippet { font-size: 13px; margin-top: 2px; }
.search-hit mark { background: #f7c948; color: #1a1d21; border-radius: 2px; }

/* Gallery */
#view-gallery { overflow-y: auto; }
#gallery { padding: 16px; max-width: 1100px; margin: 0 auto; }
.g-year { margin-bottom: 12px; }
.g-year-head {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  color: var(--fg);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}
.g-year-head:hover { background: var(--bg-hover); }
.g-caret {
  width: 0;
  height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-bottom: 7px solid var(--fg-dim);
  transform: rotate(90deg); /* closed: points right */
  transition: transform 0.15s;
}
.g-year.open .g-caret { transform: rotate(180deg); } /* open: points down */
.g-year-title { font-size: 15px; }
.g-year-count { color: var(--fg-dim); font-size: 12px; font-weight: 400; margin-left: auto; }
.g-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
  padding: 12px 0 4px;
}
.g-year:not(.open) .g-grid { display: none; }
.g-more {
  display: block;
  margin: 8px auto;
  background: var(--bg-elev);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 16px;
  cursor: pointer;
}
.g-more:hover { background: var(--bg-hover); }
.g-year:not(.open) .g-more { display: none; }
.g-item {
  position: relative;
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--bg-elev);
  aspect-ratio: 1;
  cursor: pointer;
}
.g-item img, .g-item video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.g-item .g-label {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 4px 8px;
  font-size: 11px;
  color: #fff;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.7));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0;
  transition: opacity 0.15s;
}
.g-item:hover .g-label { opacity: 1; }
.g-item .g-kind {
  position: absolute;
  top: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 10px;
  font-family: var(--mono);
  padding: 2px 6px;
  border-radius: 4px;
}
.g-item .g-jump {
  position: absolute;
  top: 6px;
  left: 6px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  border: none;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
}
.g-item:hover .g-jump { opacity: 1; }
.g-item .g-jump:hover { background: var(--accent); }
.g-file {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--fg-dim);
  font-size: 12px;
  padding: 8px;
  text-align: center;
}
.g-file .g-name { word-break: break-all; color: var(--fg); }

/* Stats */
#view-stats { overflow-y: auto; }
#stats { max-width: 900px; margin: 0 auto; padding: 20px 16px 60px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
.card {
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 18px;
  min-width: 140px;
}
.card .num { font-size: 22px; font-weight: 700; }
.card .lbl { font-size: 12px; color: var(--fg-dim); margin-top: 2px; }

h2.section { font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--fg-dim); margin: 28px 0 10px; }

.bars { display: flex; flex-direction: column; gap: 6px; }
.bar-row { display: grid; grid-template-columns: 140px 1fr 70px; gap: 10px; align-items: center; font-size: 13px; }
.bar-row .bar-track { background: var(--bg-elev); border-radius: 4px; height: 16px; }
.bar-row .bar-fill { height: 100%; border-radius: 4px; background: var(--accent); min-width: 2px; }
.bar-row .bar-val { color: var(--fg-dim); text-align: right; font-family: var(--mono); font-size: 12px; }
.bar-row .bar-lbl { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

#month-chart { display: flex; align-items: flex-end; gap: 2px; height: 140px; border-bottom: 1px solid var(--border); padding-bottom: 2px; }
#month-chart .mcol { flex: 1; background: var(--accent); border-radius: 2px 2px 0 0; min-width: 3px; position: relative; }
#month-chart .mcol:hover { background: #7983f5; }
#month-chart .mcol .tip {
  display: none;
  position: absolute;
  bottom: calc(100% + 4px);
  left: 50%;
  transform: translateX(-50%);
  background: #000;
  color: #fff;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
  z-index: 5;
}
#month-chart .mcol:hover .tip { display: block; }

/* Lightbox */
#lightbox {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}
#lightbox img, #lightbox video { max-width: 92vw; max-height: 88vh; border-radius: 4px; }
#lightbox-close {
  position: absolute;
  top: 14px;
  right: 16px;
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  border: none;
  padding: 8px 16px;
  border-radius: var(--radius);
  cursor: pointer;
}
#lightbox-close:hover { background: rgba(255, 255, 255, 0.2); }

[hidden] { display: none !important; }
'''

APP_JS = r'''"use strict";

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------

const PAGE = 50;
const GALLERY_PAGE = 60;
const GROUP_WINDOW_MS = 5 * 60 * 1000;

const els = {
  archiveSelect: document.getElementById("archive-select"),
  chatName: document.getElementById("chat-name"),
  chatSub: document.getElementById("chat-sub"),
  tabs: document.getElementById("tabs"),
  filterbar: document.getElementById("filterbar"),
  dateFrom: document.getElementById("date-from"),
  dateTo: document.getElementById("date-to"),
  fAtt: document.getElementById("f-att"),
  fLink: document.getElementById("f-link"),
  sortDir: document.getElementById("sort-dir"),
  fClear: document.getElementById("f-clear"),
  fStatus: document.getElementById("f-status"),
  chatView: document.getElementById("view-chat"),
  galleryView: document.getElementById("view-gallery"),
  statsView: document.getElementById("view-stats"),
  messages: document.getElementById("messages"),
  loadTop: document.getElementById("load-top"),
  loadTopBtn: document.getElementById("load-top-btn"),
  loadBottom: document.getElementById("load-bottom"),
  loadBottomBtn: document.getElementById("load-bottom-btn"),
  gallery: document.getElementById("gallery"),
  stats: document.getElementById("stats"),
  search: document.getElementById("search"),
  searchResults: document.getElementById("search-results"),
  searchSummary: document.getElementById("search-summary"),
  searchList: document.getElementById("search-list"),
  searchClose: document.getElementById("search-close"),
  lightbox: document.getElementById("lightbox"),
  lightboxBody: document.getElementById("lightbox-body"),
  lightboxClose: document.getElementById("lightbox-close"),
};

const state = {
  total: 0,            // unfiltered message count
  viewTotal: 0,        // message count in the current filtered view
  start: 0,            // offset of the first loaded message within the view
  loaded: [],          // loaded message objects, in view order
  byId: new Map(),     // message id -> object (loaded pages only)
  replyCache: new Map(), // replied-to id -> {author, content, index}
  loadingMore: false,
  tab: "chat",
  epoch: 0,           // bumped on archive switch; drops stale async responses
  dir: "asc",          // "asc" = oldest first (chat order), "desc" = newest first
  filters: null,       // {from, to, att, link} when any filter is active
};

const AUTHOR_COLORS = ["#5865f2", "#3ba55c", "#faa61a", "#ed4245", "#eb459e",
  "#a55bff", "#13bba1", "#f47fff", "#7289da", "#43b581"];

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function authorColor(id) {
  let hash = 0;
  const s = String(id || "");
  for (let i = 0; i < s.length; i++) hash = (hash * 31 + s.charCodeAt(i)) >>> 0;
  return AUTHOR_COLORS[hash % AUTHOR_COLORS.length];
}

function initials(name) {
  return (name || "?").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
}

function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtHoverTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function fmtDay(iso) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}

function fmtSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB";
  return (bytes / 1073741824).toFixed(2) + " GB";
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp", "bmp", "heic"];
const VIDEO_EXT = ["mp4", "mov", "webm", "mkv", "avi"];
const AUDIO_EXT = ["ogg", "mp3", "wav", "m4a", "flac"];

function extOf(filename) {
  const m = /\.([a-z0-9]+)$/i.exec(filename || "");
  return m ? m[1].toLowerCase() : "";
}

// ---------------------------------------------------------------------------
// Filters / view state
// ---------------------------------------------------------------------------

function readFilterInputs() {
  const from = els.dateFrom.value;
  const to = els.dateTo.value;
  const att = els.fAtt.checked;
  const link = els.fLink.checked;
  return (from || to || att || link) ? { from, to, att, link } : null;
}

function filterQS() {
  const parts = [];
  const f = state.filters;
  if (f) {
    if (f.from) parts.push("from=" + f.from);
    if (f.to) parts.push("to=" + f.to);
    if (f.att) parts.push("has_attachment=true");
    if (f.link) parts.push("has_link=true");
  }
  if (state.dir === "desc") parts.push("dir=desc");
  return parts.length ? "&" + parts.join("&") : "";
}

function applyFilters() {
  state.filters = readFilterInputs();
  els.searchResults.hidden = true;
  loadFirstPage();
}

function clearFilters(reload) {
  els.dateFrom.value = "";
  els.dateTo.value = "";
  els.fAtt.checked = false;
  els.fLink.checked = false;
  state.filters = null;
  els.searchResults.hidden = true;
  if (reload) loadFirstPage();
}

function toggleSort() {
  state.dir = state.dir === "asc" ? "desc" : "asc";
  els.sortDir.textContent = state.dir === "asc" ? "Oldest first" : "Newest first";
  els.searchResults.hidden = true;
  loadFirstPage();
}

function updateStatus() {
  if (state.filters) {
    els.fStatus.textContent =
      state.viewTotal.toLocaleString() + " of " + state.total.toLocaleString() + " messages match";
    els.fClear.hidden = false;
  } else {
    els.fStatus.textContent = "";
    els.fClear.hidden = true;
  }
}

// ---------------------------------------------------------------------------
// Chat rendering
// ---------------------------------------------------------------------------

function messageNode(msg, prev) {
  const compact =
    prev && prev.author === msg.author &&
    new Date(msg.timestamp) - new Date(prev.timestamp) < GROUP_WINDOW_MS &&
    sameDay(prev.timestamp, msg.timestamp) && msg.type === 0;

  const wrap = el("div", "msg" + (compact ? " compact" : " first"));
  wrap.dataset.seq = msg.seq;
  wrap.dataset.id = msg.id;

  if (!compact) {
    const avatar = el("div", "avatar", initials(msg.author));
    avatar.style.background = authorColor(msg.author_id);
    wrap.appendChild(avatar);
    const head = el("div", "head");
    head.appendChild(el("span", "author", msg.author || "unknown"));
    head.appendChild(el("span", "time", fmtTime(msg.timestamp)));
    if (msg.edited_timestamp) head.appendChild(el("span", "edited", "(edited)"));
    wrap.appendChild(head);
  }
  const hoverTime = el("div", "hover-time", fmtHoverTime(msg.timestamp));
  wrap.appendChild(hoverTime);

  if (msg.reply_to) wrap.appendChild(replyLine(msg.reply_to));

  const content = el("div", "content");
  const isSystem = msg.type !== 0 && msg.type !== 19;
  if (isSystem) wrap.classList.add("system");
  if (!msg.content && isSystem) {
    content.textContent = systemText(msg);
  } else {
    linkifyInto(content, msg.content);
  }
  wrap.appendChild(content);

  if (msg.attachments && msg.attachments.length) {
    const att = el("div", "attachments");
    for (const a of msg.attachments) att.appendChild(attachmentNode(a));
    wrap.appendChild(att);
  }
  return wrap;
}

function systemText(msg) {
  if (msg.type === 3) return "started a call";
  if (msg.type === 6) return "added a channel notice";
  return "system message (type " + msg.type + ")";
}

function sameDay(a, b) {
  return new Date(a).toDateString() === new Date(b).toDateString();
}

function replyLine(replyId) {
  const line = el("div", "reply-line");
  const arrow = el("span", "reply-arrow", "\u21b3"); // ↳
  line.appendChild(arrow);
  const body = el("span", "reply-body", "loading...");
  line.appendChild(body);
  resolveReply(replyId).then(info => {
    if (!info) {
      body.textContent = "original message unavailable";
      return;
    }
    body.replaceChildren(
      el("span", "reply-author", info.author || "unknown"),
      document.createTextNode(" " + (info.content || "(no text)"))
    );
  });
  line.addEventListener("click", () => jumpToMessage(replyId));
  return line;
}

async function resolveReply(id) {
  if (state.replyCache.has(id)) return state.replyCache.get(id);
  const local = state.byId.get(String(id));
  if (local) {
    const info = { author: local.author, content: local.content, index: local.seq };
    state.replyCache.set(id, info);
    return info;
  }
  const data = await api("/api/resolve?ids=" + encodeURIComponent(id));
  const info = data[id] || null;
  state.replyCache.set(id, info);
  return info;
}

function linkifyInto(target, text) {
  const urlRe = /(https?:\/\/[^\s<>"']+)/g;
  let last = 0;
  let m;
  while ((m = urlRe.exec(text)) !== null) {
    if (m.index > last) target.appendChild(document.createTextNode(text.slice(last, m.index)));
    const a = el("a", null, m[1]);
    a.href = m[1];
    a.target = "_blank";
    a.rel = "noreferrer";
    target.appendChild(a);
    last = m.index + m[1].length;
  }
  if (last < text.length) target.appendChild(document.createTextNode(text.slice(last)));
}

function attachmentNode(att) {
  const ext = extOf(att.filename);
  if (IMAGE_EXT.includes(ext)) {
    const img = el("img", "thumb");
    img.loading = "lazy";
    img.src = att.url;
    img.alt = att.filename;
    img.addEventListener("click", () => openLightbox("img", att.url, att.filename));
    return img;
  }
  if (VIDEO_EXT.includes(ext)) {
    const v = el("video");
    v.controls = true;
    v.preload = "metadata";
    v.src = att.url;
    return v;
  }
  if (AUDIO_EXT.includes(ext)) {
    const a = el("audio");
    a.controls = true;
    a.preload = "metadata";
    a.src = att.url;
    return a;
  }
  const chip = el("a", "file-chip");
  chip.href = att.url + "?download=1";
  chip.download = att.filename;
  chip.appendChild(el("span", null, att.filename));
  chip.appendChild(el("span", "size", fmtSize(att.size)));
  return chip;
}

function renderMessages(list, mode) {
  // mode: "replace", "prepend" (older block at top), "append" (at bottom)
  if (mode === "replace") {
    els.messages.replaceChildren();
    state.loaded = [];
    if (!list.length) {
      els.messages.appendChild(el("div", "empty", "No messages match these filters."));
      updateMoreButtons();
      return;
    }
  }
  const frag = document.createDocumentFragment();
  let prev = mode === "prepend" ? null : state.loaded[state.loaded.length - 1];
  for (const msg of list) {
    const node = messageNode(msg, prev || null);
    if (!prev || !sameDay(prev.timestamp, msg.timestamp)) {
      frag.appendChild(el("div", "day-divider", fmtDay(msg.timestamp)));
    }
    frag.appendChild(node);
    state.byId.set(msg.id, msg);
    prev = msg;
  }
  if (mode === "prepend") {
    els.messages.prepend(frag);
    state.loaded = list.concat(state.loaded);
  } else {
    els.messages.appendChild(frag);
    state.loaded = state.loaded.concat(list);
  }
  updateMoreButtons();
}

function updateMoreButtons() {
  els.loadTop.hidden = !(state.start > 0);
  els.loadBottom.hidden = !(state.start + state.loaded.length < state.viewTotal);
  // In the view, "before" is older in asc order and newer in desc order.
  const topLabel = state.dir === "asc" ? "Load older messages" : "Load newer messages";
  const bottomLabel = state.dir === "asc" ? "Load newer messages" : "Load older messages";
  els.loadTopBtn.textContent = topLabel;
  els.loadBottomBtn.textContent = bottomLabel;
}

async function loadFirstPage() {
  // Both directions start at the beginning of their view: the oldest
  // message in asc order, the newest message in desc order.
  const epoch = state.epoch;
  const data = await api(`/api/messages?start=0&count=${PAGE}${filterQS()}`);
  if (epoch !== state.epoch) return;
  state.viewTotal = data.total;
  state.start = data.start;
  renderMessages(data.messages, "replace");
  els.chatView.scrollTop = 0;
  updateStatus();
}

async function loadMore(where) {
  // where: "before" (prepends the block above the loaded window)
  //        "after" (appends the block below it)
  if (state.loadingMore) return;
  if (where === "before" && state.start <= 0) return;
  if (where === "after" && state.start + state.loaded.length >= state.viewTotal) return;
  state.loadingMore = true;
  const epoch = state.epoch;
  const prevScrollHeight = els.chatView.scrollHeight;
  const prevScrollTop = els.chatView.scrollTop;
  try {
    if (where === "before") {
      const newStart = Math.max(0, state.start - PAGE);
      const count = state.start - newStart;
      const data = await api(`/api/messages?start=${newStart}&count=${count}${filterQS()}`);
      if (epoch !== state.epoch) return;
      renderMessages(data.messages, "prepend");
      state.start = data.start;
      els.chatView.scrollTop = prevScrollTop + (els.chatView.scrollHeight - prevScrollHeight);
    } else {
      const fetchStart = state.start + state.loaded.length;
      const data = await api(`/api/messages?start=${fetchStart}&count=${PAGE}${filterQS()}`);
      if (epoch !== state.epoch) return;
      renderMessages(data.messages, "append");
    }
  } finally {
    state.loadingMore = false;
  }
}

async function jumpToMessage(id) {
  const epoch = state.epoch;
  const attempt = () =>
    api(`/api/messages?anchor=${encodeURIComponent(id)}&count=${PAGE}${filterQS()}`)
      .catch(err => {
        if (err.message.includes("-> 404")) return null; // unknown id, or excluded by filters
        throw err;
      });
  let data = await attempt();
  if (epoch !== state.epoch) return;
  if (!data && state.filters) {
    clearFilters(false);   // target is outside the filtered view: drop filters and retry
    updateStatus();
    data = await attempt();
    if (epoch !== state.epoch) return;
  }
  if (!data) return;
  state.viewTotal = data.total;
  state.start = data.start;
  renderMessages(data.messages, "replace");
  const target = els.messages.querySelector(`[data-id="${CSS.escape(String(id))}"]`);
  if (target) {
    target.scrollIntoView({ block: "center" });
    target.classList.add("highlighted");
    setTimeout(() => target.classList.remove("highlighted"), 2500);
  } else {
    els.chatView.scrollTop = 0;
  }
  updateStatus();
  switchTab("chat");
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

async function runSearch() {
  const q = els.search.value.trim();
  if (!q) {
    els.searchResults.hidden = true;
    return;
  }
  const epoch = state.epoch;
  const data = await api("/api/search?q=" + encodeURIComponent(q) + filterQS());
  if (epoch !== state.epoch) return;
  els.searchSummary.textContent =
    (data.results.length === 0 ? "No matches" : data.results.length + (data.truncated ? "+" : "") + " matches (newest first)");
  els.searchList.replaceChildren();
  for (const hit of data.results) {
    const row = el("div", "search-hit");
    const meta = el("div", "meta");
    meta.appendChild(el("span", "author", hit.author || "unknown"));
    meta.appendChild(el("span", null, fmtTime(hit.timestamp)));
    row.appendChild(meta);
    const snippet = el("div", "snippet");
    highlightInto(snippet, hit.content, q);
    row.appendChild(snippet);
    row.addEventListener("click", () => {
      els.searchResults.hidden = true;
      jumpToMessage(hit.id);
    });
    els.searchList.appendChild(row);
  }
  els.searchResults.hidden = false;
}

function highlightInto(target, text, q) {
  const needle = q.toLowerCase();
  let last = 0;
  const lower = text.toLowerCase();
  let idx = lower.indexOf(needle);
  while (idx !== -1) {
    if (idx > last) target.appendChild(document.createTextNode(text.slice(last, idx)));
    target.appendChild(el("mark", null, text.slice(idx, idx + q.length)));
    last = idx + q.length;
    idx = lower.indexOf(needle, last);
  }
  if (last < text.length) target.appendChild(document.createTextNode(text.slice(last)));
}

// ---------------------------------------------------------------------------
// Gallery
// ---------------------------------------------------------------------------

let galleryInit = false;

async function loadGallery() {
  const epoch = state.epoch;
  const data = await api("/api/attachment-years");
  if (epoch !== state.epoch) return; // archive switched while fetching
  els.gallery.replaceChildren();
  for (const y of data.years) {
    els.gallery.appendChild(yearSection(y));
  }
}

function yearSection(yearInfo) {
  // A collapsed year header; expanding it lazily loads its media in pages.
  const section = el("div", "g-year");
  const head = el("button", "g-year-head");
  head.appendChild(el("span", "g-caret"));
  head.appendChild(el("span", "g-year-title", yearInfo.year));
  head.appendChild(el("span", "g-year-count", yearInfo.count.toLocaleString() + " files"));
  const grid = el("div", "g-grid");
  const moreBtn = el("button", "g-more", "Load more");
  moreBtn.hidden = true;
  let loaded = 0;
  let expanded = false;
  let loading = false;

  const loadPage = async () => {
    if (loading) return;
    loading = true;
    try {
      const data = await api(`/api/attachments?year=${encodeURIComponent(yearInfo.year)}&start=${loaded}&count=${GALLERY_PAGE}`);
      const frag = document.createDocumentFragment();
      for (const att of data.attachments) frag.appendChild(galleryItem(att));
      grid.appendChild(frag);
      loaded += data.attachments.length;
      moreBtn.hidden = loaded >= data.total;
      moreBtn.textContent = `Load more (${loaded} of ${data.total.toLocaleString()})`;
    } finally {
      loading = false;
    }
  };

  head.addEventListener("click", () => {
    expanded = !expanded;
    section.classList.toggle("open", expanded);
    if (expanded && loaded === 0) loadPage();
  });
  moreBtn.addEventListener("click", loadPage);

  section.appendChild(head);
  section.appendChild(grid);
  section.appendChild(moreBtn);
  return section;
}

function galleryItem(att) {
  const item = el("div", "g-item");
  const ext = extOf(att.filename);
  if (IMAGE_EXT.includes(ext)) {
    const img = el("img");
    img.loading = "lazy";
    img.decoding = "async";
    img.src = att.url;
    img.alt = att.filename;
    item.appendChild(img);
    item.addEventListener("click", () => openLightbox("img", att.url, att.filename));
  } else if (VIDEO_EXT.includes(ext)) {
    const v = el("video");
    v.preload = "metadata";
    v.muted = true;
    v.src = att.url;
    item.appendChild(v);
    item.appendChild(el("span", "g-kind", ext));
    item.addEventListener("click", () => openLightbox("video", att.url, att.filename));
  } else if (AUDIO_EXT.includes(ext)) {
    item.appendChild(el("div", "g-file", ext.toUpperCase()));
    const a = el("audio");
    a.controls = true;
    a.src = att.url;
    item.appendChild(a);
    item.addEventListener("click", () => openLightbox("audio", att.url, att.filename));
  } else {
    const file = el("div", "g-file");
    file.appendChild(el("div", "g-name", att.filename));
    file.appendChild(el("div", null, fmtSize(att.size)));
    item.appendChild(file);
    item.appendChild(el("span", "g-kind", ext || "file"));
    item.addEventListener("click", () => window.open(att.url + "?download=1", "_blank"));
  }
  if (att.message_id) {
    const jump = el("button", "g-jump", "chat");
    jump.title = "View in chat";
    jump.addEventListener("click", e => {
      e.stopPropagation();
      jumpToMessage(att.message_id);
    });
    item.appendChild(jump);
  }
  item.appendChild(el("div", "g-label",
    (att.date ? att.date + " \u00b7 " : "") + att.filename + " \u00b7 " + fmtSize(att.size)));
  return item;
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

async function loadStats() {
  const epoch = state.epoch;
  const s = await api("/api/stats");
  if (epoch !== state.epoch) return; // archive switched while fetching
  const wrap = el("div");
  const cards = el("div", "cards");
  const mkCard = (num, lbl) => {
    const c = el("div", "card");
    c.appendChild(el("div", "num", num));
    c.appendChild(el("div", "lbl", lbl));
    cards.appendChild(c);
  };
  mkCard(s.total_messages.toLocaleString(), "messages");
  mkCard(s.authors.length, "participants");
  mkCard(s.total_attachments.toLocaleString(), "attachments");
  mkCard(fmtSize(s.attachment_bytes), "media stored");
  mkCard(String(s.replies), "replies");
  wrap.appendChild(cards);

  wrap.appendChild(el("h2", "section", "Messages per author"));
  const authorBars = el("div", "bars");
  const maxAuthor = Math.max(...s.authors.map(a => a.count), 1);
  for (const a of s.authors) {
    const row = el("div", "bar-row");
    row.appendChild(el("div", "bar-lbl", a.name));
    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    fill.style.width = (100 * a.count / maxAuthor).toFixed(1) + "%";
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("div", "bar-val", a.count.toLocaleString()));
    authorBars.appendChild(row);
  }
  wrap.appendChild(authorBars);

  wrap.appendChild(el("h2", "section", "Messages per month"));
  const chart = el("div");
  chart.id = "month-chart";
  const maxMonth = Math.max(...s.months.map(m => m.count), 1);
  for (const m of s.months) {
    const col = el("div", "mcol");
    col.style.height = Math.max(2, 100 * m.count / maxMonth) + "%";
    const tip = el("div", "tip", m.month + ": " + m.count.toLocaleString());
    col.appendChild(tip);
    chart.appendChild(col);
  }
  wrap.appendChild(chart);

  wrap.appendChild(el("h2", "section", "Attachment types"));
  const typeBars = el("div", "bars");
  const maxType = Math.max(...s.attachment_types.map(t => t.count), 1);
  for (const t of s.attachment_types) {
    const row = el("div", "bar-row");
    row.appendChild(el("div", "bar-lbl", t.ext));
    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    fill.style.width = (100 * t.count / maxType).toFixed(1) + "%";
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("div", "bar-val", String(t.count)));
    typeBars.appendChild(row);
  }
  wrap.appendChild(typeBars);

  els.stats.replaceChildren(wrap);
}

// ---------------------------------------------------------------------------
// Tabs & overlays
// ---------------------------------------------------------------------------

function switchTab(tab) {
  state.tab = tab;
  for (const btn of els.tabs.querySelectorAll("button")) {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  }
  els.chatView.classList.toggle("active", tab === "chat");
  els.galleryView.classList.toggle("active", tab === "gallery");
  els.statsView.classList.toggle("active", tab === "stats");
  els.filterbar.hidden = tab !== "chat";
  els.searchResults.hidden = true;
  if (tab === "stats") loadStats();
  if (tab === "gallery" && !galleryInit) {
    galleryInit = true;
    loadGallery();
  }
}

function openLightbox(kind, url, filename) {
  els.lightboxBody.replaceChildren();
  let node;
  if (kind === "img") {
    node = el("img");
    node.src = url;
    node.alt = filename;
  } else if (kind === "video") {
    node = el("video");
    node.src = url;
    node.controls = true;
    node.autoplay = true;
  } else {
    node = el("audio");
    node.src = url;
    node.controls = true;
    node.autoplay = true;
  }
  els.lightboxBody.appendChild(node);
  els.lightbox.hidden = false;
}

function closeLightbox() {
  els.lightbox.hidden = true;
  els.lightboxBody.replaceChildren();
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

els.archiveSelect.addEventListener("change", async () => {
  const name = els.archiveSelect.value;
  if (!name) return;
  const meta = await api("/api/select?archive=" + encodeURIComponent(name));
  await applyArchive(meta);
});
els.archiveSelect.addEventListener("focus", async () => {
  // Pick up archives added after the viewer started (cheap request).
  try {
    const list = await loadArchiveList();
    if (list.selected) els.archiveSelect.value = list.selected;
  } catch (err) { /* keep the current options */ }
});

els.tabs.addEventListener("click", e => {
  const btn = e.target.closest("button[data-tab]");
  if (btn) switchTab(btn.dataset.tab);
});

els.loadTopBtn.addEventListener("click", () => loadMore("before"));
els.loadBottomBtn.addEventListener("click", () => loadMore("after"));

els.chatView.addEventListener("scroll", () => {
  if (state.tab !== "chat" || state.loadingMore) return;
  const v = els.chatView;
  if (v.scrollTop < 600 && state.start > 0) {
    loadMore("before");
  } else if (v.scrollTop + v.clientHeight > v.scrollHeight - 600 &&
             state.start + state.loaded.length < state.viewTotal) {
    loadMore("after");
  }
});

els.search.addEventListener("keydown", e => {
  if (e.key === "Enter") runSearch();
  if (e.key === "Escape") els.searchResults.hidden = true;
});
els.searchClose.addEventListener("click", () => { els.searchResults.hidden = true; });

els.dateFrom.addEventListener("change", applyFilters);
els.dateTo.addEventListener("change", applyFilters);
els.fAtt.addEventListener("change", applyFilters);
els.fLink.addEventListener("change", applyFilters);
els.sortDir.addEventListener("click", toggleSort);
els.fClear.addEventListener("click", () => clearFilters(true));

els.lightbox.addEventListener("click", e => {
  if (e.target === els.lightbox || e.target === els.lightboxBody) closeLightbox();
});
els.lightboxClose.addEventListener("click", closeLightbox);
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeLightbox();
});

// ---------------------------------------------------------------------------
// Archive selection
// ---------------------------------------------------------------------------

async function loadArchiveList() {
  const list = await api("/api/archives");
  els.archiveSelect.replaceChildren();
  for (const a of list.archives) {
    const opt = el("option", null, a.chat);
    opt.value = a.name;
    els.archiveSelect.appendChild(opt);
  }
  return list;
}

async function applyArchive(meta) {
  // Full reset of per-archive state, then reload the current view.
  state.epoch++;
  state.total = meta.total_messages;
  state.viewTotal = 0;
  state.start = 0;
  state.loaded = [];
  state.byId = new Map();
  state.replyCache = new Map();
  state.filters = null;
  state.dir = "asc";
  els.search.value = "";
  els.searchResults.hidden = true;
  els.dateFrom.value = "";
  els.dateTo.value = "";
  els.fAtt.checked = false;
  els.fLink.checked = false;
  els.sortDir.textContent = "Oldest first";
  els.fStatus.textContent = "";
  els.fClear.hidden = true;
  galleryInit = false;
  els.gallery.replaceChildren();
  els.chatName.textContent = meta.chat;
  els.chatSub.textContent = meta.total_messages.toLocaleString() + " messages \u00b7 " +
    meta.total_attachments.toLocaleString() + " attachments";
  document.title = meta.chat + " \u2014 Archive";
  switchTab("chat");
  await loadFirstPage();
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

(async function boot() {
  const list = await loadArchiveList();
  let name = list.selected;
  if (!name && list.archives.length) name = list.archives[0].name;
  if (!name) {
    els.chatName.textContent = "No archives";
    els.chatSub.textContent = "";
    els.messages.replaceChildren(
      el("div", "empty", "No archives found in the archival folder. Archive a chat first."));
    return;
  }
  if (name !== list.selected) {
    await api("/api/select?archive=" + encodeURIComponent(name));
  }
  els.archiveSelect.value = name;
  const meta = await api("/api/meta");
  await applyArchive(meta);
})();
'''


# ---------------------------------------------------------------------------
# Archive loading
# ---------------------------------------------------------------------------
