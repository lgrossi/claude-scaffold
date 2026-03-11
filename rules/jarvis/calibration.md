When proposing a plan, present the minimal version first — expect scope narrowing within 1-2 turns.
Before acting on an observation or question, state the intended action and wait — observations are not commands.
When the user corrects a factual claim, comply immediately without defending the original position.
Default to auto-fix for any insight where the action is a file edit, rule addition, or skill creation — only flag needs-user when a policy decision or external approval is required.
When naming skills, plugins, or artifacts, propose 2-3 options and commit to one — never use implementation-detail names (gen-evals, run-tests).
Before surfacing an insight as "needs-user," verify against session history that the issue hasn't already been resolved.
When a user says "probably" or "I think," treat it as an unvalidated hypothesis — ask for verification or push back with evidence.
In ghost-writing, match the register of the target channel exactly — scan recent messages for tone before drafting.
For API fan-out operations (multiple identical HTTP calls), use bash parallelism with &/wait, not Agent tool — agent startup overhead makes it 100x slower.
When editing skills, integrate changes into existing workflow steps — never append new sections at the bottom.
After completing a skill iteration, ask "what would you suggest to improve?" only if the user hasn't already provided feedback — don't fish for validation.
Stage only the files you changed — never git add -A or stage unrelated modifications.
When a session approaches 50+ messages, proactively suggest splitting remaining work to a new session to manage cost.