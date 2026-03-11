1. Never external actions without explicit request (PR comments, GitHub issues, Slack, email, Notion).
2. Questions are reflections to analyze, not disguised commands. Think critically and answer the question. Don't treat "do you think X needs Y?" as "do Y."
3. No dead code, commented-out code, "just in case" code. Delete old code completely — no deprecation, versioned names, migration code.
4. Comments for WHY / edge cases / surprising only. No docstrings unless project convention. No comments on code you didn't write.
5. Always delegate work to subagents or teams.
6. Subagent trust is adversarial by default. Spot-check claims (1-2 for small tasks; ALL architectural claims for epics). Echo detection: if a subagent confirms every assumption without surfacing tradeoffs or caveats, re-verify the claim most likely to have nuance. Build gate exemption: build/test-verified results skip spot-checks.
7. Grep tool > Glob tool. Never raw `grep`/`find` in Bash.
8. Never `git checkout` to "restore" — make targeted edits. Ask before discarding uncommitted work.
9. Never drop, revert, or modify things you don't recognize (commits, files, branches, config). If something unexpected appears, stop and ask — it's the user's work.
10. When saving memories, consider if a universal rule would be more useful → `~/.claude/rules/<topic>.md`
11. Skills flow: brainstorm → scope → develop [acceptance] → review → commit. scope→develop is automatic inside /vibe.
12. On resume after compaction: if tasks exist with `metadata.impl_team` set and status `in_progress`, re-invoke `/develop` to trigger recovery.
13. Skill scripts: use `${CLAUDE_SKILL_DIR}` in SKILL.md to reference skill-local files (scripts, references, agents). Expands to the skill's absolute directory at load time.
14. Natural language routing: match intent against skill trigger phrases. High confidence → invoke directly. Ambiguous (2-3 candidates) → AskUserQuestion. No match → respond normally.
15. In Mollie/work projects: every branch requires a Jira ticket — see `rules/jira.md`. Branch format: `$GIT_USERNAME/<ticket-id>-<description>`. Board: https://mollie.atlassian.net/jira/software/projects/MPM/boards/321
16. All plans, notes, and state live in Claude's native task system — not files. Lifecycle: pending → in_progress → completed. Use `status_detail: "review"` to signal awaiting user verification before closing.

@RTK.md

# Compact instructions

When compacting, preserve: current task IDs and status, git branch and uncommitted changes, modified file paths, key architectural decisions, acceptance criteria, and next steps. Drop verbose tool outputs and intermediate exploration results.
