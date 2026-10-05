# claude-wiki-engine

A portable, Karpathy-style **LLM-wiki** for Claude Code — the curated `memory/` knowledge base plus
the skills + hook that maintain it (`/wiki-ingest`, `/wiki-sync`, `doc-review`, `wiki-index-check`).
One engine, installable into any Claude config (a personal `~/.claude` or a shared repo), on
Linux / macOS / Windows.

## Engine vs content
- **Engine** (this repo): the machinery — skills + the `memory/` framework templates + a non-blocking
  index hook + the CLAUDE.md policy block.
- **Content**: your actual wiki pages — they live in *your* memory store (in place, or your own repo).
  The engine never owns a page.

Update the engine once → consumers re-sync the machinery (`--update`); content is untouched.

## Install
Requires **Python 3** and **git** (plus **node** if you keep the hook, which is the default).
```
git clone https://github.com/oager/claude-wiki-engine.git && cd claude-wiki-engine
python3 install.py            # interactive wizard (recommended)
```
Non-interactive / flags:
```
python3 install.py --yes                        # accept all defaults
python3 install.py --into-repo /path/to/repo    # vendor the engine into a shared repo (e.g. claude-global)
python3 install.py --content-repo <git-url>     # clone a repo to BE your memory dir
python3 install.py --mode symlink               # link skills (auto-update); falls back to copy
python3 install.py --force-skills               # replace existing skills (backs up first); default skips them
python3 install.py --extras all                 # also install the optional workflow skills (see below)
python3 install.py --no-hooks                   # skip the wiki-index-check hook
python3 install.py --no-claude-md               # skip the CLAUDE.md policy block
python3 install.py --dry-run                     # print the plan, write nothing
python3 install.py --update                       # re-pull engine + re-copy ITS skills/hook; never touch content
```
`./install.sh` / `.\install.ps1` are thin shims that call `install.py`.

