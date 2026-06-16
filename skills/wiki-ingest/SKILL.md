---
name: wiki-ingest
description: >
  The canonical ingestion engine for this Claude memory wiki (memory/), implementing Karpathy's
  LLM-wiki pattern. Use to file a source / finding / research answer / lesson into the wiki as a
  cross-linked, tagged page. Invoke as /wiki-ingest (process the raw/ inbox) or /wiki-ingest <thing>
  (ingest something handed in now). /wiki-ingest lint delegates to /doc-review.
---

# /wiki-ingest

The one engine that adds knowledge to the memory wiki. Reads the rules from `memory/schema.md` and
follows them. Manual entry point; other memory / lesson-capture flows may delegate to it.

**Read `memory/schema.md` first** — it is the source of truth for the ingestion policy, page/link
conventions, routing, supersession, and guardrails. This skill is the *procedure*; schema.md is the *policy*.

---

## Modes

- `/wiki-ingest` (no args) — process every pending file in `memory/raw/` (the inbox). Skip `README.md` and `archive/`.
- `/wiki-ingest <thing>` — ingest a source handed in now: a pasted finding, a research answer, a file path, or a URL's fetched content.
- `/wiki-ingest lint` — passthrough to `/doc-review` (the Lint operation; do not reimplement here).

---

## Ingest procedure (per source)

1. **Eligibility** — check the ingestion policy in `schema.md`. If the source is routine/ephemeral
   (status updates, one-off scans, chat recaps, transient task state), STOP — don't ingest. If it is
   only partly durable, extract just the durable part.

2. **Placement** — apply the placement rule in `schema.md`: does this generalize beyond the one
   situation that produced it (→ this wiki), or is it one-off project detail (→ that project's own
   notes)? When unsure, leave it out.

3. **Route to a subfolder** (schema routing rule, decided in order):
   1. factual summary of one source → `memory/sources/`
   2. about a named person/tool/service/system → `memory/entities/`
   3. reusable lesson/pattern/rule → `memory/concepts/`
   4. synthesized answer from multiple pages → `memory/synthesis/`
   (Legacy notes already in `memory/` root stay where they are.)

4. **Ingest-as-discussion (ALWAYS, anti-hallucination)** — before writing, surface a TERSE summary:
   "Takeaways: … | Filing as: `concepts/foo.md` | tags: …". Shown even for clear cases so a misread
   is caught before it propagates across links. For a bulk `raw/` run, batch the summary.
   - Clear, eligible cases: show, then write.
   - Borderline (placement unclear, possible contradiction, low confidence): PAUSE and ask.

5. **Write the page** — frontmatter per schema.md (`name`, `description`, `type`, `tags`, `updated`,
   `source:` if from a raw file, `expires:` if time-bound). Keep source summaries FACTUAL;
   interpretation goes in a separate `concepts/` page. If it contradicts an existing page, note it
   explicitly — never silently overwrite. If it supersedes a page, mark the old one stale with a
   pointer header — never delete.

6. **Index** — add or refresh the `memory/MEMORY.md` line: `- [Title](subfolder/file.md) — ≤150-char summary`.

7. **Cross-link** — append a `Related: [[a]] · [[b]] · [[c]]` wikilink footer (≤4 highest-relevance neighbors).

8. **Log** — append to `memory/log.md` (bottom): `## [YYYY-MM-DD] ingest | <Title>` + one-line note.

9. **Archive** — if the source was a file in `memory/raw/`, MOVE it to `memory/raw/archive/`
   (immutable, kept forever). If it was pasted/typed inline, no archive step.

---

## Notes

- `raw/` accepts `.md/.pdf/.txt/images`. Video → drop a transcript instead.
- Never modify files in `raw/archive/` — they are the immutable source-of-record.
- Do NOT auto-delete or decay anything. Supersession only (see schema.md).
