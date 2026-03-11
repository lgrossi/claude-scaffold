#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Jarvis: Weekly Analyzer (file kept as daily-analyzer.py for systemd compat)

One Opus 1M call that reads all recent session compacts and produces:
1. Actionable insights → pending-insights.json
2. Effectiveness metrics → jarvis-metrics.jsonl
3. Behavioral patterns report → behavioral-patterns.md
4. Rule gaps report → jarvis-analysis/rule-gaps.md
5. Catastrophic lens report → jarvis-analysis/catastrophic-lens-report.md
   + active-strategies.json

Run: uv run daily-analyzer.py
Schedule: systemd timer (jarvis-daily-analyzer.timer), weekly (Sunday 00:15)
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

MEMORY_DIR = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
COMPACT_DIR = MEMORY_DIR / "session-compacts"
ANALYSIS_DIR = MEMORY_DIR / "jarvis-analysis"
INSIGHTS_FILE = MEMORY_DIR / "pending-insights.json"
ACTED_FILE = MEMORY_DIR / "acted-on-hints.json"
METRICS_FILE = MEMORY_DIR / "jarvis-metrics.jsonl"
STRATEGIES_FILE = MEMORY_DIR / "active-strategies.json"
SENSORS_DIR = MEMORY_DIR / "sensors"
LOOKBACK_DAYS = int(os.environ.get("JARVIS_LOOKBACK_DAYS", "7"))

REPORT_PATHS = {
    "behavioral_patterns": MEMORY_DIR / "behavioral-patterns.md",
    "rule_gaps": ANALYSIS_DIR / "rule-gaps.md",
    "catastrophic_lens": ANALYSIS_DIR / "catastrophic-lens-report.md",
    "work_diary": ANALYSIS_DIR / "work-diary.md",
    "calibration": Path(Path.home() / ".claude" / "rules" / "jarvis" / "calibration.md"),
}


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")


def load_recent_compacts() -> list[dict]:
    if not COMPACT_DIR.exists():
        return []
    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    compacts = []
    for path in sorted(COMPACT_DIR.glob("*.json")):
        try:
            c = json.loads(path.read_text())
            if c.get("date", "") < cutoff:
                continue
            if c.get("stats", {}).get("user_messages", 0) < 2:
                continue
            compacts.append(c)
        except Exception:
            continue
    return compacts


def load_acted_hints() -> list[dict]:
    if ACTED_FILE.exists():
        try:
            return json.loads(ACTED_FILE.read_text())
        except Exception:
            return []
    return []


def load_existing_insights() -> list[dict]:
    if INSIGHTS_FILE.exists():
        try:
            return json.loads(INSIGHTS_FILE.read_text())
        except Exception:
            return []
    return []


def load_recent_metrics(n: int = 4) -> list[dict]:
    if not METRICS_FILE.exists():
        return []
    try:
        lines = METRICS_FILE.read_text().strip().splitlines()
        return [json.loads(l) for l in lines[-n:]]
    except Exception:
        return []


def load_sensor(name: str) -> dict | None:
    for offset in [0, 1]:
        d = (date.today() - timedelta(days=offset)).isoformat()
        path = SENSORS_DIR / f"{name}-{d}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                continue
    return None


def load_file_if_exists(path: Path) -> str:
    if path.exists():
        return path.read_text()
    return ""


