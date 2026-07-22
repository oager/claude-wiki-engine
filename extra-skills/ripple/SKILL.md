---
name: ripple
description: Consumer-impact sweep when data or interfaces change. Use whenever new data lands (table, column, endpoint, collector, metric, feed) or existing data changes shape/semantics/path/cadence — by us or by Rich — and we need to know which surfaces (portals, dashboards, analyst, deepdesk, LLM prompts, digests, crons, scorecards, docs/memory) break, go stale, or could benefit. Also for "what did Rich change?" (git divergence, live uncommitted WIP, cron diffs). Modes — forward (new data → opportunity), reverse (changed data → blast radius), discover (partner changes). Report-first gated impact table, then executes picked rows. Trigger on "who reads/uses this", "what breaks if…", "blast radius", "ripple", any schema/rename/shape change — even when no portal or consumer is named explicitly. NOT for repo onboarding (/repo-scan) or post-bugfix hardening (/error-harden).
type: skill
---

# /ripple — Consumer-Impact Sweep

One engine, two directions through the same map: **forward** (new data → who *should* consume
it) and **reverse** (changed data → who *breaks or goes stale*). Plus a **discover** preamble
(what did the partner change → classify each finding → run reverse on it).

**Report-first**: the deliverable is a gated impact table. Execution only after the user picks
rows; big builds delegate to `/tiered-build`, small ones are direct edits under the repo's
change gates.

## Iron rule: registry is a hint, grep is the verdict

Each project carries `docs/DATA_CONSUMERS.md` (next to its sources-of-truth doc) mapping
producers → seams → consumers. Load it as a warm-start, then **live-verify every edge you act
on** — grep the actual SPA fetches, loaders, SQL, prompt files. A stale map may make you slow;
it must never make you wrong. No map in the repo? Walk the universal surface taxonomy (below)
to derive one — that walk IS the bootstrap — and write the doc as part of Step 6.

## Seam types & their characteristic failures

Every propagation incident happens at a seam. Know the failure mode before you sweep:

