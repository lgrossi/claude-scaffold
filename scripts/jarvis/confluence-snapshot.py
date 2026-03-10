#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
Jarvis: Confluence Daily Snapshot

Produces sensors/confluence-{date}.json with pages owned and watched,
plus unresolved comments across those pages.

Run: uv run ~/.claude/scripts/jarvis/confluence-snapshot.py
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

MAX_PAGES = 50
WATCHED_LOOKBACK_HOURS = 24
MY_SPACES_FILE = SENSORS_DIR / "confluence-my-spaces.json"


def build_snapshot(base_url: str, auth: tuple[str, str]) -> dict:
    session = requests.Session()
    session.auth = auth

    my_pages = _fetch_my_pages(session, base_url)
    watched_pages = _fetch_watched_pages(session, base_url)

    # Deduplicate: remove watched pages that are also owned
    owned_ids = {p["id"] for p in my_pages}
    watched_pages = [p for p in watched_pages if p["id"] not in owned_ids]

    all_pages = my_pages + watched_pages
    all_page_ids = [p["id"] for p in all_pages]

    unresolved = _fetch_unresolved_comments(session, base_url, all_page_ids)

    # Watched space activity — recent edits across monitored spaces
    watched_spaces = _load_watched_spaces()
    space_activity = []
    if watched_spaces:
        print(f"  Scanning {len(watched_spaces)} watched spaces for recent activity...")
        space_activity = _fetch_space_recent_pages(session, base_url, watched_spaces)
        print(f"    found {len(space_activity)} recently modified pages")

    def page_summary(p: dict) -> dict:
        version = p.get("version", {})
        return {
            "id": p["id"],
            "title": p["title"],
            "link": p.get("_links", {}).get("webui", ""),
            "version": version.get("number") if isinstance(version, dict) else None,
            "last_modified": version.get("createdAt", "") if isinstance(version, dict) else "",
        }

    # Extract comment body text from ADF or storage format
    def comment_digest(c: dict) -> dict:
        body = c.get("body", {})
        text = ""
        if isinstance(body, dict):
            storage = body.get("storage", {})
            if isinstance(storage, dict):
                text = storage.get("value", "")[:300]
            elif isinstance(body.get("atlas_doc_format", {}), dict):
                text = c.get("title", "")[:300]
        if not text:
            text = c.get("title", "")[:300]
        return {
            "comment_id": c["id"],
            "page_id": c.get("_page_id", ""),
            "title": c.get("title", ""),
            "text": text,
            "author": c.get("version", {}).get("by", {}).get("displayName", "") if isinstance(c.get("version"), dict) else "",
            "created": c.get("version", {}).get("createdAt", "") if isinstance(c.get("version"), dict) else "",
        }

    return {
        "date": date.today().isoformat(),
        "source": "confluence",
        "summary": {
            "my_pages": len(my_pages),
            "watched_pages": len(watched_pages),
            "unresolved_comments": len(unresolved),
            "watched_spaces": len(watched_spaces),
            "watched_space_updates": len(space_activity),
        },
        "items": {
            "my_pages": [page_summary(p) for p in my_pages],
            "watched_pages": [page_summary(p) for p in watched_pages],
            "unresolved_comments": [comment_digest(c) for c in unresolved],
            "watched_activity": space_activity,
        },
    }


def _fetch_my_pages(session: requests.Session, base_url: str) -> list[dict]:
    """Fetch pages owned by the authenticated user (v2 API)."""
    resp = session.get(
        f"{base_url}/api/v2/pages",
        params={"status": "current", "limit": MAX_PAGES, "sort": "-modified-date"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def _fetch_watched_pages(session: requests.Session, base_url: str) -> list[dict]:
    """Fetch pages the user is watching via CQL search."""
    resp = session.get(
        f"{base_url}/rest/api/content/search",
        params={"cql": "watcher = currentUser() AND type = page", "limit": MAX_PAGES},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def _load_watched_spaces() -> list[dict]:
    if MY_SPACES_FILE.exists():
        try:
            return json.loads(MY_SPACES_FILE.read_text())
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _fetch_space_recent_pages(session: requests.Session, base_url: str, spaces: list[dict]) -> list[dict]:
    """Fetch recently modified pages across watched spaces."""
    since = datetime.now(timezone.utc) - timedelta(hours=WATCHED_LOOKBACK_HOURS)
    since_str = since.strftime("%Y-%m-%d %H:%M")

    results = []
    for space in spaces:
        cql = f'space = "{space["key"]}" AND type = page AND lastModified >= "{since_str}" ORDER BY lastModified DESC'
        try:
            resp = session.get(
                f"{base_url}/rest/api/content/search",
                params={"cql": cql, "limit": 10, "expand": "version,history.lastUpdated"},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            pages = resp.json().get("results", [])
        except Exception:
            continue

        for p in pages:
            version = p.get("version", {})
            modifier = version.get("by", {}).get("displayName", "") if isinstance(version, dict) else ""
            results.append({
                "space": space["key"],
                "space_name": space["name"],
                "page_id": p.get("id", ""),
                "title": p.get("title", ""),
                "modifier": modifier,
                "modified_at": version.get("when", "") if isinstance(version, dict) else "",
                "version": version.get("number") if isinstance(version, dict) else None,
                "link": p.get("_links", {}).get("webui", ""),
            })

    return results


def _fetch_unresolved_comments(session: requests.Session, base_url: str, page_ids: list[str]) -> list[dict]:
    """Fetch footer comments for given pages, filter to unresolved client-side."""
    unresolved = []
    for page_id in page_ids:
        resp = session.get(
            f"{base_url}/api/v2/footer-comments",
            params={"page-id": page_id, "limit": 50},
            timeout=15,
        )
        if resp.status_code != 200:
            continue
        comments = resp.json().get("results", [])
        for c in comments:
            if c.get("status") != "resolved":
                c["_page_id"] = page_id
                unresolved.append(c)
    return unresolved


def main() -> None:
    base_url = os.environ.get("CONFLUENCE_URL", "").rstrip("/")
    username = os.environ.get("CONFLUENCE_USERNAME", "")
    api_token = os.environ.get("CONFLUENCE_API_TOKEN", "")

    if not all([base_url, username, api_token]):
        print("Missing CONFLUENCE_URL, CONFLUENCE_USERNAME, or CONFLUENCE_API_TOKEN", file=sys.stderr)
        sys.exit(1)

    snapshot_date = date.today()
    output_path = SENSORS_DIR / f"confluence-{snapshot_date}.json"
    SENSORS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching Confluence snapshot for {username}...")
    snapshot = build_snapshot(base_url, auth=(username, api_token))

    output_path.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSnapshot written to {output_path}")
    s = snapshot["summary"]
    print(f"  {s['my_pages']} owned pages | {s['watched_pages']} watched | {s['unresolved_comments']} unresolved comments")
    print(f"  {s.get('watched_space_updates', 0)} updates across {s.get('watched_spaces', 0)} watched spaces")


if __name__ == "__main__":
    main()
