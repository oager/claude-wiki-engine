#!/usr/bin/env python3
"""claude-wiki-engine installer - universal (Linux / macOS / Windows).

Installs the Karpathy-style LLM-wiki engine into a Claude Code config:
  - skills      (wiki-ingest, doc-review, wiki-sync)  -> <config>/skills/   (skip-if-exists)
  - extras      (optional workflow skills, opt-in)    -> <config>/skills/   (skip-if-exists)
  - framework   (schema.md, overview.md, MEMORY.md,   -> <config>/memory/   (seed-if-absent)
                 log.md, sources/entities/concepts/synthesis/raw/raw/archive)
  - hook        (wiki-index-check.cjs)                -> <config>/hooks/ + settings.json (safe merge)
  - CLAUDE.md   ingestion-policy block                -> <config>/CLAUDE.md  (sentinel-bounded)
  - session     (tools/session, with preflight/sync)  -> <config>/tools/session/  (skip-if-foreign)
  - CLAUDE.md   session-handoff block                 -> <config>/CLAUDE.md  (sentinel-bounded)

Detection-driven: every target is symlink-resolved and operated on at its REAL path, so the same
script adapts to any layout (personal ~/.claude, a shared claude-global, etc.) with no hardcoded
paths. Interactive by default; pass any flag (or --yes) to run non-interactively. Nothing is written
until you approve the printed plan (or pass --yes); --dry-run never writes.

Safe by design: existing skills are NOT overwritten (a skill may come from a plugin like ECC or be
the user's own -- use --force-skills to replace, backed up first). settings.json is merged
idempotently (backup, all other keys preserved). The installer NEVER commits the target repo.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Make console output UTF-8 + crash-proof on legacy codepages (e.g. Windows cp1252).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ENGINE = Path(__file__).resolve().parent
VERSION = (ENGINE / "VERSION").read_text(encoding="utf-8").strip() if (ENGINE / "VERSION").exists() else "0.0.0"

SKILL_SETS = {"core": ["wiki-ingest", "doc-review", "wiki-sync"]}
# Optional workflow skills. Independent of the wiki engine - install any, all, or none.
EXTRA_SKILLS = {
    "error-harden":        "Post-bugfix checklist: enumerate failure modes, auto-handle, alert, document",
    "karpathy-guidelines": "Behavioural guardrails against common LLM coding mistakes",
    "preflight":           "Session startup: sync the vault, load memory, orient, brief. Read-only",
    "recap":               "Generate a paste-ready handoff doc for another session or machine",
    "regression":          "Run the project regression suite and block on failure",
    "ripple":              "Consumer-impact sweep when data or interfaces change: what breaks downstream",
    "sync":                "End-of-session ritual: update memory, promote findings, push the vault safely",
    "tiered-build":        "Three-model build pipeline with hard gates between design, spec, and build",
    "tv":                  "Launch TradingView with a CDP debugging port for chart automation",
}
FRAMEWORK_FILES = ["schema.md", "overview.md", "MEMORY.md", "log.md"]
FRAMEWORK_DIRS = ["sources", "entities", "concepts", "synthesis", "raw", os.path.join("raw", "archive")]
# Canonical gitignore: the wiki SHOULD be version-controlled (history + sync). Only the raw inbox is
# local scratch — but keep the inbox README and the immutable archive of ingested originals.
RAW_GITIGNORE = (
    "# Wiki inbox: raw sources are local scratch — not version-controlled.\n"
    "# The wiki itself IS tracked; we only ignore unprocessed inbox files.\n"
    "# Keep the inbox README and the immutable archive of ingested originals.\n"
    "raw/*\n"
    "!raw/README.md\n"
    "!raw/archive/\n"
)
RAW_README = (
    "# raw/ - ingest inbox\n\n"
    "Drop raw sources here (`.md` / `.txt` / `.pdf` / images), then run `/wiki-ingest` to file them\n"
    "into the wiki. Ingested originals are MOVED to `raw/archive/` (kept forever, version-controlled).\n"
    "Everything else in this folder is local scratch and is gitignored.\n"
)
# (hook file under engine hooks/, the settings.json event it registers under, the tool matcher)
HOOKS = [
    ("wiki-index-check.cjs", "PostToolUse", "Write|Edit|MultiEdit"),
    ("wiki-sync-nudge.cjs", "Stop", ""),  # once-per-session /wiki-sync nudge (Stop hooks take no matcher)
]
SENTINEL_START = "<!-- wiki-engine:start -->"
SENTINEL_END = "<!-- wiki-engine:end -->"
SESSION_EXTRAS = {"preflight", "sync"}  # extras that need tools/session + the handoff templates
ENGINE_TAG = "source: claude-wiki-engine"
# SKILL.md files as earlier installers copied them, before skills carried ENGINE_TAG: an install whose bytes match
# one of these is an untouched engine copy, so --update may refresh it.
LEGACY_ENGINE_SKILL_SHA256 = {
    "427cd9b28e171f40db5a08d082d521819bf7ee67b8c92d94a360a6599bd23629",  # extra-skills/preflight/SKILL.md @701848e
    "19cc77f9364d9b4b0ad8d91619277cdf467425fe0e687dfcd96d67710e65f91f",  # extra-skills/sync/SKILL.md @701848e
    # every committed version of the core skills before they were tagged
    "fdc52c2bd3027fdd810db0eff27e40963e9d3d05d29b914f1f1e53d75d5ff389",  # skills/wiki-ingest/SKILL.md @26d1faa
    "619e5674c781551b807b05f4e7787cbad05dc2fcfaf3b9f4c2913a812f791134",  # skills/wiki-ingest/SKILL.md @aed4b19
    "5d6254cb9517719e88a28f4e4fd56a214ad673107458ab8034192046db4cdbc6",  # skills/doc-review/SKILL.md @26d1faa
    "3d317ea8ef76bbd57f5315be8ec307d5bdf47472c34e7b60d03defa3be3a1fa9",  # skills/doc-review/SKILL.md @aed4b19
    "fcaadce02a21f6c803667f34ab8e1c56be4134991cdddf993515743b571315ff",  # skills/wiki-sync/SKILL.md @377a75a
    # every committed version of the other extras before they were tagged
    "b599f6c10046577fe52d93f2877289f6ca3c34f6141c36c70f8f2bf5c59ab04b",  # extra-skills/error-harden @612edda
    "8acd43cb411fab4db68d9d82344e625b848bf2f2ceb157bab0e491eb22e34a42",  # extra-skills/karpathy-guidelines @eda2f4a
    "6a96000f9d26ced6bed2afb1fc5918b8591746b21a2ffbe89a588a5ec2a5ca0a",  # extra-skills/recap @63a11f8
    "ac7773bc419ca7cf611b11e9be6f11610bde6042946da9352036dbe98e529d2c",  # extra-skills/recap @ef4af76
    "3e3c704f7d864e6180c3e18c2be3143aa30391c6256392f3fdfe0e17a0ad5542",  # extra-skills/recap @612edda
    "65a17c49a96959e48a6c44ed43ce221598d950a9553caa375eb4ac312695ec9b",  # extra-skills/regression @612edda
    "307fdb866b43f447f3e803defaa22defcd6e9d84ffcdea49d492553b207cbc42",  # extra-skills/ripple @612edda
    "9ee435cfee0cb49bd0fa009c2bf2f54496698d721a279718131596d7b4b4a4ce",  # extra-skills/tiered-build @612edda
    "96262c63c15c6258e8d1fbac013ef77c1e01928b778c5a1cdebb697472f9e6a7",  # extra-skills/tv @c3c7de8
    "f2e75a032cc39d8b53bde881bcaf24c04336312b95c56b627e6eb7684f5885d4",  # extra-skills/tv @8923084
    "f592f40479da711b404c60261eaa43ac07a4eb862b6708fe744461f2396e62a4",  # extra-skills/tv @63a11f8
    "222accd9ffe9d4f41134cd1183fd8b44418053d539031f358572bb634ae7a902",  # extra-skills/tv @ef4af76
    "1219b2f905f7512a539f19d250426102aa146f5f8da8cf1f6c2d30d533ceb5c4",  # extra-skills/tv @612edda
}
SESSION_START = "<!-- session-handoff:start -->"
SESSION_END = "<!-- session-handoff:end -->"


# ------------------------- detection -------------------------

def git_root(path: Path) -> Path | None:
    """Repo top-level containing `path`, or None if not in a git repo / git absent."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path if path.is_dir() else path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except Exception:
        return None


