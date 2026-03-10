#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
Jarvis: Slack Daily Snapshot

Produces sensors/slack-{date}.json with a rich summary of Slack activity
from the past 24 hours: threads, mentions, channel digests, and interaction map.

Run: uv run ~/.claude/scripts/jarvis/slack-snapshot.py
"""

import json
import os
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

REACTION_THRESHOLD = 3
MAX_CHANNELS = 20
MAX_INTERACTIONS = 10


def make_api(xoxc: str, xoxd: str):
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {xoxc}"
    session.cookies.set("d", xoxd)

    def api(method: str, **params) -> dict:
        all_items = []
        cursor = None
        while True:
            if cursor:
                params["cursor"] = cursor
            resp = session.get(f"https://slack.com/api/{method}", params=params, timeout=15)
            data = resp.json()
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
    list_key = _list_key_for(method)
    if list_key:
        merged[list_key] = []
        for page in pages:
            merged[list_key].extend(page.get(list_key, []))
    return merged


def _list_key_for(method: str) -> str | None:
    mapping = {
        "conversations.list": "channels",
        "conversations.history": "messages",
        "conversations.replies": "messages",
    }
    return mapping.get(method)


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

    # Get my user ID
    auth = api("auth.test")
    my_id = auth["user_id"]
    print(f"Authenticated as {auth.get('user', my_id)}")

    # Time window: past 24h
    now = datetime.now(timezone.utc)
    oldest = str(int(now.timestamp()) - 86400)

    # Fetch joined channels
    chan_data = api("conversations.list", types="public_channel,private_channel", exclude_archived="true", limit=200)
    channels = chan_data.get("channels", [])
    print(f"Found {len(channels)} joined channels")

    # Per-channel activity scan
    user_name_cache: dict[str, str] = {}
    interaction_map: dict[str, dict] = {}  # user_id -> {sent: N, received: N}
    channel_stats = []

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
        mentions = [m for m in messages if f"<@{my_id}>" in m.get("text", "")]
        high_reaction = []
        for m in messages:
            total_reactions = sum(r.get("count", 0) for r in m.get("reactions", []))
            if total_reactions > REACTION_THRESHOLD:
                high_reaction.append(m)

        # Track interactions
        for m in messages:
            uid = m.get("user")
            if not uid or uid == my_id:
                continue
            if uid not in interaction_map:
                interaction_map[uid] = {"sent": 0, "received": 0}
            interaction_map[uid]["received"] += 1
        if my_posts:
            other_users = {m.get("user") for m in messages if m.get("user") and m.get("user") != my_id}
            for uid in other_users:
                if uid not in interaction_map:
                    interaction_map[uid] = {"sent": 0, "received": 0}
                interaction_map[uid]["sent"] += len(my_posts)

        # Threads I participated in
        thread_roots = set()
        for m in messages:
            if m.get("user") == my_id and m.get("thread_ts") and m.get("thread_ts") != m.get("ts"):
                thread_roots.add(m["thread_ts"])
            if m.get("user") == my_id and m.get("reply_count", 0) > 0:
                thread_roots.add(m["ts"])

        threads = []
        for ts in thread_roots:
            try:
                replies_data = api("conversations.replies", channel=ch_id, ts=ts, limit=50)
                replies = replies_data.get("messages", [])
                if replies:
                    last_reply = replies[-1]
                    unanswered = last_reply.get("user") != my_id
                    threads.append({
                        "channel": ch_id,
                        "ts": ts,
                        "reply_count": len(replies) - 1,
                        "unanswered": unanswered,
                    })
            except RuntimeError:
                pass
            time.sleep(0.1)

        channel_stats.append({
            "channel_id": ch_id,
            "name": ch_name,
            "messages": len(messages),
            "my_posts": len(my_posts),
            "mentions": mentions,
            "threads": threads,
            "highlights": [
                {"ts": m["ts"], "text": m.get("text", "")[:200], "reactions": sum(r.get("count", 0) for r in m.get("reactions", []))}
                for m in high_reaction[:5]
            ],
        })

        time.sleep(0.1)

    # Sort by activity, cap at top 20
    channel_stats.sort(key=lambda c: c["messages"], reverse=True)
    total_active_channels = len(channel_stats)
    channel_stats = channel_stats[:MAX_CHANNELS]

    # DM metadata
    dm_data = api("conversations.list", types="im", limit=200)
    dm_channels = dm_data.get("channels", [])
    dm_active = 0
    for dm in dm_channels:
        try:
            dm_hist = api("conversations.history", channel=dm["id"], oldest=oldest, limit=1)
            if dm_hist.get("messages"):
                dm_active += 1
        except RuntimeError:
            pass
        time.sleep(0.1)

    # Resolve top interactions to display names
    top_interactions_raw = sorted(interaction_map.items(), key=lambda x: x[1]["sent"] + x[1]["received"], reverse=True)[:MAX_INTERACTIONS]
    top_interactions = []
    for uid, counts in top_interactions_raw:
        name = _resolve_user(api, uid, user_name_cache)
        top_interactions.append({
            "user_id": uid,
            "user_name": name,
            "sent": counts["sent"],
            "received": counts["received"],
        })

    # Aggregate stats
    all_threads = [t for c in channel_stats for t in c["threads"]]
    all_mentions = [{"channel": c["channel_id"], "ts": m["ts"], "text": m.get("text", "")[:200]} for c in channel_stats for m in c["mentions"]]

    snapshot = {
        "date": snapshot_date.isoformat(),
        "source": "slack",
        "user_id": my_id,
        "summary": {
            "my_threads": len(all_threads),
            "unanswered_threads": sum(1 for t in all_threads if t["unanswered"]),
            "mentions": len(all_mentions),
            "channels_active": total_active_channels,
            "dm_active": dm_active,
            "top_channels": [{"name": c["name"], "messages": c["messages"], "my_posts": c["my_posts"]} for c in channel_stats[:10]],
            "top_interactions": top_interactions,
        },
        "items": {
            "threads": all_threads,
            "mentions": all_mentions,
            "channel_digests": [
                {
                    "channel": c["channel_id"],
                    "name": c["name"],
                    "messages": c["messages"],
                    "my_posts": c["my_posts"],
                    "highlights": c["highlights"],
                }
                for c in channel_stats
            ],
        },
    }

    output_path.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSnapshot written to {output_path}")
    print(f"  {len(channel_stats)} active channels | {len(all_threads)} threads | {len(all_mentions)} mentions | {dm_active} active DMs")


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


if __name__ == "__main__":
    main()
