#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Jarvis Validator

Tests every component and reports pass/fail.
Run: uv run ~/.claude/scripts/jarvis/validate.py

Exit code 0 = all critical checks pass.
Exit code 1 = one or more critical failures.
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

MEMORY = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
SCRIPTS = Path.home() / ".claude" / "scripts" / "jarvis"
ANALYSIS = MEMORY / "jarvis-analysis"

GREEN  = "\033[38;5;114m"
ORANGE = "\033[38;5;215m"
RED    = "\033[38;5;203m"
DIM    = "\033[38;5;242m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

results: list[tuple[str, str, str, str]] = []


def check(component: str, name: str, ok: bool, note: str = "", critical: bool = True) -> bool:
    icon = f"{GREEN}✓{RESET}" if ok else (f"{RED}✗{RESET}" if critical else f"{ORANGE}~{RESET}")
    results.append((component, name, "ok" if ok else ("fail" if critical else "warn"), note))
    status = "ok" if ok else ("FAIL" if critical else "WARN")
    col = GREEN if ok else (RED if critical else ORANGE)
    print(f"  {icon} {name:<45} {col}{status}{RESET}" + (f"  {DIM}{note}{RESET}" if note else ""))
    return ok


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


def main() -> int:
    print(f"\n{BOLD}Jarvis Validation{RESET}")
    print(f"{DIM}{'─' * 60}{RESET}")

    # ── 1. Directory structure ────────────────────────────────────
    section("1. Memory Structure")
    for f in ["profile.md", "portfolio.md"]:
        check("structure", f, (MEMORY / f).exists())
    for d in ["jarvis-analysis", "sensors", "session-compacts"]:
        check("structure", f"directory: {d}/", (MEMORY / d).is_dir())
    check("structure", "backups directory", (ANALYSIS / "backups").is_dir(), critical=False)

    # ── 2. Scripts ────────────────────────────────────────────────
    section("2. Scripts")
    for script in ["session-processor.py", "daily-analyzer.py",
                    "calendar-snapshot.py", "slack-snapshot.py",
                    "slack_tokens.py", "gitlab-snapshot.py", "gdocs-snapshot.py",
                    "jira-snapshot.py", "confluence-snapshot.py"]:
        path = SCRIPTS / script
        check("scripts", script, path.exists() and os.access(path, os.R_OK))

    # ── 3. Session compacts ───────────────────────────────────────
    section("3. Session Compacts")
    compacts_dir = MEMORY / "session-compacts"
    state_file = MEMORY / "session-processor-state.json"
    check("compacts", "state file exists", state_file.exists(), critical=False)
    if compacts_dir.exists():
        compact_count = len(list(compacts_dir.glob("*.json")))
        check("compacts", f"compact files ({compact_count})", compact_count > 0)
        # Verify a compact has expected schema
        if compact_count > 0:
            sample = next(compacts_dir.glob("*.json"))
            try:
                c = json.loads(sample.read_text())
                has_fields = all(k in c for k in ["session_id", "date", "stats", "conversation"])
                check("compacts", "compact schema valid", has_fields,
                      f"sample: {sample.name}")
            except Exception as e:
                check("compacts", "compact schema valid", False, str(e))

    # ── 4. Reports ────────────────────────────────────────────────
    section("4. Reports")
    report_files = {
        "behavioral-patterns.md": MEMORY / "behavioral-patterns.md",
        "rule-gaps.md": ANALYSIS / "rule-gaps.md",
        "catastrophic-lens-report.md": ANALYSIS / "catastrophic-lens-report.md",
    }
    for name, path in report_files.items():
        ts_files = sorted(path.parent.glob(f"{path.stem}.*.md"))
        bare_exists = path.exists() and path.stat().st_size > 0
        latest = ts_files[-1] if ts_files else None
        has_any = bare_exists or latest is not None
        if bare_exists:
            note = f"{path.stat().st_size // 1024}KB"
        elif latest:
            note = f"{latest.name} ({latest.stat().st_size // 1024}KB)"
        else:
            note = "missing/empty"
        check("reports", name, has_any, note)

    check("reports", "active-strategies.json",
          (MEMORY / "active-strategies.json").exists())
    if (MEMORY / "active-strategies.json").exists():
        try:
            strategies = json.loads((MEMORY / "active-strategies.json").read_text())
            check("reports", "strategies are list",
                  isinstance(strategies, list) and len(strategies) > 0,
                  f"{len(strategies)} strategies")
        except Exception as e:
            check("reports", "strategies parseable", False, str(e))

    # ── 5. Insights pipeline ──────────────────────────────────────
    section("5. Insights Pipeline")
    pending_file = MEMORY / "pending-insights.json"
    check("insights", "pending-insights.json exists", pending_file.exists())
    if pending_file.exists():
        try:
            insights = json.loads(pending_file.read_text())
            check("insights", f"parseable ({len(insights)} items)",
                  isinstance(insights, list))
        except Exception as e:
            check("insights", "parseable", False, str(e))

    # Smoke test: write and read a synthetic insight
    if pending_file.exists():
        existing = json.loads(pending_file.read_text())
        existing = [i for i in existing if i.get("source") != "validate-test"]
        test_id = str(uuid.uuid4())
        existing.append({
            "id": test_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "surfaced_at": None,
            "urgency": "green",
            "source": "validate-test",
            "title": "VALIDATE TEST — clear with /brief",
            "body": "Synthetic test insight from validate.py",
            "action": "Run /brief to clear",
        })
        tmp = pending_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        tmp.replace(pending_file)
        check("insights", "write/read roundtrip",
              test_id in pending_file.read_text())

    # ── 6. Sensors ────────────────────────────────────────────────
    section("6. Sensors")

    # Calendar
    env_file = Path.home() / ".config" / "jarvis" / "env"
    check("sensors", "jarvis env file", env_file.exists(),
          "~/.config/jarvis/env (for systemd)" if not env_file.exists() else "")
    adc_file = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    check("sensors", "Google Calendar ADC", adc_file.exists(), critical=False)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    check("sensors", "today's calendar snapshot",
          (MEMORY / "sensors" / f"calendar-{today}.json").exists(), critical=False)

    # GitLab token
    gitlab_token = os.environ.get("GITLAB_TOKEN")
    check("sensors", "GITLAB_TOKEN set", bool(gitlab_token), critical=False)
    check("sensors", "today's gitlab snapshot",
          (MEMORY / "sensors" / f"gitlab-{today}.json").exists(), critical=False)

    # Atlassian (Jira + Confluence) token
    jira_url = os.environ.get("JIRA_URL", "")
    jira_user = os.environ.get("JIRA_USERNAME", "")
    jira_token = os.environ.get("JIRA_API_TOKEN", "")
    check("sensors", "JIRA_URL set", bool(jira_url), critical=False)
    check("sensors", "JIRA_API_TOKEN set", bool(jira_token), critical=False)
    if jira_url and jira_user and jira_token:
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{jira_url}/rest/api/2/myself",
                headers={"Authorization": "Basic " + __import__("base64").b64encode(f"{jira_user}:{jira_token}".encode()).decode()},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                check("sensors", "Atlassian auth valid", True,
                      f"user: {data.get('displayName', '?')}", critical=False)
        except Exception as e:
            check("sensors", "Atlassian auth valid", False, str(e)[:80], critical=False)
    check("sensors", "today's jira snapshot",
          (MEMORY / "sensors" / f"jira-{today}.json").exists(), critical=False)
    check("sensors", "today's confluence snapshot",
          (MEMORY / "sensors" / f"confluence-{today}.json").exists(), critical=False)

    # Slack token extraction
    try:
        sys.path.insert(0, str(SCRIPTS))
        from slack_tokens import extract_and_validate
        _, _, user = extract_and_validate()
        check("sensors", "Slack tokens extractable", True, f"user: {user}", critical=False)
    except Exception as e:
        check("sensors", "Slack tokens extractable", False, str(e), critical=False)

    # ── 7. Statusline ─────────────────────────────────────────────
    section("7. Statusline")
    statusline = Path.home() / ".claude" / "statusline.py"
    check("statusline", "statusline.py exists", statusline.exists())
    if statusline.exists():
        check("statusline", "jarvis_insight_indicator patched",
              "jarvis_insight_indicator" in statusline.read_text())

    # ── 8. /brief skill ───────────────────────────────────────────
    section("8. /brief Skill")
    brief_skill = Path.home() / ".claude" / "skills" / "brief" / "SKILL.md"
    check("brief", "SKILL.md exists", brief_skill.exists())
    if brief_skill.exists():
        content = brief_skill.read_text()
        check("brief", "reads pending-insights.json", "pending-insights" in content)
        check("brief", "reads active-strategies", "active-strategies" in content)

    # ── 9. Systemd timers ─────────────────────────────────────────
    section("9. Systemd Timers")
    for timer in ["jarvis-sessions", "jarvis-calendar",
                   "jarvis-slack-snapshot", "jarvis-gitlab-snapshot",
                   "jarvis-gdocs-snapshot", "jarvis-jira-snapshot",
                   "jarvis-confluence-snapshot", "jarvis-daily-analyzer"]:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", f"{timer}.timer"],
                capture_output=True, text=True,
            )
            enabled = result.stdout.strip() == "enabled"
            check("timers", f"{timer}", enabled)
        except Exception:
            check("timers", f"{timer}", False)

    # Verify weekly schedule for analyzer
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", "jarvis-daily-analyzer.timer",
             "--property=TimersCalendar"],
            capture_output=True, text=True,
        )
        is_weekly = "Sun" in result.stdout
        check("timers", "analyzer runs weekly (Sun)", is_weekly,
              result.stdout.strip()[:60])
    except Exception:
        check("timers", "analyzer runs weekly", False, critical=False)

    # ── 10. Stale file check ──────────────────────────────────────
    section("10. Stale File Check")
    stale_files = [
        MEMORY / "rule-gaps.md",
        MEMORY / "catastrophic-lens.md",
        MEMORY / "daily-analyzer-debug.txt",
    ]
    for f in stale_files:
        check("stale", f"no stale {f.name}", not f.exists(),
              "should be deleted" if f.exists() else "", critical=False)

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{BOLD}{'─' * 60}{RESET}")
    total = len(results)
    passed = sum(1 for r in results if r[2] == "ok")
    failed = sum(1 for r in results if r[2] == "fail")
    warned = sum(1 for r in results if r[2] == "warn")

    print(f"{GREEN}{passed} passed{RESET}  {ORANGE}{warned} warnings{RESET}  {RED}{failed} failures{RESET}  ({total} total)\n")

    if failed:
        print(f"{RED}Critical failures:{RESET}")
        for comp, name, status, note in results:
            if status == "fail":
                print(f"  • [{comp}] {name}" + (f": {note}" if note else ""))
        print()

    if warned:
        print(f"{ORANGE}Warnings (non-critical):{RESET}")
        for comp, name, status, note in results:
            if status == "warn":
                print(f"  • [{comp}] {name}" + (f": {note}" if note else ""))
        print()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
