# Error Handling: installer (`install.py`)

Last updated: 2026-11-03

Session tools have their own file: `extra-tools/session/ERROR_HANDLING.md`.

## 1. Replacing an installed skill or tool

### Backups before a replace (fixed 2026-11-03, field report PR #21)
- What broke: `--force-skills` backed each skill up to a sibling `skills/<name>.wikibak/` (holding a `SKILL.md`, so
  Claude Code loaded it as a second copy of the skill), even when the installed copy was identical to the engine's.
- Fix: `--force-skills` goes through `_force_replace`, the same path `--update` uses: a timestamped copy under
  `<config>/.wikibak/<relative path>-<UTC ts>` only when the installed copy differs. A symlinked skill is only
  unlinked (its target is never touched), so it needs no backup.
- Alert: a failed backup prints `[warn] backup failed for <path> ...` and leaves that skill unchanged.
- Recovery: copy the wanted version back from `<config>/.wikibak/`.

### Read-only and locked files (Windows)
- Handling: `_rmtree` clears the read-only bit and retries once. Windows cannot delete a read-only file, and
  `copy2` carries that bit over from a read-only engine checkout.
- Alert: a second failure (a file held open by a running Claude Code, antivirus, a sync client) stops the run:
  `[fail] <step>: could not remove <path> (...); close Claude Code or any other program using files there, then
  run the installer again`, exit code 1. Any other `OSError` in a step (disk full, a plain file where a skill dir
  should be) stops the same way instead of a traceback.
- Recovery: close the program holding the files and run the same command again. Steps before the failure are done;
  re-running repeats them harmlessly.

## Gaps (not yet handled)

| Gap | Impact | Priority | Status |
|-----|--------|----------|--------|
| A `[fail]` partway through removing a skill leaves that skill dir half-deleted | Skill broken until the installer is re-run; an edited copy is safe in `<config>/.wikibak/` (backed up before the remove) | Low | Documented: re-run restores it |
