# Analysis & Reports

One Opus 1M call produces everything. Runs weekly (Sunday 00:15), fresh each time.

## How to run

```bash
# Default: last 7 days
uv run ~/.claude/scripts/jarvis/daily-analyzer.py

# Full history
JARVIS_LOOKBACK_DAYS=9999 uv run ~/.claude/scripts/jarvis/daily-analyzer.py
```

## What it produces

| Output | File | Behavior |
|---|---|---|
| Insights | `pending-insights.json` | Replaces previous daily-analyzer entries |
| Metrics | `jarvis-metrics.jsonl` | Appends |
| Behavioral patterns | `behavioral-patterns.{ts}.md` + `behavioral-patterns.md` | Fresh each run |
| Rule gaps | `jarvis-analysis/rule-gaps.{ts}.md` + `rule-gaps.md` | Fresh each run |
| Catastrophic lens | `jarvis-analysis/catastrophic-lens-report.{ts}.md` + fixed path | Fresh each run |
| Strategies | `active-strategies.json` | Replaced — long-term directions, not tasks |

## Design principles

- **No retro-feed**: each run generates from session data alone — no previous reports in prompt
- **Reports first, insights last**: model builds full context before producing insights
- **Insights from data only**: explicitly instructed not to derive from report content
- **Strategies are directions**: "shift from X to Y" not "finish task Z by Friday"

## Insight quality bar

Every insight must answer: **"What should Lucas do differently because of this?"**
Derived from session data only. No artificial cap — could be 3, could be 25.