def probe(path: Path) -> dict:
    """Resolve a target to its real path + describe how it's mounted (no writes)."""
    real = path.resolve()
    return {
        "path": path,
        "is_symlink": path.is_symlink(),
        "real": real,
        "exists": path.exists(),
        "git_root": git_root(real) if (path.exists() or path.parent.exists()) else None,
    }


def describe(label: str, info: dict) -> str:
    bits = []
    if info["is_symlink"]:
        bits.append(f"symlink -> {info['real']}")
    if info["git_root"]:
        bits.append(f"git: {info['git_root'].name}")
    if not info["exists"]:
        bits.append("absent - will create")
    tail = f"   ({','.join(bits)})" if bits else ""
    return f"  {label:<10} {info['path']}{tail}"


# ------------------------- plan (one path for dry-run + execute) -------------------------

class Plan:
    """Collects actions; renders them for review, then executes the SAME list."""

    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        self.steps: list[tuple[str, str, callable]] = []
        self.notes: list[str] = []

    def add(self, verb: str, detail: str, fn):
        self.steps.append((verb, detail, fn))

    def note(self, msg: str):
        self.notes.append(msg)

    def render(self) -> str:
        lines = ["-- Plan (nothing written yet) " + "-" * 30]
        for verb, detail, _ in self.steps:
            lines.append(f"  {verb:<6} {detail}")
        for n in self.notes:
            lines.append(f"  note   {n}")
        lines.append("-" * 56)
        return "\n".join(lines)

    def execute(self):
        for verb, detail, fn in self.steps:
            if self.dry_run:
                print(f"  [dry-run] {verb} {detail}")
                continue
            fn()
            print(f"  [ok] {verb} {detail}")


# ------------------------- filesystem actions -------------------------

def copy_tree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def link_or_copy(src: Path, dst: Path) -> str:
    """Try a symlink; fall back to copy if the OS refuses (e.g. Windows w/o dev-mode)."""
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        else:
            shutil.rmtree(dst)
    try:
        dst.symlink_to(src, target_is_directory=src.is_dir())
        return "symlink"
    except (OSError, NotImplementedError):
        copy_tree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
        return "copy (symlink unavailable)"


