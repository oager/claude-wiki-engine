---
name: sync
description: End-of-session ritual — update session memory + the project MEMORY.md index, then commit and push the memory vault concurrency-safely so every machine stays in sync. Use for "sync", "update the usual", or "/sync". Add "and ship" to also commit/push the project repo.
disable-model-invocation: true
---

# Sync Memory & Vault

Update persistent memory for the current project, then push the vault so every machine stays in sync.

## Step 0 — Resolve paths
- **Vault/config:** `~/.claude/` on Linux/macOS, `%USERPROFILE%\.claude\` on Windows.
- **Project memory dir:** wherever this project's memory lives (e.g. `<vault>/projects/<slug>/memory/`,
  or the project's own `memory/`).
- **Layout:** note whether the project uses a session-state file (`SESSION_RESUME.md`) or just
  `MEMORY.md` + individual pages.

## Step 1 — Update session memory
- If a `SESSION_RESUME.md` exists: update Last-updated (UTC), current state, what happened this session,
  how to resume next session, and what NOT to do.
- Otherwise: update the relevant `<project-memory>/*.md` files directly (new feedback → feedback file,
  new fact → project file, etc.).
- Keep entries factual and timestamped. Only add what's new — don't restate what's already there.

## Step 2 — Check the project MEMORY.md index
Did this session produce anything worth remembering across future sessions? (user feedback like
"always/never do X", a discovery that applies beyond this one task, a workflow or tooling lesson that
saved or wasted time, a cross-machine finding.)
- If yes: write a memory file and add a one-line index entry to `MEMORY.md` (≤150 chars).
- If no: skip — don't invent entries just to have something to show. Also scan the indexed files and
  fix or remove anything now stale.

### Step 2a — Promote globally-useful findings to the wiki
If a durable finding is broadly applicable — reusable across projects, or domain-independent rather than
specific to this one project — hand it to **`/wiki-ingest`** (the single ingestion engine: eligibility
check, subfolder routing, page write with guardrails, `MEMORY.md` index line, `Related:` links, log
entry). Clear cases → delegate; borderline → let `/wiki-ingest` pause and ask; nothing durable → skip.
Don't duplicate ingestion logic here — `/wiki-ingest` is the source of truth.

## Step 3 — Push the vault (concurrency-safe)
⚠️ If the vault is a **shared** working tree (multiple sessions and/or an auto-commit tool such as
Obsidian-git write to it), **never `git add -A`** — it stages other writers' half-finished work and
phantom deletions and can silently commit their work away. Stage ONLY the files THIS session changed,
under a lock.

### 3a. Acquire the sync lock (atomic `mkdir` mutex — atomic on every OS)
```bash
VAULT="<vault>"; LOCK="$VAULT/.sync.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  find "$LOCK" -maxdepth 0 -mmin +5 2>/dev/null | grep -q . && rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null \
    || { echo "another session is syncing — try again shortly"; exit 0; }
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT   # always release
```

### 3b. Stage ONLY your files (explicit allowlist — never `-A`)
```bash
git -C "$VAULT" add    <changed-tracked-file> ...
git -C "$VAULT" add -f <new-memory-file> ...          # see ⚠️
```
If a file you wrote shows as deleted/missing elsewhere, that's another session's phantom deletion — do
NOT let it into your commit.

⚠️ **New files can be silently skipped by `.gitignore`.** If the memory dir sits under an ignored parent
that is re-included via a negation (`!.../memory/**`), git cannot re-include a brand-NEW file with a
plain `git add <path>` — the add is silently dropped (no error, nothing staged). Force-add new memory
files (`git add -f`), and after pushing verify each landed with `git cat-file -e HEAD:<path>` (not just
`git diff --cached --stat`).

⚠️ **`git add` can silently stage nothing on case-insensitive filesystems** (Windows) when the path's
case doesn't match git's index. After staging, always confirm with `git diff --cached --stat`; if it's
empty for a file you definitely changed, re-add with `':(icase)<path>'` or the exact path that
`git status --porcelain` reports.

### 3c. Commit (skip if nothing staged)
```bash
git -C "$VAULT" diff --cached --quiet && echo "nothing to commit" \
  || git -C "$VAULT" commit -m "sync: <project> <YYYY-MM-DD>"
```

### 3d. Integrate remote, then push
```bash
git -C "$VAULT" pull --rebase --autostash 2>&1 | tail -5
git -C "$VAULT" push 2>&1 | tail -5   # if rejected (remote moved), repeat 3d ONCE more
```
- **`Permission denied` on rebase** usually means an antivirus or indexer is holding a delete-pending
  handle on a file (often one it flagged). Do **NOT** `reset --hard` / `push --force` — the local commit
  is safe (it's HEAD). A reboot reliably clears it; prevent recurrence with an AV exclusion for the
  vault directory. Defer the push and report.

Report: committed N files / nothing to commit; pushed / deferred (locked).

## Step 4 — "and ship" (only when explicitly requested)
When called as `/sync and ship`: after Steps 1–3, also commit and push the current **project** repo —
stage the meaningful changes, commit with an imperative message, push. Then report the hash and push
status.

## Rules
- **Never `git add -A`** on a shared vault — stage an explicit allowlist of only your own files (3b).
- **Never `git reset --hard` / `git push --force`** on a shared vault — recover a phantom-deleted file
  with `git checkout HEAD -- <file>`, never a reset.
- **Lock before any vault git op** (3a); release on exit; 5-minute stale-lock breaker.
- **On a `Permission denied` rebase jam** — defer the push (the local commit is safe); don't force. A
  reboot clears the handle; an AV exclusion for the vault prevents recurrence.
- **After a messy rebase, verify your edits survived** (`git show HEAD:<file>` for your key markers) —
  a same-file rebase can auto-merge changes away with no conflict shown.
- Convert relative dates to absolute when saving; keep `MEMORY.md` index entries under 150 chars; only
  add genuinely new information; if nothing meaningful changed, say so and skip.
