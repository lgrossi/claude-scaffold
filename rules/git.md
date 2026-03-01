## Commits
- Format: `TICKET-123 Imperative description`
- Subject (≤ 72 chars) says WHAT. Body says WHY. HOW is in the diff.
- One logical change per commit.

## Branches
- Format: `username/TICKET-123-short-description`

## Fixup Workflow
- Stage ONLY intended files. Never `git add -A`.
- Before `git rebase --autosquash`: stash unstaged changes.
- After rebase: `git status` — cs-fixer diffs appear unstaged. Fixup or stash.
- Use `--no-verify` for fixup commits.
- Verify commit count after rebase.
- Always `--force-with-lease`, never `--force`.