def _backup(path: Path):
    """Back up an existing file/dir before overwrite (.wikibak); best-effort, never raises."""
    if not path.exists() or path.is_symlink():
        return
    bak = Path(str(path) + ".wikibak")
    try:
        if path.is_dir():
            if not bak.exists():
                shutil.copytree(path, bak)
        else:
            shutil.copy2(path, bak)
    except Exception:
        pass


def _versioned_backup(config_base: Path, path: Path):
    """Timestamped backup OUTSIDE `skills/` -- unlike `_backup`'s single `.wikibak`, this keeps
    every prior version (so a later update doesn't silently overwrite the only backup) and never
    lands under `skills/` (a `<name>.wikibak/` dir there could be picked up as a duplicate skill).
    Copies into `<config_base>/.wikibak/<relative path>-<UTC timestamp>`; best-effort, never raises."""
    if not path.exists() or path.is_symlink():
        return
    try:
        rel = path.relative_to(config_base)
    except ValueError:
        rel = Path(path.name)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = config_base / ".wikibak" / f"{rel}-{ts}"
    n = 1
    while dest.exists():  # same-second collision -- disambiguate rather than clobber/crash
        n += 1
        dest = config_base / ".wikibak" / f"{rel}-{ts}-{n}"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, dest)
        else:
            shutil.copy2(path, dest)
    except Exception:
        pass


def read_text_keep_eol(path: Path) -> tuple[str, str]:
    """Decode as UTF-8, detect the file's line ending, and normalize the returned text to LF so
    callers can edit without EOL bookkeeping. write with `text.replace("\\n", eol)` to restore it."""
    raw = path.read_bytes()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    return text, eol


def block_span(text: str, start: str, end: str) -> tuple[int, int] | None | bool:
    """(start index, index just past the end marker) of the first well-formed block; None when neither marker is
    present; False when the markers are unpaired or out of order (end before start), which no edit may touch."""
    i = text.find(start)
    j = text.find(end, i + len(start)) if i >= 0 else -1
    if i >= 0 and j >= 0:
        return i, j + len(end)
    return None if (i < 0 and end not in text) else False


def _markers_broken(target: Path, start: str) -> None:
    print(f"  [warn] {target}: the {start} block markers are unpaired or out of order - left unchanged; "
          "fix them by hand and re-run")


def inject_block(claude_md: Path, block: str, start: str = SENTINEL_START, end: str = SENTINEL_END):
    """Insert/replace a sentinel-bounded block. Edits the real file (follows symlink)."""
    target = claude_md.resolve()
    managed = f"{start}\n{block.strip()}\n{end}"
    if target.exists():
        text, eol = read_text_keep_eol(target)
        span = block_span(text, start, end)
        if span is False:
            return _markers_broken(target, start)
        if span:
            new = text[:span[0]] + managed + text[span[1]:]
        else:
            sep = "" if text.endswith("\n") else "\n"
            new = text + sep + "\n" + managed + "\n"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        new, eol = managed + "\n", "\n"
    target.write_bytes(new.replace("\n", eol).encode("utf-8"))


def block_state(claude_md: Path, start: str = SENTINEL_START, end: str = SENTINEL_END) -> str:
    """'present', 'absent' (also: no/unreadable file) or 'broken' (see block_span)."""
    target = claude_md.resolve()
    if not target.is_file():
        return "absent"
    try:
        text, _ = read_text_keep_eol(target)
    except (OSError, UnicodeDecodeError):
        return "absent"
    span = block_span(text, start, end)
    return "broken" if span is False else "present" if span else "absent"


def remove_block(claude_md: Path, start: str = SENTINEL_START, end: str = SENTINEL_END):
    """Remove a sentinel-bounded block (inverse of inject_block, CRLF-safe); no-op when it is absent."""
    target = claude_md.resolve()
    if not target.is_file():
        return
    text, eol = read_text_keep_eol(target)
    span = block_span(text, start, end)
    if span is False:
        return _markers_broken(target, start)
    if span is None:
        return
    before, after = text[:span[0]], text[span[1]:]
    if after.startswith("\n"):   # the newline inject_block put after the end marker
        after = after[1:]
    if before.endswith("\n\n"):  # the blank line inject_block put before the start marker
        before = before[:-1]
    target.write_bytes((before + after).replace("\n", eol).encode("utf-8"))


def is_engine_skill(skill_dir: Path) -> bool:
    """A skill this engine installed carries `source: claude-wiki-engine` in its frontmatter, or is a
    byte-identical legacy copy (LEGACY_ENGINE_SKILL_SHA256). Requires real YAML frontmatter (text starting
    with `---`) so a body mention of the tag -- e.g. documentation referring to it -- is never mistaken for
    the engine's own marker."""
    try:
        data = (skill_dir / "SKILL.md").read_bytes()
    except OSError:
        return False
    if hashlib.sha256(data).hexdigest() in LEGACY_ENGINE_SKILL_SHA256:
        return True
    text = data.decode("utf-8", "replace")
    if not text.startswith("---"):
        return False
    head = text.split("\n---", 1)[0]
    return ENGINE_TAG in head


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


_RUNTIME_DIRS = {"__pycache__", ".pytest_cache"}  # written by running the code, never a user change


def _tree_files(root: Path) -> list[Path]:
    return sorted(p.relative_to(root) for p in root.rglob("*")
                  if p.is_file() and not _RUNTIME_DIRS & set(p.relative_to(root).parts))


