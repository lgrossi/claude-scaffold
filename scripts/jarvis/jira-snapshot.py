#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
Jarvis: Jira Daily Snapshot

Produces sensors/jira-{date}.json with open issues assigned to the current user,
staleness flags, and active sprint health.

Run: uv run ~/.claude/scripts/jarvis/jira-snapshot.py
"""

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

_memory_dir = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
SENSORS_DIR = _memory_dir / "sensors"

STALE_IN_PROGRESS_DAYS = 5
STALE_ANY_DAYS = 7
MAX_ISSUES = 50


def require_env(*names: str) -> dict[str, str]:
    vals = {}
    missing = []
    for name in names:
        val = os.environ.get(name)
        if not val:
            missing.append(name)
        else:
            vals[name] = val
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    return vals


def make_session(jira_url: str, username: str, api_token: str) -> tuple[requests.Session, str]:
    session = requests.Session()
    session.auth = (username, api_token)
    session.headers["Accept"] = "application/json"
    return session, jira_url.rstrip("/")


def search_issues(session: requests.Session, base_url: str) -> list[dict]:
    jql = "assignee = currentUser() AND NOT statusCategory = Done ORDER BY updated DESC"
    resp = session.get(
        f"{base_url}/rest/api/3/search/jql",
        params={"jql": jql, "maxResults": MAX_ISSUES, "fields": "summary,status,updated"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("issues", [])


def compute_staleness(issue: dict, now: datetime) -> bool:
    updated_str = issue["fields"].get("updated", "")
    if not updated_str:
        return True
    updated = datetime.fromisoformat(updated_str.replace("+0000", "+00:00"))
    days_since = (now - updated).days
    status_category = issue["fields"]["status"].get("statusCategory", {}).get("name", "")
    if status_category == "In Progress":
        return days_since > STALE_IN_PROGRESS_DAYS
    return days_since > STALE_ANY_DAYS


def normalize_issue(issue: dict, base_url: str, stale: bool) -> dict:
    return {
        "key": issue["key"],
        "summary": issue["fields"].get("summary", ""),
        "status": issue["fields"]["status"]["name"],
        "updated": issue["fields"].get("updated", ""),
        "stale": stale,
        "url": f"{base_url}/browse/{issue['key']}",
    }


def fetch_sprint_health(session: requests.Session, base_url: str, board_id: int) -> dict | None:
    try:
        resp = session.get(
            f"{base_url}/rest/agile/1.0/board/{board_id}/sprint",
            params={"state": "active"},
            timeout=30,
        )
        resp.raise_for_status()
        sprints = resp.json().get("values", [])
        if not sprints:
            return None

        sprint = sprints[0]
        sprint_id = sprint["id"]

        issues_resp = session.get(
            f"{base_url}/rest/agile/1.0/sprint/{sprint_id}/issue",
            params={"maxResults": 200, "fields": "status"},
            timeout=30,
        )
        issues_resp.raise_for_status()
        sprint_issues = issues_resp.json().get("issues", [])

        total = len(sprint_issues)
        done = sum(
            1 for i in sprint_issues
            if i["fields"]["status"].get("statusCategory", {}).get("name") == "Done"
        )

        start_date = sprint.get("startDate", "")
        end_date = sprint.get("endDate", "")
        days_remaining = None
        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            days_remaining = max(0, (end_dt - datetime.now(timezone.utc)).days)

        return {
            "name": sprint.get("name", ""),
            "start_date": start_date,
            "end_date": end_date,
            "days_remaining": days_remaining,
            "total_issues": total,
            "done_issues": done,
            "completion_pct": round(done / total * 100, 1) if total else 0,
        }
    except requests.RequestException as e:
        print(f"Sprint health fetch failed: {e}", file=sys.stderr)
        return None


def main() -> None:
    env = require_env("JIRA_URL", "JIRA_USERNAME", "JIRA_API_TOKEN")
    board_id = int(os.environ.get("JARVIS_JIRA_BOARD_ID", "321"))

    snapshot_date = date.today()
    output_path = SENSORS_DIR / f"jira-{snapshot_date}.json"
    SENSORS_DIR.mkdir(parents=True, exist_ok=True)

    session, base_url = make_session(env["JIRA_URL"], env["JIRA_USERNAME"], env["JIRA_API_TOKEN"])
    now = datetime.now(timezone.utc)

    print(f"Fetching issues from {base_url}...")
    raw_issues = search_issues(session, base_url)
    print(f"Found {len(raw_issues)} open issues")

    issues = []
    stale_count = 0
    for issue in raw_issues:
        stale = compute_staleness(issue, now)
        if stale:
            stale_count += 1
        issues.append(normalize_issue(issue, base_url, stale))

    print(f"Fetching sprint health (board {board_id})...")
    sprint = fetch_sprint_health(session, base_url, board_id)

    snapshot = {
        "date": snapshot_date.isoformat(),
        "source": "jira",
        "summary": {
            "open_issues": len(issues),
            "stale_issues": stale_count,
            "sprint_name": sprint["name"] if sprint else None,
            "sprint_days_remaining": sprint["days_remaining"] if sprint else None,
            "sprint_completion_pct": sprint["completion_pct"] if sprint else None,
        },
        "items": {
            "issues": issues,
            "sprint": sprint,
        },
    }

    output_path.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSnapshot written to {output_path}")
    print(f"  {len(issues)} issues | {stale_count} stale")
    if sprint:
        print(f"  Sprint: {sprint['name']} | {sprint['days_remaining']}d remaining | {sprint['completion_pct']}% done")


if __name__ == "__main__":
    main()
