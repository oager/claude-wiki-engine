# Universal surface taxonomy — where consumers hide

The seam table in SKILL.md says *how* consumers break; this says *where they hide*. On a project
with no map (or a map with gaps), walk EVERY category: **probe first, ask only what probes can't
see.** Each category ends with a verdict — `found` / `none (probed <date>)` / `unknown (asked)`.
A category with no verdict is the blind spot.

**A null expires.** A `none (probed <date>)` older than 30 days at sweep time is `unknown`:
re-probe it or carry it as an open gap, never quote it as coverage. A watermark shows staleness
through its commit hash; a dated null hides it.

| Category | Question to answer | Cheap probe |
|---|---|---|
| Repo inventory | Which repos WRITE this project's inputs or deploy into it — not only the ones you habitually read? | the job/unit owners of every input path; deploy scripts' source repos; package/dependency manifests. A repo with no watermark row reads identically to a clean sweep |
| UI / dashboard | Is there a UI that shows (or should show) this data? | glob `portal/ dashboard/ static/ web/ app/ grafana/`; grep client `fetch(`/route strings; the live dashboard store, not only repo JSON |
| LLM pipeline — input | Does any LLM *read* this (prompt context, gather file, retrieval index)? | grep prompt files (`*.txt`, `*.md`, `prompts/`, `system_prompt`), agent/gather dirs, model-client imports, scheduler-stored prompts |
| LLM pipeline — authority | Does anything that *decides, trades, deploys, bills or moves money* read it? (highest gate) | the repo's change-gate doc (CLAUDE.md, CONTRIBUTING, CODEOWNERS); grep the decision/execution dirs |
| Messaging / alerts | Digest, chat post, email, webhook, pager or watchdog that voices or watches it? | grep `webhook discord slack telegram smtp notify alert pager`; scheduled scripts that post |
| Scheduled consumers | Jobs/timers/services that read it downstream (graders, scorecards, recalcs, ETL)? | the profile's scheduler list commands — see the scheduler families in discover.md. Read as the user that OWNS the jobs; another user's view is false |
| Derived stores | Tables/files/caches/indexes computed FROM it (walk the derivation chain to ITS consumers too) | grep the table/file/route name for readers AND writers; grep the formula for re-derivations; views, materialized views, dbt models |
| Cross-project | Do OTHER repos/services consume it? | **probe the PRODUCER side**: enumerate this project's egress — exports/shares, non-loopback listeners, live remote connections, DB client addresses, tunnel/ingress routes, outbound webhooks, published packages/APIs, co-located repos. Bounded and fast, where grepping every sibling repo is not. Sibling grep only for a named suspect |
| Tests / fixtures | Do tests encode the OLD shape? (fixtures pass together with the bugs) | grep `tests/` `spec/` `__tests__/` for the seam name |
| Docs / contracts | Do docs, API specs, prompt contracts or READMEs assert the old behavior? | grep `docs/`, OpenAPI/proto/GraphQL schemas, prompt files |
| Memory / wiki | Do notes, project memory or a wiki assert the old shape? (knowledge pages are consumers too) | grep the project memory/notes dir and any cross-project knowledge store |
| Partner / external | Partner-private tools, third-party subscribers, customers' integrations? | **can't probe — ASK** |
| Anything else | "What else touches this that I can't see from here?" | **ASK** — on first bootstrap, and whenever categories come up suspiciously empty |

## Bootstrap (no map yet)

This walk IS the map derivation. Write `DATA_CONSUMERS.md` from
[map-template.md](map-template.md), structured by these categories, keeping empty ones visible as
`none (probed <date>)` so future runs see what was checked, not just what was found. Fill the
Profile block as you probe; ask the user only for fields no probe can answer (who owns what,
change gates you can't read, partners, flag channels). Then set the watermark to the HEAD you
examined — the first discover run starts from there.
