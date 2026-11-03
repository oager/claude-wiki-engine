# Field report: v0.6.0 on Windows 11 (Git Bash), 2026-11

Source: one install of v0.6.0 on Windows 11, Git Bash shell, Python 3.12, used through several `/preflight` and
`/sync` cycles. Every item was re-checked against `origin/main` at `eb13122` and is still open there.

**For the evaluating agent:** judge each item on its own. Adopt, adapt or reject, and record the reason. The two
`.patch` files next to this report are the local edits made to `extra-skills/preflight/SKILL.md` and
`extra-skills/sync/SKILL.md`. They were cut against the v0.6.0 copies, so line numbers will not match current `main`;
read them for intent, do not `git apply` them.

## A. Local patches worth upstreaming

### A1. `python3` does not exist on stock Windows
- Evidence: `extra-skills/preflight/SKILL.md` (2 hits) and `extra-skills/sync/SKILL.md` (9 hits) call `python3`. On
  Windows that is the Microsoft Store stub, which opens the Store or exits non-zero. The inline comment
  `# Windows Git Bash: python` only helps a reader who notices it.
- Local fix: replaced every `python3` with `python`.
- Suggested: have `install.py` rewrite the interpreter name at install time (`sys.executable` basename, or `python`
  when `os.name == "nt"`), or reference a single variable the skill defines once.

### A2. Project auto-memory is invisible to `/preflight` and `/sync`
- Evidence: Claude Code keeps per-project memory in `~/.claude/projects/<slug>/memory/` (`MEMORY.md`,
  `feedback_*.md`, and in older setups a `session.md` resume file). The handoff flow never reads it, so the user's
  standing rules (`feedback_*.md`) never reach the briefing, and a leftover `session.md` can be read later as current.
- Local fix (see patches): preflight Step 2b reads every `feedback_*.md` and adds a `Rules:` line to the report; it
  reads `session.md` only when no handoff exists and labels it legacy. Sync converts `session.md` into the first
  handoff, then deletes it and its index line.
- Suggested: make this an optional step, or have `open.py` return `project_memory: {path, feedback: [...],
  legacy_session}` so the skill does not have to locate the directory itself.

### A3. Em dashes in report templates
- Evidence: `extra-skills/preflight/SKILL.md:125` `PREFLIGHT — <key> (<type>) — <local time>`, and headings like
  `## Step 0 — Collect` in `extra-skills/sync/SKILL.md`. The model copies the template literally, so every report the
  user pastes elsewhere carries em dashes, a common tell of machine-written text.
- Local fix: `PREFLIGHT: <key> (<type>), <local time>`.
- Suggested: replace em dashes in all user-facing templates with a colon or comma.

## B. Bugs

### B1. `install.py --force-skills` crashes on Windows and leaves a duplicate skill
- Evidence: `install.py` `copy_tree` and `link_or_copy` call `shutil.rmtree(dst)` with no error handler. On Windows,
  read-only files or a handle held by a running Claude Code process cause `PermissionError` on
  `skills/wiki-ingest`. The run aborts part-way and leaves a `*.wikibak` directory inside `skills/`, which Claude Code
  then registers as a second copy of the skill.
- Reproduced by the repo's own tests: on `main` at `eb13122` (Windows 11, Python 3.12),
  `python -m unittest discover tests` gives `FAILED (errors=2)`:
  `test_update_backs_up_edited_engine_core_skill` and `test_update_of_unchanged_core_skill_makes_no_backup`, both
  `PermissionError: [WinError 5] Access is denied: '...\skills\doc-review'`.
- Suggested: `shutil.rmtree(dst, onexc=_force_remove)` (Python 3.12+; `onerror` before that) that clears the
  read-only bit and retries once; on a second failure, print which skill is locked and tell the user to close Claude
  Code. Write backups outside `skills/` so a half-finished run cannot leave a duplicate skill behind.

### B2. Missing `gh` is reported as a raw OS error, twice
- Evidence: `git.error` came back as
  `"[WinError 2] The system cannot find the file specified; [WinError 2] The system cannot find the file specified"`
  with `prs: null`, `issues_open: null`.
- Suggested: check `shutil.which("gh")` first and return `"gh not installed"` once; `"gh not logged in"` for the auth
  case.

### B3. `_USER.md` reports `exists: true` while still the raw template
- Evidence: after install, `handoffs/_USER.md` still holds `updated: <YYYY-MM-DDTHH:MMZ>` and
  `updated_by: <hostname>`, with empty Conventions. The collector reports `exists: true`, so `/preflight` never says
  the file still needs filling in.
- Suggested: add `user.template: true` when the placeholders are still present, and have the preflight User line
  say so.

### B4. Diagnostics return `null` on Windows
- Evidence: `global.clock.ntp_synced: null` and `global.claude_code.running: null` every run.
- Suggested: implement them (`w32tm /query /status` for NTP; the parent process for the running binary) or leave the
  keys out on unsupported platforms, so the skill does not read `null` as either value.

### B5. Project type comes from frontmatter alone
- Evidence: a Python repo (`*.py`, `requirements.txt`) got `type: workspace`, with `signals: ["handoff frontmatter"]`.
  The first `/sync` wrote `type: workspace` into the frontmatter, and from then on that value kept itself in place.
- Suggested: let code signals win over a frontmatter value the engine wrote itself, or keep the user-pinned type
  apart from the detected one.

## C. Interaction with other common plugins

### C1. Fact-forcing PreToolUse hooks block the first collector call
- Evidence: the ECC plugin's GateGuard hook denies the first Bash call of each session until the agent states its
  purpose. That first call is always `open.py`, so every `/preflight` takes an extra round trip.
- Suggested: one README line under Troubleshooting, plus the allowlist entry for `tools/session/*.py` if the hook
  supports one. No code change.

### C2. `wiki-sync-nudge` fires after a read-only session
- Evidence: the Stop hook asked for a `/wiki-sync` checkpoint right after a `/preflight` that wrote nothing.
- Suggested: skip the nudge when the session made no Write or Edit calls, or when the only skill run was `/preflight`.
