# DATA_CONSUMERS.md skeleton (copy, then fill as you probe)

Facts here are SHARED: true for every sweeper. Personal access notes (host aliases, shell quirks)
go in the personal layer, never here.

```markdown
# DATA_CONSUMERS.md — producer → seam → consumer map (for /ripple)

Hint, not verdict: every edge is live-verified before it is acted on.

## Profile

| Field | Value |
|---|---|
| Repos | `<org/repo>` — live checkout `<path or host:path>`, services run `<branch>`, PR/MR base `<base>`, change gate `<direct / PR-only / partner-owned>` |
| Runs on | `<host / platform / cloud>`; jobs scheduled by `<family>`, listed with `<command>` as user `<owner>` |
| Deployed copies / live stores | `<source> → <copy or store>` (how to diff) |
| Authority path | `<dirs/modules that decide, trade, deploy, bill or move money>` |
| Grep excludes | `<data/archive/cache dirs never to recurse into>` |
| Verify | tests `<command>` · smoke `<command in the real env>` |
| Partner record | `## Partners` below, or `<path>` when it lives elsewhere |

## Sweep watermark

| Repo | Last-swept commit | Date | Swept by |
|---|---|---|---|
| `<org/repo>` | `<sha>` | YYYY-MM-DD | `<name>` |

## <Seam type> (one section per seam type in use: endpoints, state files, tables, prompts, jobs…)

| Producer | Seam | Consumers (file:line) |
|---|---|---|

## Categories checked, no consumers found (nulls EXPIRE after 30 days → unknown)

| Category | Verdict | Last probed |
|---|---|---|
| `<taxonomy category>` | none (probed) | YYYY-MM-DD |

## Sanctioned consumption patterns

- `<e.g. consume X through its API, never read its DB directly>`

## Partners

### <Name or vendor>
- **Kind:** teammate / partner / vendor-API / automated job
- **Owns:** …
- **Where their work runs:** repos, branches, working trees, schedulers, owning user
- **What discover diffs:** …
- **Flag channel:** …
- **Never touch:** …
```
