#!/usr/bin/env python3
"""
Message Bulk Deleter
Delete YOUR messages from DMs or servers at 24/min rate.
Uses the platform's unofficial user API (self-bot).
WARNING: Self-bots violate the platform ToS. Use at your own risk.
"""

import requests
import time
import json
import re
import os
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import archive_viewer

API_BASE = "https://discord.com/api/v10"  # Platform API endpoint
RATE_LIMIT_DELAY = 2.6  # 24 messages per minute = ~2.5s each, use 2.6s for safety
ATTACHMENT_DELAY = 0.05  # Politeness delay between CDN downloads (CDN is not API rate limited)
FETCH_RETRIES = 5  # attempts per page before the archive run is marked incomplete
FETCH_RETRY_DELAY = 5  # seconds to wait between retries of a failed page fetch


class HistoryFetchError(Exception):
    """A page of channel history could not be fetched after retrying.

    Raised by iter_channel_history so callers can record that the archive
    is incomplete instead of treating an early stop as a finished run."""


class MessageDeleter:
    def __init__(self, token):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self.current_user = None
        self.dm_channels = []
        self.guilds = []
        
    def get_current_user(self):
        """Fetch current user information."""
        resp = self.session.get(f"{API_BASE}/users/@me")
        if resp.status_code == 200:
            self.current_user = resp.json()
            print(f"Logged in as: {self.current_user['username']}#{self.current_user['discriminator']} (ID: {self.current_user['id']})")
            return True
        else:
            print(f"Failed to get user: {resp.status_code} - {resp.text}")
            return False
    
    def get_dm_channels(self):
        """Get all DM channels."""
        resp = self.session.get(f"{API_BASE}/users/@me/channels")
        if resp.status_code == 200:
            self.dm_channels = resp.json()
            return True
        else:
            print(f"Failed to get DM channels: {resp.status_code}")
            return False
    
    def get_guilds(self):
        """Get all guilds (servers) the user is in."""
        resp = self.session.get(f"{API_BASE}/users/@me/guilds")
        if resp.status_code == 200:
            self.guilds = resp.json()
            return True
        else:
            print(f"Failed to get guilds: {resp.status_code}")
            return False
    
    def get_guild_channels(self, guild_id):
        """Get all text channels in a guild."""
        resp = self.session.get(f"{API_BASE}/guilds/{guild_id}/channels")
        if resp.status_code == 200:
            return [c for c in resp.json() if c.get('type') in (0, 5, 10, 11, 12)]  # Text, News, etc.
        else:
            print(f"Failed to get channels: {resp.status_code}")
            return []
    
    def get_all_dm_users(self):
        """Get list of all users you have DMs with (bots excluded)."""
        users = {}
        for channel in self.dm_channels:
            if 'recipients' in channel:
                last_message_id = channel.get('last_message_id')
                for recipient in channel['recipients']:
                    if recipient.get('bot'):
                        continue
                    user_id = recipient['id']
                    if user_id != self.current_user['id']:
                        users[user_id] = {
                            'id': user_id,
                            'username': recipient.get('username', 'Unknown'),
                            'discriminator': recipient.get('discriminator', '0000'),
                            'global_name': recipient.get('global_name', ''),
                            'channel_id': channel['id'],
                            'last_message_id': last_message_id
                        }
        return list(users.values())
    
    def get_channel_history(self, channel_id, limit=100):
        """Fetch all messages from a channel (paginates backwards).
        Raises HistoryFetchError when a page cannot be fetched after retrying."""
        all_messages = []
        last_id = None

        while True:
            params = {"limit": limit}
            if last_id:
                params["before"] = last_id

            resp = self._fetch_page_with_retries(
                f"{API_BASE}/channels/{channel_id}/messages", params)

            messages = resp.json()
            if not messages:
                break

            all_messages.extend(messages)
            last_id = messages[-1]['id']

            if len(messages) < limit:
                break

            time.sleep(0.5)

        return all_messages

    def iter_channel_history(self, channel_id, after_id="0", limit=100):
        """Yield messages oldest-first, one fetched page at a time, starting after after_id.
        Used by archive mode so huge chats stream without buffering the full history.
        Raises HistoryFetchError when a page cannot be fetched after retrying."""
        cursor = str(after_id)
        while True:
            params = {"limit": limit, "after": cursor}
            resp = self._fetch_page_with_retries(
                f"{API_BASE}/channels/{channel_id}/messages", params)

            messages = resp.json()
            if not messages:
                return

            # `after` pages come back oldest-first; enforce just in case
            messages.sort(key=lambda m: int(m['id']))
            for msg in messages:
                yield msg

            cursor = messages[-1]['id']
            time.sleep(0.5)

    def _fetch_page_with_retries(self, url, params):
        """GET url, retrying rate limits and transient failures. Raises
        HistoryFetchError once FETCH_RETRIES attempts are exhausted, or
        immediately for statuses that will not succeed on retry."""
        last_error = "unknown error"
        for attempt in range(1, FETCH_RETRIES + 1):
            try:
                resp = self.session.get(url, params=params)
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"
            else:
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 429:
                    retry_after = max(float(resp.headers.get("Retry-After") or FETCH_RETRY_DELAY), 1.0)
                    last_error = "rate limited (429)"
                    print(f"\n  Rate limited; retrying in {retry_after:.0f}s...")
                    time.sleep(retry_after)
                    continue
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code in (401, 403, 404):
                    break  # authentication or access errors will not succeed on retry
            if attempt < FETCH_RETRIES:
                print(f"\n  {last_error}; retrying in {FETCH_RETRY_DELAY}s "
                      f"(attempt {attempt}/{FETCH_RETRIES})...")
                time.sleep(FETCH_RETRY_DELAY)
        raise HistoryFetchError(last_error)
    
    def filter_messages_in_range(self, messages, start_time, end_time, my_only=True):
        """Filter messages within time range, optionally only yours."""
        start_ts = start_time.timestamp()
        end_ts = end_time.timestamp()
        
        filtered = []
        for msg in messages:
            msg_time = datetime.fromisoformat(msg['timestamp'].replace('Z', '+00:00')).timestamp()
            if start_ts <= msg_time <= end_ts:
                if my_only and msg['author']['id'] != self.current_user['id']:
                    continue
                filtered.append(msg)
        
        filtered.sort(key=lambda x: x['timestamp'])
        return filtered
    
    def delete_message(self, channel_id, message_id):
        """Delete a single message."""
        resp = self.session.delete(f"{API_BASE}/channels/{channel_id}/messages/{message_id}")
        return resp.status_code in (200, 204)

    def download_attachment(self, url, dest_path):
        """Stream an attachment to dest_path via a .part file, renamed on completion.
        Returns bytes written, or None on failure."""
        tmp_path = dest_path.with_name(dest_path.name + ".part")
        try:
            resp = requests.get(url, stream=True, timeout=30)
            if resp.status_code != 200:
                return None
            size = 0
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    size += len(chunk)
            tmp_path.replace(dest_path)
            return size
        except (requests.RequestException, OSError):
            try:
                tmp_path.unlink()
            except OSError:
                pass
            return None
    
    def delete_with_rate_limit(self, messages, channel_id):
        """Delete messages at 24 per minute with progress."""
        total = len(messages)
        print(f"\nFound {total} messages to delete.")
        print(f"Will delete at ~24/min (1 every {RATE_LIMIT_DELAY:.1f}s)...")
        
        confirm = input("Continue? (y/N): ").strip().lower()
        if confirm != 'y':
            print("Cancelled.")
            return
        
        deleted = 0
        failed = 0
        start_time = time.time()
        
        for i, msg in enumerate(messages, 1):
            message_id = msg['id']
            
            success = self.delete_message(channel_id, message_id)
            if success:
                deleted += 1
            else:
                failed += 1
            
            # Calculate time remaining
            remaining = (total - i) * RATE_LIMIT_DELAY
            elapsed = time.time() - start_time
            
            def fmt_secs(s):
                seconds = int(s)
                days = seconds // 86400
                seconds %= 86400
                hours = seconds // 3600
                seconds %= 3600
                minutes = seconds // 60
                seconds %= 60
                
                parts = []
                if days > 0:
                    parts.append(f"{days}d")
                if hours > 0 or days > 0:
                    parts.append(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
                else:
                    parts.append(f"{minutes:02d}:{seconds:02d}")
                return " ".join(parts)
            
            print(f"[{i}/{total}] Deleted: {deleted} | Failed: {failed} | Elapsed: {fmt_secs(elapsed)} | Remaining: {fmt_secs(remaining)} | Rate: {RATE_LIMIT_DELAY:.1f}s/msg", end='\r')
            
            time.sleep(RATE_LIMIT_DELAY)
        
        print(f"\nDone. Deleted {deleted}/{total}, Failed: {failed}")


def parse_datetime(prompt):
    """Parse user input into datetime."""
    while True:
        date_str = input(prompt).strip()
        if not date_str:
            return None
        
        try:
            for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%m/%d/%Y %H:%M"]:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except ValueError:
            print(f"Invalid format. Use: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")


def sanitize_filename(name, fallback="file"):
    """Strip characters that are unsafe in filenames."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or fallback


def app_config_dir():
    """Per-OS application data directory (holds config.json and the default
    archival folder). Cross-platform safe: no hardcoded absolute paths.

    The pre-rename data folder is returned when only it exists, so archives
    and config written by older versions keep working."""
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or str(home / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share"))
    config_dir = base / "message-deleter"
    if not config_dir.exists() and (base / "discord-deleter").exists():
        return base / "discord-deleter"  # pre-rename data folder
    return config_dir


def resolve_archive_dir(explicit=None):
    """The archival folder that stores every archive run (one folder per chat).

    Priority: explicit argument, then the DM_ARCHIVE_DIR environment variable,
    then the archive_dir recorded in the app config file, then the per-OS default."""
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


def configure_archive_dir(current):
    """Prompt for a new archival folder and persist it to the app config."""
    print("\n" + "="*80)
    print("SET ARCHIVE FOLDER")
    print(f"Current: {current}")
    print("Every archive run is stored as its own folder inside this one.")
    raw = input("New archive folder (blank to keep current): ").strip()
    if not raw:
        print("Archive folder unchanged.")
        return current
    new_dir = Path(raw).expanduser()
    try:
        new_dir.mkdir(parents=True, exist_ok=True)
        config_dir = app_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"archive_dir": str(new_dir)}) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"Could not use that folder: {exc}")
        return current
    print(f"Archive folder set to: {new_dir}")
    print("(The DM_ARCHIVE_DIR environment variable still overrides this when set.)")
    return new_dir


def select_dm_user(tool):
    """Fetch DM channels and prompt the user to select one. Returns the user dict or None."""
    if not tool.get_dm_channels():
        print("Failed to fetch DM channels.")
        return None

    users = tool.get_all_dm_users()
    if not users:
        print("No DM users found.")
        return None

    print("\nSort by:")
    print("[1] Recent interaction (default)")
    print("[2] Alphabetical by username")
    sort_choice = input("Sort mode (1 or 2): ").strip()
    if sort_choice == '2':
        users.sort(key=lambda u: (u.get('username') or '').lower())
    else:
        users.sort(key=lambda u: int(u.get('last_message_id') or 0), reverse=True)

    print("\n" + "="*80)
    print("SELECT A USER")
    print("="*80)

    for i, user in enumerate(users, 1):
        display_name = user['global_name'] or user['username']
        print(f"[{i}] {display_name}#{user['discriminator']} (ID: {user['id']})")

    print("\n[0] Cancel")

    try:
        choice = int(input("Select user (number): ").strip())
        if choice == 0:
            return None
        return users[choice - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return None


def select_guild_channel(tool):
    """Prompt the user to pick a guild and channel. Returns (guild, channel) or None."""
    if not tool.get_guilds():
        print("Failed to fetch guilds.")
        return None

    print("\n" + "="*80)
    print("SELECT A SERVER")
    print("="*80)

    for i, guild in enumerate(tool.guilds, 1):
        print(f"[{i}] {guild['name']} (ID: {guild['id']})")

    print("\n[0] Cancel")

    try:
        choice = int(input("Select server (number): ").strip())
        if choice == 0:
            return None
        selected_guild = tool.guilds[choice - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return None

    channels = tool.get_guild_channels(selected_guild['id'])
    if not channels:
        print("No text channels found.")
        return None

    print("\n" + "="*80)
    print(f"SELECT A CHANNEL IN {selected_guild['name']}")
    print("="*80)

    for i, channel in enumerate(channels, 1):
        print(f"[{i}] #{channel['name']} (ID: {channel['id']})")

    print("\n[0] Cancel")

    try:
        choice = int(input("Select channel (number): ").strip())
        if choice == 0:
            return None
        return selected_guild, channels[choice - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return None


def minimal_message(msg):
    """Project a raw API message down to the minimal archival record."""
    return {
        "id": msg["id"],
        "author_id": msg["author"]["id"],
        "author": msg["author"].get("global_name") or msg["author"].get("username"),
        "timestamp": msg["timestamp"],
        "edited_timestamp": msg.get("edited_timestamp"),  # null = never edited
        "content": msg.get("content", ""),
        "type": msg.get("type", 0),
        "reply_to": (msg.get("message_reference") or {}).get("message_id"),
        "attachment_ids": [a["id"] for a in msg.get("attachments") or []],
    }


def find_existing_archive(channel_id, archive_dir):
    """Locate the most recent archive of this channel in the archival folder
    (resume target). Recency is judged by messages.jsonl mtime — it updates on
    every resume append, unlike the folder's own mtime — falling back to the
    folder mtime for archives that never wrote a message."""
    matches = []
    try:
        children = sorted(Path(archive_dir).iterdir())
    except OSError:
        return None
    for path in children:
        meta = path / "meta.json"
        if not path.is_dir() or not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("channel_id") != str(channel_id):
            continue
        marker = path / "messages.jsonl"
        try:
            mtime = (marker if marker.exists() else path).stat().st_mtime
        except OSError:
            continue
        matches.append((mtime, path))
    return max(matches, key=lambda m: m[0], default=(0, None))[1]


def load_message_records(path):
    """Load message records from messages.jsonl, truncating any partial tail line
    left behind by a hard kill (a partial line is always the last line written)."""
    records = []
    valid_end = 0
    if path.exists():
        with open(path, "rb") as f:
            for raw in f:
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError:
                    break
                valid_end += len(raw)
        if valid_end < path.stat().st_size:
            with open(path, "r+b") as f:
                f.truncate(valid_end)
    return records


def compact_manifest(folder):
    """Rewrite manifest.jsonl with one entry per attachment (latest wins, retries
    supersede earlier failures). The rewrite is atomic — written to a temp file
    and renamed into place — so a hard kill cannot leave a truncated manifest.
    Returns the compacted entries."""
    latest = {}
    path = folder / "manifest.jsonl"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    break
                latest[entry["attachment_id"]] = entry
    tmp_path = path.with_name(path.name + ".part")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for entry in latest.values():
            f.write(json.dumps(entry) + "\n")
    tmp_path.replace(path)
    return list(latest.values())


def read_archive_status(folder):
    """The completion flag recorded by the last run: True (finished), False
    (interrupted or fetch failed), or None when no flag was ever written."""
    try:
        data = json.loads((Path(folder) / "status.json").read_text(encoding="utf-8"))
        return bool(data.get("complete"))
    except (OSError, ValueError, AttributeError):
        return None


def mark_archive_status(folder, complete):
    """Record whether the archive run finished, so the next resume and the user
    can tell a complete archive from a partial one."""
    try:
        (Path(folder) / "status.json").write_text(
            json.dumps({"complete": complete}) + "\n", encoding="utf-8")
    except OSError:
        pass  # the flag is advisory; the archive data itself is unaffected


def archive_chat(tool, channel_id, channel_label, archive_dir):
    """Archive the chat as a stream: fetch forward from the beginning of the
    conversation, write each message as it arrives, and resume an existing archive
    directory for this channel if one is already present."""
    channel_id = str(channel_id)
    archive_dir = Path(archive_dir)
    folder = find_existing_archive(channel_id, archive_dir)
    resumed = folder is not None
    if folder:
        records = load_message_records(folder / "messages.jsonl")
        archived_ids = {r["id"] for r in records}
        after_id = records[-1]["id"] if records else "0"
        entries = compact_manifest(folder)
        recorded = {e["attachment_id"]: e for e in entries}
        seq = max((e["seq"] for e in entries), default=0)
        note = "" if read_archive_status(folder) is not False else " (previous run did not finish)"
        print(f"\nResuming archive: {folder}/ ({len(archived_ids)} messages already saved{note})")
    else:
        date_part = datetime.now().strftime("%d-%m-%y")
        folder = archive_dir / f"{sanitize_filename(channel_label, 'chat')}-archive-{date_part}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.json").write_text(
            json.dumps({"channel_id": channel_id, "chat": channel_label}) + "\n",
            encoding="utf-8")
        archived_ids, after_id, recorded, seq = set(), "0", {}, 0
        print(f"\nStarting new archive: {folder}/")

    att_dir = folder / "attachments"
    for stale in att_dir.glob("*.part"):
        stale.unlink()

    def att_key(att):
        """Attachment id from a raw API attachment, or from a manifest entry on retry."""
        return att.get("id") or att.get("attachment_id")

    def manifest_entry(att, message_id, dest, size):
        return {
            "seq": seq,
            "message_id": message_id,
            "attachment_id": att_key(att),
            "filename": att.get("filename"),
            "url": att.get("url"),
            "local_path": f"attachments/{dest.name}" if size is not None else None,
            "size": size,
            "status": "ok" if size is not None else "failed",
        }

    saved = 0
    failed = 0
    count = len(archived_ids)

    try:
        with open(folder / "messages.jsonl", "a", encoding="utf-8") as jf, \
             open(folder / "manifest.jsonl", "a", encoding="utf-8") as mf:

            def save_attachment(att, message_id):
                nonlocal seq, saved, failed
                att_dir.mkdir(exist_ok=True)
                seq += 1
                dest = att_dir / f"{seq:04d}_{message_id}_{sanitize_filename(att.get('filename', 'attachment'))}"
                size = tool.download_attachment(att.get("url"), dest)
                entry = manifest_entry(att, message_id, dest, size)
                mf.write(json.dumps(entry) + "\n")
                if size is None:
                    failed += 1
                else:
                    saved += 1
                recorded[att_key(att)] = entry
                time.sleep(ATTACHMENT_DELAY)

            def already_saved(entry):
                return (entry
                        and entry["status"] == "ok"
                        and entry["local_path"]
                        and (folder / entry["local_path"]).exists())

            if resumed:
                # Retry attachments that failed in a previous run (signed URLs may still be valid)
                for entry in list(recorded.values()):
                    if entry["status"] == "failed":
                        save_attachment(entry, entry["message_id"])

            for msg in tool.iter_channel_history(channel_id, after_id=after_id):
                if msg["id"] in archived_ids:
                    continue

                for att in msg.get("attachments") or []:
                    if already_saved(recorded.get(att.get("id"))):
                        continue
                    save_attachment(att, msg["id"])

                jf.write(json.dumps(minimal_message(msg)) + "\n")
                mf.flush()
                jf.flush()
                archived_ids.add(msg["id"])
                count = len(archived_ids)
                print(f"\r[{count} msgs] this run: {saved} saved, {failed} failed", end='')

        print()
        compact_manifest(folder)
        mark_archive_status(folder, True)
        print(f"Done. {folder}/ now holds {count} messages.")
        return folder
    except HistoryFetchError as exc:
        mark_archive_status(folder, False)
        print(f"\n\nFetch failed ({exc}); the archive is incomplete.")
        print(f"Rerun the archive for the same chat to resume: {folder}/")
    except KeyboardInterrupt:
        mark_archive_status(folder, False)
        print(f"\n\nInterrupted. Rerun the archive for the same chat to resume: {folder}/")


def browse_archives(focus_channel_id=None):
    """Serve the archival folder in the local viewer and open it in the browser.
    With focus_channel_id, the viewer opens directly on that chat's archive.
    Blocks until the user presses Enter, then stops the server and returns."""
    archive_dir = resolve_archive_dir()
    select_name = None
    if focus_channel_id:
        focus = find_existing_archive(focus_channel_id, archive_dir)
        if focus and (focus / "messages.jsonl").exists():
            select_name = focus.name
    try:
        server, url = archive_viewer.create_server(archive_dir, select_archive=select_name)
    except OSError as exc:
        print(f"Could not start the viewer: {exc}")
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"\nViewer running at {url}")
    webbrowser.open(url)
    try:
        input("Press Enter to stop the viewer and return to the menu... ")
    except (KeyboardInterrupt, EOFError):
        pass
    server.shutdown()
    server.server_close()
    print("Viewer stopped.")


def handle_archive(tool):
    """Handle chat archiving (JSONL + attachments, nothing is deleted)."""
    archive_dir = resolve_archive_dir()
    print("\n" + "="*80)
    print("ARCHIVE A CHAT")
    print(f"Archival folder: {archive_dir}")
    print("="*80)
    print("[1] Archive a DM")
    print("[2] Archive a server channel")
    print("[0] Cancel")

    try:
        choice = int(input("Select (0-2): ").strip())
    except ValueError:
        print("Invalid selection.")
        return

    if choice == 1:
        selected_user = select_dm_user(tool)
        if not selected_user:
            return
        channel_id = selected_user['channel_id']
        label = selected_user['global_name'] or selected_user['username']
    elif choice == 2:
        selected = select_guild_channel(tool)
        if not selected:
            return
        guild, channel = selected
        channel_id = channel['id']
        label = f"{guild['name']} #{channel['name']}"
    else:
        return

    folder = archive_chat(tool, channel_id, label, archive_dir)
    if folder and input("\nOpen this archive in the viewer now? (y/N): ").strip().lower() == 'y':
        browse_archives(focus_channel_id=channel_id)


def handle_dm_deletion(tool):
    """Handle DM message deletion."""
    selected_user = select_dm_user(tool)
    if not selected_user:
        return
    
    print("\n" + "="*80)
    print("SELECT TIME RANGE")
    print("Leave blank for no limit")
    print("="*80)
    
    start_time = parse_datetime("Start date (YYYY-MM-DD HH:MM:SS): ")
    end_time = parse_datetime("End date (YYYY-MM-DD HH:MM:SS): ")
    
    if start_time is None:
        start_time = datetime(2015, 1, 1)
    if end_time is None:
        end_time = datetime.now() + timedelta(days=1)
    
    print(f"\nTime range: {start_time} to {end_time}")
    
    channel_id = selected_user['channel_id']
    print(f"\nFetching messages from DM with {selected_user['username']}...")

    try:
        all_messages = tool.get_channel_history(channel_id, limit=100)
    except HistoryFetchError as exc:
        print(f"Could not fetch channel history ({exc}).")
        return
    print(f"Fetched {len(all_messages)} total messages from this DM.")
    
    my_messages = tool.filter_messages_in_range(all_messages, start_time, end_time, my_only=True)
    
    if not my_messages:
        print("No messages from you found in that time range.")
        return
    
    tool.delete_with_rate_limit(my_messages, channel_id)


def handle_server_deletion(tool):
    """Handle server message deletion."""
    selected = select_guild_channel(tool)
    if not selected:
        return
    selected_guild, selected_channel = selected
    
    # Ask: delete only my messages or all messages
    print("\n" + "="*80)
    print("DELETE OPTIONS")
    print("="*80)
    my_only = input("Delete only YOUR messages? (y/N, default=N): ").strip().lower() == 'y'
    
    # Time range
    print("\n" + "="*80)
    print("SELECT TIME RANGE")
    print("Leave blank for no limit")
    print("="*80)
    
    start_time = parse_datetime("Start date (YYYY-MM-DD HH:MM:SS): ")
    end_time = parse_datetime("End date (YYYY-MM-DD HH:MM:SS): ")
    
    if start_time is None:
        start_time = datetime(2015, 1, 1)
    if end_time is None:
        end_time = datetime.now() + timedelta(days=1)
    
    print(f"\nTime range: {start_time} to {end_time}")
    print(f"Deleting: {'ONLY your messages' if my_only else 'ALL messages'}")
    
    channel_id = selected_channel['id']
    print(f"\nFetching messages from #{selected_channel['name']}...")

    try:
        all_messages = tool.get_channel_history(channel_id, limit=100)
    except HistoryFetchError as exc:
        print(f"Could not fetch channel history ({exc}).")
        return
    print(f"Fetched {len(all_messages)} total messages from this channel.")
    
    filtered_messages = tool.filter_messages_in_range(all_messages, start_time, end_time, my_only=my_only)
    
    if not filtered_messages:
        print("No messages found matching criteria.")
        return
    
    tool.delete_with_rate_limit(filtered_messages, channel_id)


def main():
    print("="*80)
    print("MESSAGE BULK DELETER")
    print("Delete messages from DMs or servers at 24/min rate")
    print("WARNING: Self-bots violate the platform ToS. Use at your own risk.")
    print("="*80)
    
    token = input("Enter your user token: ").strip()
    if not token:
        print("No token provided. Exiting.")
        return
    
    tool = MessageDeleter(token)
    
    if not tool.get_current_user():
        print("Invalid token or authentication failed.")
        return
    
    while True:
        archive_dir = resolve_archive_dir()
        print("\n" + "="*80)
        print("SELECT MODE")
        print(f"Archival folder: {archive_dir}")
        print("="*80)
        print("[1] Delete DM messages")
        print("[2] Delete server messages")
        print("[3] Archive a chat (JSONL + attachments, no deletion)")
        print("[4] Set archive folder")
        print("[5] Browse archives in the viewer")
        print("[0] Cancel")

        try:
            mode = int(input("Mode (0-5): ").strip())
        except ValueError:
            print("Invalid selection.")
            return

        if mode == 1:
            handle_dm_deletion(tool)
            return
        elif mode == 2:
            handle_server_deletion(tool)
            return
        elif mode == 3:
            handle_archive(tool)
            return
        elif mode == 4:
            configure_archive_dir(archive_dir)
        elif mode == 5:
            browse_archives()
        else:
            print("Cancelled.")
            return


if __name__ == "__main__":
    main()
