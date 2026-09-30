#!/usr/bin/env python3
"""Lightweight local viewer for chat archives produced by the archiver.

Serves a static chat UI plus a small JSON API over an archive folder:

    meta.json          channel id + chat name
    messages.jsonl      one message record per line
    manifest.jsonl      one attachment record per line
    attachments/        downloaded attachment files

Only the archive folder is read; nothing from the deleter itself is imported.

Usage:
    python archive_viewer.py [ARCHIVES_DIR_OR_ARCHIVE_FOLDER] [--host HOST] [--port PORT]

Serves the configured archival folder (one folder per archived chat) with a
selector for choosing which archive to view. If a single archive folder is
passed, it serves that archive and its siblings. If no path is given, the
archival folder is resolved the same way the archiver resolves it:
DM_ARCHIVE_DIR environment variable, then the app config file, then the
per-OS default (~/.local/share/discord-deleter/archives on Linux,
~/Library/Application Support/discord-deleter/archives on macOS,
%APPDATA%\\discord-deleter\\archives on Windows).

The viewer UI (HTML/CSS/JS) is embedded below, so this single file is
self-contained.
"""

import argparse
import bisect
import json
import mimetypes
import os
import re
import sys
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGE_DEFAULT = 50
PAGE_MAX = 200
SEARCH_MAX = 200
VIEW_CACHE_MAX = 32

