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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

_memory_dir = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
SENSORS_DIR = _memory_dir / "sensors"

STALE_IN_PROGRESS_DAYS = 5
STALE_ANY_DAYS = 7
MAX_ISSUES = 50
WATCHED_LOOKBACK_HOURS = 24
MAX_WATCHED_ISSUES = 30
MY_BOARDS_FILE = SENSORS_DIR / "jira-my-boards.json"


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


def _load_watched_boards() -> list[dict]:
    if MY_BOARDS_FILE.exists():
        try:
            return json.loads(MY_BOARDS_FILE.read_text())
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def fetch_recent_comments(session: requests.Session, base_url: str, issue_key: str) -> list[dict]:
    """Fetch comments updated in the last 24h for an issue."""
    try:
        resp = session.get(
            f"{base_url}/rest/api/3/issue/{issue_key}/comment",
            params={"maxResults": 10, "orderBy": "-created"},
            timeout=15,
        )
        resp.raise_for_status()
        comments = resp.json().get("comments", [])
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WATCHED_LOOKBACK_HOURS)
        recent = []
        for c in comments:
            created = c.get("created", "")
            if created:
                dt = datetime.fromisoformat(created.replace("+0000", "+00:00"))
                if dt < cutoff:
                    continue
            author = c.get("author", {}).get("displayName", "")
            # ADF body → extract plain text from first paragraph
            body_adf = c.get("body", {})
            text = ""
            if isinstance(body_adf, dict):
                for block in body_adf.get("content", []):
                    for inline in block.get("content", []):
                        if inline.get("type") == "text":
                            text += inline.get("text", "")
            recent.append({"author": author, "text": text[:300], "created": created})
        return recent
    except requests.RequestException:
        return []


def fetch_watched_activity(session: requests.Session, base_url: str, boards: list[dict]) -> list[dict]:
    """Fetch recently updated issues from watched boards/projects."""
    if not boards:
        return []
    keys = [b["key"] for b in boards]
    # Exclude user's own board (MPM) — already covered by assigned issues
    jql_projects = ", ".join(keys)
    since = (datetime.now(timezone.utc) - timedelta(hours=WATCHED_LOOKBACK_HOURS)).strftime("%Y-%m-%d %H:%M")
    jql = f"project in ({jql_projects}) AND updated >= '{since}' AND NOT assignee = currentUser() ORDER BY updated DESC"
    try:
        resp = session.get(
            f"{base_url}/rest/api/3/search/jql",
            params={"jql": jql, "maxResults": MAX_WATCHED_ISSUES, "fields": "summary,status,updated,comment,creator,issuetype,project"},
            timeout=30,
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
    except requests.RequestException as e:
        print(f"  Watched boards fetch failed: {e}", file=sys.stderr)
        return []

    results = []
    for issue in issues:
        fields = issue.get("fields", {})
        # Get the latest comment if any
        comments = fields.get("comment", {}).get("comments", [])
        latest_comment = None
        if comments:
            c = comments[-1]
            body_adf = c.get("body", {})
            text = ""
            if isinstance(body_adf, dict):
                for block in body_adf.get("content", []):
                    for inline in block.get("content", []):
                        if inline.get("type") == "text":
                            text += inline.get("text", "")
            latest_comment = {
                "author": c.get("author", {}).get("displayName", ""),
                "text": text[:300],
            }
        results.append({
            "key": issue["key"],
            "summary": fields.get("summary", ""),
            "project": fields.get("project", {}).get("key", ""),
            "status": fields.get("status", {}).get("name", ""),
            "type": fields.get("issuetype", {}).get("name", ""),
            "updated": fields.get("updated", ""),
            "creator": fields.get("creator", {}).get("displayName", ""),
            "latest_comment": latest_comment,
            "url": f"{base_url}/browse/{issue['key']}",
        })
    return results


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
    issues_with_comments = 0
    for issue in raw_issues:
        stale = compute_staleness(issue, now)
        if stale:
            stale_count += 1
        normalized = normalize_issue(issue, base_url, stale)
        # Fetch recent comments on assigned issues
        recent_comments = fetch_recent_comments(session, base_url, issue["key"])
        if recent_comments:
            normalized["recent_comments"] = recent_comments
            issues_with_comments += 1
        issues.append(normalized)

    print(f"  {issues_with_comments} issues with recent comments")

    # Watched boards — activity from other projects
    watched_boards = _load_watched_boards()
    print(f"Fetching watched board activity ({len(watched_boards)} boards)...")
    watched_activity = fetch_watched_activity(session, base_url, watched_boards)
    print(f"  {len(watched_activity)} recent updates on watched boards")

    print(f"Fetching sprint health (board {board_id})...")
    sprint = fetch_sprint_health(session, base_url, board_id)

    snapshot = {
        "date": snapshot_date.isoformat(),
        "source": "jira",
        "summary": {
            "open_issues": len(issues),
            "stale_issues": stale_count,
            "issues_with_recent_comments": issues_with_comments,
            "watched_boards": len(watched_boards),
            "watched_updates": len(watched_activity),
            "sprint_name": sprint["name"] if sprint else None,
            "sprint_days_remaining": sprint["days_remaining"] if sprint else None,
            "sprint_completion_pct": sprint["completion_pct"] if sprint else None,
        },
        "items": {
            "issues": issues,
            "watched_activity": watched_activity,
            "sprint": sprint,
        },
    }

    output_path.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSnapshot written to {output_path}")
    print(f"  {len(issues)} issues | {stale_count} stale | {issues_with_comments} with comments")
    print(f"  {len(watched_activity)} watched board updates")
    if sprint:
        print(f"  Sprint: {sprint['name']} | {sprint['days_remaining']}d remaining | {sprint['completion_pct']}% done")


if __name__ == "__main__":
    main()
