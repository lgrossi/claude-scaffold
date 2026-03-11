#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Weekly Claude Code cost report. Compares current week against baseline."""

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
BASELINE_FILE = Path.home() / ".claude" / "memory" / "jarvis" / "cost-baseline.json"
REPORT_DIR = Path.home() / ".claude" / "memory"

PRICING = {
    "input": 15.0,
    "output": 75.0,
    "cache_write": 3.75,
    "cache_read": 0.3,
}


def cost(tokens: dict) -> float:
    return (
        tokens["input"] * PRICING["input"]
        + tokens["output"] * PRICING["output"]
        + tokens["cache_write"] * PRICING["cache_write"]
        + tokens["cache_read"] * PRICING["cache_read"]
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
    ts = entry.get("timestamp", "")
    model = msg.get("model", "unknown")
    project = entry.get("cwd", "unknown")
    return {
        "timestamp": ts,
        "model": model,
        "project": project,
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "cache_write": usage.get("cache_creation_input_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
    }


def collect_week(start: datetime, end: datetime) -> list[dict]:
    records = []
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl in project_dir.glob("*.jsonl"):
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
        subagents_dir = project_dir / "subagents"
        if subagents_dir.is_dir():
            for jsonl in subagents_dir.glob("*.jsonl"):
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
        "input": totals["input"] * PRICING["input"] / 1_000_000,
        "output": totals["output"] * PRICING["output"] / 1_000_000,
        "cache_write": totals["cache_write"] * PRICING["cache_write"] / 1_000_000,
        "cache_read": totals["cache_read"] * PRICING["cache_read"] / 1_000_000,
    }

    model_summary = {}
    for m, v in sorted(by_model.items(), key=lambda x: cost(x[1]), reverse=True):
        model_summary[m] = {"calls": v["calls"], "cost_usd": round(cost(v), 2)}

    date_summary = {}
    for d in sorted(by_date):
        v = by_date[d]
        date_summary[d] = {"calls": v["calls"], "cost_usd": round(cost(v), 2)}

    project_summary = {}
    for p, v in sorted(by_project.items(), key=lambda x: cost(x[1]), reverse=True)[:10]:
        slug = p.replace(str(Path.home()), "~")
        project_summary[slug] = {"calls": v["calls"], "cost_usd": round(cost(v), 2)}

    return {
        "api_calls": len(records),
        "total_cost_usd": round(total_cost, 2),
        "cost_breakdown_usd": {k: round(v, 2) for k, v in cost_breakdown.items()},
        "by_model": model_summary,
        "by_date": date_summary,
        "top_projects": project_summary,
    }


def load_baseline() -> list[dict] | None:
    if not BASELINE_FILE.exists():
        return None
    with open(BASELINE_FILE) as f:
        data = json.load(f)
    return data.get("weeks", [])


def print_report(week_start: datetime, week_end: datetime, summary: dict, baseline_weeks: list[dict] | None):
    label = f"{week_start.strftime('%m/%d')}–{(week_end - timedelta(days=1)).strftime('%m/%d')}"
    print(f"\n{'='*60}")
    print(f"  Claude Code Cost Report — Week of {label}")
    print(f"{'='*60}\n")

    print(f"  Total Cost:  ${summary['total_cost_usd']:,.2f}")
    print(f"  API Calls:   {summary['api_calls']:,}\n")

    cb = summary["cost_breakdown_usd"]
    total = summary["total_cost_usd"] or 1
    print("  Cost Breakdown:")
    for k in ("cache_write", "cache_read", "output", "input"):
        pct = cb[k] / total * 100
        print(f"    {k:15s}  ${cb[k]:>8.2f}  ({pct:4.1f}%)")

    print("\n  By Model:")
    for model, v in summary["by_model"].items():
        print(f"    {model:30s}  {v['calls']:>5,} calls  ${v['cost_usd']:>8.2f}")

    print("\n  By Date:")
    for date, v in summary["by_date"].items():
        print(f"    {date}  {v['calls']:>5,} calls  ${v['cost_usd']:>8.2f}")

    if summary["top_projects"]:
        print("\n  Top Projects:")
        for proj, v in summary["top_projects"].items():
            print(f"    {proj:50s}  {v['calls']:>5,} calls  ${v['cost_usd']:>8.2f}")

    if baseline_weeks:
        print("\n  Weekly Trend (baseline + current):")
        print(f"    {'Week':15s}  {'Calls':>7s}  {'Cost':>10s}  {'$/day':>8s}")
        print(f"    {'-'*15}  {'-'*7}  {'-'*10}  {'-'*8}")
        for w in baseline_weeks:
            cpd = w.get("cost_per_active_day", 0)
            print(f"    {w['label']:15s}  {w['api_calls']:>7,}  ${w['estimated_cost_usd']:>9.2f}  ${cpd:>7.2f}")

        active_days = len(summary["by_date"])
        cpd_current = summary["total_cost_usd"] / max(active_days, 1)
        print(f"    {label:15s}  {summary['api_calls']:>7,}  ${summary['total_cost_usd']:>9.2f}  ${cpd_current:>7.2f}  ← current")

        last_baseline = baseline_weeks[-1] if baseline_weeks else None
        if last_baseline and last_baseline["cost_per_active_day"] > 0:
            delta = ((cpd_current - last_baseline["cost_per_active_day"]) / last_baseline["cost_per_active_day"]) * 100
            direction = "up" if delta > 0 else "down"
            print(f"\n  $/day change vs last baseline: {delta:+.1f}% ({direction})")

    target = 300 / 7
    current_cpd = summary["total_cost_usd"] / max(len(summary["by_date"]), 1)
    gap = current_cpd - target
    if gap > 0:
        print(f"\n  Target: $300/week (${target:.0f}/day) — ${gap:.0f}/day over target")
    else:
        print(f"\n  Target: $300/week (${target:.0f}/day) — ON TARGET")

    print()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--save":
        save = True
    else:
        save = False

    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)

    if now < week_start + timedelta(days=1):
        week_start -= timedelta(days=7)
        week_end -= timedelta(days=7)

    records = collect_week(week_start, week_end)
    if not records:
        print("No data found for the current week.")
        return

    summary = summarize(records)
    baseline_weeks = load_baseline()
    print_report(week_start, week_end, summary, baseline_weeks)

    if save:
        report = {
            "generated_at": now.isoformat(),
            "week_start": week_start.strftime("%Y-%m-%d"),
            "week_end": week_end.strftime("%Y-%m-%d"),
            **summary,
        }
        out = REPORT_DIR / f"cost-report-{week_start.strftime('%Y-%m-%d')}.json"
        with open(out, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  Saved: {out}\n")


if __name__ == "__main__":
    main()
