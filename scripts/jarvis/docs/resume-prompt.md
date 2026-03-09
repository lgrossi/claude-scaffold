# Jarvis Session Resume — 2026-03-09

## What to read first
- `~/.claude/rules/jarvis.md` — quick context (auto-loads)
- `~/.claude/scripts/jarvis/README.md` — full system overview

## Current state
- All sensors running (systemd timers): session compactor (nightly), calendar, AFK, Slack health
- Weekly analyzer: `scripts/jarvis/daily-analyzer.py` — Opus 1M, fresh each run (no retro-feed)
- Timer: Sunday 00:15 (`jarvis-daily-analyzer.timer`)
- Reports: fresh baseline generated 2026-03-09 from 146 sessions
- Strategies: long-term directions (not tasks)
- Statusline shows `🔭 strategy|🎯 priority|💡 insight|📋 note| /brief for more`

## Architecture decisions made this session

### Compact filtering
- Compactor: `EXCLUDE_SESSIONS` set for specific session IDs (e.g. `5b10331f`)
- Analyzer: `user_messages >= 2` gate drops stubs/subagent outputs
- Path-based exclusion removed — too broad, would block legitimate `~/.claude` work

### Unified analyzer (one Opus 1M call)
- Produces: insights + metrics + 3 reports + strategies
- Reports first, insights last — model builds context before surfacing insights
- Section markers (`<<<BEHAVIORAL_PATTERNS>>>` etc.) for raw markdown output
- JSON fences only for structured data (insights, metrics, strategies)
- Timeout: 1800s

### No retro-feed
- Each run generates fresh from session data — no previous reports in prompt
- Eliminates accumulated bias and "7 passes unfixed" report-metadata leaking into insights
- Insights explicitly instructed to derive from session data only, not from report content
- Fresh runs produce leaner but signal-dense reports that reflect what's actually in the data

### Weekly cadence
- Reports are reference docs acted on manually — don't need nightly refresh
- Session data only changes meaningfully over a week
- Compactor still runs nightly to keep compacts current

### Strategies are directions, not tasks
- "From personal tooling to organizational capability" — good
- "Ship MR !3 before Friday" — bad (that's a task/insight)

### Report timestamping
- Written as `report.YYYY-MM-DDTHH-MM.md` + copied to fixed path for consumers
- Old reports moved to `jarvis-analysis/backups/` before each run
- `JARVIS_LOOKBACK_DAYS` env var (default 7) for configurable window

### Insight consistency
- Tested: 7/12 insights stable across parallel runs with same data
- Red-urgency items fully stable, variance in green/orange tail — acceptable
- Prompt separation ensures insights come from session data, not report metadata

## Key files
- `scripts/jarvis/session-processor.py` — nightly compactor
- `scripts/jarvis/daily-analyzer.py` — weekly analyzer (name kept for systemd compat)
- `memory/jarvis/session-compacts/*.json` — compacted sessions
- `memory/jarvis/pending-insights.json` — insight queue
- `memory/jarvis/active-strategies.json` — persistent strategies
- `memory/jarvis/behavioral-patterns.md` — behavioral patterns report
- `memory/jarvis/jarvis-analysis/rule-gaps.md` — rule gaps report
- `memory/jarvis/jarvis-analysis/catastrophic-lens-report.md` — catastrophic lens report
- `memory/jarvis/jarvis-analysis/backups/` — old reports
- `scripts/jarvis/README.md` — system overview
- `scripts/jarvis/docs/report-prompts.md` — analysis docs

## What's left
1. **Validate weekly pipeline** — let the Sunday timer run, check output Monday morning
2. **First real /brief** — surface insights, act on auto-fixes
3. **Act on rule gaps** — "fix the top rule gaps" and Claude executes from the report
4. **Review and commit** — decide what to commit vs stays local
