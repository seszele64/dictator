# Whisper Dictate - Global Key Binding

A Python CLI for voice dictation using Whisper API (OpenAI-compatible providers) with global key binding support on Arch Linux.

## Features

- 🎤 **Toggle Recording**: Single key press to start/stop recording
- 🧠 **AI Transcription**: Uses Whisper API (OpenAI, Groq, Together AI, DeepInfra, local whisper.cpp, and more) for accurate speech-to-text
- 📋 **Clipboard Integration**: Automatically copies transcription to clipboard
- 🔔 **System Notifications**: Visual feedback via notify-send
- ⚡ **Fast Response**: Minimal latency for real-time usage
- 📊 **Persistent History**: SQLite database stores all transcriptions and logs
- 🔍 **CLI Management**: Full command-line interface for managing transcriptions and logs

## Prerequisites

### FFmpeg (Required for MP3 audio support)

FFmpeg is required for MP3 encoding and conversion. Install it via your package manager:

```bash
# Arch Linux
sudo pacman -S ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg
```

## Quick Start

### Package Manager

This project uses [uv](https://github.com/astral-sh/uv) for fast Python package management. Install it if you haven't already:

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If you prefer pip, you can still use `pip install -e .` instead of `uv sync`.

### 1. Install the Package

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

### 2. Configure Your Whisper Provider

Create a `.env` file in the project directory (copy from `.env.example`):

```bash
cp .env.example .env
```

Then edit `.env` with your provider settings. By default, it uses OpenAI:

```bash
WHISPER_PROVIDER=openai
WHISPER_API_KEY="your-api-key-here"
WHISPER_MODEL=whisper-1
```

Or use any OpenAI-compatible provider — just change the environment variables, no code changes needed:

```bash
# Example: Groq
WHISPER_PROVIDER=groq
WHISPER_API_KEY="your-groq-api-key"
WHISPER_MODEL=whisper-large-v3-turbo

# Example: DeepInfra
WHISPER_PROVIDER=deepinfra
WHISPER_API_KEY="your-deepinfra-api-key"
WHISPER_MODEL=Whisper/whisper-large-v3
WHISPER_BASE_URL=https://api.deepinfra.com/v1/openai
```

See `.env.example` for all supported providers and configuration options.

### 3. Add global bind to the CLI

Run the setup script to configure i3:

```bash
# This will modify your i3 config to add the key binding
./setup_i3.sh
```

Or manually add to your i3 config (`~/.config/i3/config`):

```bash
# Bind whisper dictate (using mod+z)
bindsym $mod+z exec whisper-dictate dictate
```

### 4. Test the CLI

```bash
# Check system info
whisper-dictate info

# Run a quick dictation test
whisper-dictate dictate
```

## CLI Usage

The `whisper-dictate` CLI provides multiple subcommands for dictation, logs management, history management, and audio maintenance.

### Global Options

| Option | Description |
|--------|-------------|
| `--log-level LEVEL` | Set logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO |

### Main Commands

#### Dictation

```bash
whisper-dictate dictate [--duration SECONDS]
```

Record audio and transcribe it to text.

**Options:**
- `--duration SECONDS` - Optional recording duration (default: unlimited, stop with Ctrl+C)

**Example:**
```bash
# Record until Ctrl+C
whisper-dictate dictate

# Record for 30 seconds
whisper-dictate dictate --duration 30

# With debug logging
whisper-dictate --log-level DEBUG dictate
```

#### Dictation Toggle

```bash
whisper-dictate toggle          # start recording, or stop + transcribe if already recording
whisper-dictate-toggle          # same implementation as a standalone console script
```

The toggle starts a background `arecord` process and returns immediately; the
next invocation stops it, transcribes the recording, copies the text to the
clipboard, and shows a dunst notification. This is the mode intended for i3
keybindings — point `bindsym` at `whisper-dictate-toggle` (it is also exposed
as `whisper-dictate toggle`). Run `setup_i3.sh` to (re)install the i3
binding; it points at `whisper-dictate-toggle`.

#### System Information

```bash
whisper-dictate info
```

Display system information including audio devices, clipboard tools, and configuration.

**Example:**
```bash
whisper-dictate info
# Output:
# 🔍 System Information:
# ========================================
#
# 🎤 Audio Devices:
#   • Built-in Microphone
#   • USB Microphone
#
# 📋 Clipboard Tools:
#   • xclip
#
# ⚙️  Configuration:
#   • model: base
#   • language: auto
#
# 📊 Logging:
#   • Log file: /home/user/.local/state/whisper-dictate/logs/whisper-dictate.log
#   • View logs: tail -f /home/user/.local/state/whisper-dictate/logs/whisper-dictate.log
```

---

## Logs Management

The CLI provides comprehensive log management with database-backed logging and configurable retention.

### List Logs

```bash
whisper-dictate logs list [OPTIONS]
```

Query application logs with filters.

**Options:**
- `--level LEVEL` - Filter by log level (DEBUG, INFO, WARNING, ERROR)
- `--source SOURCE` - Filter by source module (e.g., `whisper_dictate.audio`)
- `--from-time TIME` - Filter from timestamp (ISO format: YYYY-MM-DD HH:MM:SS)
- `--to-time TIME` - Filter to timestamp (ISO format: YYYY-MM-DD HH:MM:SS)
- `--limit N` - Maximum number of logs to display (default: 100)

**Examples:**
```bash
# List recent logs
whisper-dictate logs list

# Show only errors
whisper-dictate logs list --level ERROR

# Filter by source module
whisper-dictate logs list --source whisper_dictate.audio --limit 50

# Filter by date range
whisper-dictate logs list --from-time "2024-01-01" --to-time "2024-01-31"
```

### Export Logs

```bash
whisper-dictate logs export FILENAME [OPTIONS]
```

Export logs to a file in text or JSON format.

**Options:**
- `--format FORMAT` - Export format: text or json (default: text)
- All filter options from `logs list` are available

**Examples:**
```bash
# Export to text file
whisper-dictate logs export error_logs.txt --level ERROR

# Export to JSON
whisper-dictate logs export logs.json --format json
```

### Cleanup Logs

```bash
whisper-dictate logs cleanup [OPTIONS]
```

Clean up old logs based on retention policy.

**Options:**
- `--days N` - Delete logs older than N days (default: use configured retention)

**Examples:**
```bash
# Use default retention (configured in database)
whisper-dictate logs cleanup

# Delete logs older than 7 days
whisper-dictate logs cleanup --days 7
```

---

## History Management

Search, view, and manage your transcription history stored in the SQLite database.

### List History

```bash
whisper-dictate history list [OPTIONS]
```

List recent transcriptions with pagination.

**Options:**
- `--limit N` - Maximum number to display (default: 20)
- `--date YYYY-MM-DD` - Filter by specific date

**Examples:**
```bash
# List recent transcriptions
whisper-dictate history list

# Show last 10
whisper-dictate history list --limit 10

# Filter by date
whisper-dictate history list --date 2024-03-15
```

### Show Transcription Details

```bash
whisper-dictate history show ID [OPTIONS]
```

Show full details of a specific transcription.

**Options:**
- `--audio` - Show the audio file path

**Examples:**
```bash
# Show transcription details
whisper-dictate history show 42

# Include audio file path
whisper-dictate history show 42 --audio
```

### Search Transcriptions

```bash
whisper-dictate history search QUERY [OPTIONS]
```

Search transcriptions by text (case-insensitive).

**Options:**
- `--limit N` - Maximum number of results (default: 20)

**Examples:**
```bash
# Search for "meeting"
whisper-dictate history search "meeting"

# Search with more results
whisper-dictate history search "project" --limit 50
```

### Delete Transcription

```bash
whisper-dictate history delete ID [OPTIONS]
```

Delete a transcription and its associated audio file.

**Options:**
- `--yes` - Skip confirmation prompt

**Examples:**
```bash
# Delete with confirmation
whisper-dictate history delete 42

# Delete without confirmation
whisper-dictate history delete 42 --yes
```

### Update Transcription

```bash
whisper-dictate history update ID [OPTIONS]
```

Update a transcription's text and optionally language.

**Options:**
- `--text "NEW TEXT"` - New transcript text (required)
- `--language CODE` - New language code (optional, e.g., "en", "es")

**Examples:**
```bash
# Update text only
whisper-dictate history update 123 --text "corrected transcription"

# Update text and language
whisper-dictate history update 123 --text "new text" --language en
```

---

## Audio Management

### Cleanup Orphaned Files

```bash
whisper-dictate audio cleanup [OPTIONS]
```

Clean up orphaned audio files not referenced in the database.

**Options:**
- `--dry-run` - Show what would be deleted without actually deleting (default: True; plain `audio cleanup` is a dry run)
- `--confirm` - Actually delete the orphaned files (default: False)

If both flags are passed, `--confirm` wins (deletion is performed) —
pinned by `test_confirm_wins_over_dry_run`.

**Examples:**
```bash
# Preview what would be deleted (default)
whisper-dictate audio cleanup

# Actually delete orphaned files
whisper-dictate audio cleanup --confirm
```

---

## Migration

### Migrate Legacy State Files

```bash
whisper-dictate migrate [OPTIONS]
```

Migrate legacy state files to the database.

**Options:**
- `--force` - Force re-migration even if already completed
- `--status` - Check migration status only

**Examples:**
```bash
# Check migration status
whisper-dictate migrate --status

# Run migration
whisper-dictate migrate

# Force re-migration
whisper-dictate migrate --force
```

---

## Configuration

### Environment Variables

#### Whisper Provider Configuration

All Whisper settings are configurable via environment variables. Switch providers without touching code:

| Variable | Description | Default |
|----------|-------------|---------|
| `WHISPER_PROVIDER` | Provider: `openai`, `groq`, `together`, `deepinfra`, `local`, `custom` | `openai` |
| `WHISPER_API_KEY` | API key for the selected provider | (required for cloud providers; not needed for `local`/`custom`) |
| `WHISPER_BASE_URL` | Custom API base URL (for `custom` provider) | Provider default |
| `WHISPER_MODEL` | Model name to use | `whisper-1` |
| `WHISPER_LANGUAGE` | Language hint as ISO 639-1 code (e.g., `en`, `de`) | (unset) — Whisper auto-detects |
| `WHISPER_TEMPERATURE` | Sampling temperature (0.0-1.0) | `0.0` |
| `WHISPER_TIMEOUT` | API request timeout in seconds | `30` |
| `WHISPER_TASK` | Whisper task: `transcribe` or `translate` (translation always outputs English) | `transcribe` |

#### Supported Providers

| Provider | `WHISPER_PROVIDER` | Default Model | Notes |
|----------|-------------------|---------------|-------|
| OpenAI | `openai` | `whisper-1` | Default provider; requires `OPENAI_API_KEY` |
| Groq | `groq` | `whisper-1` (set `WHISPER_MODEL` to a model your provider supports, e.g. `whisper-large-v3-turbo`) | Fast inference; requires `GROQ_API_KEY` |
| Together AI | `together` | `whisper-1` (set `WHISPER_MODEL` to a model your provider supports, e.g. `whisper-large-v3`) | Requires `TOGETHER_API_KEY` |
| DeepInfra | `deepinfra` | `whisper-1` (set `WHISPER_MODEL` to a model your provider supports, e.g. `Whisper/whisper-large-v3`) | Requires `DEEPINFRA_API_KEY` |
| Local server | `local` | `whisper-1` (set `WHISPER_MODEL` to a model your server supports) | No API key required; set `WHISPER_BASE_URL` (default `http://localhost:8000/v1`) |
| Custom endpoint | `custom` | `whisper-1` (set `WHISPER_MODEL` to a model your server supports) | No API key required unless your endpoint needs auth; set `WHISPER_BASE_URL` |
| whisper.cpp | `local` or `custom` | `whisper-1` (`whisper-large-v3` recommended) | Keyless; set `WHISPER_BASE_URL` to your server |
| faster-whisper-server | `local` or `custom` | `whisper-1` (`large-v3` recommended) | Keyless; set `WHISPER_BASE_URL` to your server |

#### Provider-Specific API Key Fallbacks

If `WHISPER_API_KEY` is not set, the system falls back to provider-specific env vars:
- `OPENAI_API_KEY` (for `openai`)
- `GROQ_API_KEY` (for `groq`)
- `TOGETHER_API_KEY` (for `together`)
- `DEEPINFRA_API_KEY` (for `deepinfra`)

#### Other Configuration

The only environment variable read outside the `WHISPER_*` set is:

| Variable | Description | Default |
|----------|-------------|---------|
| `XDG_DATA_HOME` | Base directory for the database and recordings (XDG Base Directory spec) | `~/.local/share` |
| `XDG_STATE_HOME` | Base directory for the log file (XDG Base Directory spec) | `~/.local/state` |

There are no `LOG_LEVEL`, `LOG_RETENTION_DAYS`, `MIN_FREE_SPACE_MB`,
`MP3_ENABLED`, `MP3_BITRATE` or `KEEP_WAV` environment variables — the
application does not read them. Logging level is controlled by the CLI flag
(`whisper-dictate --log-level DEBUG`); the remaining settings are code
defaults in `whisper_dictate/config.py`.

### Database Configuration

The CLI uses a SQLite database stored at:
```
~/.local/share/whisper-dictate/whisper-dictate.db
```
(under `$XDG_DATA_HOME` when that variable is set).

### Audio Settings

The CLI uses sensible defaults:
- Sample rate: 16kHz (optimal for Whisper)
- Channels: 1 (mono)
- Format: 16-bit WAV (converted to MP3 before upload)

#### MP3 Conversion

WAV files are large (~10MB per minute at 44.1kHz stereo) but the Whisper API supports MP3 natively. By default, audio is automatically converted to MP3 before upload, achieving **80-90% file size reduction** with no impact on transcription quality for speech. Mechanism: soundfile handles WAV I/O and silence analysis, and MP3 encoding runs through a single FFmpeg subprocess call.

MP3 conversion is currently configured only through code defaults in
`whisper_dictate/config.py` (`AudioConfig`): `mp3_enabled` (true),
`mp3_bitrate` (`128k`) and `keep_wav` (false). There are no `MP3_*` or
`KEEP_WAV` environment variables — setting them in `.env` has no effect.

**Bitrate Guide:**
| Bitrate | Quality | Size | Use Case |
|---------|---------|------|----------|
| 64k | Good | Smallest | Low bandwidth, voice notes |
| 128k | Excellent | Moderate | Recommended for most users |
| 192k | Best | Largest | High quality requirements |

### Provider Examples

See `.env.example` in the project root for ready-to-use configurations for all supported providers. Simply copy the block for your provider into your `.env` file.

---

## Notification Action Buttons

When recording, the notification displays a "Stop Recording" action button. There are two ways to use it:

### Prerequisites

1. **Install dunst and dmenu** (required for action buttons):
   ```bash
   # Arch Linux
   sudo pacman -S dunst dmenu

   # Debian/Ubuntu
   sudo apt-get install dunst dmenu
   ```

2. **Start dunst notification daemon** if not already running:
   ```bash
   dunst &
   ```

### i3 Configuration for Context Menu

To use the notification action button, you need to configure a keybinding for dunst's context menu in your i3 config (`~/.config/i3/config`):

```bash
# Dunst context menu keybinding (required for notification actions)
bindsym Ctrl+Shift+. exec dunstctl context
```

Reload i3 after adding:
```bash
i3-msg reload
```

### How to Use Action Buttons

**Method 1: Click the notification (if supported)**
- Some dunst configurations support clicking action buttons directly on the notification

**Method 2: Use the context menu**
1. While recording, press `Ctrl+Shift+.` to open dunst's context menu
2. Select "Stop Recording" from the menu
3. The recording will stop and transcription will begin

**Note:** The context menu keybinding (`Ctrl+Shift+.`) is configurable in your dunst configuration. Check your dunstrc for the `shortcut` setting under `[global]` or `[keybind]` sections.

---

## Troubleshooting

### Dependencies Missing
```bash
# Install missing Python packages
uv sync
# Or: pip install -e .

# Install system packages
sudo pacman -S python-pip ffmpeg portaudio
```

### FFmpeg Installation Issues

FFmpeg is required for MP3 audio conversion. If you see warnings about FFmpeg not being found, follow these steps:

#### Verify FFmpeg is Installed
```bash
# Check if FFmpeg is installed and its version
ffmpeg -version

# Should output something like:
# ffmpeg version 6.0 Copyright (c) 2000-2023 the FFmpeg developers
```

#### Install FFmpeg
```bash
# Arch Linux
sudo pacman -S ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Fedora
sudo dnf install ffmpeg

# macOS
brew install ffmpeg
```

#### If FFmpeg is Installed but Not Working
```bash
# Check if FFmpeg is in your PATH
which ffmpeg

# Verify FFmpeg can be found by Python
python -c "import subprocess; subprocess.run(['ffmpeg', '-version'])"
```

#### Disable MP3 Conversion if FFmpeg is Unavailable

If FFmpeg cannot be installed or is not working, you can disable MP3 conversion to continue using WAV files (note: this will result in larger file sizes):

MP3 conversion cannot currently be disabled via `.env` (there is no
`MP3_ENABLED` environment variable). Change the `mp3_enabled` default in
`whisper_dictate/config.py` (`AudioConfig`) to `False` instead.

The system will continue to function with WAV files, but uploads will be larger (~10MB per minute at 16kHz mono).

#### Graceful Degradation

If FFmpeg is missing during runtime:
- The system logs a warning message
- Returns the original WAV path
- Continues to function normally with larger file sizes
- Transcription quality remains unchanged

### No Audio Devices
```bash
# List available audio devices
python -c "import sounddevice as sd; print(sd.query_devices())"
```

### Clipboard Not Working
```bash
# Install clipboard tools
sudo pacman -S xclip xsel wl-clipboard
```

### Debug Mode
```bash
# Run with debug logging
whisper-dictate --log-level DEBUG dictate
```

### View Application Logs
```bash
# Tail the log file
tail -f ~/.local/state/whisper-dictate/logs/whisper-dictate.log

# Or use the CLI to query logs
whisper-dictate logs list --level DEBUG
```

### Database Issues
```bash
# Check database location
ls -la ~/.local/share/whisper-dictate/

# Check migration status
whisper-dictate migrate --status

# Re-run migration if needed
whisper-dictate migrate --force
```

---

## Key Files

- **`whisper_dictate/`** - Main Python package
  - `cli.py` - Click-based CLI interface
  - `dictation.py` - Core dictation service
  - `database.py` - SQLite database operations
   - `transcription.py` - Whisper API abstraction and provider implementations
  - `notifications.py` - System notifications
  - `clipboard.py` - Clipboard integration
  - `__main__.py` - CLI entry point (invoked via `python -m whisper_dictate`)
- **`pyproject.toml`** - Package installation and build configuration
- **`.env.example`** - Environment configuration template

---

## Usage Tips

- **Speak clearly** and at normal pace
- **Use in quiet environment** for best results
- **Test with short recordings** first
- **Check system notifications** for status updates
- **Use `history` commands** to review past transcriptions
- **Use `logs` commands** for debugging issues

The CLI is designed to be fast and responsive, with minimal latency between key press and recording start/stop.