def build_session_key_lines(compacts: list[dict]) -> str:
    parts = []
    substantial = [c for c in compacts
                   if c.get("stats", {}).get("user_messages", 0) >= 3
                   and c.get("stats", {}).get("tool_calls", 0) >= 3]
    substantial_ids = {id(c) for c in substantial}
    trivial = [c for c in compacts if id(c) not in substantial_ids]

    parts.append(f"Sessions: {len(compacts)} ({len(substantial)} substantial, {len(trivial)} trivial)")

    if trivial:
        trivial_cwds: dict[str, int] = {}
        for c in trivial:
            cwd = str(c.get("cwd", "?")).replace(str(Path.home()), "~")
            trivial_cwds[cwd] = trivial_cwds.get(cwd, 0) + 1
        parts.append(f"\nTrivial sessions ({len(trivial)}): single-message or quick lookups")
        parts.append(f"  Projects: {', '.join(f'{k}({v})' for k, v in sorted(trivial_cwds.items(), key=lambda x: -x[1])[:10])}")

    for c in substantial:
        stats = c.get("stats", {})
        parts.append(f"\n--- {c.get('session_id', '?')} ({c.get('date', '?')}) ---")
        parts.append(f"Dir: {c.get('cwd', '?')}")
        parts.append(f"Stats: {stats.get('user_messages', 0)} msgs, {stats.get('tool_calls', 0)} tools, "
                     f"{stats.get('tool_errors', 0)} errors, {stats.get('interrupts', 0)} interrupts")
        parts.append(f"Tools: {', '.join(f'{k}({v})' for k, v in c.get('tool_usage', {}).items())}")

        conv = c.get("conversation", "")
        parts.append("\n".join(l for l in conv.split("\n")
                     if l.startswith(("[USER]", "[CLAUDE]", "[INTERRUPTED]", "[RESULT] ERROR"))))

    return "\n".join(parts)


