# Agent Dispatch

## TeamCreate (bordered panels)
Use for agents that: write files, run builds/tests, live >30s, or need user-visible progress.
Examples: /develop workers, implementation tasks, long research.

## Standalone Agent
Use for agents that: read only, return a summary, live <30s.
Examples: Explore, grep-heavy research, quick analysis, acceptance checks.

## Bash Parallelism (not Agent)
For simple API fan-outs (N identical curl calls with different parameters), use bash `&`/`wait`, not the Agent tool.
Agent startup overhead (~7s each) makes it ~100x slower than native shell parallelism for stateless HTTP calls.
Proved in session b45f39d5: 18 parallel curl calls via bash = 1.56s; same via agents = 2+ minutes.

## Both
Always track via TaskCreate so TaskList is a full control plane regardless of dispatch mode.
Launch independent agents in parallel (single message, multiple Agent calls).
