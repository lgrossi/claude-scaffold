# claude-scaffold

How I structure `$HOME/.claude` —
a real, working setup for Claude Code with plugins, skills, rules, hooks, and tools.

## The problem

Claude Code's `$HOME/.claude` directory mixes three concerns into one location:

1. **Personal config** — settings, model choice, keybindings, permissions
2. **Reusable skills and rules** — workflows, language conventions, agent behaviors
3. **Runtime state** — session data, history, cache, task lists

When people share their `$HOME/.claude` as a git repo, you have to choose:
clone theirs and lose your config, or skip it and miss the skills.
You can't compose setups from multiple sources.

## The solution: plugins

Claude Code supports local plugins via a marketplace mechanism.
Instead of cramming everything into one directory, split reusable content into plugin repos
and keep `$HOME/.claude` as the **glue layer** that wires them together.

```
$HOME/.claude/                          ← this repo (config + wiring)
├── CLAUDE.md                           ← personal instructions
├── settings.json                       ← model, permissions, enabled plugins
├── rules/                              ← global rules (git, search, etc.)
├── tools/crates/ct/                    ← CLI tools (notification, task mgmt)
├── statusline.py                       ← custom status bar
├── keybindings.json                    ← keyboard shortcuts
├── local-plugins/
│   ├── .claude-plugin/marketplace.json ← declares available plugins
│   └── plugins/
│       ├── commons → $HOME/AI/commons  ← shared skills plugin
│       ├── gt → $HOME/AI/gt            ← Graphite CLI plugin
│       └── mollie → $HOME/AI/mollie    ← org-specific plugin
└── .gitignore                          ← excludes runtime state
```

## How plugins work

A plugin is any directory with a `.claude-plugin/plugin.json`.
It can contribute skills, rules, hooks, and agents.
You register plugins through a local marketplace:

**1. Create the marketplace** at `$HOME/.claude/local-plugins/.claude-plugin/marketplace.json`:

```json
{
  "name": "local",
  "description": "Local plugins",
  "plugins": [
    {
      "name": "commons",
      "description": "Shared skills, rules, and agents",
      "source": "./plugins/commons"
    }
  ]
}
```

**2. Symlink plugin repos** into `$HOME/.claude/local-plugins/plugins/`:

```bash
ln -sf $HOME/AI/commons $HOME/.claude/local-plugins/plugins/commons
```

**3. Enable in settings.json**:

```json
{
  "extraKnownMarketplaces": {
    "local": { "source": { "source": "directory", "path": "$HOME/.claude/local-plugins" } }
  },
  "enabledPlugins": { "commons@local": true }
}
```

## What lives where

| Layer | What | Shared? |
|-------|------|---------|
| `$HOME/.claude` (this repo) | Config, wiring, tools | Reference only |
| Plugin: [commons](https://github.com/luan/dot-claude) | Workflow skills (scope, develop, review, commit) | Yes — install as plugin |
| Plugin: gt | Graphite CLI wrapper (stacked PRs) | Yes — install as plugin |
| Plugin: mollie | Org-specific skills (ADR, PubSub, Backstage) | Internal |

## What's in this repo

### Config

- **CLAUDE.md** — global instructions:
  code style, safety rules, debugging approach, workflow conventions
- **settings.json** — model selection, permissions, enabled plugins, env vars, notification hooks
- **keybindings.json** — keyboard shortcuts for the TUI

### Rules

Global rules loaded into every session:

- `git.md` — commit format, branch naming, fixup workflow
- `search-tools.md` — tool hierarchy (Grep > Glob > rg/fd > ck)
- `subagent-trust.md` — adversarial verification of subagent output
- `markup.md` — formatting conventions

### Tools

- **ct** — Rust CLI for notifications, task management, and session utilities

## Adapting this for yourself

1. Fork or clone this repo as your `$HOME/.claude`
2. Edit `CLAUDE.md` with your own instructions
3. Update `settings.json` — change `GIT_USERNAME`, model, permissions
4. Remove plugins you don't need from `marketplace.json` and `settings.json`
5. Add your own rules, hooks, and skills
6. Install shared plugins by cloning and symlinking

The runtime state (sessions, history, cache, tasks) is gitignored
and will be created by Claude Code on first run.