## What it installs
- `skills/wiki-ingest`, `skills/wiki-sync`, `skills/doc-review` → `<config>/skills/` — **only if absent**
- `extra-skills/*` → `<config>/skills/` — **opt-in only** (wizard step 6, or `--extras`); never installed by default
  (an existing skill may come from a plugin like **ECC** or be your own; the installer won't overwrite it).
- `hooks/wiki-index-check.cjs` (`PostToolUse`, non-blocking "this page isn't in MEMORY.md" reminder),
  `hooks/wiki-sync-nudge.cjs` (`Stop`, a once-per-session nudge to run `/wiki-sync` before wrapping
  up) and `hooks/session-end.cjs` (`SessionEnd`, removes the session's live-registry entry on exit; a no-op
  without the session tools) → `<config>/hooks/` + entries in `<config>/settings.json` — **merged idempotently, backed up,
  all other keys preserved**.
- `schema.md`, `overview.md`, `MEMORY.md`, `log.md` + `sources/ entities/ concepts/ synthesis/ raw/ raw/archive/`
  → `<config>/memory/` (seed-if-absent; never overwrites your pages).
- `memory/.gitignore` + `memory/raw/README.md` (seed-if-absent) — encodes the canonical pattern:
  **the wiki is tracked**, only `raw/*` (the unprocessed inbox) is ignored, and `raw/README.md` +
  `raw/archive/` (ingested originals) are kept.
- a reversible ingestion-policy block in `<config>/CLAUDE.md` (between `<!-- wiki-engine:start/end -->` sentinels).

## Optional extra skills

Beyond the wiki engine itself, the repo ships a set of **optional workflow skills** in
`extra-skills/`. They are independent of the wiki — install any, all, or none. Nothing is installed
unless you ask for it, and an existing skill of the same name is never overwritten.

| Skill | What it does |
|---|---|
| `error-harden` | Post-bugfix checklist: enumerate failure modes, auto-handle them, add alerting, write it down |
| `karpathy-guidelines` | Behavioural guardrails against common LLM coding mistakes (overcomplication, silent assumptions, unverifiable success criteria) |
| `preflight` | Session startup: sync the vault, load memory, orient on project state, brief in 10-15 lines. Read-only |
| `recap` | Generate a paste-ready handoff doc for another session or another machine |
| `regression` | Run the project's regression suite and block on failure |
| `ripple` | Consumer-impact sweep when data or interfaces change: what downstream breaks, goes stale, or could benefit |
| `sync` | End-of-session ritual: update memory, promote durable findings to the wiki, push the vault safely |
| `tiered-build` | Three-model build pipeline with hard gates between design, spec, and implementation |
| `tv` | Launch TradingView with a CDP debugging port for chart automation |

`preflight` and `sync` are the natural bookends to a session and pair with the wiki: `sync` promotes
durable findings into it, `preflight` reads the index back at startup.

### Installing extras

The wizard asks (step 6 of 6). You can enter numbers, names, `all`, or `none`:

```
[6/6] Optional extra skills - independent of the wiki engine, install any or none:
   1) error-harden         Post-bugfix checklist: enumerate failure modes, auto-handle, alert, document
   2) karpathy-guidelines  Behavioural guardrails against common LLM coding mistakes
   ...
  Enter numbers or names (comma/space separated), 'all', or 'none'.
Extras [none] > 1 3 sync
```

Non-interactively:

```bash
python3 install.py --extras all
python3 install.py --extras preflight,sync,ripple
python3 install.py --extras none          # the default
```

Same safety rules as the core skills: existing skills are skipped rather than overwritten
(`--force-skills` replaces them, backing up first), and `--mode symlink` links them so they
auto-update with the repo.

## Session handoff (preflight + sync)

`/preflight` opens a session; `/sync` closes it. Both are **user-only** slash commands (Claude cannot start them).

- **Three layers.** The skills and `tools/session/` are the same for everyone. `handoffs/_USER.md` is yours: identity,
  user-wide checks and conventions, grown by `/sync` only after you say yes to each proposal. `handoffs/<key>.md` is
  one project's handoff: Next up, Warnings, Current state, Profile, Standing notes.
- **Clean close:** the next session can start from the handoff alone — nothing hidden in git, in running processes or
  in the inbox.
- **Inbox:** `python3 ~/.claude/tools/session/close.py note --to <key> --from <you> --subject "..."` leaves a note the
  next `/preflight` in that project shows, on any machine that shares the vault.
- **Shared projects:** set `"shared": true` in the project Profile and `/sync` also writes a public
  `.claude/HANDOFF.md` (leak-guarded) for collaborators.
- **Plain setups work:** no git in `~/.claude`, one machine, no systemd — the extras switch on when present.
- **Updating:** `python install.py --update` refreshes skills tagged `source: claude-wiki-engine` (core and extras)
  and the handoff templates; any that you edited is backed up to a timestamped copy under `<config>/.wikibak/` first
  (never under `skills/`, so an old backup can't be picked up as a duplicate skill). `handoffs/_USER.md` is never
  touched. Untouched copies from older versions are recognised by their exact bytes; any other untagged skill is
  treated as yours and skipped. To swap one for the engine's: move it out of `skills/` (rename or delete it), then run
  `python install.py` (plus `--extras <name>` for an extra, e.g. `--extras preflight,sync`; components already present
  are skipped).
- **Your own `/preflight` or `/sync` wins:** if `skills/preflight` or `skills/sync` is your own skill, the installer
  leaves it alone and skips the session system as a whole: both engine session skills, `tools/session` and the
  session-handoff CLAUDE.md block, so nothing points the model at your skill. `--update` does the same and removes
  a session-handoff block an earlier install left in CLAUDE.md. A note says how to switch.
- **Other locations:** the skills call `~/.claude/tools/session/` by that path, and the tools keep handoffs in
  `~/.claude` unless `CLAUDE_VAULT` is set. For an `--into-repo` or `CLAUDE_DIR` install, edit that path in
  `skills/preflight` and `skills/sync` (the installer prints the exact path); `CLAUDE_VAULT` moves the vault only.
- **Converting an old `SESSION_RESUME.md`:** the first `/sync` does it. Archive every dated section, carry every rule
  unless shown obsolete, list only verified service names, give ports an `owner`, write Current state from live data,
  and keep Warnings honest.

## How it adapts (no hardcoding)
The installer resolves symlinks and writes to the **real** target, so it fits any layout — a personal
`~/.claude`, or a shared global that other configs symlink to — without per-user configuration.

## Safety (lessons from real installs)
- **Never clobbers existing skills** — GateGuard, `doc-review`, etc. often come from the **ECC plugin**
  (`~/.claude/plugins/`) and won't show up in `skills/` or `settings.json`; the installer skips any skill
  already present so it never duplicates or downgrades a plugin/user version (`--force-skills` to override).
- **`settings.json` is edited surgically** — parsed/merged/written as JSON (valid by construction),
  backed up to `.wikibak`, every other key preserved, trailing newline kept. The `.wikibak` snapshot is
  taken **once per run**, before any wiring — a run that wires several hooks would otherwise overwrite it
  with a mid-install checkpoint, leaving you unable to restore true pre-install state.
- **The installer NEVER commits the target repo** — it only writes files; you commit your own changes,
  so it can't sweep up an owner's in-progress work.
- **Track the wiki; ignore only the inbox.** Claude reads `memory/` from disk regardless of git, but
  you *want* it version-controlled — history, backup, and cross-machine sync. The installer seeds a
  `memory/.gitignore` so `raw/*` (unprocessed inbox) stays out of git while the pages, `raw/README.md`,
  and `raw/archive/` (ingested originals) are committed. **Pitfall:** if a parent directory is excluded
  wholesale (e.g. a repo whose `.gitignore` drops all of `users/`), your entire live wiki silently loses
  history and sync — and a stale tracked copy elsewhere becomes a confusion trap. Track the real wiki dir.

## Tests
Stdlib `unittest`, no dependencies — from the repo root:
```bash
python -m unittest discover tests
```
Regression coverage for the surgical `settings.json` merge: the `.wikibak` snapshot survives a multi-hook
run, repeat/idempotent calls don't clobber it, and unrelated user keys are preserved.

## Notes
- Defaults to **copy** (works everywhere). `--mode symlink` is opt-in and falls back to copy if the OS blocks symlinks.
- `--update` refreshes engine-owned files only; your content is never touched, and an edited engine file is backed
  up under `<config>/.wikibak/` before it is replaced. It also
  **re-wires `settings.json` (self-healing)**: a stale/broken hook command from an older install —
  e.g. a pre-fix Windows backslash path — is repaired in place, not left behind.
- The `Stop` nudge fires **once per session** (a tmp flag keyed on the session id, or the transcript
  path when no id is present), is loop-safe, and lets Claude no-op on a routine session; disable with `WIKI_SYNC_NUDGE=off`.
- The `wiki-index-check` hook is **config-adaptive**: it finds the wiki by the nearest `MEMORY.md`
  above the written file, so it works for a global `~/.claude/memory`, a repo-vendored wiki, a
  project-scoped `.claude/projects/<slug>/memory`, or any custom `--memory` path — no fixed location.
- Roadmap: submodule mode; more optional skills (dictionary / postmortem).
