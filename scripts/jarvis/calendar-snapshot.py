#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "google-auth>=2.0",
#   "google-api-python-client>=2.0",
# ]
# ///
"""
Jarvis: Google Calendar Daily Snapshot (ADC approach)

Uses Application Default Credentials (gcloud auth application-default login).
No service account key, no OAuth client setup.

SETUP (one-time):
  gcloud auth application-default login \
    --scopes=https://www.googleapis.com/auth/calendar.readonly

Run: uv run ~/.claude/scripts/jarvis/calendar-snapshot.py
Cron: 0 6 * * * bash ~/.claude/scripts/jarvis/daily-cron.sh calendar
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
LOOKAHEAD_DAYS = 14
_calendar_filter = os.environ.get("JARVIS_CALENDAR_FILTER", "")
CALENDAR_INCLUDE = {c.strip() for c in _calendar_filter.split(",") if c.strip()} if _calendar_filter else set()


def build_service():
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/calendar.readonly"]
    )
    return build("calendar", "v3", credentials=creds)


def list_calendars(service) -> list[dict]:
    result = service.calendarList().list().execute()
    items = result.get("items", [])
    return [c for c in items if c.get("summary") in CALENDAR_INCLUDE]


def fetch_events(service, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
    events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
            maxResults=250,
        ).execute()
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events


def normalize_event(item: dict, calendar_name: str) -> dict:
    start_raw = item.get("start", {})
    end_raw = item.get("end", {})

    all_day = "date" in start_raw and "dateTime" not in start_raw

    if all_day:
        start_str = start_raw.get("date", "")
        end_str = end_raw.get("date", "")
        start_dt = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc) if start_str else None
        end_dt = datetime.fromisoformat(end_str).replace(tzinfo=timezone.utc) if end_str else None
    else:
        start_str = start_raw.get("dateTime", "")
        end_str = end_raw.get("dateTime", "")
        start_dt = datetime.fromisoformat(start_str) if start_str else None
        end_dt = datetime.fromisoformat(end_str) if end_str else None

    duration_minutes = None
    if start_dt and end_dt:
        duration_minutes = int((end_dt - start_dt).total_seconds() / 60)

    attendees = item.get("attendees", [])
    recurrence = item.get("recurringEventId") or item.get("recurrence")

    return {
        "title": item.get("summary", "(no title)"),
        "calendar": calendar_name,
        "start": start_dt.isoformat() if start_dt else start_str,
        "end": end_dt.isoformat() if end_dt else end_str,
        "duration_minutes": duration_minutes,
        "all_day": all_day,
        "recurring": bool(recurrence),
        "attendee_count": len(attendees),
        "location": item.get("location", ""),
        "status": item.get("status", ""),
    }


def analyze_events(events: list[dict]) -> dict:
    today = date.today()
    today_str = today.isoformat()
    tomorrow_str = (today + timedelta(days=1)).isoformat()

    timed = [e for e in events if e["duration_minutes"] is not None and not e["all_day"]]
    total_minutes = sum(e["duration_minutes"] for e in timed)

    daily_load: dict[str, int] = {}
    for e in timed:
        day = e["start"][:10]
        daily_load[day] = daily_load.get(day, 0) + e["duration_minutes"]

    return {
        "total_events": len(events),
        "total_meeting_minutes": total_minutes,
        "avg_daily_meeting_minutes": round(total_minutes / LOOKAHEAD_DAYS, 1),
        "recurring_event_count": sum(1 for e in events if e["recurring"]),
        "today_event_count": sum(1 for e in events if e["start"].startswith(today_str)),
        "tomorrow_event_count": sum(1 for e in events if e["start"].startswith(tomorrow_str)),
        "busiest_day": max(daily_load, key=lambda d: daily_load[d]) if daily_load else None,
        "lightest_day": min(daily_load, key=lambda d: daily_load[d]) if daily_load else None,
        "daily_load_minutes": daily_load,
        "deep_work_days": [day for day, mins in daily_load.items() if mins < 60],
    }


def main() -> None:
    snapshot_date = date.today()
    output_path = SENSORS_DIR / f"calendar-{snapshot_date}.json"
    SENSORS_DIR.mkdir(parents=True, exist_ok=True)

    service = build_service()

    calendars = list_calendars(service)
    print(f"Found {len(calendars)} calendar(s): {', '.join(c.get('summary', c['id']) for c in calendars)}")

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=LOOKAHEAD_DAYS)

    all_events: list[dict] = []
    calendar_summary = []

    for cal in calendars:
        cal_id = cal["id"]
        cal_name = cal.get("summary", cal_id)
        print(f"  Fetching: {cal_name}...")
        try:
            items = fetch_events(service, cal_id, now, window_end)
            events = [normalize_event(item, cal_name) for item in items]
            all_events.extend(events)
            calendar_summary.append({"name": cal_name, "event_count": len(events)})
            print(f"    {len(events)} events in next {LOOKAHEAD_DAYS} days")
        except Exception as e:
            print(f"    Failed: {e}", file=sys.stderr)
            calendar_summary.append({"name": cal_name, "event_count": 0, "error": str(e)})

    analysis = analyze_events(all_events)

    snapshot = {
        "snapshot_date": snapshot_date.isoformat(),
        "lookahead_days": LOOKAHEAD_DAYS,
        "calendars": calendar_summary,
        "analysis": analysis,
        "events": sorted(all_events, key=lambda e: e["start"]),
    }

    output_path.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSnapshot written to {output_path}")
    print(f"  {len(all_events)} events | {analysis['total_meeting_minutes']}min total | "
          f"avg {analysis['avg_daily_meeting_minutes']}min/day")
    if analysis["deep_work_days"]:
        print(f"  Light days (<1h meetings): {', '.join(sorted(analysis['deep_work_days']))}")


if __name__ == "__main__":
    main()
