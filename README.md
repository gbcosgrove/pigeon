# Pigeon

Turn iMessage into an AI assistant interface. Text your Mac, get LLM responses back.

Pigeon is a macOS daemon that watches your iMessage self-chat for trigger messages, dispatches them to an LLM (Claude, GPT-4, Ollama, etc.), and sends the response back as an iMessage. It works from any Apple device — iPhone, iPad, Apple Watch, or Mac.

## How It Works

```
You (iPhone) → iMessage → Messages.app → chat.db → Pigeon → LLM → iMessage → You
```

1. You send a message to yourself starting with your trigger keyword (e.g., `pigeon: what's the weather?`)
2. Pigeon polls the local Messages database (read-only, every 5 seconds)
3. It sends an immediate acknowledgment ("Got it...")
4. A cheap triage model classifies the message (instant answer vs. needs tools vs. long task)
5. The main LLM processes the prompt and Pigeon sends the response back via iMessage
6. Long responses are automatically truncated with an expand command

## Features

- **Multi-session** — Run unlimited concurrent AI conversations with emoji labels (🔴🔵🟢🟡🟣 and 15 more)
- **Triage** — Cheap model pre-classifies messages for faster response
- **Pluggable LLM backends** — Claude CLI, Anthropic API, OpenAI API, Ollama (local)
- **Truncation + expand** — Long responses truncated for iMessage; reply to get the full text
- **Session persistence** — Sessions survive daemon restarts
- **Optional database** — SQLite (local) or PostgreSQL for session/usage logging
- **launchd integration** — Auto-starts on login, auto-restarts on crash
- **Zero network exposure** — No open ports, no webhooks, no HTTP server

## Requirements

