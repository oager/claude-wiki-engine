# Memory Index

The catalog of this wiki — one line per page. Read at session start. `/wiki-ingest` keeps it current.

Each entry is a link + a one-line summary, long enough to decide whether to open the page and no
longer — there is no character cap. Once this outgrows a single screen, split it into `##` sections
by category (see schema.md "Page conventions"); `/wiki-ingest` then files new lines by folder + tags.

- [Overview — Front Door](overview.md) — START HERE: narrative map of themes + current state.
- [Memory Wiki Schema](schema.md) — the constitution: ingestion policy, page/link conventions, supersession rule.
- [Activity Log](log.md) — append-only record of ingests / lints / material changes.
