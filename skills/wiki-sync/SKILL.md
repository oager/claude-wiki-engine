---
name: wiki-sync
description: >
  End-of-session memory checkpoint. Reviews what was learned this session for durable,
  ingest-worthy findings and files them via /wiki-ingest, then verifies the MEMORY.md index is
  current. Use at the end of substantive work, or on "sync", "checkpoint memory", "save what we
  learned", "wrap up".
---

# /wiki-sync -- Memory Wiki Checkpoint

Lightweight end-of-session sweep so durable knowledge is not lost. Delegates the actual filing to
`/wiki-ingest` (the single ingestion engine); this skill is the *review + checkpoint*.

## Steps
1. **Review the session** for DURABLE, reusable findings per the eligibility gate in
   `memory/schema.md`: post-incident lessons, root causes, decisions, reusable patterns/gotchas, or
   facts you will reference again. Skip routine/ephemeral output (status, one-off scans, recaps).
2. **Surface candidates (gated)** -- list them tersely: "Ingest candidates: <one line each> -- file
   these? (y / pick / skip)". Do NOT write without the user's nod (conservative: cheaper to miss
   than to pollute).
3. **Ingest approved** -- for each, invoke **`/wiki-ingest`** (it owns the page write, routing,
   MEMORY.md index line, Related footer, and log entry per `schema.md`). Do not reimplement it.
4. **Index integrity** -- confirm every page touched this session is referenced in `memory/MEMORY.md`
   (the `wiki-index-check` hook flags misses); refresh `overview.md` if a theme/state changed.
5. **Report** -- "Ingested N (...); index OK" or "nothing durable this session".

## Notes
- On-demand version of the CLAUDE.md "proactively ingest -- don't wait" rule.
- Content lives on disk in `memory/`; `/wiki-ingest` + `schema.md` govern quality.