def _same_tree(a: Path, b: Path) -> bool:
    """True when two dirs hold the same files with the same bytes, so replacing one with the other loses nothing."""
    try:
        fa, fb = _tree_files(a), _tree_files(b)
        return fa == fb and all(_same_file(a / r, b / r) for r in fa)
    except OSError:
        return False


def plan_skill_refresh(plan: Plan, base: Path, name: str, src: Path, dst: Path, label: str, reinstall: str):
    """--update for one present skill: replace it only when it is an engine copy (ENGINE_TAG or a legacy hash),
    backing it up to <config>/.wikibak/ first when it differs from the engine's. A symlinked install already
    tracks the engine; anything else is the user's own (or a plugin's) and is left alone."""
    if dst.is_symlink():
        plan.note(f"skip '{name}' (symlinked install - already tracks the engine)")
    elif is_engine_skill(dst):
        plan.add("copy", f"{src.parent.name}/{name} -> {dst}",
                 lambda s=src, d=dst, b=base: (None if _same_tree(s, d) else _versioned_backup(b, d),
                                               copy_tree(s, d)))
    else:
        plan.note(f"skip {label}'{name}' (not tagged as an engine copy; move the old copy out of "
                  f"skills/ (rename or delete it), then run: {reinstall})")


def session_conflicts(skills_real: Path, installing: set[str]) -> list[str]:
    """preflight/sync skills that will be the USER's own after this run: present, not an engine copy, and not
    being replaced by one. The session block tells the model to use /preflight and /sync, so wiring it next to a
    same-named skill of the user's would point it at their unrelated workflow."""
    return sorted(n for n in SESSION_EXTRAS
                  if n not in installing and ((skills_real / n).exists() or (skills_real / n).is_symlink())
                  and not is_engine_skill(skills_real / n))


def session_conflict_note(conflicts: list[str], update: bool = False, removed_block: bool = False) -> str:
    """One note for a preflight/sync conflict. An install skips the session system as a whole (both engine
    session skills, tools/session, the CLAUDE.md block): /preflight and /sync only work as a set."""
    names = " and ".join(f"skills/{n}" for n in conflicts)
    verb = "is your own skill" if len(conflicts) == 1 else "are your own skills"
    what = ("no refresh of preflight/sync, no tools/session, no CLAUDE.md block" if update
            else "engine preflight + sync skills, tools/session, CLAUDE.md block")
    note = (f"skip the session handoff system as a whole ({what}): {names} {verb}, not the engine's, and the "
            f"engine's /preflight and /sync only work together with their tools and block, which would send "
            f"/{conflicts[0]} to yours.")
    if removed_block:
        note += " Removing the engine's session-handoff block from CLAUDE.md (left by an earlier install)."
    return note + " To use it, rename or remove yours, then run: install.py --extras preflight,sync"


def home_claude() -> Path:
    """Where the session skills look for their tools: they call ~/.claude/tools/session by that path."""
    return Path.home() / ".claude"


def session_plan(plan: Plan, base: Path, update: bool, claude_md: bool):
    """What /preflight and /sync need besides SKILL.md: tools/session, handoff templates, _USER.md, a CLAUDE.md block."""
    if base.resolve() != home_claude().resolve():
        # The skills hard-code the tool path; lib.vault() reads CLAUDE_VAULT (default ~/.claude) for handoffs only.
        plan.note(f"the session skills run python3 ~/.claude/tools/session/... by that fixed path, so for this "
                  f"install they work only after you edit that path (also written $HOME/.claude/tools/session) "
                  f"to {base / 'tools' / 'session'} in skills/preflight and skills/sync; the tools keep handoffs "
                  f"in ~/.claude/handoffs unless CLAUDE_VAULT is set (set it to {base} in the environment Claude "
                  "Code runs in - it moves the vault only, not the tool path)")
    src_tools, dst_tools = ENGINE / "extra-tools" / "session", base / "tools" / "session"
    if dst_tools.exists() and not (dst_tools / ".engine").exists():
        plan.note("skip tools/session (present and not from the engine - not overwriting)")
    elif dst_tools.exists() and not update:
        plan.note("keep tools/session (engine copy present; --update refreshes it)")
    else:
        plan.add("copy", f"extra-tools/session -> {dst_tools}",
                 lambda s=src_tools, d=dst_tools, b=base: (
                     d.parent.mkdir(parents=True, exist_ok=True),
                     None if not d.exists() or _same_tree(s, d) else _versioned_backup(b, d), copy_tree(s, d)))
    hand = base / "handoffs"
    for name in ("_TEMPLATE.md", "_USER.template.md"):
        s, d = ENGINE / "templates" / "handoffs" / name, hand / name
        if not d.exists():
            plan.add("seed", f"templates/handoffs/{name} -> {hand}",
                     lambda s=s, d=d: (d.parent.mkdir(parents=True, exist_ok=True), shutil.copy2(s, d)))
        elif not _same_file(s, d):  # edited (or an older engine copy): keep the old one under .wikibak/
            plan.add("copy", f"templates/handoffs/{name} -> {hand} (yours backed up to .wikibak/)",
                     lambda s=s, d=d, b=base: (_versioned_backup(b, d), shutil.copy2(s, d)))
    user = hand / "_USER.md"
    if user.exists():
        plan.note("keep handoffs/_USER.md (yours)")
    else:
        tmpl = ENGINE / "templates" / "handoffs" / "_USER.template.md"
        plan.add("seed", f"_USER.md -> {hand}",
                 lambda s=tmpl, d=user: (d.parent.mkdir(parents=True, exist_ok=True), shutil.copy2(s, d)))
    if claude_md:
        block = (ENGINE / "claude-md" / "session-handoff.md").read_text(encoding="utf-8")
        cmd = base / "CLAUDE.md"
        plan.add("edit", f"CLAUDE.md (+ session-handoff block) -> {cmd}",
                 lambda c=cmd, b=block: inject_block(c, b, SESSION_START, SESSION_END))


