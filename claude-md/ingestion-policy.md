## Memory Wiki

This config uses a curated **memory wiki** (`memory/`) following Karpathy's LLM-wiki pattern.

- **At session start**, read `memory/MEMORY.md` (the index) and `memory/overview.md` (the narrative map). Open individual pages when relevant.
- **Ingest durable knowledge proactively:** when you learn a reusable lesson, root cause, decision, or a fact you'll reference again, file it with `/wiki-ingest` — don't wait. Routine or ephemeral output does NOT go in the wiki.
- **`memory/schema.md` is the constitution** — ingestion policy, page/link conventions, supersession. `/wiki-ingest` and `/doc-review` enforce it.
- **Supersession, not deletion** — mark stale pages with a pointer to what replaced them; never delete durable lessons.
