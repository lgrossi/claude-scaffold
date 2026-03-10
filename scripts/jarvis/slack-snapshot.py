#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pycookiecheat", "requests"]
# ///
"""
Jarvis: Slack Daily Snapshot

Captures content from channels the user participates in, focusing on
things they might have missed. The analyzer uses this to surface
relevant discussions, decisions, and action items.

Run: uv run ~/.claude/scripts/jarvis/slack-snapshot.py
"""

import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import slack_tokens

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

_memory_dir = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
SENSORS_DIR = _memory_dir / "sensors"

SCAN_CHANNELS = 50
MAX_MESSAGES_PER_CHANNEL = 30
MY_CHANNELS_FILE = SENSORS_DIR / "slack-my-channels.json"

SKIP_PATTERNS = re.compile(
    r"(alerts?|errors?|logs?|notifications?|deploy|bot|monitoring|sentry|datadog|pagerduty)",
    re.IGNORECASE,
)


def make_api(xoxc: str, xoxd: str):
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {xoxc}"
    session.cookies.set("d", xoxd)

    def api(method: str, **params) -> dict:
        all_items: list[dict] = []
        cursor = None
        while True:
            if cursor:
                params["cursor"] = cursor
            data = {}
            for attempt in range(3):
                resp = session.get(f"https://slack.com/api/{method}", params=params, timeout=15)
                data = resp.json()
                if data.get("error") == "ratelimited":
                    wait = int(resp.headers.get("Retry-After", 5))
                    print(f"  Rate limited on {method}, waiting {wait}s (attempt {attempt + 1}/3)")
                    time.sleep(wait)
                    continue
                break
            if not data.get("ok"):
                raise RuntimeError(f"Slack API {method} failed: {data.get('error', 'unknown')}")
            all_items.append(data)
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return all_items[0] if len(all_items) == 1 else _merge_paginated(all_items, method)

    return api


def _merge_paginated(pages: list[dict], method: str) -> dict:
    merged = dict(pages[0])
    list_key = {"conversations.list": "channels", "conversations.history": "messages", "conversations.replies": "messages"}.get(method)
    if list_key:
        merged[list_key] = []
        for page in pages:
            merged[list_key].extend(page.get(list_key, []))
    return merged


def _load_my_channels() -> set[str]:
    if MY_CHANNELS_FILE.exists():
        try:
            return set(json.loads(MY_CHANNELS_FILE.read_text()))
        except (json.JSONDecodeError, TypeError):
            pass
    return set()


def _save_my_channels(channel_ids: set[str]) -> None:
    MY_CHANNELS_FILE.write_text(json.dumps(sorted(channel_ids), indent=2))


def _resolve_user(api, user_id: str, cache: dict[str, str]) -> str:
    if user_id in cache:
        return cache[user_id]
    try:
        data = api("users.info", user=user_id)
        name = data.get("user", {}).get("profile", {}).get("display_name") or data.get("user", {}).get("real_name", user_id)
        cache[user_id] = name
    except RuntimeError:
        name = user_id
        cache[user_id] = name
    return name


def _message_digest(m: dict, user_cache: dict[str, str], api) -> dict:
    """Extract a content-focused digest from a message."""
    user = _resolve_user(api, m.get("user", ""), user_cache) if m.get("user") else "unknown"
    return {
        "user": user,
        "text": m.get("text", "")[:500],
        "ts": m.get("ts", ""),
        "reactions": sum(r.get("count", 0) for r in m.get("reactions", [])),
        "reply_count": m.get("reply_count", 0),
    }