_SNAPSHOTTED: set[str] = set()  # files backed up THIS run -- snapshot once, before ANY wiring


def merge_hook(settings_path: Path, command: str, event: str, matcher: str):
    """Register (or RECONCILE) a hook command in settings.json: backup first, preserve every other
    key, keep a trailing newline. Surgical -- never touches the owner's other settings, never commits.

    The .wikibak snapshot is taken ONCE PER RUN, not per hook. Wiring two hooks in one run used to
    overwrite the backup on the second call, so .wikibak held a mid-install checkpoint (already
    containing the first hook) instead of the true pre-install state -- useless for reverting.

    Idempotent AND self-healing: matches an existing entry by the hook SCRIPT FILENAME (the stable
    identity), so a stale/broken command for the same hook -- e.g. a pre-fix Windows backslash path
    that a POSIX shell mangles -- is UPDATED in place instead of left untouched. Without this, a fix to
    the generated command (like the as_posix path fix) could never reach an already-installed hook: the
    old filename-substring check treated 'same filename' as 'already correct' and skipped."""
    import json
    sp = settings_path.resolve() if settings_path.is_symlink() else settings_path
    try:
        d = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    except Exception:
        return  # never risk corrupting an unreadable/locked settings.json
    arr = d.setdefault("hooks", {}).setdefault(event, [])
    script = command.split()[-1]                      # the hook script path (last token of `node <path>`)
    fname = script.replace("\\", "/").split("/")[-1]  # its filename = the hook's stable identity
    found = updated = False
    for e in arr:
        for h in e.get("hooks", []):
            hc = h.get("command", "")
            hc_fname = hc.replace("\\", "/").split("/")[-1] if hc else ""
            if hc_fname == fname:                      # same hook script -> this is our entry
                found = True
                if hc != command:                      # stale/broken command -> reconcile in place
                    h["command"] = command
                    updated = True
    if found and not updated:
        return  # already registered AND current (idempotent no-op)
    if sp.exists() and str(sp) not in _SNAPSHOTTED:
        shutil.copy2(sp, str(sp) + ".wikibak")
        _SNAPSHOTTED.add(str(sp))
    if not found:
        entry = {"hooks": [{"type": "command", "command": command}]}
        if matcher:
            entry = {"matcher": matcher, **entry}      # Stop/SessionStart hooks take no matcher
        arr.append(entry)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")


# ------------------------- prompts -------------------------

def ask(prompt: str, default: str) -> str:
    try:
        ans = input(f"{prompt} [{default}] >").strip()
    except EOFError:
        return default
    return ans or default


def confirm(prompt: str, default_yes: bool = True) -> bool:
    d = "Y/n" if default_yes else "y/N"
    ans = ask(prompt, d)
    if ans in ("Y/n", "y/N"):
        return default_yes
    return ans.lower().startswith("y")


def choose(prompt: str, options: list[tuple[str, str]], default: int = 1) -> int:
    print(prompt)
    for i, (label, desc) in enumerate(options, 1):
        mark = "  <- recommended" if i == default else ""
        print(f"  {i}) {label:<10} {desc}{mark}")
    ans = ask("Choose", str(default))
    try:
        n = int(ans)
        return n if 1 <= n <= len(options) else default
    except ValueError:
        return default


# ------------------------- wizard -------------------------

def pick_extras() -> list[str]:
    """Offer the optional workflow skills. Returns the chosen names (possibly empty)."""
    print("\n[6/6] Optional extra skills - independent of the wiki engine, install any or none:")
    names = list(EXTRA_SKILLS)
    for i, n in enumerate(names, 1):
        print(f"  {i:>2}) {n:<20} {EXTRA_SKILLS[n]}")
    print("\n  Enter numbers or names (comma/space separated), 'all', or 'none'.")
    ans = ask("Extras", "none").strip().lower()
    if ans in ("", "none", "n"):
        return []
    if ans in ("all", "a"):
        return names
    chosen, unknown = [], []
    for tok in ans.replace(",", " ").split():
        if tok.isdigit():
            i = int(tok)
            if 1 <= i <= len(names):
                chosen.append(names[i - 1])
            else:
                unknown.append(tok)
        elif tok in EXTRA_SKILLS:
            chosen.append(tok)
        else:
            unknown.append(tok)
    if unknown:
        print(f"  ignored (not a skill): {', '.join(unknown)}")
    seen = dict.fromkeys(chosen)  # de-dupe, keep order
    print(f"  selected: {', '.join(seen) if seen else 'none'}")
    return list(seen)


