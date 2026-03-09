# Plugin Authoring

## Never Edit the Cache

Plugin cache lives at `~/.claude/plugins/cache/`.
Edits there are **silently lost** when the plugin is refreshed.

When a skill file is under `~/.claude/plugins/cache/`, STOP.
Find and edit the source repo instead:

| Plugin | Source |
|---|---|
| commons | `~/AI/commons/` |
| mollie-claude-plugins (mdp, pubsub, skills-forger, product) | `~/Mollie/mollie-claude-plugins/plugins/` |
| project skills | project's `.claude/skills/` directory |

After editing the source, refresh the cache:
`claude plugin install <plugin-name>@local`

## Exception

Editing the cache is acceptable for a **quick live test** of an unreleased skill,
as long as you immediately apply the same edit to the source repo before the session ends.
