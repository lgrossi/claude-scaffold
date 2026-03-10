#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "google-auth>=2.0",
#   "google-api-python-client>=2.0",
# ]
# ///
"""
Jarvis: Google Docs Daily Snapshot (ADC approach)

Captures recently modified Google Docs/Slides/Sheets with unresolved comments,
and cross-references presentations against calendar events.

Uses Application Default Credentials (gcloud auth application-default login).

SETUP (one-time — same as calendar-snapshot.py but with Drive + Docs scopes):
  gcloud auth application-default login \
    --scopes=https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/calendar.readonly,\
https://www.googleapis.com/auth/drive.readonly

Run: uv run ~/.claude/scripts/jarvis/gdocs-snapshot.py
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import google.auth
from googleapiclient.discovery import build

_memory_dir = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
SENSORS_DIR = _memory_dir / "sensors"
LOOKBACK_HOURS = int(os.environ.get("JARVIS_GDOCS_LOOKBACK_HOURS", "24"))
MAX_FILES = 30

GOOGLE_DOC_TYPES = (
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
)


def build_drive_service():
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)


def fetch_recent_files(service, since: datetime) -> list[dict]:
    mime_filter = " or ".join(f"mimeType='{m}'" for m in GOOGLE_DOC_TYPES)
    query = f"modifiedTime > '{since.isoformat()}' and ({mime_filter}) and trashed = false"

    files = []
    page_token = None
    while len(files) < MAX_FILES:
        resp = service.files().list(
            q=query,
            fields="nextPageToken,files(id,name,mimeType,modifiedTime,owners,lastModifyingUser,webViewLink)",
            orderBy="modifiedTime desc",
            pageSize=min(MAX_FILES - len(files), 100),
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return files[:MAX_FILES]


def fetch_unresolved_comments(service, file_id: str) -> list[dict]:
    comments = []
    page_token = None
    while True:
        resp = service.comments().list(
            fileId=file_id,
            fields="nextPageToken,comments(id,content,author(displayName),resolved,replies(id,content,author(displayName)))",
            pageSize=100,
            pageToken=page_token,
        ).execute()
        comments.extend(resp.get("comments", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return [c for c in comments if not c.get("resolved")]


def load_calendar_events() -> list[dict]:
    today = date.today()
    for offset in [0, 1]:
        d = (today - timedelta(days=offset)).isoformat()
        path = SENSORS_DIR / f"calendar-{d}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return data.get("events", [])
            except Exception:
                continue
    return []


def match_presentations_to_calendar(files: list[dict], calendar_events: list[dict]) -> dict[str, list[str]]:
    """Match presentation file names against calendar event titles."""
    matches: dict[str, list[str]] = {}
    presentations = [
        f for f in files
        if f.get("mimeType") == "application/vnd.google-apps.presentation"
    ]
    if not presentations or not calendar_events:
        return matches

    for pres in presentations:
        pres_name = pres.get("name", "").lower()
        if not pres_name:
            continue
        pres_words = set(pres_name.split())
        matched_events = []
        for event in calendar_events:
            event_title = event.get("title", "").lower()
            if not event_title:
                continue
            event_words = set(event_title.split())
            # Match if significant word overlap (>= 2 words or exact substring)
            overlap = pres_words & event_words - {"the", "a", "an", "and", "or", "for", "to", "in", "of", "-", "—"}
            if len(overlap) >= 2 or pres_name in event_title or event_title in pres_name:
                matched_events.append(event.get("title", ""))
        if matched_events:
            matches[pres["id"]] = matched_events

    return matches


def normalize_file(file: dict, unresolved_comments: list[dict], calendar_matches: list[str] | None) -> dict:
    mime = file.get("mimeType", "")
    type_map = {
        "application/vnd.google-apps.document": "doc",
        "application/vnd.google-apps.spreadsheet": "sheet",
        "application/vnd.google-apps.presentation": "slides",
    }
    result = {
        "id": file["id"],
        "name": file.get("name", "(untitled)"),
        "type": type_map.get(mime, "unknown"),
        "modified_at": file.get("modifiedTime", ""),
        "last_modifier": file.get("lastModifyingUser", {}).get("displayName", ""),
        "owner": (file.get("owners") or [{}])[0].get("displayName", ""),
        "url": file.get("webViewLink", ""),
        "unresolved_comments": [
            {
                "author": c.get("author", {}).get("displayName", ""),
                "content": c.get("content", "")[:200],
                "reply_count": len(c.get("replies", [])),
            }
            for c in unresolved_comments
        ],
    }
    if calendar_matches:
        result["calendar_matches"] = calendar_matches
    return result


def main() -> None:
    snapshot_date = date.today()
    output_path = SENSORS_DIR / f"gdocs-{snapshot_date}.json"
    SENSORS_DIR.mkdir(parents=True, exist_ok=True)

    service = build_drive_service()
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    print(f"Fetching files modified since {since.isoformat()[:19]}Z...")
    files = fetch_recent_files(service, since)
    print(f"Found {len(files)} recently modified file(s)")

    # Load calendar for cross-referencing presentations
    calendar_events = load_calendar_events()
    calendar_matches = match_presentations_to_calendar(files, calendar_events)

    # Fetch unresolved comments for each file
    normalized = []
    for f in files:
        file_id = f["id"]
        try:
            comments = fetch_unresolved_comments(service, file_id)
        except Exception as e:
            print(f"  Comments failed for {f.get('name', file_id)}: {e}", file=sys.stderr)
            comments = []
        cal_matches = calendar_matches.get(file_id)
        normalized.append(normalize_file(f, comments, cal_matches))

    # Summary stats
    total_comments = sum(len(f["unresolved_comments"]) for f in normalized)
    type_counts: dict[str, int] = {}
    for f in normalized:
        type_counts[f["type"]] = type_counts.get(f["type"], 0) + 1
    files_with_calendar = sum(1 for f in normalized if f.get("calendar_matches"))

    snapshot = {
        "date": snapshot_date.isoformat(),
        "source": "gdocs",
        "lookback_hours": LOOKBACK_HOURS,
        "summary": {
            "total_files": len(normalized),
            "by_type": type_counts,
            "total_unresolved_comments": total_comments,
            "files_with_unresolved_comments": sum(1 for f in normalized if f["unresolved_comments"]),
            "presentations_matched_to_calendar": files_with_calendar,
        },
        "files": normalized,
    }

    output_path.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSnapshot written to {output_path}")
    print(f"  {len(normalized)} files | {total_comments} unresolved comments | "
          f"{files_with_calendar} calendar-matched presentations")
    if type_counts:
        print(f"  Types: {', '.join(f'{t}({n})' for t, n in sorted(type_counts.items()))}")


if __name__ == "__main__":
    main()
