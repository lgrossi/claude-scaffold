---
name: prep
description: "Synthesize Jarvis reports into 1:1, Show & Tell, or self-tracking briefings."
argument-hint: "[1:1 | show-and-tell | self-track]"
user-invocable: true
allowed-tools:
  - Read
  - Glob
---

# Prep

Read-only synthesis of Jarvis reports into audience-specific briefings.

## Arguments

- `1:1` (default): Manager 1:1 prep
- `show-and-tell`: Demo/presentation prep
- `self-track`: Personal tracking and reflection

## Artifact Paths

All paths under `~/.claude/memory/jarvis/`:
- `active-strategies.json` — [{title, body, updated}]
- `jarvis-analysis/catastrophic-lens-report.md` — Protect/Dash/Evolving classification, Starts, Stops, Strategic Signals
- `jarvis-analysis/work-diary.md` — Shipped, In Progress, Communications, Blocked/Stale
- `behavioral-patterns.md` — behavioral patterns with session evidence (latest timestamped version)
- `pending-insights.json` — [{urgency, title, body, action, surfaced_at, acted_at}]

## Instructions

1. Read all artifact paths. Use Glob for timestamped files: `~/.claude/memory/jarvis/behavioral-patterns.*.md` (use the most recent). For files that may not exist (work-diary.md), handle gracefully — note "_(no data available)_" for that section.

2. Route based on argument:

### 1:1 Mode (default)

Output format:

```
## Strategies
- <title>: <one-line body summary>

## Work Summary
### Shipped
<from work-diary.md ## Shipped, or "_(no data)_">
### In Progress
<from work-diary.md ## In Progress, or "_(no data)_">
### Blocked
<from work-diary.md ## Blocked/Stale, or "_(no data)_">

## Strategic Signals
<from catastrophic-lens-report.md ## Strategic Signals section only>

## Attention Items
<red + orange insights where surfaced_at is null, grouped by urgency>
```

### Show & Tell Mode

Output format:

```
## What's New
<from catastrophic-lens-report.md ## Starts section — format as narrative bullets>

## What Shipped
<from work-diary.md ## Shipped, or "_(no data)_">
```

### Self-Track Mode

Output format:

```
## Session Distribution
<Protect/Dash/Evolving ratio table from catastrophic-lens-report.md>

## Top Patterns
<Top 3 patterns from behavioral-patterns.md — title + calibration note only>

## Open Insights
<ALL insights where surfaced_at is null, sorted red -> orange -> green, with body text>
```

3. Output as conversation text. No file writes. This skill does NOT modify `surfaced_at` — that remains /brief's responsibility.
