"""Local web server for browsing archives plus the standalone viewer entry.

Serves the embedded UI (viewer.frontend) and a small JSON API over an
archival folder: archive selection, message paging, search, media gallery,
and stats. Loading and querying live in viewer.archive.

Usage:
    python archive_viewer.py [ARCHIVES_DIR_OR_ARCHIVE_FOLDER] [--host HOST] [--port PORT]

Serves the configured archival folder (one folder per archived chat) with a
selector for choosing which archive to view. A single archive folder
argument is served with its siblings. With no path, the archival folder is
resolved the same way the archiver resolves it (see message_guillotine.config)."""


import argparse
import ipaddress
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from message_guillotine.config import resolve_archive_dir
from message_guillotine.viewer.archive import Archive, find_archives, parse_filter_params
from message_guillotine.viewer.frontend import APP_JS, INDEX_HTML, STYLE_CSS


PAGE_DEFAULT = 50
PAGE_MAX = 200


class ClientInputError(ValueError):
    """A request query parameter was malformed; the handler replies 400."""


def int_param(params, name, default):
    """An int query parameter value, or default when absent. Raises
    ClientInputError on malformed input instead of crashing the handler."""
    raw = (params.get(name) or [None])[0]
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ClientInputError(f"invalid {name}: {raw!r}")


# ---------------------------------------------------------------------------
# Embedded viewer UI (served from memory, no external files)
# ---------------------------------------------------------------------------


class ArchiveLibrary:
    """The archival folder and the archives inside it. One archive is loaded
    at a time; a couple of recently used ones stay cached in memory."""

    CACHE_MAX = 2

    def __init__(self, root):
        self.root = Path(root).absolute()
        self._cache = {}  # folder name -> Archive; insertion order is LRU order
        self._lock = threading.Lock()  # guards _cache and selected across handler threads
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
        with self._lock:
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
        try:
            self._route_get()
        except ClientInputError as exc:
            self.send_json({"error": str(exc)}, 400)

    def host_allowed(self):
        """Reject non-local Host headers (DNS-rebinding protection). The Host
        hostname must be an IP literal or "localhost"; DNS names are refused,
        since a rebound name would resolve to this loopback server."""
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return False
        if host.startswith("[") and "]" in host:  # [::1]:port
            name = host[1:host.index("]")]
        elif ":" in host and host.rsplit(":", 1)[-1].isdigit():
            name = host.rsplit(":", 1)[0]
        else:
            name = host
        if name == "localhost":
            return True
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            return False

    def _route_get(self):
        if not self.host_allowed():
            return self.send_json({"error": "forbidden host"}, 403)
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
            count = min(int_param(params, "count", PAGE_DEFAULT), PAGE_MAX)
            filters = parse_filter_params(params)
            reverse = params.get("dir", ["asc"])[0] == "desc"
            if "anchor" in params:
                payload = archive.anchor_payload(params["anchor"][0], count, filters, reverse)
                if payload is None:
                    return self.send_json({"error": "unknown message id"}, 404)
                return self.send_json(payload)
            start = int_param(params, "start", 0)
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
            count = min(int_param(params, "count", 60), PAGE_MAX)
            start = int_param(params, "start", 0)
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


def create_server(root, select_archive=None, host="127.0.0.1", port=8765):
    """Create a viewer server for an archival folder (embedding entry point).

    `select_archive` names a folder under `root` to open directly; when it is
    missing or unknown the most recently modified archive is preselected
    instead, matching main(). Binds to `port`, falling back to an ephemeral
    port when it is already taken. Returns (server, url); the caller runs
    server.serve_forever() (own thread or main) and server.shutdown() to stop.
    """
    root = Path(root)
    library = ArchiveLibrary(root)
    ViewerHandler.library = library
    archives = find_archives(root)
    if select_archive in {a["name"] for a in archives}:
        library.select(select_archive)
    elif archives:
        library.select(archives[0]["name"])
    try:
        server = ViewerServer((host, port), ViewerHandler)
    except OSError:
        if port == 0:
            raise
        server = ViewerServer((host, 0), ViewerHandler)
    bound_host, bound_port = server.server_address[:2]
    return server, f"http://{bound_host}:{bound_port}/"


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

    try:
        server, url = create_server(root, select_archive=initial,
                                    host=args.host, port=args.port)
    except OSError as exc:
        sys.exit(f"could not start the viewer: {exc}")

    library = ViewerHandler.library
    print(f"Archival folder: {library.root}", file=sys.stderr)
    archives = find_archives(root)
    print(f"  {len(archives)} archive(s) found", file=sys.stderr)
    if library.selected:
        print(f"  {len(library.selected.messages)} messages, "
              f"{len(library.selected.attachments)} attachments", file=sys.stderr)
    else:
        print("  nothing to serve yet; archive a chat first", file=sys.stderr)
    print(f"Serving at {url} (Ctrl-C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.", file=sys.stderr)


if __name__ == "__main__":
    main()
