# Error Handling — session tools (`open.py` / `close.py` / `lib.py`)

Last updated: 2026-09-28

## 1. Collector never crashes the skill

### Command runner (`lib._run`)
- Handling: every subprocess goes through `lib.RUN`, which never raises: timeout → rc 124, missing binary → rc 127,
  output decoded as UTF-8 with `errors="replace"`.
- Alert: the caller turns a bad rc into a check with status `unknown` and the reason in `detail`.
- Recovery: none needed; the next run retries.

### Checks report "unknown", not "down"
- Handling: a check whose tool failed (curl/ss/systemctl missing, timeout, unreadable file) is `unknown`; only an
  observed bad state is `fail`/`warn`. Guessed unit names that miss are "unverified".
- Recovery: fix the Profile entry, or install the missing tool.

## 2. Running work at close (`close.running_work`)

### Harness filter misses Bash-tool jobs (fixed 2026-09-28)
- What broke: Claude was recognized only by the process name `claude`. Native installs run `versions/<ver>`, so the
  session process is named e.g. `2.1.283`; every job started through the Bash tool was classified as a harness helper
  and dropped, giving a false "nothing running" (a false clean close).
- Fix: `_is_claude` accepts `claude`, a version-shaped name, or the basename of `CLAUDE_CODE_EXECPATH`.
- Guard: when running under Claude (`CLAUDE_CODE_EXECPATH` set) and no ancestor process is recognized, the naming has
  changed again: `running_work` returns `supported: false` with `reason`, and `/sync` writes
  `running work unchecked (<reason>)` instead of `none`.
- Recovery: add the new process name to `_CLAUDE_BIN` in `procs.py`; `tests/test_review_fixes.py` has the fixtures.

### No `/proc` (Windows, macOS)
- Handling: a command-line probe (`procs.table`: PowerShell CIM on Windows, `ps` on macOS) matches the project path;
  a probe error or timeout is `supported: false` with `reason`.
- The probe matches command lines and also reports this session's own descendants, but other jobs started with
  relative args elsewhere remain invisible.
- See Gaps.

## 3. Identity and version

### Hub folders (`lib.resolve_identity`)
- Handling: a folder holding several repos returns `ambiguous` (the skill asks) unless the folder already has its own
  handoff `local-<folder>.md`, then `folder-handoff`. An explicit `--project` always wins.

### Claude Code version (`open.cc_version`)
- Handling: version read from the binary name (Linux native) or its parent folder (Windows desktop app); an npm shim
  is asked `--version` with a 5 s timeout. Anything unreadable → `null`, and `relaunch_needed` stays false.

## 4. Vault writes (`close.push`, `close.trim`)
- Handling: `push` returns a status for every outcome (`ok`, `nothing`, `locked`, `stage_failed`, `rebase_conflict`,
  `autostash_conflict`, `commit_failed`, `push_failed`, `committed_local` for a git vault without an upstream); the
  sync skill has a recovery row for each. `trim` asserts
  that no content is lost and flags files over 100 KB.
- `push` refuses directories (2026-09-28, security): any listed path that is a directory (or `.` / empty
  string) stages nothing, all-or-nothing — a directory, especially the vault root, would otherwise silently
  commit ignored files (`.credentials.json`, `projects/**`) and other sessions' half-writes.
- `push` refuses ignored and secret-shaped files (2026-09-28, security): `add -f` force-adds any listed file, so an
  explicitly listed `.credentials.json` or `.env` would be committed. Before staging, a file whose name is
  secret-shaped (`.credentials.json`, `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`) is refused
  whatever its ignore state, tracked or not; an UNTRACKED file `git check-ignore --no-index` calls ignored is refused
  unless it is under `projects/<x>/memory/` (the only place `-f` is meant for). A tracked file (`ls-files
  --error-unmatch`) skips the ignore check: a pattern added later must not block an already-committed file. All-or-nothing, `stage_failed` naming the path.
  check-ignore runs without `--literal-pathspecs` (it rejects that flag with rc 128; it takes plain pathnames, no
  glob magic); an rc other than 0/1 refuses too.
