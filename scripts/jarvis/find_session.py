#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Search Jarvis session compacts by keyword.

Usage: uv run ~/.claude/scripts/jarvis/find_session.py <keyword> [keyword2 ...]

Keywords are ANDed — all must match. Case-insensitive substring search
across the conversation field and cwd. Sorted by date (most recent first).
Skips trivial sessions (< 2 user messages).
"""

import json
import sys
from pathlib import Path

COMPACTS_DIR = Path.home() / ".claude/memory/jarvis/session-compacts"
CONTEXT_CHARS = 120


def search(keywords: list[str]) -> list[dict]:
    hits = []
    for f in COMPACTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        if data.get("stats", {}).get("user_messages", 0) < 2:
            continue

        conversation = data.get("conversation", "")
        cwd = data.get("cwd", "")
        searchable = (conversation + "\n" + cwd).lower()

        if not all(kw.lower() in searchable for kw in keywords):
            continue

        # Find first keyword match position for excerpt
        conv_lower = conversation.lower()
        pos = conv_lower.find(keywords[0].lower())
        start = max(0, pos - CONTEXT_CHARS // 2)
        end = min(len(conversation), pos + len(keywords[0]) + CONTEXT_CHARS // 2)
        excerpt = conversation[start:end].replace("\n", " ").strip()
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(conversation):
            excerpt = excerpt + "..."

        hits.append({
            "session_id": data.get("session_id", f.stem),
            "date": data.get("date", "unknown"),
            "cwd": cwd,
            "excerpt": excerpt,
        })

    hits.sort(key=lambda h: h["date"], reverse=True)
    return hits


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <keyword> [keyword2 ...]", file=sys.stderr)
        sys.exit(1)

    keywords = sys.argv[1:]
    hits = search(keywords)

    if not hits:
        print(f"No sessions found matching: {' AND '.join(keywords)}", file=sys.stderr)
        sys.exit(0)

    print(f"Found {len(hits)} session(s) matching: {' AND '.join(keywords)}\n")
    for h in hits:
        print(f"  {h['session_id']}  {h['date']}  {h['cwd']}")
        print(f"    {h['excerpt']}")
        print()


if __name__ == "__main__":
    main()
