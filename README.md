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
python3 install.py --no-hooks                   # skip the wiki-index-check hook
python3 install.py --no-claude-md               # skip the CLAUDE.md policy block
python3 install.py --dry-run                     # print the plan, write nothing
python3 install.py --update                       # re-pull engine + re-copy ITS skills/hook; never touch content
```
`./install.sh` / `.\install.ps1` are thin shims that call `install.py`.

## What it installs
- `skills/wiki-ingest`, `skills/wiki-sync`, `skills/doc-review` → `<config>/skills/` — **only if absent**
  (an existing skill may come from a plugin like **ECC** or be your own; the installer won't overwrite it).
- `hooks/wiki-index-check.cjs` → `<config>/hooks/` + a `PostToolUse` entry in `<config>/settings.json`
  (non-blocking "this page isn't in MEMORY.md" reminder) — `settings.json` is **merged idempotently,
  backed up, all other keys preserved**.
- `schema.md`, `overview.md`, `MEMORY.md`, `log.md` + `sources/ entities/ concepts/ synthesis/ raw/ raw/archive/`
  → `<config>/memory/` (seed-if-absent; never overwrites your pages).
- a reversible ingestion-policy block in `<config>/CLAUDE.md` (between `<!-- wiki-engine:start/end -->` sentinels).

## How it adapts (no hardcoding)
The installer resolves symlinks and writes to the **real** target, so it fits any layout — a personal
`~/.claude`, or a shared global that other configs symlink to — without per-user configuration.

## Safety (lessons from real installs)
- **Never clobbers existing skills** — GateGuard, `doc-review`, etc. often come from the **ECC plugin**
  (`~/.claude/plugins/`) and won't show up in `skills/` or `settings.json`; the installer skips any skill
  already present so it never duplicates or downgrades a plugin/user version (`--force-skills` to override).
- **`settings.json` is edited surgically** — parsed/merged/written as JSON (valid by construction),
  backed up to `.wikibak`, every other key preserved, trailing newline kept.
- **The installer NEVER commits the target repo** — it only writes files; you commit your own changes,
  so it can't sweep up an owner's in-progress work.
- **Content lives on disk** in `memory/` and may be gitignored by the surrounding repo — that's fine;
  Claude reads it from disk regardless.

## Notes
- Defaults to **copy** (works everywhere). `--mode symlink` is opt-in and falls back to copy if the OS blocks symlinks.
- `--update` refreshes engine-owned files only; your content and edits are never touched.
- The `wiki-index-check` hook keys on a `…/.claude/memory/…` path; if your memory dir is mounted
  elsewhere, writes that go through the `~/.claude/memory` symlink still trigger it.
- Roadmap: submodule mode; optional extra skills (dictionary / postmortem).
