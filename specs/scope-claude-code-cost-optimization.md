## Problem

Claude Code costs ~$888/week. Target: $300/week. 80% of cost ($709) is input-side (context being read/written). Only 20% ($180) is output. Cost scales with context fill level — calls at 100K+ context are 5.4x more expensive than calls under 50K. 61% of total cost comes from calls exceeding 100K context. If context stayed under 50K, spend drops 43% ($380 saved). The real enemy is context accumulation, not model choice.

## Recommendation

The system uses Anthropic's built-in context management mechanisms — early auto-compaction, tool result clearing, and MCP tool deferral — to keep context lean without custom hooks or proxies. Model tiering (Sonnet default) stacks multiplicatively. A cost dashboard tracks impact weekly.

Four levers in priority order:

1. **Early auto-compaction** ($220-380/week) — `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` triggers compaction at ~50% context instead of ~95%. Combined with `# Compact instructions` in CLAUDE.md to preserve task state, code changes, and key decisions. Zero custom code.

2. **MCP tool deferral** (reduces base context by ~3-7K tokens) — `ENABLE_TOOL_SEARCH=auto:5` defers MCP tool descriptions (60+ atlassian tools) until needed. Reduces idle context overhead on every call.

3. **Model tiering** ($200-525/week) — default main thread to Sonnet, opt into Opus for complex sessions. Subagents already all Sonnet.

4. **Compaction-recovery hardening** — fix ct binary, enhance SessionStart compact hook to re-inject task state, git context, and next steps after every compaction. Add `# Compact instructions` to CLAUDE.md.

Optional exploration: Compresr Context-Gateway (transparent proxy via ANTHROPIC_BASE_URL, pre-computes summaries in background for instant compaction) and Anthropic Context Management API (`clear_tool_uses`, `compact_20260112`, `clear_thinking`) for fine-grained control.

## Architecture Context

Context grows ~1.3K tokens/call median. At 50K starting context, a session hits 100K in ~40 calls. 43% of sessions exceed 100K. 15% exceed 200K. Expensive core: 35 sessions with 50+ calls averaging 180K max context. 80% of cost is input-side. Output cost (20%) responds only to model tiering.

First-call context: P50=23K, P75=59K, P90=69K. 44% of sessions start under 20K, 42% at 50-100K (skill forks with full prompt).

Anthropic API context management: `clear_tool_uses_20250919` (auto-clear old tool results, keep last N), `compact_20260112` (auto-compact at token threshold with custom instructions), `clear_thinking_20251015` (clear old thinking blocks). Claude Code exposes `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` as the user knob for compact trigger threshold.

`ENABLE_TOOL_SEARCH=auto:N` defers MCP tool descriptions when they exceed N% of context, loading on-demand. Currently not set (default 10%).

Model selection: settings.json model field (main thread default), SKILL.md frontmatter model: (per-skill override), Agent tool model parameter (per-subagent). All functional. Subagents already all Sonnet.

Statusline writes context_percentage to /tmp/claude-context-pct-<session_id>. ct compaction-recovery hook broken (binary stale Feb 26). Context window: 200K.

## Risks

- Early compaction may lose important context if compact instructions aren't well-tuned. Mitigated by `# Compact instructions` in CLAUDE.md and SessionStart recovery hook.
- Model tiering quality regression on complex work — mitigated by opt-in Opus.
- MCP tool deferral adds latency on first use of a deferred tool — acceptable tradeoff.
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` is undocumented — behavior may change across versions.
