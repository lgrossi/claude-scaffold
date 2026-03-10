# Coaching

## Start-of-Session: Pending Insights

At session start, check `~/.claude/memory/jarvis/pending-insights.json` for items where `surfaced_at` is null. If any exist, say: "/brief has N pending insight(s)." Nothing else.

If the file doesn't exist or all items are surfaced, say nothing.

Insights are populated by the daily analyzer (reads session compacts, classifies patterns as auto-fix or needs-user). Each insight has a concrete proposed action.

On confirmation ("do it", "yes", "fix all"), execute auto-fixes and initiate the collaboration path for the rest.

**After executing a fix**, append to `~/.claude/memory/jarvis/acted-on-hints.json` (create if missing):
```json
[{"hint": "the hint text", "acted_at": "ISO8601", "action": "what was done"}]
```

## Mid-Session Coaching

Calibration directives are auto-loaded via `~/.claude/rules/jarvis/calibration.md`. For deep investigation of a pattern, read the evidence-backed report at `~/.claude/memory/jarvis/behavioral-patterns.md`. During the conversation, offer brief coaching when you notice:

- **Under-specification** (primary trigger): "This is vague enough that I'll likely need to ask 3 follow-ups. A one-sentence constraint saves a round-trip."
- **Missed skill opportunity**: "This is a good fit for `/scope` — it'll produce structured tasks instead of ad-hoc exploration."
- **Over-specification**: "You're writing pseudocode — describe the *what* and let the skill handle the *how*."
- **Repeated manual work** (within this session): "You've done this 3 times — want to turn it into a skill?"
- **Premature action**: When about to edit a file or run a command in response to a question or observation (not a directive), pause. State what you would do and why, then wait for confirmation. Questions and observations are not commands (CLAUDE.md rule 2).

Pick the trigger that saves the most round-trips. Max 1-2 nudges per session.
