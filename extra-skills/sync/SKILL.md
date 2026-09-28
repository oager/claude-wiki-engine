---
source: claude-wiki-engine
name: sync
description: Close a session cleanly — write this project's handoff (~/.claude/handoffs/<key>.md), report git state and running work, triage the inbox, propose user-wide conventions, file global knowledge, push the vault. Add "and ship" to also commit and push the project repo.
disable-model-invocation: true
---

# Sync Memory & Status

Update all persistent memory and status files for the current project, then push the vault so both machines stay in sync.

## Step 0 — Collect

```bash
python3 ~/.claude/tools/session/close.py --cwd "$PWD"     # Windows Git Bash: python
```

One JSON object: `identity`, `handoff {path, exists, size_kb}`, `handoff_updated`, `sessions {me, registered, focus,
others}`, `updated_seen`, `legacy`, `git {dirty, dirty_count, unpushed, no_pr_branches, ci_pending}`,
`running {supported, procs, others_procs, via, reason}`, `drift`,
`inbox_untriaged`, `inbox_notes`, `repo_handoff`, `repo_sha`, `vault_sha`.
`identity.how == "ambiguous"` →
ask which project, re-run with `--project <key>`. Keep this `vault_sha`: it is recorded **before** this session's
push, which is exactly what the next `/preflight` diffs from.

## Step 1 — Write the handoff (the clean-close contract)

A clean close = the next session can start from the handoff alone, with nothing hidden in git, in running processes
or in the inbox.

