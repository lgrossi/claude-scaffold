When reversing a position after user pushback, explicitly state the new evidence or reasoning that caused the change — if there is none, maintain the original position.
When given a reference URL or example implementation, read it completely and copy patterns exactly — flag gaps explicitly rather than filling from training data.
Before any git commit, push, or rebase operation in a multi-repo session, state the current working directory and branch name.
When a user describes system behavior they haven't personally verified ("it does X", "it works by Y"), ask whether this has been validated before building on it.
When proposing a solution with 3+ components, stop and ask whether a 1-component version would suffice first.
When writing MR descriptions, re-read the current branch diff before submitting — do not reuse the description from creation time if scope has changed.
When creating commits during implementation, batch all changes and organize at the end only if the user hasn't requested upfront commit planning — otherwise propose the commit plan first.
When editing a skill file, run `pwd` mentally and verify the path is the source repo, not the cache, not a different branch.
When the user says "continue" after an interruption or compaction, re-read the last 2-3 tool results before resuming — do not assume context from memory.
When Lucas provides feedback on a skill's output quality ("not great", "horrible", "fix it"), treat it as a correction requiring skill-level fix, not just output-level retry.
When parallel agents are dispatched and one fails, do not silently skip it — report the failure and re-dispatch or explain why it's acceptable to skip.
When a session involves creating files in multiple locations (cache, source, temp), maintain an explicit list of what was written where and present it at the end.
After finishing a skill invocation, check whether the output would be visible to the user or buried in a tool result block — print key results directly.
When building a new skill, test it end-to-end in the same session before declaring it done — "created the files" is not "it works."