def build_prompt(compacts: list[dict], acted: list[dict], metrics: list[dict], **sensors) -> str:
    parts = []
    parts.append("""You are Jarvis. Your task is to analyze session data and produce output in a STRICT format.

YOU MUST output 6 sections using EXACT markers. Do NOT summarize. Do NOT describe what you would write.
Write the ACTUAL content for each section. This is a data pipeline — your raw text output is parsed programmatically.
The exact format for each section is specified in the OUTPUT INSTRUCTIONS at the end.

Now here is the data to analyze:
""")
    parts.append(f"Today: {date.today().isoformat()}")
    parts.append(f"Sessions in last {LOOKBACK_DAYS} days: {len(compacts)}")
    parts.append("")

    if acted:
        parts.append(f"Previously acted-on hints ({len(acted)} total, last 5):")
        for a in acted[-5:]:
            parts.append(f"  - [{a.get('acted_at', '?')[:10]}] {a.get('hint', '')[:100]}")
        parts.append("")

    calendar = sensors.get("calendar")
    if calendar:
        analysis = calendar.get("analysis", {})
        parts.append(f"Calendar: {analysis.get('total_events', 0)} events next 14 days, "
                     f"avg {analysis.get('avg_daily_meeting_minutes', 0)} min/day meetings")
        deep_work = analysis.get("deep_work_days", [])
        if deep_work:
            parts.append(f"  Deep work days (<1h meetings): {', '.join(sorted(deep_work))}")
        parts.append("")

    slack = sensors.get("slack")
    if slack:
        s = slack.get("summary", {})
        parts.append(f"Slack (yesterday): {s.get('mentions', 0)} mentions, "
                     f"{s.get('my_threads', 0)} threads started, "
                     f"{s.get('unanswered_threads', 0)} unanswered threads")
        top_ch = s.get("top_channels", [])[:3]
        if top_ch:
            parts.append("  Top channels: " + ", ".join(c["name"] + f"({c['messages']} msgs)" for c in top_ch))
        top_ix = s.get("top_interactions", [])[:5]
        if top_ix:
            parts.append("  Top interactions: " + ", ".join(i["user_name"] + f"(sent {i['sent']}, rcvd {i['received']})" for i in top_ix))
        parts.append("")

    gitlab = sensors.get("gitlab")
    if gitlab:
        g = gitlab.get("summary", {})
        parts.append(f"GitLab (yesterday): {g.get('open_mrs', 0)} open MRs, "
                     f"{g.get('stale_mrs', 0)} stale, "
                     f"{g.get('review_requested', 0)} pending reviews, "
                     f"{g.get('recently_merged', 0)} merged this week")
        open_mrs = gitlab.get("items", {}).get("open_mrs", [])
        drafts = sum(1 for mr in open_mrs if mr.get("draft"))
        with_threads = [mr for mr in open_mrs if mr.get("unresolved_threads", 0) > 0]
        if drafts:
            parts.append(f"  Drafts: {drafts}")
        if with_threads:
            parts.append("  Unresolved threads: " + ", ".join(
                f"!{mr['id']}({mr['unresolved_threads']})" for mr in with_threads[:5]
            ))
        parts.append("")

    gdocs = sensors.get("gdocs")
    if gdocs:
        s = gdocs.get("summary", {})
        parts.append(f"Google Docs (last {gdocs.get('lookback_hours', 24)}h): "
                     f"{s.get('total_files', 0)} modified files, "
                     f"{s.get('total_unresolved_comments', 0)} unresolved comments")
        by_type = s.get("by_type", {})
        if by_type:
            parts.append("  By type: " + ", ".join(f"{t}({n})" for t, n in sorted(by_type.items())))
        cal_matched = s.get("presentations_matched_to_calendar", 0)
        if cal_matched:
            parts.append(f"  Presentations matched to calendar events: {cal_matched}")
        parts.append("")

    jira = sensors.get("jira")
    if jira:
        s = jira.get("summary", {})
        parts.append(f"Jira: {s.get('open_issues', 0)} open issues, "
                     f"{s.get('stale_issues', 0)} stale")
        sprint_name = s.get("sprint_name")
        if sprint_name:
            parts.append(f"  Sprint: {sprint_name} | "
                         f"{s.get('sprint_days_remaining', '?')}d remaining | "
                         f"{s.get('sprint_completion_pct', '?')}% done")
        parts.append("")

    confluence = sensors.get("confluence")
    if confluence:
        s = confluence.get("summary", {})
        parts.append(f"Confluence: {s.get('my_pages', 0)} owned pages, "
                     f"{s.get('watched_pages', 0)} watched, "
                     f"{s.get('unresolved_comments', 0)} unresolved comments")
        parts.append("")

    cost_data = sensors.get("cost")
    if cost_data:
        s = cost_data.get("summary", {})
        parts.append(f"Claude Code Cost (week {cost_data.get('week_start', '?')} to {cost_data.get('week_end', '?')}): "
                     f"${s.get('total_cost_usd', 0):.2f} total, "
                     f"${s.get('cost_per_active_day', 0):.2f}/day, "
                     f"{s.get('api_calls', 0)} API calls, "
                     f"{s.get('active_days', 0)} active days")
        if s.get("vs_baseline_pct") is not None:
            parts.append(f"  vs baseline: {s['vs_baseline_pct']:+.1f}% (baseline ${s.get('baseline_avg_per_day', 0):.2f}/day)")
        target = s.get("target_per_day", 42.86)
        if s.get("on_target"):
            parts.append(f"  Status: ON TARGET (target ${target:.0f}/day)")
        else:
            parts.append(f"  Status: ${s.get('gap_per_day', 0):.0f}/day OVER target (target ${target:.0f}/day)")
        breakdown = cost_data.get("cost_breakdown_usd", {})
        if breakdown:
            total = s.get("total_cost_usd", 1) or 1
            parts.append("  Breakdown: " + ", ".join(
                f"{k} ${v:.2f} ({v/total*100:.0f}%)" for k, v in breakdown.items()
            ))
        by_model = cost_data.get("by_model", {})
        if by_model:
            parts.append("  By model: " + ", ".join(
                f"{m} {v['calls']} calls ${v['cost_usd']:.2f}" for m, v in by_model.items()
            ))
        top = cost_data.get("top_projects", {})
        if top:
            parts.append("  Top projects: " + ", ".join(
                f"{p} ${v['cost_usd']:.2f}" for p, v in list(top.items())[:5]
            ))
        parts.append("")

    if metrics:
        parts.append("Recent metrics trend:")
        for m in metrics[-3:]:
            parts.append(f"  [{m.get('date', '?')}] recurrence={m.get('struggle_recurrence_rate', '?')} "
                         f"conversion={m.get('hint_conversion_rate', '?')} "
                         f"protect/dash={m.get('protect_dash_ratio', '?')}")
        parts.append("")

    key_lines = build_session_key_lines(compacts)
    parts.append(key_lines)

    # Context files for reports
    parts.append("\n=== CONTEXT ===")

    profile = load_file_if_exists(MEMORY_DIR / "profile.md")
    if profile:
        parts.append(f"\n--- profile.md ---\n{profile}")

    portfolio = load_file_if_exists(MEMORY_DIR / "portfolio.md")
    if portfolio:
        parts.append(f"\n--- portfolio.md ---\n{portfolio}")


    parts.append("\n=== OUTPUT INSTRUCTIONS ===")
    parts.append("""
Output using these EXACT section markers. Write each report as raw markdown (not inside JSON).
Write reports FIRST, then insights LAST.

<<<BEHAVIORAL_PATTERNS>>>
Write the full updated behavioral patterns report in markdown.
For each existing pattern: confirm with new evidence, add nuance, or remove if unverified.
Add NEW patterns only when supported by 2+ sessions. Cite session IDs.
This calibrates coaching.md.
<<<END_BEHAVIORAL_PATTERNS>>>

<<<RULE_GAPS>>>
Write the full updated rule gaps report in markdown.
Categorize gaps as: missing mental model, tool/workflow gap, unclear existing rule, or model limitation.
If 5 gaps share a root cause, that's 1 gap. End with a "## Top Actions" section.
<<<END_RULE_GAPS>>>

<<<CATASTROPHIC_LENS>>>
Write the full updated catastrophic lens report in markdown.
Classify sessions as Protect / Dash / Evolving. Compare ratios to previous report.
Update stops/starts. Flag calendar opportunities. End with "## Strategic Signals" section.
<<<END_CATASTROPHIC_LENS>>>

<<<STRATEGIES>>>
```json
[{"title": "...", "body": "...", "updated": "YYYY-MM-DD"}]
```
1-3 long-term strategic directions — NOT tasks or deadlines.
Strategies are persistent visions to pursue over weeks/months, not items to check off.
Bad: "Ship MR !3 before Friday" — that's a task.
Good: "Shift from building AI tools to demonstrating organizational impact" — that's a direction.
Evaluate previous strategies — keep if still relevant, replace if trajectory shifted.
<<<END_STRATEGIES>>>

<<<WORK_DIARY>>>
Write a concise work diary entry in markdown for today. Synthesize from ALL sensor data above.
Sections:
## Shipped
MRs merged, Jira tickets closed/resolved this period.
## In Progress
Active MRs (with status: draft/review/pipeline), active Jira tickets.
## Communications
Slack threads participated in, review comments given/received, Confluence activity.
## Blocked/Stale
Stale MRs, stale Jira tickets, unanswered threads, unresolved comments.

If a section has no data, write "None." — do not omit the heading.
<<<END_WORK_DIARY>>>

<<<METRICS>>>
```json
{"struggle_recurrence_rate": 0.0, "hint_conversion_rate": 0.0, "protect_dash_ratio": [0, 0], "novel_vs_repeated": [0, 0]}
```
<<<END_METRICS>>>

<<<CALIBRATION>>>
Synthesize the behavioral patterns above into <=20 imperative one-line directives for Claude.
Format: each line starts with a verb, is a direct instruction. Present tense.
Skip patterns already fully covered by existing CLAUDE.md rules or other rules files (e.g., "questions are reflections" is already CLAUDE.md rule 2).
Skip patterns with evidence from only 1 session.
Example: "When proposing a plan, present the minimal version first — expect scope narrowing within 1-2 turns."
Example: "Ask for a concrete example when the user uses speculative language ('probably', 'I think')."
Output raw text lines (no markdown headings, no JSON, no fences).
<<<END_CALIBRATION>>>

<<<INSIGHTS>>>
```json
[
  {"urgency": "red|orange|green", "title": "...", "body": "...", "action": "auto-fix: ...|needs-user: ...", "action_payload": {"file": "/absolute/path", "op": "append|prepend|replace_section", "section": "optional heading for replace_section", "content": "the text to write"}}
]
```
For auto-fix insights, include action_payload with structured file edit data when the fix targets a specific file.
The field is optional — omit it for needs-user insights or when the fix is too complex for a single file edit.

IMPORTANT: This is the PRIMARY output. Derive insights ONLY from session data above — not from
the current reports. The reports are context for updating reports, not a source of insights.
If a pattern appears in sessions, report it. If it only appears in a previous report but not
in the session data, do NOT re-surface it as an insight.

- Be thorough — surface EVERY cross-session pattern worth acting on.
- Each insight must answer: "What should the user do differently because of this?"
- No artificial cap. Could be 3, could be 15, could be 25 — inspect the data and report everything that meets the bar.
- Group recurring patterns — 5 sessions with the same issue = 1 insight not 5.
- Agreeableness detection: scan [USER]/[CLAUDE] turn pairs for: (a) Claude proposes X → user questions X → Claude reverses to user's position with no counter-argument or new evidence cited; (b) Claude validates speculative user input ("probably", "I think") as fact without surfacing it as a hypothesis; (c) agreement language ("you're right", "great point", "that makes sense") followed by position change without new evidence. When found across 2+ sessions, surface as orange insight with format: "Claude accepted '[exact claim]' without evidence in session <id>. Should have asked: '[specific question]'."
- Cross-reference acted-on hints — don't re-surface fixed issues.
- action prefix rules — default is auto-fix:
  - auto-fix: Claude can execute without asking. Editing a file, adding a rule, creating a skill, writing documentation, fixing a pattern, adding a hook — all auto-fix.
  - needs-user: ONLY when the action requires something Claude cannot provide: a policy call with real tradeoffs, a priority/cost decision, external approval, or information only the user has. "Should we build X?" is needs-user. "Add rule X to file Y" is auto-fix. If in doubt, use auto-fix — the user can always say "don't do that."
- red: system health, 3+ week recurrence, strategic. orange: actionable recurring. green: trend with recommendation.
<<<END_INSIGHTS>>>
""")

    return "\n".join(parts)


