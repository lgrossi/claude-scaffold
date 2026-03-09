# Jarvis — Personal AI Assistant for Claude Code

Observes your Claude Code sessions, finds recurring patterns, and surfaces actionable insights weekly.

## What it does

```
NIGHTLY (Python, no LLM, seconds)
  Session JSONLs → session compacts (structured summaries)
  Calendar / AFK / Slack sensors → daily snapshots

WEEKLY (one Opus 1M call, ~10min)
  Reads all session key lines → produces:
  - Actionable insights (auto-fix or needs-user)
  - 3 reports (behavioral patterns, rule gaps, catastrophic lens)
  - Long-term strategic directions
  - Effectiveness metrics

SESSION START (no LLM)
  Statusline: 🔭 strategies | 🎯 priorities | 💡 insights | 📋 notes
  /brief: displays everything, clears the queue, executes fixes
```

## Setup

### 1. Install the scripts

Clone or copy `scripts/jarvis/` into your `~/.claude/scripts/jarvis/`.

### 2. Create the data directory

```bash
mkdir -p ~/.claude/memory/jarvis/{session-compacts,sensors,jarvis-analysis/backups}
```

Or set `JARVIS_MEMORY_DIR` to a custom location — all scripts respect this env var.

### 3. Install rules and skill

Copy into your `~/.claude/`:
- `rules/jarvis.md` — auto-loads context when editing Jarvis files
- `rules/coaching.md` — session-start insight checks + mid-session nudges
- `skills/brief/SKILL.md` — the `/brief` command

### 4. Patch your statusline

Add the `jarvis_insight_indicator()` function from `statusline.py` to your own statusline. It reads `pending-insights.json` and `active-strategies.json` to show insight counts.

### 5. Set up systemd timers (Linux)

Create user timers for each component:

```bash
# Session compactor — nightly
# jarvis-sessions.timer: OnCalendar=*-*-* 00:10:00
# jarvis-sessions.service: uv run ~/.claude/scripts/jarvis/session-processor.py

# Weekly analyzer — Sunday night
# jarvis-daily-analyzer.timer: OnCalendar=Sun *-*-* 00:15:00
# jarvis-daily-analyzer.service: uv run ~/.claude/scripts/jarvis/daily-analyzer.py

# Calendar snapshot — daily
# jarvis-calendar.timer: OnCalendar=*-*-* 06:00:00
# jarvis-calendar.service: uv run ~/.claude/scripts/jarvis/calendar-snapshot.py

# ActivityWatch summary — daily
# jarvis-activitywatch.timer: OnCalendar=*-*-* 00:05:00
# jarvis-activitywatch.service: uv run ~/.claude/scripts/jarvis/activitywatch-summary.py

# Slack health check — hourly
# jarvis-slack.timer: OnCalendar=*-*-* *:00:00
# jarvis-slack.service: uv run ~/.claude/scripts/jarvis/slack-health-check.py
```

Each service should:
- Set `Type=oneshot`
- Include `Environment=PATH=/home/you/.local/bin:/usr/local/bin:/usr/bin:/bin`
- Log to `StandardOutput=append:~/.claude/memory/jarvis/cron.log`

Enable: `systemctl --user enable --now jarvis-sessions.timer jarvis-daily-analyzer.timer`

### 6. Optional: sensor setup

**Google Calendar** — requires Application Default Credentials:
```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/calendar.readonly
```
Filter calendars with `JARVIS_CALENDAR_FILTER=you@company.com,Team Calendar`.

**ActivityWatch** — install from [activitywatch.net](https://activitywatch.net/). No config needed.

**Slack** — set `SLACK_XOXC_TOKEN` and `SLACK_XOXD_TOKEN` (browser session tokens). See `rules/mollie/slack.md` for extraction steps.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `JARVIS_MEMORY_DIR` | `~/.claude/memory/jarvis` | Data directory for all runtime files |
| `JARVIS_LOOKBACK_DAYS` | `7` | How many days of sessions to analyze |
| `JARVIS_CALENDAR_FILTER` | (empty = all) | Comma-separated calendar names/emails to include |
| `JARVIS_EXCLUDE_SESSIONS` | (empty) | Comma-separated session ID prefixes to skip in compaction |

## Personal context (optional)

Jarvis uses optional profile files for richer analysis. Create these in your memory directory:

- `profile.md` — who you are, decision-making patterns, friction points
- `portfolio.md` — what you're working on, project priorities
- `communication.md` — writing style, registers, tone preferences
- `technical-taste.md` — coding principles, language preferences

These are read by the weekly analyzer as context. If they don't exist, analysis still works — it just lacks personal calibration.

## Validate

```bash
uv run ~/.claude/scripts/jarvis/validate.py
```

Checks: directory structure, scripts, compacts, reports, insights pipeline, sensors, statusline, /brief skill, systemd timers, stale files.

## Architecture decisions

- **No retro-feed**: each weekly run generates fresh from session data. No accumulated bias from previous reports.
- **Insights from session data only**: the LLM is explicitly told not to derive insights from report content.
- **Strategies are directions, not tasks**: "shift from building to demonstrating" not "ship MR by Friday".
- **Reports first, insights last**: the model writes reports first to build context, then produces insights.
- **Section markers**: raw markdown output parsed with `<<<SECTION>>>` markers. JSON fences only for structured data.

## File layout

```
scripts/jarvis/
  session-processor.py    # Nightly compactor (no LLM)
  daily-analyzer.py       # Weekly analyzer (Opus 1M)
  calendar-snapshot.py    # Calendar sensor
  activitywatch-summary.py # AFK sensor
  slack-health-check.py   # Slack token monitor
  validate.py             # Pipeline validator
  docs/
    report-prompts.md     # Analysis architecture docs

rules/
  jarvis.md               # Auto-loads for jarvis file edits
  coaching.md             # Session-start + mid-session nudges

skills/brief/
  SKILL.md                # /brief command

memory/jarvis/            # Runtime data (gitignored)
  session-compacts/       # Compacted session JSONs
  sensors/                # Calendar, AFK snapshots
  jarvis-analysis/        # Reports + backups
  pending-insights.json   # Insight queue
  active-strategies.json  # Persistent strategies
  behavioral-patterns.md  # Behavioral patterns report
```
