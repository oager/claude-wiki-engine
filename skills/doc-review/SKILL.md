---
name: doc-review
description: >
  Review and clean the memory wiki — find stale content, duplicates, dead weight, broken links,
  orphans, and frontmatter gaps; propose fixes; apply only what you approve. Also the wiki "Lint"
  operation that /wiki-ingest lint delegates to. Triggers: "clean up the wiki", "audit memory",
  "docs are getting stale".
---

# /doc-review — Memory Wiki Review & Cleanup

Reviews memory wiki files, identifies issues, proposes changes, and applies only what's approved.
**Read everything before judging anything** — no edits until the full analysis pass is complete.

## Step 0 — Scope
| Arg | Files reviewed |
|-----|---------------|
| (empty) / `memory` | the `memory/` wiki |
| `all` | `memory/` + a repo `.md` scan (READMEs, `docs/`) |

Read `memory/schema.md` FIRST — it defines the ingestion policy, tag vocabulary, link conventions,
and supersession rule that Pass G enforces. **Never edit `memory/raw/` or `memory/raw/archive/`** —
skip them. List all files in scope and report the count before reading.

## Step 1 — Read ALL files in full
Do not skip any file. Do not form opinions yet. This is the most important rule in this skill.

## Step 2 — Analysis passes (run all mentally before reporting)
- **A · Staleness** — content true when written but no longer: outdated counts/versions/paths, "just fixed" notes now old, dead cross-references. Quote it, say why, propose the fix.
- **B · Duplicates** — same substantive info in 2+ places. Name the canonical home; propose removing/one-lining the copy. (Don't flag deliberate cross-references or differing-detail copies.)
- **C · Dead weight** — content with no future signal. Propose remove/collapse. **Never remove** durable lessons, postmortems, root causes, or active rules.
- **D · Compress** — verbose prose shortenable losslessly. Secondary; never compress exact values/params/numbers. When in doubt, leave it.
- **G · Wiki integrity** (enforces schema.md). *Structural checks — cheap, mechanical:*
  - **Orphans** — pages with no inbound `[[wikilinks]]`; propose 2–4 `Related:` links or merge. (Hub files MEMORY.md/log.md/schema.md/overview.md exempt.)
  - **Broken links** — `[[name]]` with no matching `name.md`; propose the right target or removal.
  - **Frontmatter** — a page missing `tags:`/`updated:` is silently dropped from queries; propose additions. Also flag fields nested under a `metadata:` key — queries read those as `metadata.*`, so the page drops out just as silently.
  - **Expiry** — `expires:` in the past → MARK STALE with a pointer header; **do not delete**.
  - **Index length is NOT a check** — there is no character cap (removed v0.4.0). Flag a summary only if it fails the role test: it contains the finding itself instead of helping you decide whether to open the page.
- **H · Semantic integrity — run this FIRST when time is limited.** Karpathy's lint list is entirely
  semantic and mentions formatting nowhere; a pass returning dozens of formatting findings and zero
  contradictions is aimed wrong. These are where the real defects live:
  - **Contradictions** — two pages asserting incompatible facts (counts, verdicts, causes, "X does" vs "X does not"). Highest-value check and the easiest to skip, because both sides read as confident prose. Quote both, say which is ground-truth-verified, propose the fix on the wrong one — never silently overwrite; note the reversal explicitly.
  - **Stale claims** — assertions a newer source or later page has superseded (distinct from Pass A: page-vs-page, not page-vs-world).
  - **Concepts without a page** — a term used across ≥2 pages as if established, with no page defining it. Propose creating it, or pointing at the page that already covers it.
  - **Data gaps** — claims resting on a number, quote, or threshold with no cited source, especially ones that steer decisions. Propose verifying against the primary source. **A rule is a hypothesis too**: if a convention cites no source and the corpus violates it lopsidedly, the rule is the likely defect, not the corpus.

## Step 3 — Present findings
Group by pass; for each: `[CATEGORY] file:line` / Current / Proposed / Risk (low|med). End with a summary table, then ask: "Which categories should I apply?"

## Step 4 — Apply approved changes
One file at a time; report "Updated <file> — N changes." For expired/superseded pages, mark stale with a pointer — never delete. Update the `MEMORY.md` index entry if an indexed file changed.

## Rules
- Read-first, always. Conservative by default — when uncertain, flag rather than remove.
- Supersession, not deletion (per schema.md) — never auto-delete a durable lesson or postmortem.
- `raw/archive/` is immutable; skip `raw/` entirely.
- Frontmatter completeness isn't optional — missing `tags:`/`updated:` breaks queries.
- No auto-apply — gate on confirmation. Preserve exact values (numbers, IDs, paths, timestamps).
