# Claude Code Session Memory

## Jarvis Architecture (2026-03-09)

Weekly analyzer (Sunday 00:15), one Opus 1M call, no retro-feed.
Full docs: `~/.claude/scripts/jarvis/README.md`

Key decisions:
- **No retro-feed**: fresh each run — previous reports not in prompt. Eliminates bias and report-metadata leaking into insights.
- **Insights from session data only**: prompt explicitly separates insight source from report context.
- **Strategies are directions, not tasks**: "shift from X to Y" not "ship Z by Friday".
- **Reports first, insights last**: model builds context before producing insights.
- **Section markers**: `<<<SECTION>>>` for raw markdown, JSON fences for structured data.
- **Compact filtering**: `user_messages >= 2` (analyzer) + `EXCLUDE_SESSIONS` set (compactor).
- **Timestamped reports**: `report.YYYY-MM-DDTHH-MM.md` + fixed path copy. Old → `backups/`.
- **Consistency**: 7/12 insights stable across parallel runs. Red items fully stable.

## Skill Design Patterns

### Product Vision Skill (product:vision)

**Posture fix (2026-03-06):**
- Don't retract on first pushback during build-vs-buy validation. User skepticism ≠ evidence that the gap is invalid. Hold the skepticism as a discovery gap and move forward.
- Scope narrowing trap: first use case anchors the vision. Early zoom-out check required: "Is X the first case for a more general capability?" Prevents re-narrowing mid-conversation.

**Output template learnings:**
- Capabilities + Principles + North Star + KPIs works better than Now/Next/Later when timeline is premature.
- North star = directional statement (what users want/experience), not a KPI. KPIs are measurables for tracking progress.
- Target users: situational framing ("Developers of services that...") beats role labels ("Backend engineers / SREs").
- Principles: one sentence each, no complex subordination or semicolons.
- Remove implementation details and tool names from vision (user feedback: "the plugin is too specific to the implementation").

**Post-vision workflow (NEW):**
- Skill should NOT stop after writing. Read the vision + discovery gaps and propose next artifact with reasoning.
- Decision rule: major discovery gaps → brainstorm; open technical choice → decide; solid vision → scope.
- Present as one-sentence reasoning + named next skill, not as a menu.

### Decision Skill (mdp:decide)

**Inherited constraint (2026-03-06):**
- ADR-0009 in edge-app: Lua-based plugins are limited to <10ms latency, no per-request-class state across requests.
- Any fallback router needing stateful circuit breaker (count failures, trip, recover) cannot live in Lua → must be an internal service.
- Informs architectural boundary for APISIX plugin work.
