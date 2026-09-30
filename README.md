# Message Deleter

Bulk delete and archive your DM and server messages via the platform's unofficial user API (self-bot — violates the platform ToS, use at your own risk).

## Features

| Feature | Description |
|---------|-------------|
| DM deletion | Delete your own DM messages, filtered by user and time range |
| Server deletion | Delete your messages (or all, with admin) from a server channel |
| Rate limiting | 24 messages/minute with live progress and ETA |
| Archiving | Save a full chat — both sides, oldest first — as `messages.jsonl` + `attachments/`, streamed page by page |
| Resume | Interrupted archives pick up where they stopped; partial writes are cleaned up automatically |
| Attachments | Downloaded with atomic writes and retried on resume; runs that end early are flagged incomplete in `status.json` |
| Viewer | Local web UI to browse archives: search, date/attachment/link filters, reply threading, media gallery, stats — launched from menu option `[5]` or `archive-viewer`, opens your browser automatically |
| Config | Archive folder set via CLI arg, `DM_ARCHIVE_DIR`, or menu option `[4]`; per-OS default otherwise |

## Development

Requires Python 3.8+. `requests` is the only runtime dependency.

```bash
git clone https://github.com/bashout/dm-deleter.git
cd dm-deleter

# Run with uv (pinned deps from uv.lock)
uv run dm_deleter.py        # deleter / archiver
uv run archive_viewer.py    # archive viewer (localhost web UI)

# Or install
pip install .
message-deleter
archive-viewer
```

The tool prompts for your user token on start. Archives are written to your
archive folder (one folder per chat); the viewer serves that folder.

Run the tests (config resolution, archive format, archiver resume/retry,
API filtering, viewer queries, and the HTTP server end to end):

```bash
uv sync --extra dev --locked
uv run pytest
```

Build a standalone binary (PyInstaller; includes the viewer):

```bash
uv sync --extra build --locked
uv run python build_exe.py
```
