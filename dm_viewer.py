#!/usr/bin/env python3
"""
DM Viewer & Deleter
Uses the platform's unofficial user API (self-bot).
WARNING: Self-bots violate the platform's ToS. Use at your own risk.
"""

import requests
import json
import time
from datetime import datetime

API_BASE = "https://discord.com/api/v9"  # Platform API endpoint

class DMTool:
    def __init__(self, token):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self.current_user = None
        self.dm_channels = []
        self.all_messages = []
        
    def get_current_user(self):
        """Fetch current user information."""
        resp = self.session.get(f"{API_BASE}/users/@me")
        if resp.status_code == 200:
            self.current_user = resp.json()
            print(f"Logged in as: {self.current_user['username']}#{self.current_user['discriminator']}")
            return True
        else:
            print(f"Failed to get user: {resp.status_code} - {resp.text}")
            return False
    
    def get_dm_channels(self):
        """Get all DM channels (1-on-1 and group DMs)."""
        resp = self.session.get(f"{API_BASE}/users/@me/channels")
        if resp.status_code == 200:
            self.dm_channels = resp.json()
            print(f"Found {len(self.dm_channels)} DM channels")
            return True
        else:
            print(f"Failed to get DM channels: {resp.status_code}")
            return False
    
    def get_channel_messages(self, channel_id, limit=50):
        """Get messages from a specific channel."""
        messages = []
        params = {"limit": limit}
        
        resp = self.session.get(f"{API_BASE}/channels/{channel_id}/messages", params=params)
        if resp.status_code == 200:
            messages = resp.json()
        return messages
    
    def get_all_recent_messages(self, limit_per_channel=20):
        """Get recent messages from all DM channels."""
        all_msgs = []
        for channel in self.dm_channels:
            channel_id = channel['id']
            # Get channel name (recipient or group name)
            if 'recipients' in channel:
                names = [r['username'] for r in channel['recipients'] if r['id'] != self.current_user['id']]
                channel_name = ", ".join(names) if names else "Unknown"
            else:
                channel_name = channel.get('name', 'Unknown')
            
            messages = self.get_channel_messages(channel_id, limit_per_channel)
            for msg in messages:
                all_msgs.append({
                    'channel_id': channel_id,
                    'channel_name': channel_name,
                    'message_id': msg['id'],
                    'content': msg.get('content', '[No content]'),
                    'author_id': msg['author']['id'],
                    'author_name': msg['author'].get('username', 'Unknown'),
                    'timestamp': msg['timestamp'],
                    'is_me': msg['author']['id'] == self.current_user['id']
                })
            # Rate limit safety
            time.sleep(0.2)
        
        # Sort by timestamp descending (newest first)
        self.all_messages = sorted(all_msgs, key=lambda x: x['timestamp'], reverse=True)
        return self.all_messages
    
    def format_message(self, msg):
        """Format a message for display."""
        dt = datetime.fromisoformat(msg['timestamp'].replace('Z', '+00:00'))
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        author = "You" if msg['is_me'] else msg['author_name']
        return f"[{date_str}] {author} in {msg['channel_name']}: {msg['content'][:150]}"
    
    def delete_message(self, channel_id, message_id):
        """Delete a message from a channel."""
        resp = self.session.delete(f"{API_BASE}/channels/{channel_id}/messages/{message_id}")
        if resp.status_code in (200, 204):
            return True
        else:
            print(f"Failed to delete: {resp.status_code} - {resp.text}")
            return False
    
    def display_and_select(self):
        """Display messages and let user select which to delete."""
        if not self.all_messages:
            print("No messages found.")
            return
        
        print("\n" + "="*80)
        print("RECENT DMS (Newest First)")
        print("="*80)
        
        for i, msg in enumerate(self.all_messages[:50], 1):  # Show first 50
            print(f"\n[{i}] {self.format_message(msg)}")
            if len(msg['content']) > 150:
                print(f"    ... (truncated, full: {msg['content'][:500]})")
        
        print("\n" + "="*80)
        print("Enter message numbers to delete (comma-separated, e.g., 1,3,5)")
        print("Or 'q' to quit")
        print("="*80)
        
        selection = input("Selection: ").strip()
        if selection.lower() == 'q':
            return
        
        indices = [int(x.strip()) - 1 for x in selection.split(',') if x.strip().isdigit()]
        
        for idx in indices:
            if 0 <= idx < len(self.all_messages):
                msg = self.all_messages[idx]
                print(f"Deleting: {self.format_message(msg)}")
                success = self.delete_message(msg['channel_id'], msg['message_id'])
                if success:
                    print(f"  ✓ Deleted message {msg['message_id']}")
                else:
                    print(f"  ✗ Failed to delete message {msg['message_id']}")
                time.sleep(1)  # Rate limit


def main():
    print("="*80)
    print("DM VIEWER & DELETER")
    print("WARNING: Self-bots violate the platform ToS. Use at your own risk.")
    print("="*80)
    
    token = input("Enter your user token: ").strip()
    if not token:
        print("No token provided. Exiting.")
        return
    
    tool = DMTool(token)
    
    if not tool.get_current_user():
        print("Invalid token or authentication failed.")
        return
    
    if not tool.get_dm_channels():
        print("Failed to fetch DM channels.")
        return
    
    print("\nFetching recent messages from DM channels...")
    tool.get_all_recent_messages(limit_per_channel=20)
    
    tool.display_and_select()


if __name__ == "__main__":
    main()