def call_llm(prompt: str) -> str | None:
    """One LLM call via claude --print. Returns raw text."""
    try:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            ["claude", "--print", "--model", "claude-opus-4-6[1m]"],
            input=prompt,
            capture_output=True, text=True, timeout=1800,
            env=env,
        )
        if result.returncode != 0:
            print(f"  claude error: {result.stderr[:200]}", file=sys.stderr)
            return None
        return result.stdout.strip() if result.stdout.strip() else None
    except Exception as e:
        print(f"  LLM error: {e}", file=sys.stderr)
        return None


def extract_section(text: str, marker: str) -> str:
    """Extract content between <<<MARKER>>> and <<<END_MARKER>>>."""
    start = f"<<<{marker}>>>"
    end = f"<<<END_{marker}>>>"
    if start not in text or end not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def extract_json_from_section(section: str) -> object:
    """Extract JSON from a section that may contain ```json fences."""
    if "```json" in section:
        section = section.split("```json")[1].split("```")[0].strip()
    elif "```" in section:
        section = section.split("```")[1].split("```")[0].strip()
    return json.loads(section)


def backup_reports() -> None:
    backup_dir = ANALYSIS_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in REPORT_PATHS.values():
        if path.exists() and path.stat().st_size > 0:
            # Timestamped reports already have their ts in the name — just move them
            for ts_file in path.parent.glob(f"{path.stem}.*.md"):
                shutil.move(str(ts_file), str(backup_dir / ts_file.name))
                print(f"    {ts_file.name} → backups/")
            # Remove the fixed-path copy (will be recreated from new ts file)
            if path.exists():
                path.unlink()
                print(f"    {path.name} removed")


