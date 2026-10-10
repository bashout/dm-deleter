"""Interactive CLI for deleting and archiving your own messages.

Delete YOUR messages from DMs or servers at 24/min rate.
Uses the platform's unofficial user API (self-bot).
WARNING: Self-bots violate the platform ToS. Use at your own risk.

Entry point: guillotine.py"""


import argparse
import threading
import webbrowser
from datetime import datetime, timedelta

from message_guillotine.api import HistoryFetchError, MessageGuillotine
from message_guillotine.archive_format import (
    find_existing_archive,
    list_archives,
    read_meta,
)
from message_guillotine.archiver import archive_chat
from message_guillotine.config import configure_archive_dir, resolve_archive_dir
from message_guillotine.viewer.server import create_server


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
    if not tool.get_guilds() or not tool.guilds:
        print("No servers found.")
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


def browse_archives(focus_channel_id=None, archive_dir=None):
    """Serve the archival folder in the local viewer and open it in the browser.
    With focus_channel_id, the viewer opens directly on that chat's archive.
    Blocks until the user presses Enter, then stops the server and returns."""
    archive_dir = resolve_archive_dir(archive_dir)
    select_name = None
    if focus_channel_id:
        focus = find_existing_archive(focus_channel_id, archive_dir)
        if focus and (focus / "messages.jsonl").exists():
            select_name = focus.name
    try:
        server, url = create_server(archive_dir, select_archive=select_name)
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


def pick_merge_target(channel_id, archive_dir):
    """Offer merging into an existing archive when the chat has no archive of
    its own. Returns the chosen folder path, or None to start a new archive.
    Returns False when the user cancels the archive run entirely."""
    if find_existing_archive(channel_id, archive_dir) is not None:
        return None  # this chat already has an archive: it resumes automatically
    others = list_archives(archive_dir)
    if not others:
        return None

    while True:
        print("\n" + "="*80)
        print("NO PREVIOUS ARCHIVE FOR THIS CHAT")
        print("="*80)
        print("[1] Start a new archive (default)")
        print("[2] Merge into an existing archive")
        print("[0] Cancel")

        try:
            choice = int(input("Select (0-2): ").strip())
        except ValueError:
            print("Invalid selection.")
            continue
        if choice == 0:
            return False
        if choice == 1:
            return None
        if choice != 2:
            print("Invalid selection.")
            continue
        break

    print("\n" + "="*80)
    print("MERGE INTO AN EXISTING ARCHIVE")
    print("="*80)
    for i, path in enumerate(others, 1):
        meta = read_meta(path)
        chat = meta.get("chat") or path.name
        channel = meta.get("channel_id") or "?"
        print(f"[{i}] {chat} (channel ID: {channel})")
    print("\n[0] Cancel")

    while True:
        try:
            choice = int(input("Select archive (number): ").strip())
        except ValueError:
            print("Invalid selection.")
            continue
        if choice == 0:
            return False
        if not 1 <= choice <= len(others):
            print("Invalid selection.")
            continue
        return others[choice - 1]


def handle_archive(tool, archive_dir=None):
    """Handle chat archiving (JSONL + attachments, nothing is deleted)."""
    archive_dir = resolve_archive_dir(archive_dir)
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

    merge_target = pick_merge_target(str(channel_id), archive_dir)
    if merge_target is False:
        print("Cancelled.")
        return
    folder = archive_chat(tool, channel_id, label, archive_dir,
                          merge_target=merge_target)
    if folder and input("\nOpen this archive in the viewer now? (y/N): ").strip().lower() == 'y':
        browse_archives(focus_channel_id=channel_id, archive_dir=archive_dir)


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
    print("Deleting: ONLY your messages")

    channel_id = selected_channel['id']
    print(f"\nFetching messages from #{selected_channel['name']}...")

    try:
        all_messages = tool.get_channel_history(channel_id, limit=100)
    except HistoryFetchError as exc:
        print(f"Could not fetch channel history ({exc}).")
        return
    print(f"Fetched {len(all_messages)} total messages from this channel.")

    filtered_messages = tool.filter_messages_in_range(all_messages, start_time, end_time, my_only=True)
    
    if not filtered_messages:
        print("No messages found matching criteria.")
        return
    
    tool.delete_with_rate_limit(filtered_messages, channel_id)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="message-guillotine",
        description="Delete and archive your DM and server messages "
                     "(self-bot — violates the platform ToS, use at your own risk).")
    parser.add_argument("--archive-dir", metavar="FOLDER",
                        help="archival folder for archives and the viewer "
                             "(overrides DM_ARCHIVE_DIR and the config file; "
                             "menu option [4] can still change it in-session)")
    args = parser.parse_args(argv)

    print("="*80)
    print("MESSAGE GUILLOTINE")
    print("Delete messages from DMs or servers at 24/min rate")
    print("WARNING: Self-bots violate the platform ToS. Use at your own risk.")
    print("="*80)

    token = input("Enter your user token: ").strip()
    if not token:
        print("No token provided. Exiting.")
        return

    tool = MessageGuillotine(token)

    if not tool.get_current_user():
        print("Invalid token or authentication failed.")
        return

    # The --archive-dir override stays in effect until the user picks a
    # different folder in-session (menu option [4]), which then wins.
    cli_archive_dir = args.archive_dir
    while True:
        archive_dir = resolve_archive_dir(cli_archive_dir)
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
            handle_archive(tool, archive_dir=cli_archive_dir)
            return
        elif mode == 4:
            new_dir = configure_archive_dir(archive_dir)
            if new_dir != archive_dir:
                cli_archive_dir = None  # the in-session choice replaces the CLI arg
        elif mode == 5:
            browse_archives(archive_dir=cli_archive_dir)
        else:
            print("Cancelled.")
            return


if __name__ == "__main__":
    main()
