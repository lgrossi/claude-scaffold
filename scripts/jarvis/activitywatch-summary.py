#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
Jarvis: ActivityWatch Daily Summary

Queries ActivityWatch API (localhost:5600) for yesterday's activity.
Writes structured summary to $JARVIS_MEMORY_DIR/sensors/activitywatch-YYYY-MM-DD.json

ActivityWatch is an open-source time tracker: https://activitywatch.net
Install: https://activitywatch.net/downloads/

Run: uv run ~/.claude/scripts/jarvis/activitywatch-summary.py
Cron: 0 1 * * * uv run ~/.claude/scripts/jarvis/activitywatch-summary.py
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests

AW_BASE = "http://localhost:5600/api/0"
_memory_dir = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
SENSORS_DIR = _memory_dir / "sensors"

FOCUS_THRESHOLD_MINUTES = 25  # Pomodoro-style: uninterrupted block = focus session
IDLE_THRESHOLD_SECONDS = 120  # AFK watcher idle threshold

# App categories for analysis
WORK_APPS = {"code", "cursor", "rider", "phpstorm", "terminal", "kitty", "alacritty", "gnome-terminal"}
BROWSER_APPS = {"chrome", "chromium", "firefox", "brave"}
COMM_APPS = {"slack", "teams", "zoom", "discord"}


def aw_get(path: str) -> dict | list:
    resp = requests.get(f"{AW_BASE}{path}", timeout=5)
    resp.raise_for_status()
    return resp.json()


def get_yesterday_range() -> tuple[str, str]:
    yesterday = date.today() - timedelta(days=1)
    start = datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def get_buckets() -> dict:
    buckets = aw_get("/buckets")
    return {
        "window": next((b for b in buckets if "window" in b.lower()), None),
        "afk": next((b for b in buckets if "afk" in b.lower()), None),
    }


def get_events(bucket_id: str, start: str, end: str) -> list[dict]:
    if not bucket_id:
        return []
    try:
        events = aw_get(f"/buckets/{bucket_id}/events?start={start}&end={end}&limit=10000")
        return events if isinstance(events, list) else []
    except Exception:
        return []


def summarize_apps(window_events: list[dict]) -> list[dict]:
    """Aggregate total time per app."""
    app_time: dict[str, float] = {}
    for event in window_events:
        duration = event.get("duration", 0)
        data = event.get("data", {})
        app = data.get("app", "unknown").lower()
        # Normalize app name
        app = app.replace(".exe", "").split("/")[-1]
        app_time[app] = app_time.get(app, 0) + duration

    return sorted(
        [{"app": app, "minutes": round(secs / 60, 1)} for app, secs in app_time.items()],
        key=lambda x: x["minutes"],
        reverse=True,
    )[:20]


def detect_focus_sessions(window_events: list[dict], afk_events: list[dict]) -> list[dict]:
    """Find uninterrupted focus blocks > FOCUS_THRESHOLD_MINUTES."""
    # Build idle intervals from AFk events
    idle_intervals = []
    for event in afk_events:
        if event.get("data", {}).get("status") == "afk":
            start = event.get("timestamp", "")
            duration = event.get("duration", 0)
            if start and duration > IDLE_THRESHOLD_SECONDS:
                idle_intervals.append((start, duration))

    focus_sessions = []
    current_start = None
    current_duration = 0.0

    for event in sorted(window_events, key=lambda e: e.get("timestamp", "")):
        ts = event.get("timestamp", "")
        duration = event.get("duration", 0)
        app = event.get("data", {}).get("app", "").lower()

        # Skip comm apps during focus counting
        if any(comm in app for comm in COMM_APPS):
            if current_duration >= FOCUS_THRESHOLD_MINUTES * 60:
                focus_sessions.append({
                    "start": current_start,
                    "minutes": round(current_duration / 60, 1),
                })
            current_start = None
            current_duration = 0
            continue

        if current_start is None:
            current_start = ts
            current_duration = duration
        else:
            current_duration += duration

    if current_duration >= FOCUS_THRESHOLD_MINUTES * 60:
        focus_sessions.append({
            "start": current_start,
            "minutes": round(current_duration / 60, 1),
        })

    return focus_sessions


def count_context_switches(window_events: list[dict]) -> int:
    """Count app-level context switches per hour."""
    if not window_events:
        return 0
    switches = 0
    prev_app = None
    for event in sorted(window_events, key=lambda e: e.get("timestamp", "")):
        app = event.get("data", {}).get("app", "").lower()
        if app != prev_app and prev_app is not None:
            switches += 1
        prev_app = app
    return switches


def main() -> None:
    target_date = date.today() - timedelta(days=1)
    output_path = SENSORS_DIR / f"activitywatch-{target_date}.json"

    if output_path.exists():
        print(f"Already processed {target_date}, skipping.")
        return

    try:
        aw_get("/info")
    except Exception:
        print("ActivityWatch not running at localhost:5600. Skipping.", file=sys.stderr)
        print("Install: https://activitywatch.net/downloads/")
        sys.exit(0)

    start, end = get_yesterday_range()
    buckets = get_buckets()

    if not buckets["window"]:
        print("No window watcher bucket found. Is aw-watcher-window running?", file=sys.stderr)
        sys.exit(0)

    window_events = get_events(buckets["window"], start, end)
    afk_events = get_events(buckets["afk"], start, end) if buckets["afk"] else []

    total_active = sum(e.get("duration", 0) for e in window_events)
    total_idle = sum(
        e.get("duration", 0) for e in afk_events
        if e.get("data", {}).get("status") == "afk"
    )

    app_summary = summarize_apps(window_events)
    focus_sessions = detect_focus_sessions(window_events, afk_events)
    context_switches = count_context_switches(window_events)

    # Categorize top apps
    work_minutes = sum(
        a["minutes"] for a in app_summary
        if any(w in a["app"] for w in WORK_APPS)
    )
    comm_minutes = sum(
        a["minutes"] for a in app_summary
        if any(c in a["app"] for c in COMM_APPS)
    )

    summary = {
        "date": target_date.isoformat(),
        "total_active_minutes": round(total_active / 60, 1),
        "total_idle_minutes": round(total_idle / 60, 1),
        "work_tool_minutes": round(work_minutes, 1),
        "communication_minutes": round(comm_minutes, 1),
        "context_switches": context_switches,
        "context_switches_per_hour": round(
            context_switches / max(total_active / 3600, 1), 1
        ),
        "focus_sessions": focus_sessions,
        "focus_session_count": len(focus_sessions),
        "longest_focus_minutes": max((s["minutes"] for s in focus_sessions), default=0),
        "top_apps": app_summary[:10],
    }

    SENSORS_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2))
    print(f"ActivityWatch summary written to {output_path}")
    print(f"  Active: {summary['total_active_minutes']}m | Focus sessions: {summary['focus_session_count']} | Switches: {summary['context_switches']}")


if __name__ == "__main__":
    main()
