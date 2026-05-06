#!/usr/bin/env python3
"""
Message Bulk Deleter
Delete YOUR messages from DMs or servers at 24/min rate.
Uses the platform's unofficial user API (self-bot).
WARNING: Self-bots violate the platform ToS. Use at your own risk.
"""

import requests
import time
from datetime import datetime, timedelta

API_BASE = "https://discord.com/api/v9"  # Platform API endpoint
RATE_LIMIT_DELAY = 2.6  # 24 messages per minute = ~2.5s each, use 2.6s for safety

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
        """Get list of all users you have DMs with."""
        users = {}
        for channel in self.dm_channels:
            if 'recipients' in channel:
                for recipient in channel['recipients']:
                    user_id = recipient['id']
                    if user_id != self.current_user['id']:
                        users[user_id] = {
                            'id': user_id,
                            'username': recipient.get('username', 'Unknown'),
                            'discriminator': recipient.get('discriminator', '0000'),
                            'global_name': recipient.get('global_name', ''),
                            'channel_id': channel['id']
                        }
        return list(users.values())
    
    def get_channel_history(self, channel_id, limit=100):
        """Fetch all messages from a channel (paginates)."""
        all_messages = []
        last_id = None
        
        while True:
            params = {"limit": limit}
            if last_id:
                params["before"] = last_id
            
            resp = self.session.get(f"{API_BASE}/channels/{channel_id}/messages", params=params)
            
            if resp.status_code != 200:
                print(f"  Error fetching messages: {resp.status_code}")
                break
            
            messages = resp.json()
            if not messages:
                break
            
            all_messages.extend(messages)
            last_id = messages[-1]['id']
            
            if len(messages) < limit:
                break
            
            time.sleep(0.5)
        
        return all_messages
    
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


def handle_dm_deletion(tool):
    """Handle DM message deletion."""
    if not tool.get_dm_channels():
        print("Failed to fetch DM channels.")
        return
    
    users = tool.get_all_dm_users()
    if not users:
        print("No DM users found.")
        return
    
    print("\n" + "="*80)
    print("SELECT A USER TO DELETE MESSAGES FROM")
    print("="*80)
    
    for i, user in enumerate(users, 1):
        display_name = user['global_name'] or user['username']
        print(f"[{i}] {display_name}#{user['discriminator']} (ID: {user['id']})")
    
    print("\n[0] Cancel")
    
    try:
        choice = int(input("Select user (number): ").strip())
        if choice == 0:
            return
        selected_user = users[choice - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
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
    
    all_messages = tool.get_channel_history(channel_id, limit=100)
    print(f"Fetched {len(all_messages)} total messages from this DM.")
    
    my_messages = tool.filter_messages_in_range(all_messages, start_time, end_time, my_only=True)
    
    if not my_messages:
        print("No messages from you found in that time range.")
        return
    
    tool.delete_with_rate_limit(my_messages, channel_id)


def handle_server_deletion(tool):
    """Handle server message deletion."""
    if not tool.get_guilds():
        print("Failed to fetch guilds.")
        return
    
    print("\n" + "="*80)
    print("SELECT A SERVER")
    print("="*80)
    
    for i, guild in enumerate(tool.guilds, 1):
        print(f"[{i}] {guild['name']} (ID: {guild['id']})")
    
    print("\n[0] Cancel")
    
    try:
        choice = int(input("Select server (number): ").strip())
        if choice == 0:
            return
        selected_guild = tool.guilds[choice - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return
    
    # Get channels
    channels = tool.get_guild_channels(selected_guild['id'])
    if not channels:
        print("No text channels found.")
        return
    
    print("\n" + "="*80)
    print(f"SELECT A CHANNEL IN {selected_guild['name']}")
    print("="*80)
    
    for i, channel in enumerate(channels, 1):
        print(f"[{i}] #{channel['name']} (ID: {channel['id']})")
    
    print("\n[0] Cancel")
    
    try:
        choice = int(input("Select channel (number): ").strip())
        if choice == 0:
            return
        selected_channel = channels[choice - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return
    
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
    
    all_messages = tool.get_channel_history(channel_id, limit=100)
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
    
    print("\n" + "="*80)
    print("SELECT MODE")
    print("="*80)
    print("[1] Delete DM messages")
    print("[2] Delete server messages")
    print("[0] Cancel")
    
    try:
        mode = int(input("Mode (1 or 2): ").strip())
    except ValueError:
        print("Invalid selection.")
        return
    
    if mode == 1:
        handle_dm_deletion(tool)
    elif mode == 2:
        handle_server_deletion(tool)
    else:
        print("Cancelled.")


if __name__ == "__main__":
    main()