**Concurrent /sync:** compare `updated_seen` (the handoff version this session last read or wrote) with
`handoff_updated` (the version on disk now), both from Step 0. Different → another session synced since this one last
looked: **merge** — keep their new Next up, Open items and Standing notes, add this session's, re-rank — never
rewrite over them, and say `merged with a concurrent /sync (<updated_by>)` in the report. `updated_seen` null and the
handoff exists → **merge** (the safe direction). Never rewrite a handoff you cannot prove you last read.
Re-read the handoff's `updated` immediately before writing it; if it changed since Step 0, merge again.
**Lanes:** while `sessions.others` is non-empty, prefix each Next up item this session adds with `[<focus>]` (this
session's focus) and leave items in other lanes untouched. `sessions.focus` empty → set a focus first
(`python3 ~/.claude/tools/session/close.py --cwd "$PWD" session focus "<text>"`), then tag. If `sessions.registered`
is false, run `python3 ~/.claude/tools/session/close.py --cwd "$PWD" session refresh` first, then set the focus.
When naming another session, show `<id>/<pid>` when two ids match (a fork keeps its parent's id).

File: `handoff.path`. **New project** → copy `~/.claude/handoffs/_TEMPLATE.md` there. **`legacy` set** → convert
it: Open Items / Pending → Next up; the STATE section and any `status.json` → Current state; known units, ports and
log paths → Profile; the dated diary → Last session (trim archives the old part); "What NOT to do" and procedures →
Standing notes. Leave the legacy file where it is.

| Section | Rule |
|---|---|
| Next up | **Rewrite.** Max 5, ranked; item 1 = where the next session starts. From this session's work, the previous Next up and Open items. |
| Warnings | **Rewrite LAST**, after Steps 1a–1d (trim, inbox triage, repo handoff, proposals), because their results feed it. From Step 0: dirty / unpushed work, `no_pr_branches`, `ci_pending`, `running.procs`, `drift: true`, plus background tasks this session launched. `running.supported: false` (no process probe on this platform, or the probe failed; `running.reason` says which) → write `running work unchecked (<reason>)`, never `none`; likewise `git.error` → `PR state unchecked`. Untriaged notes = `inbox_notes` minus the notes Step 1b moved; any left → `N inbox notes untriaged`. From Step 1c's result: `ignored: true` → `repo handoff is gitignored (.claude/ ignored) — collaborators can't see it`; `uncommitted: true` → `repo handoff not committed`. Nothing → `none` (= clean close). `running.others_procs` → Current state as `other session's work (<focus>)`, not Warnings. While `sessions.others` is non-empty, add one Warnings line: `another session is active here — dirty files may be theirs; commit only files you changed`. |
| Current state | **Rewrite:** live / deployed state and repo state. `running.via == "cmdline"` (Windows and macOS match the project path in command lines, weaker evidence than the Linux `/proc` probe) with empty `running.procs` → add `running work: none found (command-line match)` here, not under Warnings: it does not block a clean close. |
| Open items | Add new, remove done. |
| Profile | Add checks this session verified (preflight's `guessed` / `unknown` candidates that proved right, real unit names, health URLs, queue files, `deploys_from_repo`). List every Profile change in the Step 5 report. |
| Standing notes | Add new gotchas. Never drop one on a rewrite. |
| Last session | Prepend `- **YYYY-MM-DD** — <what happened>`. That exact bullet form is what trim dates. |
| Frontmatter | `updated` (UTC `YYYY-MM-DDTHH:MMZ`), `updated_by` (hostname), `repo_sha` + `vault_sha` from Step 0, `type`. |

Verify the Profile still parses (must print `"profile_error": null`):

```bash
python3 ~/.claude/tools/session/close.py check-profile <handoff.path>
```

### Step 1a — Trim

```bash
python3 ~/.claude/tools/session/close.py trim <handoff.path>
```

Moves Last session entries older than 14 days into `<key>.archive.md` (created if needed). `over_100kb: true` means an
undated section has grown: split it by hand, and never cut Standing notes.

### Step 1b — Inbox triage

For every note `/preflight` listed: act on it, or turn it into a Next up item that cites the note's subject. Then
move the triaged notes and add every path the command prints under `stage` to the Step 3 push:

```bash
python3 ~/.claude/tools/session/close.py inbox-done --files <note paths…>
```
Notes listed under `already_done` were triaged by another session: nothing to do. Paths under `refused` are not
inbox notes (a folder, a `done/` entry, a symlink, a non-`.md` file, or a path outside `handoffs/inbox/<key>/`) and
were not moved: fix the list.
Notes left untouched stay and appear under Warnings.

### Step 1c — Shared repo handoff (only when the Profile has `"shared": true`)

```bash
python3 ~/.claude/tools/session/close.py repo-handoff --cwd "$PWD"
```
`written: true` → the file is committed with the project's normal flow (Step 4 "and ship", or the next PR). The
result carries `uncommitted` and `ignored`, which Warnings reports (see Step 1). Each /sync overwrites the file from
this handoff, so collaborators leave notes in a PR or issue, not in the file. `refused` non-empty → the leak guard
found personal strings; fix the private handoff's public sections (Next up, Current state, Warnings, Open items) and
re-run. `refused` empty with a `reason` → `_USER.md` has no identity strings to guard with; nothing is written until
it does (propose filling it in Step 1d). `written: false` with a `reason` naming a symlink or "outside the repo" →
`.claude` or `HANDOFF.md` in the repo is a symlink (possibly committed by a collaborator); nothing was written.
Report it; never replace the link by hand. Never commit a refused file by hand.

### Step 1d — User handoff proposals (`handoffs/_USER.md`)

Propose a change only with evidence of one of:
1. the user stated a general rule this session that names no single project;
2. the same Convention, check or Standing note already sits in two or more project handoffs (propose lifting it into
   `_USER.md` and removing the duplicates);
3. this session verified a user-wide fact (a queue or script no single project owns).

Test: "would this still be true in a different project tomorrow?" When unsure, it stays in the project handoff. Skip
anything under `Declined`. Show proposals in the report and wait for a per-item answer:

```
User:     2 proposals for _USER.md (reply e.g. "1 yes, 2 no")
  1. + Conventions: "<line>"      evidence: <where it came from>
  2. - Standing notes: "<line>"   contradicted: <by what>
```
`yes` → write it and add `_USER.md` to the Step 3 push. `_USER.md` missing: the installer creates it; if it's still
missing, create it from `handoffs/_USER.template.md` when the user accepts the first proposal. `no` → add `- **YYYY-MM-DD** — <proposal> (<reason>)` under
`Declined`. Anything unclear → write nothing and propose again next time. Removals use the same gate; a Standing note
is never dropped silently. If `/preflight` reported `global.user.over_max`, say so and suggest `/doc-review`; never
trim `_USER.md` yourself.

## Step 2 — Check per-project MEMORY.md

Path: `<project-memory>/MEMORY.md`

Ask: did this session produce anything worth remembering across future sessions?
- New feedback from the user ("don't do X", "always do Y")
- A discovery that applies beyond this one setup or trade
- A workflow or tooling pattern that saved or wasted time
- A cross-machine or cross-project finding

If yes: write a new memory file and add a one-line index entry to MEMORY.md (a link + one-line
summary; no character cap — see `memory/schema.md` "Page conventions").
If no: skip — don't create entries just to have something to show.

Also scan existing memory files referenced in the index. If anything is now stale or wrong, update or remove it.

### Step 2a — Delegate global-eligible knowledge to /wiki-ingest

This is the **ingest** checkpoint for the global memory wiki — but `/sync` does NOT contain the
ingestion logic. When the durable finding qualifies for the GLOBAL wiki (per the promotion rule in `_USER.md`
Conventions (with none: promote only what is validated in two or more projects or clearly general — cheaper to miss
than to poison)), **hand it to `/wiki-ingest`**
(invoke the skill). It owns the single ingestion path: schema eligibility check, subfolder routing,
page write (with guardrails), MEMORY.md index line, `Related:` footer, and the `log.md` entry.

- Clear global lessons → auto-delegate to `/wiki-ingest` (it shows takeaways before writing).
- Borderline (global vs project unclear) → `/wiki-ingest` pauses and asks.
- Nothing durable this session → skip; Step 3 just commits/pushes as normal.

Do NOT duplicate the ingestion steps here — `/wiki-ingest` is the source of truth.

### Step 2b — Auto-memory harvest (gated, periodic)

The native auto-memory (`<vault>/projects/<slug>/memory/`) grows automatically and is a separate
store from the global wiki (`<vault>/memory/`). Durable cross-project lessons can get stranded there.
This step is the **gated bridge** — it PROPOSES, never auto-writes.

**Run it only periodically (not every `/sync`)** — roughly weekly, or when you haven't harvested in a
while. Skip silently otherwise.

1. **Delta scan (cheap):** find the last harvest timestamp = date of the most recent
   `## [YYYY-MM-DD] harvest |` entry in `<vault>/memory/log.md` (if none, use ~14 days ago). List
   auto-memory `*.md` whose mtime is newer than that. Don't re-read the whole store.
   ```bash
   last=$(grep -oE '^## \[[0-9-]+\] harvest' "<vault>/memory/log.md" | tail -1 | grep -oE '[0-9-]+' || echo "")
   find "<vault>/projects/<slug>/memory" -name '*.md' -newermt "${last:-14 days ago}"
   ```
2. **2-question filter** per candidate: (a) does it pass the promotion rule in `_USER.md` Conventions (with none:
   promote only what is validated in two or more projects or clearly general — cheaper to miss than to poison)? (b) is it already covered by a wiki page
   (`grep` its topic in `memory/MEMORY.md`)? Only survivors proceed. Skip transient/operator/state
   pages (SESSION_RESUME, live state, per-trader raw profiles, project-specific bug fixes).
3. **Propose, gated:** show the user the shortlist with one-line rationales. Do NOT write anything
   without confirmation (promotion rule is deliberately conservative — "cheaper to miss than poison").
4. **On approval:** hand each to `/wiki-ingest` (it adds the `source:` backlink to the auto-memory
   original; leave the original in place — supersession-safe).
5. **Record:** append one `## [YYYY-MM-DD] harvest | N promoted, M reviewed` line to `log.md` so the
   next delta scan is cheap.

If nothing new is promote-worthy, just log nothing and move on.

## Step 3 — Push vault

```bash
python3 ~/.claude/tools/session/close.py push --message "sync: <key> session <YYYY-MM-DD>" \
  --files <handoff.path> [<archive path>] <every memory / wiki file THIS session changed>
```

`<archive path>` = the archive file's full path, next to the handoff (`<handoffs dir>/<key>.archive.md`, i.e. Step 1a's
`archive` value), listed only if trim created or changed it. Never a bare name: relative paths resolve against the
current folder and fail the all-or-nothing push.

It takes the `.sync.lock` mutex (stale after 5 min), stages **only** the listed files with `add -f` (new files under
`projects/*/memory/` are silently skipped without `-f`), makes a pathspec commit so other sessions' staged work stays
out, runs `pull --rebase --autostash`, pushes (one retry), and checks each file with `git cat-file -e HEAD:<path>`.

| `status` | Do |
|---|---|
| `ok` | Report `sha`. If `missing` is non-empty, re-run push with those files. |
| `nothing` | Report "nothing to commit" (nothing staged and nothing left unpushed). |
| `locked` | Another session is syncing: retry once a minute later, else report the push as deferred. |
| `stage_failed` | No listed file exists or is tracked, a listed path is a directory (list files, never folders), a listed untracked file is ignored, or any listed file is secret-shaped (`.credentials.json`, `.env*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`; `add -f` is only for new `projects/*/memory/` files), or a listed file is not stageable (e.g. inside a nested repository): `detail` names the path. Fix the list and re-run. Nothing was staged. |
| `dropped` non-empty (on any status) | These listed paths don't exist and were never committed, so they were skipped. Harmless only for an archive file `trim` never created; anything else means the file list is wrong — fix it and re-run push. |
| `local` | The vault is not a git repo: the files are written locally and there is nothing to push. Report "vault: local". |
| `committed_local` | No upstream to push to: committed locally, nothing pushed. Report `sha` — see `reason` for why (no remote / no upstream tracking / detached HEAD) and what to do. If `missing` is non-empty, re-run push with those files. |
| `rebase_conflict` | The remote changed the same file. close.py already ran `git rebase --abort`: the vault is back on the branch with your commit intact and nothing pushed. Pull the other side's change, merge the file by hand (union-merge append-only files), commit, and re-run push; a re-run pushes the existing commit. |
| `autostash_conflict` | Your commit was pushed, but popping OTHER sessions' uncommitted work conflicted. Follow the recovery below using the `stash` sha from the output. |
| `commit_failed` / `push_failed` | Report `detail`. `Permission denied` = an antivirus handle: defer the push (the local commit is safe); a reboot clears it. Re-running push later pushes the waiting commit. |

**Autostash conflict recovery** (other sessions' uncommitted work is in the stash whose sha push returned as
`stash`; call it `$S`. Use the sha, never `stash@{0}`: the vault can hold older autostash entries):
1. Resolve the conflicted files. For an append-only file (`memory/log.md`) always union-merge: keep every entry,
   ordered by date. Never pick a side.
2. Clear the conflict state without committing their work: `git add <file>` then `git restore --staged <file>`.
3. Verify every stashed file survived before dropping the stash:
   ```bash
   for f in $(git stash show --name-only "$S"); do
     git diff --quiet HEAD -- "$f" && echo "LOST: $f" || echo "ok: $f"
   done
   ```
4. Autostash restores files STAGED that were unstaged before: `git restore --staged <files>`.
5. Only then drop exactly that entry: find its index with `git stash list --format='%H %gd' | grep "^$S"` and
   `git stash drop <that stash@{N}>`.

**Never commit a shared index line that points at a file you are not committing.** `memory/MEMORY.md` and
`memory/log.md` are written by every session; if another session's new page is still untracked, leave the shared
file unstaged and let the owning session's commit carry both.

### Step 3b — Refresh this session's registry entry

```bash
python3 ~/.claude/tools/session/close.py --cwd "$PWD" session refresh
```
It records the handoff version this session just wrote, so a later concurrent /sync is detected; it is local and
never committed.

## Step 4 — "and ship" (only when explicitly requested)

When called as `/sync and ship`: after completing Steps 1–3, commit and push the current project repo. If a `ship`
skill is installed, invoke it; otherwise commit and push the project repo yourself on a branch and open a PR, then
stop (merge only if the user asked for it; never merge a repo that runs production or real money without
confirmation). Report the PR URL.

## Step 5 — Report

```
SYNC — <key> — <local time>
Handoff:  <handoff.path> · clean close ✓ | warnings: <list>
Profile:  <checks added/changed | unchanged>
Vault:    pushed <sha> | nothing to commit | deferred (<reason>)
```

## Gotchas

Hardest-won traps (distilled — see Step 3 + the concept pages for full rationale):

- **Never `git add -A` on the vault** — it's a shared multi-session working tree; `-A` stages other sessions' half-writes and phantom deletions and silently commits their work away. Stage an explicit allowlist of only the files THIS session touched (Step 3, `close.py push`).
- **Never `git reset --hard` / `git push --force` on the vault** — destroys concurrent sessions' work. Recover a phantom-deleted file with targeted `git checkout HEAD -- <file>`, never a reset.
- **Lock before any vault git op** — `mkdir`-based atomic mutex (Step 3, `close.py push`), released on exit, 5-min stale breaker. One committer at a time.
- **`git add` can silently stage nothing** (Windows `core.ignorecase=true` case drift) — always confirm with `git diff --cached --stat`; if empty for a file you changed, re-add with `':(icase)<path>'` or the exact path from `git status --porcelain`. Case drift can come back whenever a folder is renamed, so keep the check.
- **NEW `projects/*/memory/` files need `git add -f`** — `.gitignore` re-includes that dir via a negation, and git can't re-include a brand-NEW file under an ignored parent with a plain `git add <path>` (silently skipped, nothing staged). Already-tracked files are fine; only new files drop. Force-add them and verify with `git cat-file -e HEAD:<path>` after push.
- **`Permission denied` on rebase = antivirus, not git** — AV real-time protection quarantines a file with security-incident/IOC content and holds a delete-pending handle. Do NOT force or reset; the local commit is safe (it's HEAD). Reboot clears it; add an AV exclusion for `~/.claude` to prevent recurrence. Windows Search is a red herring. Defer the push and report.
- **After any messy rebase, verify your edits survived** — a two-session same-file rebase can auto-merge your changes away with NO conflict shown. `grep HEAD:<file>` for your key markers before assuming the commit kept them.
- **Auto-memory is path/case-fragile** — durable cross-machine knowledge belongs in the global wiki (`memory/`) via `/wiki-ingest`, not the cwd-keyed project store. Launch Claude from the canonical path to keep the slug stable.
- **Handoffs are trimmed every sync (Step 1a)** — `close.py trim` archives Last session entries older than 14 days, so the file `/preflight` reads stays small. It never cuts undated sections (Standing notes are live procedure, not history). Without trimming, a handoff grows to hundreds of KB.

## Rules
- **NEVER `git add -A` on the vault** — shared multi-session working tree; `-A` commits other sessions'
  half-writes and phantom deletions. Stage only your own files (Step 3, `close.py push`).
- **Never `git reset --hard` / `git push --force` on the vault** — destroys concurrent sessions' work.
  Recover phantom deletions with targeted `git checkout HEAD -- <file>`, never `reset --hard`.
- **Lock before git** (Step 3, `close.py push`) — serialize commits across sessions. Release on exit.
- **On a `Permission denied` rebase jam** — defer the push (local commit is safe), don't force; reboot clears
  the handle. Add an **antivirus exclusion for `~/.claude`** to prevent it (AV quarantining flagged file content
  was the real cause — not Windows Search).
- Don't create duplicate memory entries — check the index first
- Convert relative dates to absolute dates when saving
- MEMORY.md index entries are a link + a one-line summary — no character cap;
  the test is whether the line helps you decide to open the page, not its length
- Only add genuinely new information — restating known facts wastes context next session
- If nothing meaningful changed, say so and skip
