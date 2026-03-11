---
topic: realtime-cost-statusline
project: /home/lgrossi/.claude
created: 2026-03-11T12:24:34Z
---
## Problem

The statusline's session cost display (cost.total_cost_usd from Claude Code's stdin payload) excludes subagent and team costs — roughly 30% of API calls are invisible. The cost-snapshot sensor has two bugs: it looks for subagent files at project_dir/subagents/ instead of project_dir/{session_id}/subagents/, and applies flat Opus pricing to all models (inflating Sonnet/Haiku costs ~5x). No daily aggregate cost tracking exists — spend vs the $43/day target is only visible post-hoc via the nightly sensor.

## Recommendation

The statusline computes session cost incrementally from the active session's JSONL files (main thread + subagents) with per-model pricing. Rather than re-parsing entire files on each refresh, it tracks byte offsets and only processes new lines — keeping refresh cost under 1ms regardless of session length. A daily accumulator aggregates cost across all sessions for the current day, displayed as a budget segment (e.g., $87/$43) with threshold-based color coding. The cost sensor uses the same per-model pricing and correct subagent file discovery.

Incremental parsing is chosen because JSONL files are strictly append-only — Claude Code never modifies previous lines. A byte-offset safety check (file shrank → full rescan) handles the impossible-but-defensive case. This is preferred over full re-parse (wasteful — re-reads 500+ lines for 2-5 new ones) and hook-based accumulators (no PostToolUse hook exists).

## Architecture Context

The statusline (statusline.py) receives a JSON payload on stdin every render cycle containing session_id, workspace, context window state, and built-in cost. It uses file-based TTL caching (read_cache/write_cache to /tmp/) to avoid expensive recomputation.

A session cost function discovers the active session's JSONL at ~/.claude/projects/{project_dir}/{session_id}.jsonl and subagent files at ~/.claude/projects/{project_dir}/{session_id}/subagents/*.jsonl. On each refresh (30s TTL), it reads from the last byte offset, parses only new assistant-type entries, extracts token fields (input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens) and model identifier, applies per-model pricing, and adds to the running total. The cache file stores {offset, subagent_offsets, cost} — not just a scalar. If any file's size is less than its cached offset, a full rescan is triggered.

A daily cost function reads the cost sensor file (sensors/cost-{date}.json) when available, falling back to scanning all today's JSONL files (mtime pre-filter). Daily total cached with 60s TTL, rendered as budget segment in line 2.

The cost sensor (cost-snapshot.py) uses the same per-model pricing and correct subagent discovery paths for batch/real-time consistency.

Per-model pricing (per 1M tokens):
- Opus: input=$15, cache_write=$3.75, cache_read=$0.30, output=$75
- Sonnet: input=$3, cache_write=$0.375, cache_read=$0.03, output=$15
- Haiku: input=$0.80, cache_write=$0.10, cache_read=$0.008, output=$4

## Risks

1. Large JSONL files — multi-MB file-history lines. Incremental parsing means these are only read once (on first scan); subsequent refreshes skip past them via byte offset.
2. Session ID absence — silently omit session cost segment.
3. Project dir discovery — ~20 dirs to scan. Glob + per-session cache makes it one-time.
4. Pricing drift — hardcoded dict needs manual update on rate changes.
5. Sensor/statusline pricing divergence — acceptable duplication across two files.
6. New subagent files appearing mid-session — on each refresh, re-glob subagent dir to discover new files. New files start at offset 0; existing files resume from cached offset.
