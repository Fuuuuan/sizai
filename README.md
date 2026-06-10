# 思·在 (Thinking · Being) — A Philosophical Garden

A minimalist space for philosophical reflection. One question a day. Free writing. Every thought becomes a star.

## Usage

### Online
Open in any browser:
```
https://fuuuuan.github.io/sizai/
```
On mobile, add to home screen to use as a PWA.

### Local (with AI Dialogue)
```bash
python3 server.py
```
Open `http://localhost:8899` to engage in real-time philosophical dialogue with Claude. All conversations are automatically saved as threaded stars in the Garden.

Or double-click `思在.command` on macOS for one-click launch.

## Features

- **Daily Question** — 170+ philosophical prompts, refreshed daily
- **Write** — Pour your thoughts onto the page, save as a star
- **Garden** — All writings displayed as cards; edit, continue threaded conversations
- **Dialogue with Claude** — Available when local server is running; multi-turn conversations saved as threads
- **PWA** — Installable on mobile home screen

## Project Structure

```
index.html      — Frontend (static, deployable independently)
server.py       — Local Python server for AI dialogue
manifest.json   — PWA manifest
sw.js           — Service Worker (offline caching)
start.sh        — CLI launch script
思在.command    — macOS double-click launcher
```

## Dependencies

- **Frontend**: A browser. That's it.
- **Server**: Python 3 (stdlib only) + Claude Code CLI for AI replies
- **AI question generation** (optional): Set `ANTHROPIC_API_KEY` environment variable

## License

MIT
