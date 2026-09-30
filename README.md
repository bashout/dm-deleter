# Message Bulk Deleter

Bulk delete DM or server messages at 24/minute rate.

**WARNING:** Self-bots violate the platform's Terms of Service. Use at your own risk.

## Features

- Delete your own messages from DMs or servers
- Filter by user, channel, and time range
- Rate-limited to 24 messages per minute (avoids bans)
- Shows real-time progress with time remaining

## Quick Start

### Download a prebuilt binary (no install needed)

1. Go to the [Releases page](https://github.com/bashout/dm-deleter/releases).
2. Download the file for your operating system:
   - **Windows:** `message-deleter-windows.exe`
   - **macOS (Apple Silicon):** `message-deleter-macos-arm64`
   - **macOS (Intel):** `message-deleter-macos-x86_64`
   - **Linux:** `message-deleter-linux`
3. Double-click to run (Windows opens a terminal window automatically).

**macOS / Linux note:** the first time you run it, grant execute permission and
approve the "unidentified developer" prompt:

```bash
chmod +x message-deleter-macos-arm64
./message-deleter-macos-arm64
```

In Finder, right-click the binary → **Open** → **Open Anyway** to bypass
Gatekeeper. Windows may show a SmartScreen warning the first time — click
**More info** → **Run anyway**.

### Install with pipx (developers)

```bash
# Clone the repo
git clone https://github.com/bashout/dm-deleter.git
cd dm-deleter

# Install
pipx install .

# Run
message-deleter
```

### Run from source with uv

Installs the exact pinned versions from `uv.lock`, and fetches a suitable
Python for you:

```bash
git clone https://github.com/bashout/dm-deleter.git
cd dm-deleter

uv run dm_deleter.py
```

### Run directly with Python

Requires Python 3.8 or newer.

```bash
# Install the project and its dependencies
pip install .

# Run
python dm_deleter.py      # Windows
python3 dm_deleter.py     # macOS / Linux
```

## Getting Your Token

**Browser:**
1. Open the platform in Chrome/Edge (`https://discord.com/app`)
2. Press `Ctrl+Shift+I` (or `F12`) to open DevTools
3. Go to **Application** → **Local Storage** → `https://discord.com`
4. Copy the value of the `token` field

**Desktop App:**
```bash
# Linux
cat ~/.config/discord/Local\ Storage/https_discord.com_0.localstorage | grep -o '"token":"[^"]*"' | head -1 | cut -d'"' -f4

# Windows (PowerShell)
Select-String -Path "$env:APPDATA\discord\Local Storage\https_discord.com_0.localstorage" -Pattern '"token":"([^"]+)"' | Select -First 1 -Expand Matches | ForEach { $_.Groups[1].Value }
```

## Usage

1. Run `message-deleter` or `python3 dm_deleter.py`
2. Enter your user token
3. Select mode: `[1]` Delete DM, `[2]` Delete server, or `[3]` Archive a chat
4. Follow the prompts to select user/server/channel
5. Set time range (leave blank for all messages)
6. Confirm deletion

## Archiving

Mode `[3]` archives a full conversation to a local folder — nothing is deleted. The chat is streamed from the beginning of the conversation (one 100-message page at a time, writing as it goes), so chats with hundreds of thousands of messages archive without buffering the whole history in memory.

- Both sides of the chat, in chronological order (all messages, not just yours)
- `meta.json` — the channel ID and chat name; used to locate the archive on resume
- `messages.jsonl` — one minimal record per message: `{id, author_id, author, timestamp, edited_timestamp, content, type, reply_to, attachment_ids}`. `edited_timestamp` is `null` unless the message was edited; `type` marks system messages; `reply_to` links replies
- `attachments/` — every attachment, named `NNNN_message-id_filename` so they sort chronologically
- `manifest.jsonl` — one line per attachment: `{seq, message_id, attachment_id, filename, url, local_path, size, status}`. `local_path` points at the downloaded copy (relative to the archive folder) or is `null` when `status` is `failed` — join to messages on `attachment_ids` / `attachment_id`

**Resume:** if the run is interrupted, rerun the archive for the same chat — it finds the existing folder (by channel ID), skips messages and attachments already saved, retries attachments that previously failed, and continues from where it stopped. Partial files and half-written lines from a hard kill are cleaned up automatically. Messages sent after the original run started are not picked up by a backwards-only fetch; run a fresh archive (delete or rename the folder) to capture those.

The archive is written to `{chatName}-archive-{DD-MM-YY}/` inside your **archival folder**, so every archive run lives in one place. The folder is resolved the same way by the archiver and the viewer:

1. an explicit path, when one is given
2. the `DM_ARCHIVE_DIR` environment variable
3. the `archive_dir` recorded in the app config file (set via archiver menu option `[4] Set archive folder`)
4. the per-OS default: `~/.local/share/discord-deleter/archives` (Linux), `~/Library/Application Support/discord-deleter/archives` (macOS), `%APPDATA%\discord-deleter\archives` (Windows)

Run the archive before deleting: attachment URLs are signed and expire (~24h), so images must be downloaded while the messages are still fetched.

## Browsing an Archive

`archive_viewer.py` serves a local web UI over your archival folder (it reads only `meta.json`, `messages.jsonl`, `manifest.jsonl`, and `attachments/` from each archive inside it). The UI is embedded in the script — this one file is all you need. A dropdown in the header switches between archived chats; newly archived chats appear when the dropdown regains focus:

```bash
python archive_viewer.py            # serves the configured archival folder
python archive_viewer.py ~/archives # or any folder of archives / single archive folder
```

`--host`/`--port` are configurable; it uses only the Python standard library. Only the selected archive is kept in memory (one other recently used archive stays cached for fast switching).

- **Chat** — reply threading, inline images/video/audio, day dividers, and infinite scroll in both directions
- **Search** — full-text search (newest match first), click a result to jump to the message
- **Filters** — date range (from/to), "has attachment", and "has link", combinable with each other and with search; a status line shows how many messages match
- **Sort** — toggle between oldest-first and newest-first ordering; the log opens on the first message of the chosen direction and pages forward from there
- **Jump** — reply previews, search results, and gallery items link back to the original message (filters clear automatically if the target is outside the current view)
- **Gallery** — media grouped into collapsible year sections; expanding a year loads its files in pages (nothing is fetched until a year is opened), with a per-item link back to its message
- **Stats** — message counts per author, per-month histogram, attachment breakdown

## Rate Limiting

- 24 messages per minute (1 every ~2.6 seconds)
- Built-in delay prevents the platform from rate-limiting your account
- Progress shows: `[5/240] Deleted: 5 | Failed: 0 | Elapsed: 00:13 | Remaining: 1d 02:15:00`

## Notes

- You can only delete messages **you** sent (unless in server mode with admin perms)
- Deleted messages cannot be recovered
- This uses the platform's unofficial user API