def resolve_extras(arg: str | None) -> list[str]:
    """Non-interactive --extras parsing: 'all', 'none', or a comma-separated list."""
    if not arg or arg.lower() == "none":
        return []
    if arg.lower() == "all":
        return list(EXTRA_SKILLS)
    out, unknown = [], []
    for tok in arg.replace(",", " ").split():
        (out if tok in EXTRA_SKILLS else unknown).append(tok)
    if unknown:
        print(f"warning: unknown extra skill(s) ignored: {', '.join(unknown)}")
    return list(dict.fromkeys(out))


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude"))


def run_wizard(cfg: dict) -> dict:
    print(f"\n  claude-wiki-engine - setup (v{VERSION})\n")

    # [1] target config
    base = claude_dir()
    print("[1/5] Target config")
    for lbl, sub in (("skills", "skills"), ("memory", "memory"), ("CLAUDE.md", "CLAUDE.md")):
        print(describe(lbl, probe(base / sub)))
    t = choose("  Install into…", [
        ("personal", f"this config - {base}  (follows your symlinks)"),
        ("repo", "vendor into a specific repo (e.g. a shared claude-global)"),
    ], default=1)
    if t == 2:
        repo = ask("  Repo path", str(base))
        cfg["config_base"] = Path(repo).expanduser()
    else:
        cfg["config_base"] = base

    # [2] engine delivery
    m = choose("\n[2/5] How to install the skills", [
        ("copy", "real files; update later with --update"),
        ("symlink", "auto-update on git pull (falls back to copy if OS blocks symlinks)"),
    ], default=1)
    cfg["mode"] = "copy" if m == 1 else "symlink"

    # [3] content location
    c = choose("\n[3/5] Where should your wiki CONTENT live?", [
        ("in-place", f"{cfg['config_base']}/memory"),
        ("own repo", "clone a git repo to BE your memory dir"),
        ("custom", "a path you specify"),
    ], default=1)
    if c == 2:
        cfg["content_repo"] = ask("  Content repo URL", "")
        cfg["memory"] = cfg["config_base"] / "memory"
    elif c == 3:
        cfg["memory"] = Path(ask("  Memory path", str(cfg["config_base"] / "memory"))).expanduser()
    else:
        cfg["memory"] = cfg["config_base"] / "memory"

    # [4] CLAUDE.md policy
    cfg["claude_md"] = confirm(
        f"\n[4/5] Add the ingestion-policy block to {cfg['config_base'].name}/CLAUDE.md (reversible)?")

    # [5] skills + hook
    cfg["skills"] = SKILL_SETS["core"]
    print(f"\n[5/6] Core skills: {', '.join(cfg['skills'])} (skip any already present) + wiki-index-check hook")

    # [6] optional extra skills
    cfg["extra_skills"] = pick_extras()
    return cfg


# ------------------------- build + run -------------------------

