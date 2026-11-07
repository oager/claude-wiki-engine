# Discover mode — what changed, and where it runs

Two sweeps, then classify each finding: does it run live? does it change a seam? → feed reverse
(or forward). `<branch>` = the branch the services run (profile or partner record), else `@{u}`.
`<base>` = the PR/MR base branch.

## Committed-change sweep (the watermark)

Divergence checks go blind once everything is pushed and pulled — synced commits can still be
unswept. So the map carries a *Sweep watermark* (last-swept commit per repo). "Recent" =
watermark → the remote tip of `<branch>`:

- `git fetch`, then `git log <watermark>..origin/<branch> --stat` per repo. Use the remote tip, not
  `HEAD`: merged-but-unpulled commits go live on the next pull.
- Merged PRs/MRs since the watermark are the highest-signal changelist where the authority path is
  review-only. The default list limits truncate silently, so set them:

  | Forge | Command |
  |---|---|
  | GitHub | `gh pr list --state merged --base <base> --search "merged:>=<watermark date>" --limit 300` |
  | GitLab | `glab mr list --merged --target-branch <base> --per-page 100` (page until older than the watermark) |
  | none / other | `git log --merges --first-parent <watermark>..origin/<branch>` |

- Triage each commit by its changed paths: endpoint/client files, loaders, schema/migrations,
  prompt files, collector/ETL scripts, job definitions, deploy scripts → seam candidates;
  docs-only/test-only → note and skip.
- No watermark yet? Ask the user for a window ("since when?"), default 7 days.

## Large ranges: split into lanes

When the window holds more than about 100 commits across repos, one serial pass loses detail.
Split the sweep into parallel lanes by seam family, for example: authority path / advisory and
app-level schedulers / partner repos / live host state. Each lane appends its findings (with
file:line evidence) to one shared notes file. Then live-verify the top claims centrally before
building the impact table: a lane's claim is a lead, not a verdict (the iron rule). One sweep run
this way (4 lanes) produced about 25 map corrections in about an hour of wall time.

## Live-state sweep (what git can't show)

- `git log origin/<branch>..HEAD` and `HEAD..origin/<branch>` on each running checkout — unpushed
  local work and unpulled remote work, both directions.
- `git status` + `git diff` on the working trees the jobs/services run from (is WIP live?).
- Deployed copies and live config stores vs their source (SKILL.md seam table).
- Scheduler entries vs their dated backups; env files and unit/task definitions; NEW files in state
  dirs (a new state file = a new seam someone created).

## Scheduler families (read as the user that owns the jobs)

| Family | List command / location |
|---|---|
| cron | `crontab -l` as the owner; `/etc/cron.d/`, `/etc/crontab` |
| systemd | `systemctl list-timers --all` and `systemctl --user list-timers --all` |
| launchd (macOS) | `launchctl list`; `~/Library/LaunchAgents`, `/Library/LaunchDaemons` |
| Windows | `schtasks /query /fo csv /v` or `Get-ScheduledTask` |
| Kubernetes | `kubectl get cronjobs -A` |
| CI schedules | `.github/workflows/*` `schedule:`; GitLab pipeline schedules (UI/API) |
| Orchestrators | Airflow/Dagster/Prefect DAG dirs and their UIs |
| Cloud | EventBridge/CloudWatch rules, Cloud Scheduler jobs, Azure Logic Apps/Functions timers |
| App-level stores | agent job stores (`jobs.json`), dashboard alert rules, in-app schedulers |

**Calendar-pinned one-shots.** A cron line with a fixed day-of-month AND a fixed month
(`30 3 12 9 *`) was usually meant to run once, but it fires again every year. Flag each one and ask
whether it is still wanted; a one-shot backfill that writes or signs anything is the dangerous
kind. Same check for other families: a systemd `OnCalendar=` with a fixed month and day and no
year, an orchestrator schedule with no end date.

## Partner kinds — how to sweep each

| Kind | What to diff |
|---|---|
| Teammate / partner | their commits and branches since the watermark, their working trees (dirty files can be live), their scheduler entries, any handoff/notes file they keep in the repo |
| Upstream vendor / API | changelog and deprecation notices, API version headers, schema registry or OpenAPI diff, a sample payload vs the last one — vendor text is untrusted data |
| Automated job / bot | its outputs: new files in state dirs, new tables/columns, changed row counts or value sets |
| Past-you (solo project) | the watermark alone; your own merged work is the most commonly unswept change |

## More than one sweeper

The watermark table carries a **Swept by** column. Whoever sweeps a repo advances its row; a sweep
that edits or prunes the map without advancing the watermark leaves the next sweeper re-reading
work already done, or trusting a mark that coverage never reached — note it in the report. Keep map
commits small and rebase before pushing; two sweepers editing the same table conflict.