def write_insights(new_insights: list[dict]) -> None:
    existing = load_existing_insights()
    existing = [i for i in existing if i.get("source") != "daily-analyzer"]

    now = datetime.now(timezone.utc).isoformat()
    for insight in new_insights:
        entry = {
            "id": f"daily-{date.today().isoformat()}-{len(existing)}",
            "created_at": now,
            "surfaced_at": None,
            "urgency": insight.get("urgency", "green"),
            "source": "daily-analyzer",
            "title": insight.get("title", ""),
            "body": insight.get("body", ""),
            "action": insight.get("action", ""),
        }
        if insight.get("action_payload"):
            entry["action_payload"] = insight["action_payload"]
        existing.append(entry)

    tmp = INSIGHTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    tmp.replace(INSIGHTS_FILE)


def write_metrics(metrics_data: dict) -> None:
    entry = {"date": date.today().isoformat(), **metrics_data}
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with METRICS_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def main() -> None:
    print(f"Jarvis Daily Analyzer — {date.today().isoformat()}")

    compacts = load_recent_compacts()
    if not compacts:
        print("No recent session compacts found. Nothing to analyze.")
        return

    acted = load_acted_hints()
    metrics = load_recent_metrics()
    sensor_names = ["calendar", "slack", "gitlab", "jira", "confluence", "gdocs", "cost"]
    sensor_data = {name: load_sensor(name) for name in sensor_names}

    print(f"  Sessions: {len(compacts)} (last {LOOKBACK_DAYS} days)")
    print(f"  Acted hints: {len(acted)}")
    for name in sensor_names:
        label = {"gdocs": "Google Docs"}.get(name, name.title())
        print(f"  {label}: {'loaded' if sensor_data[name] else 'none'}")
    print(f"  Prior metrics: {len(metrics)} entries")

    prompt = build_prompt(compacts, acted, metrics, **{k: v for k, v in sensor_data.items() if v is not None})
    tokens = len(prompt) // 4
    print(f"  Prompt size: ~{tokens:,} tokens")

    print("  Calling LLM...", flush=True)
    raw = call_llm(prompt)
    if not raw:
        print("  Analysis failed. Will retry next run.")
        return

    # Verify all sections present before touching any files
    required = ["BEHAVIORAL_PATTERNS", "RULE_GAPS", "CATASTROPHIC_LENS", "INSIGHTS"]
    missing = [s for s in required if not extract_section(raw, s)]
    if missing:
        print(f"  Missing sections: {', '.join(missing)}. Aborting — no files modified.", file=sys.stderr)
        debug_path = MEMORY_DIR / "daily-analyzer-debug.txt"
        debug_path.write_text(raw)
        print(f"  Raw output saved to {debug_path}")
        return

    print("  Backing up reports...")
    backup_reports()

    # Insights
    insights_section = extract_section(raw, "INSIGHTS")
    insights: list[dict] = []
    if insights_section:
        try:
            parsed = extract_json_from_section(insights_section)
            if isinstance(parsed, list):
                insights = parsed
        except Exception as e:
            print(f"  Failed to parse insights: {e}", file=sys.stderr)

    print(f"  Insights: {len(insights)}")
    for i in insights:
        icon = {"red": "🎯", "orange": "💡", "green": "📋"}.get(str(i.get("urgency", "")), "?")
        action_type = "auto-fix" if i.get("action", "").startswith("auto-fix") else "needs-user"
        print(f"    {icon} [{action_type}] {i.get('title', '')[:80]}")
    if insights:
        write_insights(insights)

    # Metrics
    metrics_section = extract_section(raw, "METRICS")
    if metrics_section:
        try:
            metrics_data = extract_json_from_section(metrics_section)
            if isinstance(metrics_data, dict):
                write_metrics(metrics_data)
                print(f"  Metrics appended")
        except Exception as e:
            print(f"  Failed to parse metrics: {e}", file=sys.stderr)

    # Reports — write with timestamp, copy to fixed path for consumers
    ts = timestamp()
    print("  Writing reports...")
    section_map = {
        "behavioral_patterns": "BEHAVIORAL_PATTERNS",
        "rule_gaps": "RULE_GAPS",
        "catastrophic_lens": "CATASTROPHIC_LENS",
        "work_diary": "WORK_DIARY",
        "calibration": "CALIBRATION",
    }
    for report_key, marker in section_map.items():
        content = extract_section(raw, marker)
        if content:
            path = REPORT_PATHS[report_key]
            path.parent.mkdir(parents=True, exist_ok=True)
            # Timestamped backup — always in backups dir to avoid polluting rules/
            backup_dir = ANALYSIS_DIR / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts_path = backup_dir / f"{path.stem}.{ts}.md"
            ts_path.write_text(content)
            # Fixed path for consumers (statusline, /brief, coaching.md)
            shutil.copy2(str(ts_path), str(path))
            print(f"    {ts_path.name} ({len(content)} chars)")

    # Strategies
    strategies_section = extract_section(raw, "STRATEGIES")
    if strategies_section:
        try:
            strategies = extract_json_from_section(strategies_section)
            if isinstance(strategies, list):
                STRATEGIES_FILE.write_text(json.dumps(strategies, indent=2))
                print(f"    active-strategies.json ({len(strategies)} strategies)")
        except Exception as e:
            print(f"  Failed to parse strategies: {e}", file=sys.stderr)

    print("Done.")


if __name__ == "__main__":
    main()