def build_plan(cfg: dict) -> Plan:
    plan = Plan(cfg["dry_run"])
    base: Path = cfg["config_base"]
    skills_dir = (base / "skills")
    memory_dir: Path = cfg["memory"]
    mode = cfg["mode"]

    # content repo: clone to BE the memory dir (must be empty/absent)
    if cfg.get("content_repo"):
        url = cfg["content_repo"]
        if memory_dir.exists() and any(memory_dir.iterdir()):
            plan.note(f"SKIP clone: {memory_dir} exists and is non-empty - seeding in place instead")
        else:
            plan.add("clone", f"{url} -> {memory_dir}",
                     lambda u=url, d=memory_dir: subprocess.run(["git", "clone", u, str(d)], check=True))

    # skills - SKIP existing (could be a plugin/ECC or the user's own); --force-skills replaces (backup first)
    skills_real = skills_dir.resolve() if skills_dir.is_symlink() else skills_dir
    for name in cfg["skills"]:
        src = ENGINE / "skills" / name
        dst = skills_real / name
        if dst.exists() and not cfg.get("force_skills"):
            why = ("engine copy present; --update refreshes it" if is_engine_skill(dst)
                   else "not overwriting; --force-skills to replace")
            plan.note(f"skip skill '{name}' (already present - {why})")
            continue
        if mode == "symlink":
            plan.add("link", f"{name} -> {dst}",
                     lambda s=src, d=dst: (d.parent.mkdir(parents=True, exist_ok=True), _backup(d), link_or_copy(s, d)))
        else:
            plan.add("copy", f"skills/{name} -> {dst}",
                     lambda s=src, d=dst: (d.parent.mkdir(parents=True, exist_ok=True), _backup(d), copy_tree(s, d)))

    # optional extra skills - same skip-if-exists safety as the core set
    extras = cfg.get("extra_skills") or []
    # Session system (preflight + sync + tools/session + CLAUDE.md block) goes in as a whole or not at all: never
    # next to a /preflight or /sync that will still be the user's own after this plan.
    session_wanted = SESSION_EXTRAS & set(extras)
    session_writes = {n for n in session_wanted if (ENGINE / "extra-skills" / n).exists()
                      and (cfg.get("force_skills") or not (skills_real / n).exists())}
    conflicts = session_conflicts(skills_real, session_writes) if session_wanted else []
    if conflicts:
        plan.note(session_conflict_note(conflicts))
    for name in extras:
        src = ENGINE / "extra-skills" / name
        dst = skills_real / name
        if name in SESSION_EXTRAS and conflicts:
            continue  # covered by the one conflict note above
        if not src.exists():
            plan.note(f"skip extra '{name}' (not in this engine version)")
            continue
        if dst.exists() and not cfg.get("force_skills"):
            why = ("engine copy present; --update refreshes it" if is_engine_skill(dst)
                   else "not overwriting; --force-skills to replace")
            plan.note(f"skip extra '{name}' (already present - {why})")
            continue
        if mode == "symlink":
            plan.add("link", f"{name} (extra) -> {dst}",
                     lambda s=src, d=dst: (d.parent.mkdir(parents=True, exist_ok=True), _backup(d), link_or_copy(s, d)))
        else:
            plan.add("copy", f"extra-skills/{name} -> {dst}",
                     lambda s=src, d=dst: (d.parent.mkdir(parents=True, exist_ok=True), _backup(d), copy_tree(s, d)))

    if session_wanted and not conflicts:
        session_plan(plan, base, update=False, claude_md=cfg["claude_md"])

    # framework (seed-if-absent)
    mem_real = memory_dir.resolve() if memory_dir.is_symlink() else memory_dir
    for f in FRAMEWORK_FILES:
        src, dst = ENGINE / "memory-template" / f, mem_real / f
        if dst.exists():
            plan.note(f"keep {f} (exists)")
        else:
            plan.add("seed", f"{f} -> {mem_real}",
                     lambda s=src, d=dst: (d.parent.mkdir(parents=True, exist_ok=True), shutil.copy2(s, d)))
    for d in FRAMEWORK_DIRS:
        dst = mem_real / d
        if not dst.exists():
            plan.add("mkdir", f"memory/{d}/", lambda dd=dst: dd.mkdir(parents=True, exist_ok=True))

    # gitignore the inbox (seed-if-absent): wiki stays tracked, raw/* is scratch, archive is kept.
    gi = mem_real / ".gitignore"
    if gi.exists():
        plan.note("keep memory/.gitignore (exists)")
    else:
        plan.add("seed", f".gitignore (track wiki; ignore raw/*, keep archive) -> {mem_real}",
                 lambda g=gi: (g.parent.mkdir(parents=True, exist_ok=True), g.write_text(RAW_GITIGNORE, encoding="utf-8")))
    rr = mem_real / "raw" / "README.md"
    if not rr.exists():
        plan.add("seed", f"raw/README.md (inbox doc) -> {mem_real}",
                 lambda r=rr: (r.parent.mkdir(parents=True, exist_ok=True), r.write_text(RAW_README, encoding="utf-8")))

    # hooks - copy the (non-blocking) wiki-index-check + safe idempotent settings.json merge
    if cfg.get("hooks", True):
        hooks_real = base / "hooks"
        for hf, event, matcher in HOOKS:
            hsrc, hdst = ENGINE / "hooks" / hf, hooks_real / hf
            if not hsrc.exists():
                continue
            plan.add("hook", f"{hf} -> {hdst}",
                     lambda s=hsrc, d=hdst: (d.parent.mkdir(parents=True, exist_ok=True), shutil.copy2(s, d)))
            cmd, sp = f"node {hdst.as_posix()}", base / "settings.json"
            plan.add("wire", f"settings.json[{event}] += {hf} (idempotent, backup)",
                     lambda c=cmd, e=event, m=matcher, s=sp: merge_hook(s, c, e, m))

    # CLAUDE.md policy block
    if cfg["claude_md"]:
        cmd = base / "CLAUDE.md"
        block = (ENGINE / "claude-md" / "ingestion-policy.md").read_text(encoding="utf-8")
        plan.add("edit", f"CLAUDE.md (+ sentinel block) -> {cmd.resolve() if cmd.exists() else cmd}",
                 lambda c=cmd, b=block: inject_block(c, b))

    # version stamp
    stamp = mem_real / ".wiki-engine-version"
    plan.add("stamp", f".wiki-engine-version = {VERSION}",
             lambda s=stamp: (s.parent.mkdir(parents=True, exist_ok=True), s.write_text(VERSION + "\n", encoding="utf-8")))
    return plan