LINK_RE = re.compile(r"https?://", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Embedded viewer UI (served from memory, no external files)
# ---------------------------------------------------------------------------

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
  const data = await api("/api/attachment-years");
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
  const s = await api("/api/stats");
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

class Archive:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.meta = self._load_json(self.folder / "meta.json", default={})
        self.messages = self._load_jsonl(self.folder / "messages.jsonl")
        self.index_by_id = {m["id"]: i for i, m in enumerate(self.messages)}
        self.attachments_by_id = {}
        for entry in self._load_jsonl(self.folder / "manifest.jsonl"):
            if entry.get("attachment_id") and entry.get("local_path"):
                self.attachments_by_id[entry["attachment_id"]] = entry
        self.attachments = sorted(
            self.attachments_by_id.values(), key=lambda e: e.get("seq", 0)
        )
        self.mime_guesser = mimetypes.MimeTypes()
        # Lazily built, immutable-after-load filter indexes (archive is read-only)
        self._attachment_indices = None
        self._link_indices = None
        self._view_cache = {}
        self._attachment_records = None

    @staticmethod
    def _load_json(path, default=None):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {} if default is None else default

    @staticmethod
    def _load_jsonl(path):
        """Load JSONL records, dropping a partial tail line (same rule the
        archiver uses when resuming after a hard kill)."""
        records = []
        try:
            with open(path, "rb") as f:
                for raw in f:
                    try:
                        records.append(json.loads(raw))
                    except json.JSONDecodeError:
                        break
        except OSError:
            pass
        return records

    def attachment_name(self, entry):
        return Path(entry["local_path"]).name

    def attachment_mime(self, name):
        guessed, _ = self.mime_guesser.guess_type(name)
        return guessed or "application/octet-stream"

    def resolve(self, name):
        """Map a bare attachment filename to a real path inside the archive,
        refusing anything that escapes the attachments directory."""
        base = (self.folder / "attachments").resolve()
        candidate = (base / name).resolve()
        if candidate.parent != base or not candidate.is_file():
            return None
        return candidate

    # -- API payloads -------------------------------------------------------

    def meta_payload(self):
        return {
            "chat": self.meta.get("chat", "archive"),
            "channel_id": self.meta.get("channel_id"),
            "total_messages": len(self.messages),
            "total_attachments": len(self.attachments),
            "first_timestamp": self.messages[0]["timestamp"] if self.messages else None,
            "last_timestamp": self.messages[-1]["timestamp"] if self.messages else None,
        }

    def attachment_view(self, attachment_id):
        """Message-facing view of one attachment, or None if it is not on disk."""
        entry = self.attachments_by_id.get(str(attachment_id))
        if not entry:
            return None
        name = self.attachment_name(entry)
        if self.resolve(name) is None:
            return None
        return {
            "id": entry.get("attachment_id"),
            "filename": entry.get("filename") or name,
            "size": entry.get("size"),
            "url": "/media/" + name,
        }

    # -- filtered views ------------------------------------------------------
    # A "view" is the ordered list of archive indices matching the active
    # filters. None means the unfiltered full log. Timestamps are uniform UTC
    # ISO strings, so lexical comparison equals chronological comparison.

    def _indices_with_attachments(self):
        if self._attachment_indices is None:
            self._attachment_indices = frozenset(
                i for i, m in enumerate(self.messages) if m.get("attachment_ids")
            )
        return self._attachment_indices

    def _indices_with_links(self):
        if self._link_indices is None:
            self._link_indices = frozenset(
                i for i, m in enumerate(self.messages)
                if LINK_RE.search(m.get("content") or "")
            )
        return self._link_indices

    def filtered_view(self, filters):
        """indices (ascending) matching (date_from, date_to, has_attachment, has_link)."""
        cached = self._view_cache.get(filters)
        if cached is not None:
            return cached
        date_from, date_to, has_attachment, has_link = filters
        attachments = self._indices_with_attachments() if has_attachment else None
        links = self._indices_with_links() if has_link else None
        view = []
        for i, message in enumerate(self.messages):
            timestamp = message.get("timestamp") or ""
            if date_from and timestamp < date_from:
                continue
            if date_to and timestamp > date_to:
                continue
            if attachments is not None and i not in attachments:
                continue
            if links is not None and i not in links:
                continue
            view.append(i)
        if len(self._view_cache) >= VIEW_CACHE_MAX:
            self._view_cache.clear()
        self._view_cache[filters] = view
        return view

    def ordered_view(self, filters, reverse):
        """Filtered view or the full log (a range), in the requested direction."""
        if filters is None:
            return range(len(self.messages)) if not reverse else range(len(self.messages) - 1, -1, -1)
        view = self.filtered_view(filters)
        return view if not reverse else view[::-1]

    def anchor_position(self, message_id, filters, reverse):
        """Position of a message within the ordered view, or None if the
        message does not exist or is excluded by the filters."""
        index = self.index_by_id.get(str(message_id))
        if index is None:
            return None
        ascending = self.ordered_view(filters, False)
        position = bisect.bisect_left(ascending, index)
        if position >= len(ascending) or ascending[position] != index:
            return None
        return len(ascending) - 1 - position if reverse else position

    # -- API payloads --------------------------------------------------------

    def page_payload(self, start, count, filters=None, reverse=False):
        ordered = self.ordered_view(filters, reverse)
        total = len(ordered)
        if start < 0:  # negative counts back from the end of the view
            start = max(0, total + start)
        start = max(0, min(start, total))
        out = []
        for index in ordered[start:start + count]:
            message = self.messages[index]
            item = dict(message)
            item["seq"] = index  # position in the archive, not Discord id
            item["attachments"] = [
                view
                for view in (self.attachment_view(a) for a in message.get("attachment_ids") or [])
                if view
            ]
            out.append(item)
        return {"total": total, "start": start, "messages": out}

    def anchor_payload(self, message_id, count, filters=None, reverse=False):
        position = self.anchor_position(message_id, filters, reverse)
        if position is None:
            return None
        start = max(0, position - count // 2)
        payload = self.page_payload(start, count, filters, reverse)
        payload["anchor_index"] = position
        return payload

    def resolve_payload(self, ids):
        out = {}
        for message_id in ids:
            index = self.index_by_id.get(str(message_id))
            if index is None:
                continue
            message = self.messages[index]
            out[message["id"]] = {
                "index": index,
                "author": message.get("author"),
                "content": (message.get("content") or "")[:140],
                "timestamp": message.get("timestamp"),
            }
        return out

    def search_payload(self, query, author=None, filters=None, limit=SEARCH_MAX):
        query = query.lower()
        author = author.lower() if author else None
        ordered = self.ordered_view(filters, False)
        hits = []
        # Most recent matches first: the view is ascending, scan it backwards.
        for index in reversed(ordered):
            message = self.messages[index]
            if author and (message.get("author") or "").lower() != author:
                continue
            if query not in (message.get("content") or "").lower():
                continue
            hits.append(
                {
                    "index": index,
                    "id": message["id"],
                    "author": message.get("author"),
                    "timestamp": message.get("timestamp"),
                    "content": message.get("content") or "",
                }
            )
            if len(hits) >= limit:
                break
        return {"query": query, "results": hits, "truncated": len(hits) >= limit}

    def attachment_records(self):
        """Attachments enriched with their message date, as
        (entry, year, date) tuples in seq order (built once)."""
        if self._attachment_records is None:
            records = []
            for entry in self.attachments:
                index = self.index_by_id.get(str(entry.get("message_id")))
                timestamp = self.messages[index].get("timestamp") if index is not None else None
                date = (timestamp or "")[:10] or None
                records.append((entry, (date or "?")[:4], date))
            self._attachment_records = records
        return self._attachment_records

    def attachment_year_counts(self):
        """Year -> attachment count, newest year first."""
        counts = Counter(year for _, year, _ in self.attachment_records())
        return [{"year": year, "count": counts[year]}
                for year in sorted(counts, reverse=True)]

    def attachments_payload(self, start, count, year=None):
        records = self.attachment_records()
        if year is not None:
            records = [r for r in records if r[1] == year]
        total = len(records)
        start = max(0, min(start, total))
        items = []
        for entry, _year, date in records[start:start + count]:
            name = self.attachment_name(entry)
            message_id = entry.get("message_id")
            items.append(
                {
                    "seq": entry.get("seq"),
                    "attachment_id": entry.get("attachment_id"),
                    "message_id": message_id,
                    "message_index": self.index_by_id.get(str(message_id)),
                    "filename": entry.get("filename"),
                    "size": entry.get("size"),
                    "date": date,
                    "url": "/media/" + name,
                }
            )
        return {"total": total, "start": start, "attachments": items}

    def stats_payload(self):
        authors = Counter()
        months = Counter()
        edited = 0
        replies = 0
        with_attachments = 0
        for message in self.messages:
            authors[message.get("author") or "unknown"] += 1
            months[(message.get("timestamp") or "")[:7]] += 1
            if message.get("edited_timestamp"):
                edited += 1
            if message.get("reply_to"):
                replies += 1
            if message.get("attachment_ids"):
                with_attachments += 1
        extensions = Counter()
        total_bytes = 0
        for entry in self.attachments:
            extensions[Path(entry.get("filename") or "").suffix.lower() or "?"] += 1
            total_bytes += entry.get("size") or 0
        return {
            "total_messages": len(self.messages),
            "total_attachments": len(self.attachments),
            "attachment_bytes": total_bytes,
            "authors": [{"name": name, "count": count} for name, count in authors.most_common()],
            "months": [{"month": month, "count": count} for month, count in sorted(months.items())],
            "edited": edited,
            "replies": replies,
            "with_attachments": with_attachments,
            "attachment_types": [{"ext": ext, "count": count} for ext, count in extensions.most_common()],
        }


def parse_filter_params(params):
    """Turn query params into a filter key, or None when nothing is filtered.

    Returns (date_from, date_to, has_attachment, has_link). Dates accept either
    YYYY-MM-DD or a full ISO timestamp; a bare end date includes that whole day.
    """
    date_from = (params.get("from") or [None])[0]
    date_to = (params.get("to") or [None])[0]
    if date_to and len(date_to) == 10:
        date_to += "T23:59:59.999999+00:00"
    has_attachment = (params.get("has_attachment") or ["false"])[0] == "true"
    has_link = (params.get("has_link") or ["false"])[0] == "true"
    if date_from or date_to or has_attachment or has_link:
        return (date_from, date_to, has_attachment, has_link)
    return None


def find_archives(root):
    """Archive folders directly under root (meta.json + messages.jsonl),
    most recently modified first."""
    archives = []
    try:
        children = sorted(Path(root).iterdir())
    except OSError:
        return archives
    for path in children:
        if not path.is_dir() or not (path / "meta.json").is_file():
            continue
        if not (path / "messages.jsonl").is_file():
            continue
        try:
            meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        archives.append({
            "name": path.name,
            "chat": meta.get("chat") or path.name,
            "channel_id": meta.get("channel_id"),
            "mtime": mtime,
        })
    archives.sort(key=lambda a: a["mtime"], reverse=True)
    return archives


def app_config_dir():
    """Per-OS application data directory, matching the archiver's resolution."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "discord-deleter"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        return Path(base) / "discord-deleter"
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(base) / "discord-deleter"


def resolve_archive_dir(explicit=None):
    """The archival folder: explicit path, then DM_ARCHIVE_DIR, then the
    archive_dir in the app config file, then the per-OS default."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("DM_ARCHIVE_DIR")
    if env:
        return Path(env).expanduser()
    try:
        config = json.loads((app_config_dir() / "config.json").read_text(encoding="utf-8"))
        return Path(config["archive_dir"]).expanduser()
    except (OSError, ValueError, TypeError, KeyError):
        return app_config_dir() / "archives"


class ArchiveLibrary:
    """The archival folder and the archives inside it. One archive is loaded
    at a time; a couple of recently used ones stay cached in memory."""

    CACHE_MAX = 2

    def __init__(self, root):
        self.root = Path(root).absolute()
        self._cache = {}  # folder name -> Archive; insertion order is LRU order
        self.selected = None
        self.selected_name = None

    def select(self, name):
        folder = self.root / name
        # Only bare child names are accepted: this rejects traversal ("..",
        # embedded separators) without resolving, so symlinked archive folders work.
        if folder.parent != self.root:
            return None
        if not (folder / "meta.json").is_file() or not (folder / "messages.jsonl").is_file():
            return None
        archive = self._cache.pop(name, None)
        if archive is None:
            archive = Archive(folder)  # may take a few seconds for large archives
        self._cache[name] = archive
        while len(self._cache) > self.CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self.selected = archive
        self.selected_name = name
        return archive


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class ViewerHandler(BaseHTTPRequestHandler):
    library = None  # ArchiveLibrary, set on the class before serving
    server_version = "ArchiveViewer/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet: one line per request is noise
        pass

    def require_archive(self):
        """The currently selected archive, or None after sending an error."""
        archive = self.library.selected
        if archive is None:
            self.send_json({"error": "no archive selected"}, 409)
        return archive

    # -- helpers ------------------------------------------------------------

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_media(self, fs_path, mime, download_name=None):
        """Serve a file with single-range support so <video>/<audio> can seek."""
        try:
            size = fs_path.stat().st_size
        except OSError:
            return self.send_json({"error": "not found"}, 404)

        disposition = "inline"
        if download_name:
            disposition = 'attachment; filename="%s"' % download_name.replace('"', "")

        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if match and (match.group(1) or match.group(2)):
                if match.group(1):
                    start = int(match.group(1))
                    if match.group(2):
                        end = min(int(match.group(2)), size - 1)
                else:  # suffix range: last N bytes
                    start = max(0, size - int(match.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Disposition", disposition)
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command != "HEAD":
            with open(fs_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(remaining, 256 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    # -- routing ------------------------------------------------------------

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/":
            return self.send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/app.js":
            return self.send_bytes(APP_JS.encode("utf-8"), "application/javascript; charset=utf-8")
        if path == "/style.css":
            return self.send_bytes(STYLE_CSS.encode("utf-8"), "text/css; charset=utf-8")

        if path == "/api/archives":
            archives = find_archives(self.library.root)
            for entry in archives:
                entry.pop("mtime", None)
            return self.send_json({
                "archives": archives,
                "selected": self.library.selected_name,
                "root": str(self.library.root),
            })

        if path == "/api/select":
            name = (params.get("archive") or [None])[0]
            if not name:
                return self.send_json({"error": "archive parameter required"}, 400)
            archive = self.library.select(name)
            if archive is None:
                return self.send_json({"error": "unknown archive"}, 404)
            payload = archive.meta_payload()
            payload["archive"] = name
            return self.send_json(payload)

        if path == "/api/meta":
            archive = self.require_archive()
            if archive is None:
                return
            return self.send_json(archive.meta_payload())

        if path == "/api/messages":
            archive = self.require_archive()
            if archive is None:
                return
            count = min(int(params.get("count", [PAGE_DEFAULT])[0]), PAGE_MAX)
            filters = parse_filter_params(params)
            reverse = params.get("dir", ["asc"])[0] == "desc"
            if "anchor" in params:
                payload = archive.anchor_payload(params["anchor"][0], count, filters, reverse)
                if payload is None:
                    return self.send_json({"error": "unknown message id"}, 404)
                return self.send_json(payload)
            start = int(params.get("start", [0])[0])
            return self.send_json(archive.page_payload(start, count, filters, reverse))

        if path == "/api/resolve":
            archive = self.require_archive()
            if archive is None:
                return
            ids = params.get("ids", [""])[0].split(",")[:100]
            return self.send_json(archive.resolve_payload(ids))

        if path == "/api/search":
            archive = self.require_archive()
            if archive is None:
                return
            query = params.get("q", [""])[0].strip()
            if not query:
                return self.send_json({"query": "", "results": [], "truncated": False})
            author = params.get("author", [None])[0]
            return self.send_json(archive.search_payload(query, author, parse_filter_params(params)))

        if path == "/api/attachment-years":
            archive = self.require_archive()
            if archive is None:
                return
            return self.send_json({"years": archive.attachment_year_counts()})

        if path == "/api/attachments":
            archive = self.require_archive()
            if archive is None:
                return
            count = min(int(params.get("count", [60])[0]), PAGE_MAX)
            start = int(params.get("start", [0])[0])
            year = (params.get("year") or [None])[0]
            return self.send_json(archive.attachments_payload(start, count, year))

        if path == "/api/stats":
            archive = self.require_archive()
            if archive is None:
                return
            return self.send_json(archive.stats_payload())

        if path.startswith("/media/"):
            archive = self.require_archive()
            if archive is None:
                return
            name = path[len("/media/"):]
            fs_path = archive.resolve(name)
            if fs_path is None:
                return self.send_json({"error": "not found"}, 404)
            mime = archive.attachment_mime(name)
            download = "download" in params
            return self.send_media(fs_path, mime, download_name=name if download else None)

        return self.send_json({"error": "not found"}, 404)


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Browse chat archives locally.")
    parser.add_argument(
        "folder", nargs="?",
        help="archival folder, or a single archive folder "
             "(default: the configured archival folder)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    target = Path(args.folder).expanduser() if args.folder else resolve_archive_dir()
    if (target / "meta.json").is_file() and (target / "messages.jsonl").is_file():
        root, initial = target.parent, target.name  # a single archive was passed
    else:
        root, initial = target, None
        if not find_archives(root) and find_archives(Path.cwd()):
            print("note: no archives in the archival folder; "
                  "falling back to the current directory", file=sys.stderr)
            root = Path.cwd()

    library = ArchiveLibrary(root)
    ViewerHandler.library = library
    print(f"Archival folder: {library.root}", file=sys.stderr)
    archives = find_archives(root)
    print(f"  {len(archives)} archive(s) found", file=sys.stderr)
    if archives:
        name = initial if initial in {a["name"] for a in archives} else archives[0]["name"]
        print(f"Loading '{name}' ...", file=sys.stderr)
        library.select(name)
        print(f"  {len(library.selected.messages)} messages, "
              f"{len(library.selected.attachments)} attachments", file=sys.stderr)
    else:
        print("  nothing to serve yet; archive a chat first", file=sys.stderr)

    server = ViewerServer((args.host, args.port), ViewerHandler)
    print(f"Serving at http://{args.host}:{args.port}/ (Ctrl-C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.", file=sys.stderr)


if __name__ == "__main__":
    main()
