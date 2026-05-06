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

1. Go to the [Releases page](https://github.com/yourusername/message-deleter/releases).
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
git clone https://github.com/yourusername/message-deleter.git
cd message-deleter

# Install
pipx install .

# Run
message-deleter
```

### Run directly with Python

```bash
# Install dependencies
pip install requests

# Run
python3 dm_deleter.py
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
3. Select mode: `[1]` DM or `[2]` Server
4. Follow the prompts to select user/server/channel
5. Set time range (leave blank for all messages)
6. Confirm deletion

## Rate Limiting

- 24 messages per minute (1 every ~2.6 seconds)
- Built-in delay prevents the platform from rate-limiting your account
- Progress shows: `[5/240] Deleted: 5 | Failed: 0 | Elapsed: 00:13 | Remaining: 1d 02:15:00`

## Notes

- You can only delete messages **you** sent (unless in server mode with admin perms)
- Deleted messages cannot be recovered
- This uses the platform's unofficial user API
