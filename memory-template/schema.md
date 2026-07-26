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
- Index line = **a link + a one-line summary**: `- [Title](file.md) — summary`. **No character cap.**
  The test is a role test, not a count: the line exists to help you decide *whether to open the page*,
  never to substitute for reading it. If a line contains the finding itself, that detail belongs on
  the page. (Karpathy specifies "a link, a one-line summary"; Anthropic's memory guidance says "one
  line per entry, move detail into topic files". Neither states a character count — a `≤150` cap
  shipped here through v0.3.3 was invented, and in practice ~95% of entries violated it, so it only
  ever produced false lint findings.)
- **Organize `MEMORY.md` into `##` sections by category** once it outgrows a single screen — Karpathy
  specifies an index *"organized by category (entities, concepts, sources, etc.)"*, and Anthropic's
  structure guidance agrees: *"organized sections are easier to follow than dense paragraphs."* This
  is a **routing/scannability** win, not a token one (the whole file still loads) — don't evaluate it
  as a cost saving. Pick categories that fit your domain; the simplest scheme mirrors the routing
  folders (Concepts & lessons · Sources · Entities · Synthesis), and a large `concepts/` set is worth
  splitting thematically. Keep placement **derivable** (folder + tags) so ingest never has to guess,
  and apply any bulk re-section **programmatically with a before/after assertion that the set of
  index lines is unchanged** — hand-editing an index silently drops entries.
- Dates absolute (`2026-06-16`), never relative.
- Frontmatter (keep consistent — a missing field can silently drop the note from queries):
  ```
  name: <title>
  description: <one sentence>
  type: feedback | reference | project | concept
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

**Corrected in v0.4.0.** Through v0.3.3 this section claimed a read-the-whole-index approach *"breaks
down past ~100–200 pages"*. That **inverted** the source. Karpathy's gist, verbatim:

> "The LLM reads the index first to find relevant pages, then drills into them. **This works
> surprisingly well at moderate scale (~100 sources, ~hundreds of pages)** and avoids the need for
> embedding-based RAG infrastructure."

Same subject — reading the whole index at that scale — opposite verdict. The likely origin of the old
figure is "~100 **sources**, ~hundreds of **pages**" collapsed into one number with the units lost.
**No hard page ceiling is stated anywhere in the gist.** If you are in the hundreds of pages, you are
inside the range the pattern is documented to work in; measure a real cost before restructuring.

**The escape hatch is search, not surgery.** Per the gist: *"at small scale the index file is enough,
but as the wiki grows you want proper search"* → [qmd](https://github.com/tobi/qmd), a local hybrid
BM25/vector search over markdown with LLM re-ranking, shipping both a CLI and an MCP server. Reach
for that before splitting the index, and before capping summary length (a length cap is lossy and
buys little; see Page conventions).

**Don't confuse this with Anthropic's auto-memory limit.** Claude Code hard-limits its *auto-memory*
index — *"the first 200 lines of `MEMORY.md`, or the first 25KB, whichever comes first"*, with the
remainder **silently dropped at session start** — and the runtime warns/errors on write near it. That
governs `~/.claude/projects/<slug>/memory/MEMORY.md`. A wiki that Claude reads via a `CLAUDE.md`
instruction with the Read tool is **not** subject to it. Know which of the two you are looking at
before acting on a size number: they obey different rules.