def main() -> None:
    snapshot_date = date.today()
    output_path = SENSORS_DIR / f"slack-{snapshot_date}.json"
    SENSORS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        xoxc, xoxd, _ = slack_tokens.extract_and_validate()
    except ValueError as e:
        print(f"Token extraction failed: {e}", file=sys.stderr)
        sys.exit(1)

    api = make_api(xoxc, xoxd)

    auth = api("auth.test")
    my_id = auth["user_id"]
    print(f"Authenticated as {auth.get('user', my_id)}")

    now = datetime.now(timezone.utc)
    oldest = str(int(now.timestamp()) - 86400)

    # Build scan list from cached channels + fill from conversations.list
    my_channel_ids = _load_my_channels()
    cached_channels = []
    for ch_id in list(my_channel_ids)[:SCAN_CHANNELS]:
        try:
            info = api("conversations.info", channel=ch_id)
            ch = info.get("channel", {})
            if ch and not ch.get("is_archived"):
                cached_channels.append(ch)
        except RuntimeError:
            pass

    remaining = SCAN_CHANNELS - len(cached_channels)
    cached_ids = {ch["id"] for ch in cached_channels}
    fill_channels = []
    if remaining > 0:
        resp = requests.get(
            "https://slack.com/api/conversations.list",
            params={"types": "public_channel,private_channel,mpim", "exclude_archived": "true", "limit": 200},
            headers={"Authorization": f"Bearer {xoxc}"},
            cookies={"d": xoxd},
            timeout=15,
        )
        chan_data = resp.json()
        if chan_data.get("ok"):
            for ch in chan_data.get("channels", []):
                if ch["id"] not in cached_ids and not SKIP_PATTERNS.search(ch.get("name", "")):
                    fill_channels.append(ch)
            fill_channels.sort(key=lambda ch: ch.get("updated", 0), reverse=True)
            fill_channels = fill_channels[:remaining]

    channels = cached_channels + fill_channels
    print(f"Scanning {len(cached_channels)} from history + {len(fill_channels)} recent = {len(channels)} channels")

    user_cache: dict[str, str] = {}
    channel_digests = []  # channels I wasn't active in — content to review
    my_activity = []      # channels I was active in — threads/mentions
    unanswered_threads = []
    mentions = []

    for ch in channels:
        ch_id = ch["id"]
        ch_name = ch.get("name", ch_id)
        try:
            hist = api("conversations.history", channel=ch_id, oldest=oldest, limit=100)
        except RuntimeError as e:
            print(f"  Skipping #{ch_name}: {e}", file=sys.stderr)
            time.sleep(0.1)
            continue

        messages = hist.get("messages", [])
        if not messages:
            time.sleep(0.1)
            continue

        my_posts = [m for m in messages if m.get("user") == my_id]
        my_mentions = [m for m in messages if f"<@{my_id}>" in m.get("text", "")]

        # Collect mentions with context
        for m in my_mentions:
            mentions.append({
                "channel": ch_name,
                "from": _resolve_user(api, m.get("user", ""), user_cache),
                "text": m.get("text", "")[:500],
                "ts": m.get("ts", ""),
            })

        # Find unanswered threads (someone replied to my thread, I haven't responded)
        for m in messages:
            is_my_thread = m.get("user") == my_id and m.get("reply_count", 0) > 0
            replied_to_me = m.get("thread_ts") and m.get("thread_ts") != m.get("ts") and m.get("user") == my_id
            if is_my_thread or replied_to_me:
                ts = m.get("thread_ts", m["ts"]) if replied_to_me else m["ts"]
                try:
                    replies_data = api("conversations.replies", channel=ch_id, ts=ts, limit=50)
                    replies = replies_data.get("messages", [])
                    if replies and replies[-1].get("user") != my_id:
                        unanswered_threads.append({
                            "channel": ch_name,
                            "reply_count": len(replies) - 1,
                            "last_reply_from": _resolve_user(api, replies[-1].get("user", ""), user_cache),
                            "last_reply_text": replies[-1].get("text", "")[:300],
                            "ts": ts,
                        })
                except RuntimeError:
                    pass
                time.sleep(0.1)

        if my_posts:
            # Channel I was active in — just track participation
            my_activity.append({
                "channel": ch_name,
                "my_posts": len(my_posts),
                "total_messages": len(messages),
            })
        else:
            # Channel I wasn't active in — capture content for the analyzer
            # Take the most substantive messages (longest text, most reactions)
            substantive = [m for m in messages if len(m.get("text", "")) > 20 and m.get("subtype") is None]
            substantive.sort(key=lambda m: (
                sum(r.get("count", 0) for r in m.get("reactions", [])),
                len(m.get("text", "")),
            ), reverse=True)

            digested = [_message_digest(m, user_cache, api) for m in substantive[:MAX_MESSAGES_PER_CHANNEL]]
            if digested:
                channel_digests.append({
                    "channel": ch_name,
                    "total_messages": len(messages),
                    "content": digested,
                })

        time.sleep(0.1)

    # Update my channels cache
    active_ids = {ch["id"] for ch in channels
                  if any(a["channel"] == ch.get("name", ch["id"]) for a in my_activity)}
    if active_ids:
        my_channel_ids |= active_ids
        _save_my_channels(my_channel_ids)

    # DM count
    dm_data = api("conversations.list", types="im", limit=200)
    dm_active = 0
    for dm in dm_data.get("channels", []):
        try:
            dm_hist = api("conversations.history", channel=dm["id"], oldest=oldest, limit=1)
            if dm_hist.get("messages"):
                dm_active += 1
        except RuntimeError:
            pass
        time.sleep(0.1)

    snapshot = {
        "date": snapshot_date.isoformat(),
        "source": "slack",
        "user_id": my_id,
        "summary": {
            "channels_scanned": len(channels),
            "channels_from_history": len(cached_channels),
            "channels_i_posted_in": len(my_activity),
            "channels_to_review": len(channel_digests),
            "unanswered_threads": len(unanswered_threads),
            "mentions": len(mentions),
            "dm_active": dm_active,
        },
        "items": {
            "unanswered_threads": unanswered_threads,
            "mentions": mentions,
            "my_activity": my_activity,
            "missed_content": channel_digests,
        },
    }

    output_path.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSnapshot written to {output_path}")
    print(f"  {len(my_activity)} channels active | {len(channel_digests)} to review | {len(unanswered_threads)} unanswered | {len(mentions)} mentions | {dm_active} DMs")


if __name__ == "__main__":
    main()
