---
paths:
  - "scripts/jarvis/**"
  - "memory/jarvis/**"
  - "skills/brief/**"
---

# Jarvis

Personal AI assistant layer. Observes sessions, surfaces actionable insights, executes fixes on confirmation.

## Quick context

- **Data store**: `memory/jarvis/session-compacts/*.json` — Python-compacted session transcripts (no LLM)
- **Weekly analyzer**: `scripts/jarvis/daily-analyzer.py` — reads compacts, produces insights + 3 reports + strategies. Opus 1M, one call/week (Sunday 00:15). No retro-feed — fresh each run.
- **Delivery**: statusline shows `🔭 strategy|🎯 priorities|💡 insights|📋 notes| /brief for more`. `/brief` clears insights, strategies persist.
- **Sensors**: session compactor (nightly), calendar, AFK, Slack health — all systemd timers.

## Key files

- `scripts/jarvis/README.md` — setup guide and system overview
- `scripts/jarvis/docs/report-prompts.md` — analysis architecture
- `memory/jarvis/pending-insights.json` — insight queue (auto-clear)
- `memory/jarvis/active-strategies.json` — persistent strategies (replaced each weekly run)
- `memory/jarvis/behavioral-patterns.md` — behavioral calibration for coaching.md
- `rules/coaching.md` — session-start behavior + mid-session nudges