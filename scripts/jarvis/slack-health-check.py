#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
Jarvis: Slack Token Health Check

Validates the current SLACK_XOXC_TOKEN + SLACK_XOXD_TOKEN via auth.test.
If tokens are expired, writes an orange insight to pending-insights.json
so the statusline alerts the user to manually refresh slack-env.sh.

Manual refresh when tokens expire:
  1. Open Chrome → Slack → DevTools → Application → Cookies → copy 'd' (xoxd)
  2. DevTools → Console → copy TS.boot_data.token (xoxc)
  3. Update ~/.claude/secrets/slack-env.sh and re-source it

Run: uv run ~/.claude/scripts/jarvis/slack-health-check.py
Schedule: systemd timer (jarvis-slack.timer), hourly
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

SLACK_HOST = "molliehq.slack.com"
ENV_FILE = Path.home() / ".claude" / "secrets" / "slack-env.sh"
INSIGHTS_FILE = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis"))) / "pending-insights.json"
INSIGHT_ID_PREFIX = "slack-tokens-expired"


def check_tokens(xoxc: str, xoxd: str) -> tuple[bool, str]:
    try:
        resp = requests.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {xoxc}"},
            cookies={"d": xoxd},
            timeout=5,
        )
        data = resp.json()
        if data.get("ok"):
            return True, data.get("user", "?")
        return False, data.get("error", "unknown error")
    except Exception as e:
        return False, str(e)


def load_insights() -> list[dict]:
    if INSIGHTS_FILE.exists():
        try:
            return json.loads(INSIGHTS_FILE.read_text())
        except Exception:
            return []
    return []


def save_insights(insights: list[dict]) -> None:
    INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = INSIGHTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(insights, indent=2))
    tmp.replace(INSIGHTS_FILE)


def remove_stale_slack_insight(insights: list[dict]) -> list[dict]:
    return [i for i in insights if not i.get("id", "").startswith(INSIGHT_ID_PREFIX)]


def write_expired_insight() -> None:
    insights = load_insights()
    insights = remove_stale_slack_insight(insights)
    insights.append({
        "id": f"{INSIGHT_ID_PREFIX}-{str(uuid.uuid4())[:8]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "surfaced_at": None,
        "urgency": "orange",
        "source": "slack-health",
        "title": "Slack tokens expired — manual refresh needed",
        "body": (
            "SLACK_XOXC_TOKEN / SLACK_XOXD_TOKEN failed auth.test. "
            "Tokens expire with the browser session."
        ),
        "action": (
            "1. Open Chrome → Slack → DevTools (F12) → Application → Cookies → copy 'd' value (xoxd)\n"
            "2. DevTools → Console → run: copy(TS.boot_data.token) (xoxc)\n"
            f"3. Update {ENV_FILE} and run: source {ENV_FILE}"
        ),
    })
    save_insights(insights)
    print("Orange insight written to pending-insights.json — statusline will alert.")


def clear_expired_insight() -> None:
    insights = load_insights()
    cleaned = remove_stale_slack_insight(insights)
    if len(cleaned) < len(insights):
        save_insights(cleaned)
        print("Cleared stale Slack token insight.")


def main() -> None:
    xoxc = os.environ.get("SLACK_XOXC_TOKEN", "")
    xoxd = os.environ.get("SLACK_XOXD_TOKEN", "")

    if not xoxc or not xoxd:
        print("SLACK_XOXC_TOKEN or SLACK_XOXD_TOKEN not set in environment.")
        print(f"Source {ENV_FILE} and ensure it's loaded from ~/.bashrc")
        write_expired_insight()
        return

    ok, info = check_tokens(xoxc, xoxd)

    if ok:
        print(f"Slack tokens valid (user: {info})")
        clear_expired_insight()
    else:
        print(f"Slack tokens invalid: {info}")
        write_expired_insight()


if __name__ == "__main__":
    main()
