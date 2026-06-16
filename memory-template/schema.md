---
name: Memory Wiki Schema
description: Conventions and operating rules for this Claude memory wiki — what gets ingested, how pages are formatted/linked, how lint and supersession work. The constitution; the /wiki-ingest and /doc-review skills enforce it.
type: reference
tags: [workflow-meta]
updated: 2026-01-01
---

# Memory Wiki Schema

This directory is a curated knowledge wiki following Andrej Karpathy's "LLM wiki" pattern: you
curate sources and ask questions; Claude summarizes, files, cross-references, and keeps the
bookkeeping. *"The editor is the IDE; the LLM is the programmer; the wiki is the codebase."*

## Layers

- `MEMORY.md` — the **index / catalog**. Every page = one `- [Title](file.md) — one-line summary`. Updated on every ingest.
- `overview.md` — the **narrative front-door**. Themes + current state; the cold-start orientation doc. Distinct from the catalog.
- `*.md` (+ typed subfolders) — the **wiki pages** (one topic each).
- `log.md` — **append-only activity log** (newest at bottom).
- `schema.md` — this file (the constitution).
- `raw/` — **manual-ingest inbox** (local scratch) + `raw/archive/` (processed originals, kept
  forever as immutable source-of-record). Accepts `.md/.pdf/.txt/images`; video needs a transcript first.

## Page routing

Legacy/loose notes may stay flat in the root. NEW ingested pages route into typed subfolders by this
deterministic rule (decided in order):

1. Factual summary of ONE source → `sources/`
2. About a named person / tool / service / system → `entities/`
3. Reusable lesson / pattern / rule → `concepts/`
4. Synthesized answer from multiple pages → `synthesis/`

`MEMORY.md` indexes everything regardless of folder (`[Title](concepts/foo.md)`).

## Operations

- **Ingest** — `/wiki-ingest` is the engine. Invoked manually or delegated from your own
  memory-sync / lesson-capture flows. Always surfaces the extracted takeaways + destination before
  writing (anti-hallucination).
- **Query** — ask a question against the wiki; a good answer can be filed back as a page (→ `synthesis/`).
- **Lint** — `/doc-review` (staleness, duplicates, dead weight, contradictions, orphans, broken links). Gated on approval.

## Ingestion policy (eligibility to become a page)

The wiki holds **durable, reusable knowledge** — not ephemera. Use this gate:

| Source | Ingest? |
|---|---|
| Post-incident lessons, decisions, root causes, research findings | YES — keep forever |
| A reusable pattern / rule / gotcha validated at least once | YES |
| Factual summary of an external source you'll reference again | YES (→ `sources/`) |
| Profile of a person / tool / system you work with | SELECTIVE — durable facts only |
| Routine status, one-off scans, chat recaps, transient task state | NO |

**Placement (global vs project):** a finding belongs in THIS wiki only if it's reusable beyond the
one situation that produced it — i.e. it generalizes across projects/contexts OR is a standalone fact
you'll reach for again. One-off, project-specific details stay in that project's own notes. **When
unsure, leave it out** — it is cheaper to miss a lesson than to pollute the wiki with noise that
later reverses.

## Page conventions

- One topic per page; lead with what it is + why it matters.
- Index line ≤150 chars: `- [Title](file.md) — summary`.
- Dates absolute (`2026-06-16`), never relative.
- Frontmatter (keep consistent — a missing field can silently drop the note from queries):
  ```
  name: <title>
  description: <one sentence>
  type: feedback | reference | project
  tags: [<from your controlled vocabulary>]
  updated: YYYY-MM-DD
  source: <raw/archive/file>   # only when ingested from a raw source
  expires: YYYY-MM-DD          # only on time-bound pages
  ```

## Anti-hallucination guardrails

The pattern's #1 failure mode is errors getting baked in as "facts" and propagating across linked
pages. Defenses:

- Keep source-summary pages FACTUAL — interpretation goes in separate `concepts/` pages.
- Cite `source:` provenance; the chain of links IS the trust signal (no numeric confidence scores).
- Flag uncertain claims rather than asserting them.
- When sources/findings contradict, note it explicitly — never silently overwrite.
- `/wiki-ingest` shows takeaways + destination before writing so a misread is caught early.

## Link conventions

- Page-to-page = wikilinks in a `Related:` footer, e.g. `Related: [[page-a]] · [[page-b]]` (cap ~4, relevance over volume).
- `MEMORY.md` keeps markdown `[Title](file.md)` links (must stay clickable everywhere).

## Supersession, not deletion

*"Old doesn't mean stale; don't decay mistakes."*

- A stale page is **marked stale with a header pointing to what replaced it**, and kept for history.
- NEVER auto-delete a durable lesson.
- Raw originals in `raw/archive/` are immutable.

## Scaling ceiling

A read-the-whole-index approach breaks down past ~100–200 pages. When this wiki exceeds ~150 pages,
revisit a hybrid (BM25 + vector) search instead of full-index reads.