- **macOS** (Apple Silicon or Intel)
- **Python 3.10+**
- **Messages.app** configured with iMessage
- **Full Disk Access** for your Python binary (to read chat.db)
- **Automation permission** for Messages.app
- An LLM backend:
  - [Claude Code](https://claude.ai/claude-code) CLI (default, no API key needed)
  - Or: Anthropic API key, OpenAI API key, or [Ollama](https://ollama.com) running locally

## Quick Start

```bash
# Install
pip install pigeon-imessage

# Or install with specific LLM backends
pip install "pigeon-imessage[anthropic]"   # Anthropic API
pip install "pigeon-imessage[openai]"      # OpenAI API
pip install "pigeon-imessage[all]"         # Everything

# Run interactive installer
pigeon install
```

The installer will:
1. Scan your Messages database and help you identify your self-chat
2. Ask which LLM backend you want to use
3. Configure your trigger keyword
4. Build the AppleScript message sender
5. Set up the launchd daemon

After install, send a message to yourself:
```
pigeon: hello, are you there?
```

## Manual Setup

If you prefer to configure manually:

```bash
# 1. Create config directory
mkdir -p ~/.pigeon

# 2. Detect your self-chat ID
pigeon detect-chat

# 3. Edit config
cat > ~/.pigeon/config.yaml << 'EOF'
chat:
  ids: [YOUR_CHAT_ID]
  identifier: "your-email@example.com"

trigger:
  keyword: "pigeon"
  expand_keyword: "pigeon:cc"
  status_keyword: "pigeon:status"
  off_keyword: "pigeon:off"

llm:
  main:
    backend: claude-cli    # or: anthropic, openai, ollama
    model: null            # null = backend default
  triage:
    backend: claude-cli
    model: null

sessions:
  max: 0                   # 0 = unlimited

response:
  truncation_limit: 2000

database:
  backend: none            # or: sqlite, postgres
EOF

# 4. Start
pigeon install    # Sets up launchd
# Or run in foreground for debugging:
pigeon run -v
```

## Usage

### Basic Commands (via iMessage to yourself)

| Message | Action |
|---------|--------|
| `pigeon: <prompt>` | Start a new session |
| `<message>` | Continue the front session |
| `1: <message>` | Send to session 1 (and switch to it) |
| `🔴 <message>` | Send to the red session |
| `pigeon:1` | Switch to session 1 (no message sent) |
| `pigeon:status` | Show all active sessions |
| `pigeon:off` | End all sessions |
| `pigeon:off 1` | End session 1 |
| `pigeon:off 🔴` | End the red session |
| `pigeon:cc` | Expand last truncated response |

### CLI Commands

```bash
pigeon install       # Interactive setup
pigeon detect-chat   # Find your self-chat ID
pigeon start         # Start the daemon
pigeon stop          # Stop the daemon
pigeon restart       # Restart the daemon
pigeon status        # Check daemon status
pigeon run -v        # Run in foreground (debug mode)
pigeon uninstall     # Remove daemon and optionally config
```

## LLM Backends

### Claude CLI (Default)

Uses [Claude Code](https://claude.ai/claude-code) CLI. No API key needed — uses your existing Claude Code authentication. Supports session resume for multi-turn conversations.

```yaml
llm:
  main:
    backend: claude-cli
```

### Anthropic API

Direct API calls. Requires `ANTHROPIC_API_KEY` environment variable.

```bash
pip install "pigeon-imessage[anthropic]"
export ANTHROPIC_API_KEY="sk-ant-..."
```

```yaml
llm:
  main:
    backend: anthropic
    model: claude-sonnet-4-20250514
  triage:
    backend: anthropic
    model: claude-haiku-4-5-20251001
```

### OpenAI API

Works with OpenAI, Azure OpenAI, or any compatible endpoint. Requires `OPENAI_API_KEY`.

```bash
pip install "pigeon-imessage[openai]"
export OPENAI_API_KEY="sk-..."
# Optional: export OPENAI_BASE_URL="https://your-endpoint.com/v1"
```

```yaml
llm:
  main:
    backend: openai
    model: gpt-4o
```

### Ollama (Local)

Run models locally with [Ollama](https://ollama.com). No API key needed.

```bash
ollama pull llama3.2
# Optional: export OLLAMA_HOST="http://localhost:11434"
```

```yaml
llm:
  main:
    backend: ollama
    model: llama3.2
```

## Database

Session history and usage logging are optional. By default, no database is used — session state is tracked in a JSON file.

### SQLite (Recommended)

Zero-config local database:

```yaml
database:
  backend: sqlite
  path: ~/.pigeon/pigeon.db
```

### PostgreSQL / Supabase

For remote access or dashboard integration:

```yaml
database:
  backend: postgres
  url: "${DATABASE_URL}"
```

```bash
pip install "pigeon-imessage[postgres]"
export DATABASE_URL="postgresql://user:pass@host:5432/db"
```

## macOS Permissions

Pigeon needs two permissions, both set once:

### Full Disk Access

Required to read `~/Library/Messages/chat.db`.

1. Open **System Settings > Privacy & Security > Full Disk Access**
2. Click **+** and add your Python binary (e.g., `/usr/bin/python3` or your venv's python)

To find your Python binary:
```bash
python3 -c "import sys; print(sys.executable)"
```

### Automation (Messages.app)

Required to send iMessages via AppleScript. macOS will prompt you the first time Pigeon tries to send a message. Click **Allow**.

## Architecture

```
~/.pigeon/
├── config.yaml          # Your configuration
├── state.json           # Session state (survives restarts)
├── heartbeat            # Daemon liveness file
├── PigeonSend.app       # Compiled AppleScript sender
├── pigeon.db            # SQLite database (if enabled)
├── logs/
│   ├── stdout.log
│   └── stderr.log
└── responses/           # Full text of truncated responses
```

### How the Daemon Works

1. **Polling** — Every 5 seconds, reads new messages from `chat.db` (read-only, WAL mode)
2. **Filtering** — Only processes messages in your configured self-chat(s) matching the trigger keyword
3. **Triage** — First message in a session goes through a cheap model to classify: instant answer, needs tools, or long task
4. **Dispatch** — Routes to the configured LLM backend
5. **Response** — Strips markdown, truncates if needed, sends back via AppleScript
6. **Watchdog** — If the heartbeat file goes stale, the daemon force-exits and launchd restarts it

### Security Model

- **Read-only database access** — Pigeon never writes to chat.db
- **No network listener** — No HTTP server, no webhooks, no open ports
- **Local auth only** — Authentication is your macOS user account + Apple ID
- **Secure config directory** — `~/.pigeon/` created with 700 permissions
- **No credentials in config** — API keys via environment variables, never stored in config files

## Troubleshooting

### Daemon won't start
```bash
# Check logs
tail -50 ~/.pigeon/logs/stderr.log

# Run in foreground for detailed output
pigeon run -v
```

### "Cannot read chat.db"
Full Disk Access not granted. See [macOS Permissions](#macos-permissions).

### Messages not being detected
1. Make sure you're sending to yourself (not a group chat)
2. Check your chat ID: `pigeon detect-chat`
3. Verify the trigger keyword matches your config

### Responses not sending
1. Check Messages.app is open (it can be minimized)
2. Grant Automation permission when prompted
3. Check `~/.pigeon/logs/stderr.log` for AppleScript errors

## Development

```bash
git clone https://github.com/gbcosgrove/pigeon.git
cd pigeon
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/ tests/

# Run in debug mode
pigeon run -v
```

## License

MIT
