#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Jarvis: Session Compactor

Reads ~/.claude/projects/**/*.jsonl files, compacts each into a chronological
summary preserving user messages, assistant text, tool call names + outcomes,
interruptions, and errors. No LLM needed — pure Python.

Compacts are the single data store for the weekly analyzer.

Run: uv run session-processor.py
Schedule: systemd timer (jarvis-sessions.timer), nightly
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

PROJECTS_DIR = Path.home() / ".claude" / "projects"
MEMORY_DIR = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
COMPACT_DIR = MEMORY_DIR / "session-compacts"
STATE_FILE = MEMORY_DIR / "session-processor-state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception as e:
            print(f"  Warning: corrupt state file, starting fresh: {e}", file=sys.stderr)
    return {"compacted": {}}


def save_state(state: dict) -> None:
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2))


EXCLUDE_SESSIONS: set[str] = set(
    filter(None, os.environ.get("JARVIS_EXCLUDE_SESSIONS", "").split(","))
)


def find_new_files(state: dict) -> list[Path]:
    """Find JSONL files new or modified since last compaction."""
    files = []
    processed = state.get("compacted", {})

    for path in PROJECTS_DIR.rglob("*.jsonl"):
        if "subagents" in str(path) or "tool-results" in str(path):
            continue
        if any(path.stem.startswith(sid) for sid in EXCLUDE_SESSIONS):
            continue
        mtime = path.stat().st_mtime
        if mtime > processed.get(str(path), 0):
            files.append(path)

    return sorted(files)


def compact_session(path: Path) -> dict | None:
    """Compact a session JSONL into a chronological summary."""
    session_id = None
    cwd = None
    transcript: list[str] = []
    tool_counts: dict[str, int] = {}
    error_count = 0
    interrupt_count = 0
    total_entries = 0
    user_msg_count = 0
    assistant_text_count = 0
    tool_call_count = 0

    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            total_entries += 1

            if not session_id and entry.get("sessionId"):
                session_id = entry["sessionId"]
            if not cwd and entry.get("cwd"):
                cwd = entry["cwd"]

            entry_type = entry.get("type")

            if entry_type == "user":
                msg = entry.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    if "[Request interrupted by user]" in content:
                        transcript.append("[INTERRUPTED]")
                        interrupt_count += 1
                    elif not content.startswith("<"):
                        transcript.append(f"[USER] {content}")
                        user_msg_count += 1
                elif isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            text = block["text"]
                            if "[Request interrupted by user]" in text:
                                transcript.append("[INTERRUPTED]")
                                interrupt_count += 1
                            elif not text.startswith("<"):
                                transcript.append(f"[USER] {text}")
                                user_msg_count += 1
                        elif block.get("type") == "tool_result":
                            result_text = _compact_tool_result(block)
                            if result_text:
                                transcript.append(f"[RESULT] {result_text}")
                            if block.get("is_error"):
                                error_count += 1

            elif entry_type == "assistant":
                msg = entry.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            transcript.append(f"[CLAUDE] {block['text']}")
                            assistant_text_count += 1
                        elif block.get("type") == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            tool_counts[name] = tool_counts.get(name, 0) + 1
                            tool_call_count += 1
                            summary = _compact_tool_call(name, inp)
                            transcript.append(f"[TOOL] {summary}")

    except Exception as e:
        print(f"  Error reading {path.name}: {e}", file=sys.stderr)
        return None

    if total_entries < 5:
        return None

    mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)

    return {
        "session_id": session_id or path.stem,
        "date": mtime.strftime("%Y-%m-%d"),
        "cwd": cwd,
        "source_file": str(path),
        "stats": {
            "total_entries": total_entries,
            "user_messages": user_msg_count,
            "assistant_responses": assistant_text_count,
            "tool_calls": tool_call_count,
            "tool_errors": error_count,
            "interrupts": interrupt_count,
        },
        "conversation": "\n".join(transcript),
        "tool_usage": dict(sorted(tool_counts.items(), key=lambda x: -x[1])),
    }


def _compact_tool_call(name: str, inp: dict) -> str:
    """One-line summary of a tool call: name + key parameter."""
    if "command" in inp:
        return f"{name}: {str(inp['command'])[:120]}"
    if "file_path" in inp:
        return f"{name}: {inp['file_path']}"
    if "pattern" in inp:
        return f"{name}: /{str(inp['pattern'])[:60]}/"
    if "query" in inp:
        return f"{name}: {str(inp['query'])[:80]}"
    if "prompt" in inp:
        return f"{name}: {str(inp['prompt'])[:80]}"
    if "old_string" in inp:
        return f"{name}: {inp.get('file_path', '?')} (edit)"
    if "content" in inp and "file_path" in inp:
        return f"{name}: {inp['file_path']} (write)"
    return name


def _compact_tool_result(msg: dict) -> str | None:
    """Compact a tool result to its outcome. Returns None to skip verbose successes."""
    if not isinstance(msg, dict):
        return None

    is_error = msg.get("is_error", False)
    content = msg.get("content", "")

    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        content = "\n".join(texts)
    content = str(content)

    if is_error:
        return f"ERROR: {content[:200]}"

    if not content or content == "Tool ran without output or errors":
        return None

    if len(content) < 200:
        return content

    first_line = content.split("\n")[0][:150]
    line_count = content.count("\n") + 1
    return f"{first_line} [...{line_count} lines]"


def main() -> None:
    state = load_state()
    files = find_new_files(state)

    if not files:
        print("No new session files to compact.")
        return

    COMPACT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Compacting {len(files)} session(s)...")

    compacted = 0
    skipped = 0
    total_raw = 0
    total_compact = 0

    for path in files:
        compact = compact_session(path)
        if compact is None:
            skipped += 1
            state.setdefault("compacted", {})[str(path)] = path.stat().st_mtime
            continue

        output_path = COMPACT_DIR / f"{compact['session_id']}.json"
        output_text = json.dumps(compact, indent=2)
        output_path.write_text(output_text)

        raw_size = path.stat().st_size
        compact_size = len(output_text)
        total_raw += raw_size
        total_compact += compact_size
        compacted += 1
        state.setdefault("compacted", {})[str(path)] = path.stat().st_mtime
        print(f"  {compact['session_id'][:40]}  {raw_size//1024}KB → {compact_size//1024}KB  msgs={compact['stats']['user_messages']} tools={compact['stats']['tool_calls']}")

    save_state(state)

    ratio = (total_compact / total_raw * 100) if total_raw else 0
    print(f"\nDone. {compacted} compacted, {skipped} skipped.")
    print(f"  {total_raw / 1024 / 1024:.1f} MB → {total_compact / 1024 / 1024:.1f} MB ({ratio:.0f}%)")


if __name__ == "__main__":
    main()
