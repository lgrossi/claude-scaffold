---
name: brief
description: "Read and clear pending Jarvis insights + show active strategies. Shows what the background analysis layer surfaced since last check — calendar anomalies, session patterns, Slack signals, ActivityWatch data. Triggers: '/brief', 'what did jarvis find', 'show insights', 'any updates', 'what's pending'."
argument-hint: "[optional: urgency filter — red, orange, green, strategy]"
user-invocable: true
allowed-tools:
  - Read
  - Bash
  - Write
---

# /brief — Jarvis Insight Reader

Read pending insights, show pending actions, and display active strategies.

## Files

- `~/.claude/memory/jarvis/pending-insights.json` — insight queue
- `~/.claude/memory/jarvis/active-strategies.json` — persistent strategies (replaced by deep analysis)

## Insight lifecycle

Each insight has two timestamps: `surfaced_at` (shown to user) and `acted_at` (resolved).

| State | `surfaced_at` | `acted_at` | Shown in |
|---|---|---|---|
| New | null | null | "NEW" sections (prominent) |
| Pending action | set | null | "PENDING ACTIONS" section (if actionable) |
| Resolved | set | set | Hidden. Pruned after 30 days. |

**Actionable** = has an `action` field that does NOT contain "no further action needed" or "for awareness".
Informational insights (no action, or action says "no further action needed") skip the pending-action state — once surfaced, they're done.

## What sets `acted_at`

- **Auto-fix executed** — Claude runs the fix, sets `acted_at`, appends to `acted-on-hints.json`
- **Needs-lucas decided** — user gives a decision (yes/no/accepted), Claude sets `acted_at`
- **Explicitly dismissed** — user says "dismiss #3", "clear the greens", etc.

## Workflow

### 1. Show active strategies

Read `active-strategies.json`. If it exists and has entries, show first:

```
--- 🔭 ACTIVE STRATEGIES (persistent) ---
[updated: YYYY-MM-DD] title
body text
```

These are NOT cleared — they persist until the next deep analysis replaces them.

### 2. Show pending actions (from previous briefs)

Load `pending-insights.json`. Filter to items where `surfaced_at` is set, `acted_at` is null, and the insight is actionable.

If any exist, show before new insights:

```
--- ⏳ PENDING ACTIONS (from previous briefs) ---
#idx [source] title
  → action text
```

Number them so the user can reference by index ("dismiss #3", "do #1").

### 3. Show new insights

Filter to items where `surfaced_at` is null.
If an urgency argument was passed, filter to that level. Invalid argument → show all.
Display by urgency group in order: red → orange → green.

```
--- 🎯 PRIORITIES (red) ---
[source] title
body text
→ action (if present)

--- 💡 INSIGHTS (orange) ---
...

--- 📋 NOTES (green) ---
...
```

### 4. Mark new insights as surfaced

Update `pending-insights.json`:
- Set `surfaced_at` to current ISO8601 for all newly displayed items.
- Prune items where `acted_at` is set and older than 30 days.
- Write via temp file + rename.

Do NOT set `acted_at` here — that only happens when the user acts on an insight.
Do NOT modify `active-strategies.json` — strategies are persistent.

### 5. Summarize

`Surfaced N new insights (X red, Y orange, Z green). M pending actions. K active strategies.`

## Hard rules

- Never delete unsurfaced insights — only set `surfaced_at`.
- Never set `acted_at` without user action (auto-fix, decision, or dismiss).
- Resolved insights (`acted_at` set) older than 30 days may be pruned.
- Never clear strategies — they persist until replaced by deep analysis.
- If a file doesn't parse, say so and don't overwrite.