def do_update(cfg: dict):
    print("Updating engine + re-copying ITS skills + refreshing the hook (content untouched)…")
    if not cfg.get("no_pull"):
        subprocess.run(["git", "-C", str(ENGINE), "pull", "--ff-only"], check=False)
    plan = Plan(cfg["dry_run"])
    base, skills_dir = cfg["config_base"], cfg["config_base"] / "skills"
    skills_real = skills_dir.resolve() if skills_dir.is_symlink() else skills_dir
    for name in cfg["skills"]:
        src, dst = ENGINE / "skills" / name, skills_real / name
        if dst.exists() or dst.is_symlink():
            plan_skill_refresh(plan, base, name, src, dst, "", "install.py")
        else:
            plan.add("copy", f"skills/{name} -> {dst}",
                     lambda s=src, d=dst: (d.parent.mkdir(parents=True, exist_ok=True), copy_tree(s, d)))
    if cfg.get("hooks", True):
        for hf, event, matcher in HOOKS:
            hsrc, hdst = ENGINE / "hooks" / hf, base / "hooks" / hf
            if hsrc.exists():
                plan.add("hook", f"{hf} -> {hdst}",
                         lambda s=hsrc, d=hdst: (d.parent.mkdir(parents=True, exist_ok=True), shutil.copy2(s, d)))
                # Re-wire settings.json too (idempotent + self-healing) so an update actually
                # REPAIRS a stale/broken command on an existing install, not just the hook file.
                cmd_hook, sp = f"node {hdst.as_posix()}", base / "settings.json"
                plan.add("wire", f"settings.json[{event}] reconcile {hf}",
                         lambda c=cmd_hook, e=event, m=matcher, s=sp: merge_hook(s, c, e, m))
    if cfg["claude_md"]:
        cmd = base / "CLAUDE.md"
        block = (ENGINE / "claude-md" / "ingestion-policy.md").read_text(encoding="utf-8")
        plan.add("edit", f"CLAUDE.md block refresh -> {cmd.resolve() if cmd.exists() else cmd}",
                 lambda c=cmd, b=block: inject_block(c, b))
    # An --update never changes who owns preflight/sync. While either is the user's own, the engine's session
    # skills are left exactly as they are: a refresh could turn a working older /preflight (which needed no
    # tools) into one that calls tools/session, which the conflict path withholds.
    engine_session = any(is_engine_skill(skills_real / n) for n in SESSION_EXTRAS)
    conflicts = session_conflicts(skills_real, set())
    for name in EXTRA_SKILLS:
        src, dst = ENGINE / "extra-skills" / name, skills_real / name
        if name in SESSION_EXTRAS and conflicts:
            continue  # covered by the one conflict note below
        if dst.exists() and src.exists():
            plan_skill_refresh(plan, base, name, src, dst, "extra ", f"install.py --extras {name}")
    cmd = base / "CLAUDE.md"
    state = block_state(cmd, SESSION_START, SESSION_END) if conflicts and cfg["claude_md"] else "absent"
    stale = state == "present"
    if state == "broken":
        plan.note(f"CLAUDE.md: session-handoff markers are unpaired or out of order - left unchanged ({cmd})")
    if conflicts and (engine_session or stale):
        plan.note(session_conflict_note(conflicts, update=True, removed_block=stale))
        if stale:  # an earlier install wired the block next to the user's own skill: take it back out
            plan.add("edit", f"CLAUDE.md (- session-handoff block) -> {cmd.resolve()}",
                     lambda c=cmd: remove_block(c, SESSION_START, SESSION_END))
    elif engine_session:
        session_plan(plan, base, update=True, claude_md=cfg["claude_md"])
    print(plan.render())
    if cfg["dry_run"]:
        print("\n(dry-run - nothing was written)")
        return
    if not (cfg.get("yes") or confirm("\nProceed?", default_yes=False)):
        print("aborted - nothing written")
        return
    plan.execute()


def main():
    ap = argparse.ArgumentParser(description="Install the claude-wiki-engine into a Claude Code config.")
    ap.add_argument("--into-repo", help="vendor the engine into this repo path instead of ~/.claude")
    ap.add_argument("--memory", help="content/memory directory (default: <config>/memory)")
    ap.add_argument("--content-repo", help="git URL to clone AS the memory dir")
    ap.add_argument("--mode", choices=["copy", "symlink"], help="how to install skills (default: copy)")
    ap.add_argument("--force-skills", action="store_true", help="replace existing skills (backs up first); default skips them")
    ap.add_argument("--no-hooks", action="store_true", help="do not install the wiki-index-check hook")
    ap.add_argument("--no-claude-md", action="store_true", help="skip the CLAUDE.md policy block")
    ap.add_argument("--skills", choices=list(SKILL_SETS), default="core")
    ap.add_argument("--extras", metavar="LIST",
                    help="optional extra skills: 'all', 'none' (default), or a comma-separated "
                         f"subset of: {', '.join(EXTRA_SKILLS)}")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit; write nothing")
    ap.add_argument("-y", "--yes", action="store_true", help="accept defaults, no prompts")
    ap.add_argument("--update", action="store_true", help="re-pull engine + re-copy ITS skills/hook; never touch content")
    args = ap.parse_args()

    flags_given = any([args.into_repo, args.memory, args.content_repo, args.mode, args.force_skills,
                       args.no_hooks, args.no_claude_md, args.update])
    interactive = not (args.yes or flags_given) and sys.stdin.isatty()

    base = Path(args.into_repo).expanduser() if args.into_repo else claude_dir()
    cfg = {
        "dry_run": args.dry_run,
        "config_base": base,
        "mode": args.mode or "copy",
        "memory": Path(args.memory).expanduser() if args.memory else base / "memory",
        "content_repo": args.content_repo,
        "claude_md": not args.no_claude_md,
        "skills": SKILL_SETS[args.skills],
        "force_skills": args.force_skills,
        "hooks": not args.no_hooks,
        "extra_skills": resolve_extras(args.extras),
        "yes": args.yes,
    }
    if interactive:
        preset_extras = cfg["extra_skills"]
        cfg = run_wizard(cfg)
        if args.extras:            # explicit flag wins over the wizard prompt
            cfg["extra_skills"] = preset_extras
        cfg["dry_run"] = args.dry_run
    elif not args.yes and not flags_given:
        print("non-interactive (no TTY) - using defaults")

    if args.update:
        do_update(cfg)
        return

    plan = build_plan(cfg)
    print("\n" + plan.render())
    if cfg["dry_run"]:
        print("\n(dry-run - nothing was written)")
        return
    if not (args.yes or confirm("\nProceed?", default_yes=False)):
        print("aborted - nothing written")
        return
    plan.execute()
    print(f"\n  [ok] installed (v{VERSION}). Note: GateGuard may already come from the ECC plugin - "
          f"the installer skips existing skills, so nothing was duplicated. Next: open Claude, run /wiki-ingest.")


if __name__ == "__main__":
    main()
