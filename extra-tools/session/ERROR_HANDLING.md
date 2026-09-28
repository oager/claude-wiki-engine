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

## 5. Text encoding
- Handling: every text read/write and text-mode subprocess names `encoding="utf-8"`. Windows defaults to cp1252,
  which broke 6 tests on an em-dash (Task 16). `tests/test_hygiene.py` fails on any new unencoded call.

## Gaps (not yet handled)

| Gap | Impact | Priority | Status |
|-----|--------|----------|--------|
| Running-work probe on Windows/macOS | Clean close unreachable there (always "unchecked") | Medium | Done 2026-09-28 (procs.py); residual: relative-arg jobs not started by this session are invisible |
| npm-installed Claude runs as `node` | An EXECPATH basename of `node` counted every node process as Claude, hiding node dev servers (a false clean close) | Low | Done: runtime basenames ignored (`procs._RUNTIMES`); such an install reports running work "unchecked" |
