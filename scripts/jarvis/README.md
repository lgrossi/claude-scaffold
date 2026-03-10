# Jarvis — Personal AI Assistant for Claude Code

Observes your Claude Code sessions, finds recurring patterns, and surfaces actionable insights weekly.

## What it does

```
NIGHTLY (Python, no LLM, seconds)
  Session JSONLs → session compacts (structured summaries)
  Calendar / Slack / GitLab / Google Docs / Jira / Confluence sensors → daily snapshots

WEEKLY (one Opus 1M call, ~10min)
  Reads all session key lines → produces:
  - Actionable insights (auto-fix or needs-user)
  - 4 reports (behavioral patterns, rule gaps, catastrophic lens, work diary)
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

# Slack snapshot — daily
# jarvis-slack-snapshot.timer: OnCalendar=*-*-* 06:15:00
# jarvis-slack-snapshot.service: uv run ~/.claude/scripts/jarvis/slack-snapshot.py

# GitLab snapshot — daily
# jarvis-gitlab-snapshot.timer: OnCalendar=*-*-* 06:20:00
# jarvis-gitlab-snapshot.service: uv run ~/.claude/scripts/jarvis/gitlab-snapshot.py

# Google Docs snapshot — daily
# jarvis-gdocs-snapshot.timer: OnCalendar=*-*-* 06:35:00
# jarvis-gdocs-snapshot.service: uv run ~/.claude/scripts/jarvis/gdocs-snapshot.py

# Jira snapshot — daily
# jarvis-jira-snapshot.timer: OnCalendar=*-*-* 06:25:00
# jarvis-jira-snapshot.service: uv run ~/.claude/scripts/jarvis/jira-snapshot.py

# Confluence snapshot — daily
# jarvis-confluence-snapshot.timer: OnCalendar=*-*-* 06:30:00
# jarvis-confluence-snapshot.service: uv run ~/.claude/scripts/jarvis/confluence-snapshot.py
```

Each service should:
- Set `Type=oneshot`
- Include `Environment=PATH=/home/you/.local/bin:/usr/local/bin:/usr/bin:/bin`
- Log to `StandardOutput=append:~/.claude/memory/jarvis/cron.log`

Enable: `systemctl --user enable --now jarvis-sessions.timer jarvis-daily-analyzer.timer jarvis-gitlab-snapshot.timer jarvis-gdocs-snapshot.timer jarvis-jira-snapshot.timer jarvis-confluence-snapshot.timer`

### 6. Optional: sensor setup

**Google Calendar + Docs** — both require Application Default Credentials. Login once with all scopes:
```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/calendar.readonly,\
https://www.googleapis.com/auth/drive.readonly
```
Filter calendars with `JARVIS_CALENDAR_FILTER=you@company.com,Team Calendar`.

**Google Docs** — captures recently modified Docs/Sheets/Slides, unresolved comments, and cross-references presentations with calendar events. Uses the same ADC credentials as Calendar (ensure `drive.readonly` scope above).

**GitLab** — requires `GITLAB_TOKEN` (a personal access token with `read_api` scope) and optionally `GITLAB_HOST` (default: `gitlab.com`). Export both in your shell profile:
```bash
export GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
export GITLAB_HOST=gitlab.yourcompany.com  # omit for gitlab.com
```
The sensor fetches authored open MRs, review-requested MRs, and recently merged MRs. It also fetches per-MR discussion threads to compute unresolved comment counts. Stale detection flags MRs with: no reviewer after 3 days, failed pipeline after 24h, or no updates after 5 days.

**Jira** — requires `JIRA_URL`, `JIRA_USERNAME`, and `JIRA_API_TOKEN`. Uses HTTP Basic auth against the Jira REST API. The sensor fetches open issues assigned to you, sprint health, and stale issue detection.
```bash
export JIRA_URL=https://yourcompany.atlassian.net
export JIRA_USERNAME=you@company.com
export JIRA_API_TOKEN=your-api-token
```

**Confluence** — requires `CONFLUENCE_URL`, `CONFLUENCE_USERNAME`, and `CONFLUENCE_API_TOKEN`. Shares the same Atlassian API token as Jira. The sensor fetches owned pages, watched pages, and unresolved comments.
```bash
export CONFLUENCE_URL=https://yourcompany.atlassian.net/wiki
export CONFLUENCE_USERNAME=you@company.com
export CONFLUENCE_API_TOKEN=your-api-token
```

**Slack** — tokens are automatically extracted from Chromium's cookie store by `slack_tokens.py`. See `rules/mollie/slack.md` for details.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `JARVIS_MEMORY_DIR` | `~/.claude/memory/jarvis` | Data directory for all runtime files |
| `JARVIS_LOOKBACK_DAYS` | `7` | How many days of sessions to analyze |
| `JARVIS_CALENDAR_FILTER` | (empty = all) | Comma-separated calendar names/emails to include |
| `JARVIS_EXCLUDE_SESSIONS` | (empty) | Comma-separated session ID prefixes to skip in compaction |
| `JARVIS_GDOCS_LOOKBACK_HOURS` | `24` | How many hours back to scan for modified Google Docs |
| `GITLAB_TOKEN` | (required) | GitLab personal access token (`read_api` scope) |
| `GITLAB_HOST` | `gitlab.com` | GitLab instance hostname |
| `JIRA_URL` | (required) | Jira instance URL (e.g. `https://company.atlassian.net`) |
| `JIRA_USERNAME` | (required) | Jira account email |
| `JIRA_API_TOKEN` | (required) | Atlassian API token |
| `CONFLUENCE_URL` | (required) | Confluence instance URL (e.g. `https://company.atlassian.net/wiki`) |
| `CONFLUENCE_USERNAME` | (required) | Confluence account email |
| `CONFLUENCE_API_TOKEN` | (required) | Atlassian API token (same as Jira) |

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
  slack-snapshot.py       # Slack channel snapshot
  slack_tokens.py         # Slack token extractor
  gitlab-snapshot.py      # GitLab MR status sensor
  gdocs-snapshot.py       # Google Docs/Sheets/Slides sensor
  jira-snapshot.py        # Jira issues + sprint health sensor
  confluence-snapshot.py  # Confluence pages + comments sensor
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
  sensors/                # Calendar, Slack, GitLab, Google Docs, Jira, Confluence snapshots
  jarvis-analysis/        # Reports + backups
    work-diary.md         # Weekly work diary (shipped, in-progress, comms, blocked)
  pending-insights.json   # Insight queue
  active-strategies.json  # Persistent strategies
  behavioral-patterns.md  # Behavioral patterns report
```
