# claude-wiki-engine

A portable, Karpathy-style **LLM-wiki** for Claude Code — the curated `memory/` knowledge base plus
the `/wiki-ingest` and `/doc-review` skills that maintain it. One engine, installable into any Claude
config (a personal `~/.claude` or a shared repo), on Linux / macOS / Windows.

## Engine vs content
- **Engine** (this repo): the machinery — skills + the `memory/` framework templates + the CLAUDE.md policy block.
- **Content**: your actual wiki pages — they live in *your* memory store (in place, or your own repo). The engine never owns a page.

Update the engine once → every consumer re-syncs the same machinery; content is untouched.

## Install
Requires **Python 3** and **git**.
```
git clone https://github.com/oager/claude-wiki-engine.git && cd claude-wiki-engine
python3 install.py            # interactive wizard (recommended)
```
Non-interactive / automation:
```
python3 install.py --yes                        # accept all defaults
python3 install.py --into-repo /path/to/repo    # vendor the engine into a shared repo (a team/shared config)
python3 install.py --content-repo <git-url>     # clone a repo to BE your memory dir
python3 install.py --mode symlink               # link skills to this clone (auto-update); falls back to copy
python3 install.py --dry-run                     # print the plan, write nothing
python3 install.py --update                       # re-pull engine + re-copy skills; never touch content
```
`./install.sh` and `.\install.ps1` are thin shims that call `install.py`.

## What it installs
- `skills/wiki-ingest`, `skills/doc-review` → `<config>/skills/`
- `schema.md`, `overview.md`, `MEMORY.md`, `log.md` + `sources/ entities/ concepts/ synthesis/ raw/ raw/archive/` → `<config>/memory/` (seed-if-absent; never overwrites your pages)
- a reversible ingestion-policy block in `<config>/CLAUDE.md` (between `<!-- wiki-engine:start/end -->` sentinels)

## How it adapts (no hardcoding)
The installer resolves symlinks and writes to the **real** target, so it fits any layout — a personal
`~/.claude`, or a shared global that other configs symlink to — without per-user configuration.

## Notes
- Defaults to **copy** (works everywhere). `--mode symlink` is opt-in and falls back to copy if the OS blocks symlinks.
- `--update` refreshes engine-owned files only; your content and edits are never touched.
- Roadmap: submodule mode; optional extra skills (dictionary / postmortem / memory-sync delegators).
