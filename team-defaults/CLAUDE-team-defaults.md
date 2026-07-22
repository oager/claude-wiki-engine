<!-- BEGIN team-working-defaults (managed block — safe to remove or replace as one unit) -->
# Team Working Defaults

Shared conventions for how Claude works on this machine. Portable — no machine-specific paths,
no project-specific lore. Append this whole block to the global `CLAUDE.md`; remove it as a unit
to opt out.

## Response style
Default to a terse, high-signal style for chat, status updates, quick answers, and analysis:
drop filler and hedging, lead with the answer. But NEVER omit technical substance — code,
numbers, file paths, and reasoning always stay. Use normal prose only for formal docs or when
the user explicitly asks for it.

## Coding behavior
- **Before** writing, reviewing, or refactoring any code → apply `/karpathy-guidelines` (it is
  `disable-model-invocation`, so read the SKILL.md and follow it directly): read before you
  write, inspect real data, simplest thing first, one change at a time, verify assumptions
  explicitly.
- **After** any bug fix → `/error-harden` then `/regression`: enumerate the failure modes and add
  handling/alerts, then run the regression suite before treating the fix as done.

## Delegate-down (model tiering)
Keep the MAIN loop on the strongest model for judgment — decisions, irreversible calls, plans,
synthesis, and the final review. Auto-defer bounded, low-judgment subtasks to a cheaper-model
subagent:
- search / "where is X" / multi-file reads where only the conclusion matters → an `Explore` /
  `code-explorer` agent
- mechanical or bulk edits, build & lint fixes, formatting → a build-resolver / `code-simplifier`
  agent
- log/data parsing, bulk lookups, doc fetches, first-pass classification → a `general-purpose`
  agent
- first-pass code review → `code-reviewer` (the main loop does the final adversarial verify)

When unsure, delegate and escalate back only if the cheap pass falls short. Don't delegate a
trivial one-shot where the round-trip costs more than doing it inline.

## Sub-agent fan-out
Fan out to parallel subagents when a task has ≥3 independent non-trivial subtasks, or is a large
parallelizable sweep (multi-file review, multi-symbol analysis, cross-module audit). Never fan
out for trivial or strictly sequential work. If you're on a metered / pay-as-you-go API path
(rather than an included subscription), say so and confirm before a large fan-out — parallel
agents multiply token spend.
<!-- END team-working-defaults -->