| Seam | Consumers found by | Characteristic failure |
|---|---|---|
| HTTP endpoint | grep SPA/clients for the route | Shape change kills a frontend panel SILENTLY; HTTP-200 smoke passes a dead panel |
| State file (JSON sidecar) | grep loaders for the filename/env var | Consumer reads stale/absent forever; nobody notices |
| DB table/column | grep SQL + ORM for table/column | Semantics misread (a value's *meaning* changed, not its shape) — consumers compute confidently wrong numbers |
| Prompt contract | grep prompt files for the input filename | New input file with no prompt paragraph = the LLM ignores it or hallucinates a read |
| Framework state key | the state TypedDict/schema definition | Undeclared key silently dropped in transit; all readers see None |
| File path/rename | grep for old path AND glob fallbacks | Hardened trading path survives; advisory consumers break quietly |
| Live-vs-git | `git status` on the box working tree | Crons run WORKING-TREE files: uncommitted WIP can be LIVE, and the committed version the regression. Never assume uncommitted = inactive |

## Universal surface taxonomy — makes this runnable on ANY project

The seam table above says *how* consumers break; this table says *where consumers hide*. On a
project with no map (or a map with gaps), walk EVERY category: **probe first, ask the user
only what probes can't see.** Each category ends with a verdict — `found` / `none (probed)` /
`unknown (asked)`. A category with no verdict is the blind spot.

| Category | Question to answer | Cheap probe |
|---|---|---|
| Portal / dashboard | Is there a UI that shows (or should show) this data? | glob `portal/ dashboard/ static/*.html grafana/`; grep SPA `fetch(`/api routes |
| LLM pipeline — input | Does any LLM *read* this (prompt context, gather file, capture)? | grep prompt files (`*.txt`, `prompts/`, `system_prompt`), agents/gather dirs, model-client imports |
| LLM pipeline — authority | Does anything that *decides or trades* read it? (highest gate) | repo change-gate doc (CLAUDE.md); grep the trading/decision dirs for the seam |
| Messaging / alerts | Digest, Discord/Slack, webhook, watchdog that voices or watches it? | grep `webhook discord telegram notify alert`; cron scripts that post |
| Scheduled consumers | Crons/timers/services that read it downstream (graders, scorecards, recals)? | `crontab -l`, `systemctl list-timers`, scripts/ + cron/ dirs |
| Derived stores | Tables/files/caches computed FROM it (walk the derivation chain to ITS consumers too) | grep the table/file/route name repo-wide for readers AND writers |
| Cross-project | Do OTHER repos/bots in the portfolio consume it? | grep the seam name across sibling workspaces (portfolio index = the repo directory table in global CLAUDE.md) |
| Tests / fixtures | Do tests encode the OLD shape? (fixtures pass together with the bugs) | grep `tests/` for the seam name |
| Docs / contracts | Do docs, prompt contracts, or READMEs assert the old behavior? | grep `docs/` + prompt files for the seam name |
| Memory / wiki | Do project-memory or global-wiki pages assert the old shape? (knowledge pages are consumers too) | grep the project memory dir + `~/.claude/memory/` for the seam name |
| Partner / external | Partner-private tools, exposed endpoints, third-party subscribers? | **can't probe — ASK the user** |
| Anything else | "What else touches this that I can't see from the repo?" | **ASK** — on first bootstrap, and whenever categories come up suspiciously empty |

Bootstrap: on a repo with no `docs/DATA_CONSUMERS.md`, this walk IS the map-derivation — write
the doc structured by these categories, keeping empty ones visible as `none (probed <date>)`
so future runs see what was checked, not just what was found.

## Step 0 — Classify

- **forward**: new data/table/endpoint exists → opportunity sweep.
- **reverse**: existing data changed (shape, semantics, path, cadence) → blast radius.
- **discover**: "what did <partner> change?" / "run it against recent changes" → two sweeps,
  then classify each finding:

  **Committed-change sweep (the watermark):** divergence checks go blind once everything is
  pushed and pulled — synced commits can still be unswept. So `docs/DATA_CONSUMERS.md` carries
  a *Sweep watermark* (last-swept commit per portfolio repo). "Recent" = watermark→HEAD:
  - `git fetch` + `git log <watermark>..HEAD --stat` per repo; merged PRs since the watermark
    (`gh pr list --state merged`) are the highest-signal changelist where trading-path = PR-only
  - triage each commit for seam relevance by its changed paths: endpoint/SPA files, loaders,
    schema/init.sql, prompt files, gather/collector scripts, cron defs → seam candidates;
    docs-only/test-only → note and skip
  - no watermark yet (first run)? ask the user for a window ("since when?") and default to 7d

  **Live-state sweep (what git can't show):**
  - `log origin/main..HEAD` and `HEAD..origin/main` (divergence, unpulled work — both directions)
  - `git status` + `git diff` on box working trees (is WIP live? see seam table)
  - crontab vs its dated backups; `.env` / systemd unit diffs; NEW files in state dirs
    (a new state file = a new seam someone created)

  For each finding: does it run live? does it change a seam? → feed reverse (or forward) mode.

## Step 1 — Ground

1. Load `docs/DATA_CONSUMERS.md` (warm-start). No map → run the taxonomy bootstrap first.
2. Identify which seam(s) the change touches. One change often touches several.
3. Live-verify each seam's consumer list by grep (per the seam table). Add any consumer
   the registry missed — note it for Step 6.
3b. **Taxonomy completeness pass** (even with a map): walk the surface-taxonomy categories
   for this seam; any category the map has no row for gets probed-or-asked NOW. The map
   tells you what's known; the taxonomy tells you what could be missing.
4. **Probe for existing equivalents** before proposing anything new: does a capture, panel,
   check, or pipeline already do this? (One probe here routinely kills a whole redundant
   workstream.) State what exists and where.
5. Confirm current architecture direction: recently retired couplings, sanctioned
   consumption patterns (e.g. "consume-as-a-service, never re-embed"). A new edge that
   reverses a fresh retirement decision is a design bug, not a feature.

## Step 2 — Impact table

One row per consumer surface (including "none — checked"):

| surface | seam | impact | evidence | gate |
|---|---|---|---|---|
| e.g. portal panel X | endpoint /api/y | **breaks** / **stale** / **opportunity** / none | file:line | advisory / trading-path / partner-owned |

Impact verdicts must carry evidence (file:line from Step 1's greps), not registry hearsay.

## Step 3 — Gate each row

- **Coupling**: does the fix/feature respect the sanctioned consumption pattern? Prefer the
  loosest edge that works (published state file > HTTP client > direct DB read > embedding).
- **Instrument fidelity**: ungraded/new data gets *narration and context* now; *authority*
  (gates, sizing, prominent UI, alerts) waits for scorecard/grading evidence. Say which side
  of the line each row is on.
- **Change class**: advisory/display → direct-commit; trading-path or unsure → PR-only;
  partner-owned surface → flag to partner, don't touch.

## Step 4 — Present & execute

Present the gated table with a recommendation per row; let the user pick (AskUserQuestion for
real forks). Execute chosen rows: multi-file builds → `/tiered-build`; small advisory edits →
direct, matching surrounding style. Never execute partner-owned rows.

## Step 5 — Verify (per seam type — this list is the paid-for part)

- Endpoint changed → grep its frontend/client consumers and **exercise them** (DOM/render
  check, not HTTP 200).
- New LLM input file → its prompt-contract paragraph exists and matches the actual fields.
- New framework state key → declared in the state schema, or nested under an existing key.
- Anything deployed → **real-env smoke** in the real venv/env with real files (fixtures pass
  together with the bugs; a missing dep only surfaces live).
- Data not flowing yet → smoke the **empty path** explicitly (valid empty artifact, benign
  consumer output, no crash) and note when the populated path gets verified.
- Restarted a service → poll the port; "unit active" ≠ port bound.

## Step 6 — Bank

- Registry self-heal: add every consumer/seam discovered that wasn't in
  `docs/DATA_CONSUMERS.md`; correct anything wrong. Commit the doc (it's advisory).
- **Advance the sweep watermark**: set each swept repo's entry to the HEAD you examined
  (commit + date). Skipped a repo this run? Leave its watermark alone — the next discover
  run picks up exactly where coverage actually stopped, not where you wish it had.
- Stale docs/memory found by the sweep: **trivial** (one wrong line/claim) → correct inline
  now; **structural** (contradictions across pages, duplicated claims, multi-page drift) →
  hand the specific file list to `/doc-review` (it owns doc-hygiene method — scoped lint,
  never a full sweep from inside a ripple run).
- Durable lessons → project memory; cross-bot lessons → the promotion rule.
- Partner-owned findings → flag through the usual channel with evidence.

## Boundaries

- `/repo-scan` = onboarding a repo; `/ripple` assumes you know the repo and asks who consumes
  a specific seam.
- `/workspace-surface-audit` = agent-workspace hygiene; not data seams.
- `/error-harden` = after a bug is fixed; `/ripple` reverse mode is how you find the
  consumers that bug (or change) reached in the first place. They chain: harden the fix,
  ripple the seam.
- `/tiered-build` = execution engine for the big rows /ripple selects.
- `/doc-review` = doc-hygiene owner; /ripple *finds* seam-stale pages (taxonomy Memory/wiki +
  Docs rows) and hands structural rot to it scoped — it never runs a full sweep itself.
