#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
Jarvis: GitLab Daily Snapshot

Produces sensors/gitlab-{date}.json with a summary of MR status:
authored open MRs, review-requested MRs, recently merged, and stale detection.

Run: uv run ~/.claude/scripts/jarvis/gitlab-snapshot.py
Run tests: uv run ~/.claude/scripts/jarvis/gitlab-snapshot.py --test
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

_memory_dir = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
SENSORS_DIR = _memory_dir / "sensors"

MAX_MRS = 30
STALE_NO_REVIEWER_DAYS = 3
STALE_UNTOUCHED_DAYS = 5
STALE_FAILED_PIPELINE_HOURS = 24
RECENTLY_MERGED_DAYS = 7


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


def make_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers["PRIVATE-TOKEN"] = token
    session.headers["Accept"] = "application/json"
    return session


def fetch_mrs(session: requests.Session, base_url: str, scope: str, state: str, extra: dict | None = None) -> list[dict]:
    params: dict = {"scope": scope, "state": state, "per_page": MAX_MRS}
    if extra:
        params.update(extra)
    resp = session.get(f"{base_url}/api/v4/merge_requests", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_unresolved_threads(session: requests.Session, base_url: str, mr: dict) -> int:
    project_id = mr["project_id"]
    mr_iid = mr["iid"]
    try:
        resp = session.get(
            f"{base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/discussions",
            params={"per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        discussions = resp.json()
    except requests.RequestException as e:
        print(f"  Discussion fetch failed for MR {mr['iid']}: {e}", file=sys.stderr)
        return 0

    unresolved = 0
    for disc in discussions:
        for note in disc.get("notes", []):
            # Only count resolvable notes that are not resolved
            if note.get("resolvable") and not note.get("resolved"):
                unresolved += 1
                break  # one unresolved note = one unresolved thread
    return unresolved


def is_stale(mr: dict, now: datetime) -> bool:
    updated_str = mr.get("updated_at", "")
    created_str = mr.get("created_at", "")

    def parse_dt(s: str) -> datetime | None:
        if not s:
            return None
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    updated = parse_dt(updated_str)
    created = parse_dt(created_str)

    reviewers = mr.get("reviewers", [])
    pipeline = mr.get("head_pipeline") or {}
    pipeline_status = pipeline.get("status", "")

    # No reviewer assigned + age > STALE_NO_REVIEWER_DAYS
    if not reviewers and created:
        age_days = (now - created).total_seconds() / 86400
        if age_days > STALE_NO_REVIEWER_DAYS:
            return True

    # Failed pipeline + age > STALE_FAILED_PIPELINE_HOURS since update
    if pipeline_status == "failed" and updated:
        hours_since_update = (now - updated).total_seconds() / 3600
        if hours_since_update > STALE_FAILED_PIPELINE_HOURS:
            return True

    # Untouched > STALE_UNTOUCHED_DAYS
    if updated:
        days_since_update = (now - updated).total_seconds() / 86400
        if days_since_update > STALE_UNTOUCHED_DAYS:
            return True

    return False


def normalize_mr(mr: dict, unresolved_threads: int, stale: bool) -> dict:
    return {
        "id": mr["iid"],
        "title": mr.get("title", ""),
        "project": mr.get("references", {}).get("full", mr.get("web_url", "")).split("/-/")[0].split("/")[-1],
        "web_url": mr.get("web_url", ""),
        "updated_at": mr.get("updated_at", ""),
        "created_at": mr.get("created_at", ""),
        "draft": mr.get("draft", False),
        "reviewers": [r.get("username") for r in mr.get("reviewers", [])],
        "pipeline_status": (mr.get("head_pipeline") or {}).get("status"),
        "unresolved_threads": unresolved_threads,
        "stale": stale,
    }


def main() -> None:
    env = require_env("GITLAB_TOKEN")
    gitlab_host = os.environ.get("GITLAB_HOST", "gitlab.com")
    base_url = f"https://{gitlab_host}"

    snapshot_date = date.today()
    output_path = SENSORS_DIR / f"gitlab-{snapshot_date}.json"
    SENSORS_DIR.mkdir(parents=True, exist_ok=True)

    session = make_session(env["GITLAB_TOKEN"])
    now = datetime.now(timezone.utc)

    print(f"Fetching MRs from {base_url}...")

    # 1. Authored open MRs
    print("  → authored open MRs")
    authored_raw = fetch_mrs(session, base_url, scope="created_by_me", state="opened")
    time.sleep(0.1)

    # 2. Review-requested MRs
    print("  → review-requested MRs")
    review_raw = fetch_mrs(session, base_url, scope="assigned_to_me", state="opened")
    time.sleep(0.1)

    # 3. Recently merged (last 7 days)
    print("  → recently merged MRs")
    seven_days_ago = (now - timedelta(days=RECENTLY_MERGED_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged_raw = fetch_mrs(session, base_url, scope="created_by_me", state="merged",
                           extra={"updated_after": seven_days_ago})
    time.sleep(0.1)

    # Fetch unresolved threads for open MRs (cap total at MAX_MRS)
    open_count = min(len(authored_raw) + len(review_raw), MAX_MRS)
    print(f"  → fetching discussions for {open_count} open MRs")

    authored_normalized = []
    stale_count = 0
    for mr in authored_raw:
        unresolved = fetch_unresolved_threads(session, base_url, mr)
        stale = is_stale(mr, now)
        if stale:
            stale_count += 1
        authored_normalized.append(normalize_mr(mr, unresolved, stale))
        time.sleep(0.1)

    review_normalized = []
    for mr in review_raw:
        # Don't double-count stale for review MRs (they are someone else's)
        unresolved = fetch_unresolved_threads(session, base_url, mr)
        review_normalized.append(normalize_mr(mr, unresolved, False))
        time.sleep(0.1)

    merged_normalized = []
    for mr in merged_raw[:MAX_MRS]:
        merged_normalized.append({
            "id": mr["iid"],
            "title": mr.get("title", ""),
            "project": mr.get("references", {}).get("full", mr.get("web_url", "")).split("/-/")[0].split("/")[-1],
            "web_url": mr.get("web_url", ""),
            "merged_at": mr.get("merged_at", ""),
        })

    snapshot = {
        "date": snapshot_date.isoformat(),
        "source": "gitlab",
        "summary": {
            "open_mrs": len(authored_normalized),
            "review_requested": len(review_normalized),
            "stale_mrs": stale_count,
            "recently_merged": len(merged_normalized),
        },
        "items": {
            "open_mrs": authored_normalized,
            "review_requested": review_normalized,
            "recently_merged": merged_normalized,
        },
    }

    output_path.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSnapshot written to {output_path}")
    print(f"  {len(authored_normalized)} open MRs | {stale_count} stale | "
          f"{len(review_normalized)} reviews pending | {len(merged_normalized)} merged this week")


def test_schema() -> int:
    """Validate that a snapshot file (if present) has all required schema keys."""
    today = date.today().isoformat()
    path = SENSORS_DIR / f"gitlab-{today}.json"

    if not path.exists():
        print("No snapshot for today found — run the script first to produce output, then test.", file=sys.stderr)
        return 1

    data = json.loads(path.read_text())

    required_top = {"date", "source", "summary", "items"}
    required_summary = {"open_mrs", "review_requested", "stale_mrs", "recently_merged"}
    required_items = {"open_mrs", "review_requested", "recently_merged"}

    errors: list[str] = []

    missing_top = required_top - set(data.keys())
    if missing_top:
        errors.append(f"Missing top-level keys: {missing_top}")

    summary = data.get("summary", {})
    missing_summary = required_summary - set(summary.keys())
    if missing_summary:
        errors.append(f"Missing summary keys: {missing_summary}")

    items = data.get("items", {})
    missing_items = required_items - set(items.keys())
    if missing_items:
        errors.append(f"Missing items keys: {missing_items}")

    if data.get("source") != "gitlab":
        errors.append(f"Expected source='gitlab', got {data.get('source')!r}")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1

    print(f"OK: schema valid — {path}")
    print(f"  summary: {summary}")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(test_schema())
    main()
