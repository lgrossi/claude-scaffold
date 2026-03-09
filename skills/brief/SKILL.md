---
name: brief
description: "Surfaces pending Jarvis insights and active strategies. Triggers: '/brief', 'what did jarvis find', 'show insights', 'any updates', 'what's pending'."
argument-hint: "[optional: urgency filter — red, orange, green, strategy]"
user-invocable: true
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
  - Write
---

# /brief — Jarvis Insight Reader

Read pending insights, show pending actions, and display active strategies.

## Files

- `~/.claude/memory/jarvis/pending-insights.json` — insight queue
- `~/.claude/memory/jarvis/active-strategies.json` — persistent strategies (replaced by deep analysis)

## Insight lifecycle

| State | `surfaced_at` | `acted_at` | Shown in |
|---|---|---|---|
| New | null | null | "NEW" sections (prominent) |
| Pending action | set | null | "PENDING ACTIONS" section (if actionable) |
| Resolved | set | set | Hidden. Pruned after 30 days. |

**Actionable** = has an `action` field that does NOT contain "no further action needed" or "for awareness".
Informational insights skip the pending-action state — once surfaced, they're done.

`acted_at` is set by: auto-fix executed (Claude runs it), user decision (yes/no/accepted), or explicit dismiss ("dismiss #3").

## Workflow

### 1. Show active strategies

Read `active-strategies.json`. If it exists and has entries, show first:

```
--- 🔭 ACTIVE STRATEGIES (persistent) ---
[updated: YYYY-MM-DD] title
body text
```

### 2. Show pending actions (from previous briefs)

Load `pending-insights.json`. Filter to items where `surfaced_at` is set, `acted_at` is null, and the insight is actionable.

**Urgency filters apply only to new insights (step 3) — not to pending.**

**Stale detection.** For each pending item, cross-check against current conversation context and session knowledge.

- **Concrete evidence of resolution** → set `acted_at` immediately, skip from display, note: `✓ auto-dismissed: <reason>` at the end of the pending section.
- **Genuinely uncertain** → flag inline and let the user decide:
  ```
  #idx [source] title ⚠ may be resolved — confirm?
    → action text
  ```

Default to resolving when evidence is clear; flag when unsure.

If any exist, show before new insights:

```
--- ⏳ PENDING ACTIONS (from previous briefs) ---
#idx [source] title
  → action text
```

Number them so the user can reference by index ("dismiss #3", "do #1").

### 3. Pre-display verification for new insights

Before showing anything, run three checks on every new insight (`surfaced_at` is null):

**A. Auto-fix: already applied?**

For each `auto-fix:` item, grep/read the target file(s) mentioned or implied by the action text.
- Already present → set `acted_at` now, exclude from display, record `✓ auto-dismissed: already applied` in the summary.
- Absent → keep in the display queue.

**B. needs-user: does this genuinely require a human?**

Reclassify `needs-user:` → `auto-fix:` unless the action requires something only the user can provide:
- A policy or priority call with real tradeoffs (cost, risk, direction)
- Approval to contact someone or take an external action
- Information only the user has

The bar for keeping needs-user is: "I cannot complete this without input." If Claude can execute it — editing a file, creating a skill, writing a rule, documenting a limitation — it's auto-fix. Tentative phrasing ("consider whether", "evaluate if") doesn't affect classification — assess what the action requires, not how it's worded. Example: "consider whether to build a skill for X" → auto-fix: build the skill.

**C. All items: already resolved based on session knowledge?**

Reason against what you know from session compacts, conversation history, and loaded context:
- Has this decision already been made? (user said "let's not do X", "we discontinued Y")
- Does a referenced artifact already exist? (skill shipped, hook wired, rule written)
- Is the described system visibly functioning right now? (observable current state is valid evidence — state it explicitly in the dismissal reason)
- Was the approach explicitly abandoned or deprioritized? (a decision to stop counts as resolved — state the abandonment decision explicitly in the dismissal reason)

If yes → set `acted_at` now, exclude from display, record `✓ auto-dismissed: <specific reason>` in the summary.

This applies to ALL items, including needs-user. Session knowledge is as valid as a file grep.

### 4. Show new insights

Filter to items where `surfaced_at` is null (after step 3 exclusions).
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

### 5. Mark new insights as surfaced

Update `pending-insights.json`:
- Set `surfaced_at` to current ISO8601 for all newly displayed items.
- Persist any action-prefix reclassifications from step 3B.
- Prune items where `acted_at` is set and older than 30 days.
- Write via temp file + rename.

### 6. Summarize

`Surfaced N new insights (X red, Y orange, Z green). M pending actions. K active strategies.`
If any were auto-dismissed or reclassified, list each with its reason: `✓ auto-dismissed: <title> — <reason>. Reclassified N needs-user → auto-fix.`

## Hard rules

- Never delete unsurfaced insights — only set `surfaced_at`.
- `acted_at` is only set when there is traceable evidence: fix verified present, explicit user decision, or explicit dismiss. Never set it as a guess.
- Never modify `active-strategies.json` — strategies persist until replaced by deep analysis.
- If a file doesn't parse, say so and don't overwrite.
