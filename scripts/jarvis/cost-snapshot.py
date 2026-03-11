#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Jarvis: Cost Daily Snapshot

Produces sensors/cost-{date}.json with Claude Code token cost summary.
Parses JSONL session files, computes cost by model/project/date.

Run: uv run ~/.claude/scripts/jarvis/cost-snapshot.py
"""

import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

_memory_dir = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
SENSORS_DIR = _memory_dir / "sensors"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
BASELINE_FILE = _memory_dir / "cost-baseline.json"

PRICING = {
    "claude-opus":   {"input": 15.0,  "output": 75.0,  "cache_write": 3.75,  "cache_read": 0.3},
    "claude-sonnet": {"input": 3.0,   "output": 15.0,  "cache_write": 0.375, "cache_read": 0.03},
    "claude-haiku":  {"input": 0.8,   "output": 4.0,   "cache_write": 0.10,  "cache_read": 0.008},
}
PRICING_DEFAULT = PRICING["claude-opus"]


def _resolve_pricing(model: str) -> dict:
    m = model.lower()
    for key in ("haiku", "sonnet", "opus"):
        if key in m:
            return PRICING[f"claude-{key}"]
    return PRICING_DEFAULT


def cost(tokens: dict, model: str = "") -> float:
    p = _resolve_pricing(model)
    return (
        tokens["input"] * p["input"]
        + tokens["output"] * p["output"]
        + tokens["cache_write"] * p["cache_write"]
        + tokens["cache_read"] * p["cache_read"]
    ) / 1_000_000


def parse_jsonl(path: Path) -> list[dict]:
    entries = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except (OSError, PermissionError):
        pass
    return entries


def extract_usage(entry: dict) -> dict | None:
    if entry.get("type") != "assistant":
        return None
    msg = entry.get("message", {})
    usage = msg.get("usage")
    if not usage:
        return None
    return {
        "timestamp": entry.get("timestamp", ""),
        "model": msg.get("model", "unknown"),
        "project": entry.get("cwd", "unknown"),
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "cache_write": usage.get("cache_creation_input_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
    }


def collect_period(start: datetime, end: datetime) -> list[dict]:
    records = []
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        jsonl_files = list(project_dir.glob("*.jsonl")) + list(project_dir.glob("*/subagents/*.jsonl"))
        for jsonl in jsonl_files:
            try:
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)
                if mtime < start - timedelta(days=1):
                    continue
            except OSError:
                continue
            for entry in parse_jsonl(jsonl):
                usage = extract_usage(entry)
                if not usage:
                    continue
                try:
                    ts = datetime.fromisoformat(usage["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
                except (ValueError, AttributeError):
                    continue
                if start <= ts < end:
                    records.append(usage)
    return records


def summarize(records: list[dict]) -> dict:
    totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    by_model = defaultdict(lambda: {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "calls": 0})
    by_date = defaultdict(lambda: {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "calls": 0})
    by_project = defaultdict(lambda: {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "calls": 0})

    for r in records:
        for k in ("input", "output", "cache_write", "cache_read"):
            totals[k] += r[k]
            by_model[r["model"]][k] += r[k]
            by_date[r["timestamp"][:10]][k] += r[k]
            by_project[r["project"]][k] += r[k]
        by_model[r["model"]]["calls"] += 1
        by_date[r["timestamp"][:10]]["calls"] += 1
        by_project[r["project"]]["calls"] += 1

    total_cost = cost(totals)
    cost_breakdown = {
        "input": round(totals["input"] * PRICING_DEFAULT["input"] / 1_000_000, 2),
        "output": round(totals["output"] * PRICING_DEFAULT["output"] / 1_000_000, 2),
        "cache_write": round(totals["cache_write"] * PRICING_DEFAULT["cache_write"] / 1_000_000, 2),
        "cache_read": round(totals["cache_read"] * PRICING_DEFAULT["cache_read"] / 1_000_000, 2),
    }

    model_summary = {}
    for m, v in sorted(by_model.items(), key=lambda x: cost(x[1], x[0]), reverse=True):
        model_summary[m] = {"calls": v["calls"], "cost_usd": round(cost(v, m), 2)}

    date_summary = {}
    for d in sorted(by_date):
        v = by_date[d]
        date_summary[d] = {"calls": v["calls"], "cost_usd": round(cost(v), 2)}

    project_summary = {}
    for p, v in sorted(by_project.items(), key=lambda x: cost(x[1]), reverse=True)[:10]:
        slug = p.replace(str(Path.home()), "~")
        project_summary[slug] = {"calls": v["calls"], "cost_usd": round(cost(v), 2)}

    active_days = len(date_summary)
    cost_per_day = round(total_cost / max(active_days, 1), 2)

    return {
        "api_calls": len(records),
        "total_cost_usd": round(total_cost, 2),
        "cost_per_active_day": cost_per_day,
        "active_days": active_days,
        "cost_breakdown_usd": cost_breakdown,
        "by_model": model_summary,
        "by_date": date_summary,
        "top_projects": project_summary,
    }


def load_baseline_avg() -> float | None:
    if not BASELINE_FILE.exists():
        return None
    try:
        data = json.loads(BASELINE_FILE.read_text())
        weeks = data.get("weeks", [])
        if not weeks:
            return None
        cpds = [w.get("cost_per_active_day", 0) for w in weeks if w.get("cost_per_active_day", 0) > 0]
        return round(sum(cpds) / len(cpds), 2) if cpds else None
    except Exception:
        return None


def main():
    print(f"Jarvis Cost Snapshot — {date.today().isoformat()}")

    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)

    if now < week_start + timedelta(days=1):
        week_start -= timedelta(days=7)
        week_end -= timedelta(days=7)

    records = collect_period(week_start, week_end)
    if not records:
        print("  No data found for current week.")
        return

    summary = summarize(records)
    baseline_avg = load_baseline_avg()

    target_per_day = round(300 / 7, 2)
    gap = round(summary["cost_per_active_day"] - target_per_day, 2)

    output = {
        "snapshot_date": date.today().isoformat(),
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": week_end.strftime("%Y-%m-%d"),
        "summary": {
            "total_cost_usd": summary["total_cost_usd"],
            "cost_per_active_day": summary["cost_per_active_day"],
            "active_days": summary["active_days"],
            "api_calls": summary["api_calls"],
            "target_per_day": target_per_day,
            "gap_per_day": gap,
            "on_target": gap <= 0,
            "baseline_avg_per_day": baseline_avg,
        },
        "cost_breakdown_usd": summary["cost_breakdown_usd"],
        "by_model": summary["by_model"],
        "by_date": summary["by_date"],
        "top_projects": summary["top_projects"],
    }

    if baseline_avg and baseline_avg > 0:
        delta_pct = round(((summary["cost_per_active_day"] - baseline_avg) / baseline_avg) * 100, 1)
        output["summary"]["vs_baseline_pct"] = delta_pct

    SENSORS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SENSORS_DIR / f"cost-{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(output, indent=2))

    print(f"  Week: {week_start.strftime('%m/%d')}–{(week_end - timedelta(days=1)).strftime('%m/%d')}")
    print(f"  Cost: ${summary['total_cost_usd']:.2f} ({summary['active_days']} days, ${summary['cost_per_active_day']:.2f}/day)")
    print(f"  Target: ${target_per_day:.2f}/day — {'ON TARGET' if gap <= 0 else f'${gap:.2f}/day over'}")
    if baseline_avg:
        print(f"  Baseline: ${baseline_avg:.2f}/day ({output['summary'].get('vs_baseline_pct', 0):+.1f}%)")
    print(f"  Written: {out_path}")


if __name__ == "__main__":
    main()