- `push` verifies the index after `add` (2026-09-28): a file inside a nested repository is silently not staged
  (`add` exits 0). Every existing listed file must be in the index, else `stage_failed` naming it, and what this
  call staged is unstaged again (`restore --staged`), so `/sync` never loops on `missing`.
- Stale lock (`.sync.lock`, > 300 s): broken by renaming it to `.sync.lock.stale-<pid>-<nonce>` and checking the
  renamed dir's inode + mtime still match the lock judged stale; if not (another waiter already replaced it with a
  fresh lock), it is renamed back and the wait goes on. rmdir-by-name let a second waiter delete the first one's
  fresh lock.
- A held lock is never empty: after `mkdir` the holder creates `.sync.lock/owner` (pid + nonce) with O_EXCL. Linux
  `rename` replaces an EMPTY directory, so without it a rename-back could land on a third waiter's fresh lock (two
  holders); now that waiter's O_EXCL fails and it keeps waiting. A rename-back that fails (the path is held) leaves
  the `.sync.lock.stale-*` dir in place: it is someone's lock, never deleted. The holder re-checks its owner token
  before staging (a lock moved aside that way means another holder took the path: status `locked`, nothing staged),
  and release removes `owner` then the dir only while `owner` is still its own.
  The lock dir also carries a `.gitignore` (`*`), so a held or leftover lock never shows in `git status` and an
  `add -A` elsewhere (Obsidian-git) never commits it.
- Vault state (`rebase-merge`, `rebase-apply`, `MERGE_HEAD`) is located with `git rev-parse --git-path`, so a
  worktree or `.git`-file vault is checked; if git fails, `<vault>/.git/<name>` as before.

## 4b. Profile entries and the repo handoff
- A malformed Profile entry (`{"health": [{"URL": ...}]}`, `{"services": ["unit"]}`, a section that is not a list)
  is one check with status `unknown` and detail `bad check: <reason>` in `/preflight`; `/sync`'s `drift` lists it
  with `drift: null` and the same detail. Same rule as the `_USER.md` checks.
- A Profile value that becomes a command argument (ssh target, systemd unit, health URL) and starts with `-` is
  refused the same way (`-oProxyCommand=...` would run a command); `--` also precedes the positional argument for
  ssh, systemctl and curl.
- `repo-handoff` refuses (`written: false`, `reason`) when `<repo>/.claude` or `HANDOFF.md` is a symlink or the file
  resolves outside the repo (a committed symlink would let `/sync` overwrite e.g. `~/.bashrc`); it writes through a
  temp file in the same folder + `os.replace`.
- `inbox-done` moves only regular `.md` files directly in `handoffs/inbox/<key>/`; anything else is listed under
  `refused` and the rest still move.
- Leak guard: needles and text are compared after NFKC + casefold with zero-width characters removed; the whole text
  is also scanned with whitespace collapsed (a name wrapped across lines); the home directory path is always a
  needle (in `find`, not `needles`, so an empty identity still refuses). The bare user name is not a needle (too
  many false positives).

## 5. Text encoding
- Handling: every text read/write and text-mode subprocess names `encoding="utf-8"`. Windows defaults to cp1252,
  which broke 6 tests on an em-dash (Task 16). `tests/test_hygiene.py` fails on any new unencoded call.

## Gaps (not yet handled)

| Gap | Impact | Priority | Status |
|-----|--------|----------|--------|
| Running-work probe on Windows/macOS | Clean close unreachable there (always "unchecked") | Medium | Done 2026-09-28 (procs.py); residual: relative-arg jobs not started by this session are invisible |
| npm-installed Claude runs as `node` | An EXECPATH basename of `node` counted every node process as Claude, hiding node dev servers (a false clean close) | Low | Done: runtime basenames ignored (`procs._RUNTIMES`); such an install reports running work "unchecked" |
