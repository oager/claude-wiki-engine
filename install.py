#!/usr/bin/env python3
"""claude-wiki-engine installer - universal (Linux / macOS / Windows).

Installs the Karpathy-style LLM-wiki engine into a Claude Code config:
  - skills      (wiki-ingest, doc-review, wiki-sync)  -> <config>/skills/   (skip-if-exists)
  - framework   (schema.md, overview.md, MEMORY.md,   -> <config>/memory/   (seed-if-absent)
                 log.md, sources/entities/concepts/synthesis/raw/raw/archive)
  - hook        (wiki-index-check.cjs)                -> <config>/hooks/ + settings.json (safe merge)
  - CLAUDE.md   ingestion-policy block                -> <config>/CLAUDE.md  (sentinel-bounded)

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
import os
import shutil
import subprocess
import sys
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
FRAMEWORK_FILES = ["schema.md", "overview.md", "MEMORY.md", "log.md"]
FRAMEWORK_DIRS = ["sources", "entities", "concepts", "synthesis", "raw", os.path.join("raw", "archive")]
# (hook file under engine hooks/, the settings.json event it registers under, the tool matcher)
HOOKS = [
    ("wiki-index-check.cjs", "PostToolUse", "Write|Edit|MultiEdit"),
    ("wiki-sync-nudge.cjs", "Stop", ""),  # once-per-session /wiki-sync nudge (Stop hooks take no matcher)
]
SENTINEL_START = "<!-- wiki-engine:start -->"
SENTINEL_END = "<!-- wiki-engine:end -->"


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


def read_text_keep_eol(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    return raw.decode("utf-8"), eol


def inject_block(claude_md: Path, block: str):
    """Insert/replace the sentinel-bounded policy block. Edits the real file (follows symlink)."""
    target = claude_md.resolve()
    managed = f"{SENTINEL_START}\n{block.strip()}\n{SENTINEL_END}"
    if target.exists():
        text, eol = read_text_keep_eol(target)
        if SENTINEL_START in text and SENTINEL_END in text:
            pre = text.split(SENTINEL_START)[0]
            post = text.split(SENTINEL_END, 1)[1]
            new = pre + managed + post
        else:
            sep = "" if text.endswith("\n") else "\n"
            new = text + sep + "\n" + managed + "\n"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        new, eol = managed + "\n", "\n"
    target.write_bytes(new.replace("\n", eol).encode("utf-8"))


def merge_hook(settings_path: Path, command: str, event: str, matcher: str):
    """Idempotently add a hook command to settings.json: backup first, preserve every other key,
    keep a trailing newline. Surgical -- never touches the owner's other settings, never commits."""
    import json
    sp = settings_path.resolve() if settings_path.is_symlink() else settings_path
    try:
        d = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    except Exception:
        return  # never risk corrupting an unreadable/locked settings.json
    arr = d.setdefault("hooks", {}).setdefault(event, [])
    tail = command.split("/")[-1]
    if any(tail in h.get("command", "") for e in arr for h in e.get("hooks", [])):
        return  # already registered (idempotent)
    if sp.exists():
        shutil.copy2(sp, str(sp) + ".wikibak")
    entry = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        entry = {"matcher": matcher, **entry}   # Stop/SessionStart hooks take no matcher
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
    print(f"\n[5/5] Skills: {', '.join(cfg['skills'])} (skip any already present) + wiki-index-check hook")
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
            plan.note(f"skip skill '{name}' (already present - not overwriting; --force-skills to replace)")
            continue
        if mode == "symlink":
            plan.add("link", f"{name} -> {dst}",
                     lambda s=src, d=dst: (d.parent.mkdir(parents=True, exist_ok=True), _backup(d), link_or_copy(s, d)))
        else:
            plan.add("copy", f"skills/{name} -> {dst}",
                     lambda s=src, d=dst: (d.parent.mkdir(parents=True, exist_ok=True), _backup(d), copy_tree(s, d)))

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

    # hooks - copy the (non-blocking) wiki-index-check + safe idempotent settings.json merge
    if cfg.get("hooks", True):
        hooks_real = base / "hooks"
        for hf, event, matcher in HOOKS:
            hsrc, hdst = ENGINE / "hooks" / hf, hooks_real / hf
            if not hsrc.exists():
                continue
            plan.add("hook", f"{hf} -> {hdst}",
                     lambda s=hsrc, d=hdst: (d.parent.mkdir(parents=True, exist_ok=True), shutil.copy2(s, d)))
            cmd, sp = f"node {hdst}", base / "settings.json"
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
    subprocess.run(["git", "-C", str(ENGINE), "pull", "--ff-only"], check=False)
    plan = Plan(cfg["dry_run"])
    base, skills_dir = cfg["config_base"], cfg["config_base"] / "skills"
    skills_real = skills_dir.resolve() if skills_dir.is_symlink() else skills_dir
    for name in cfg["skills"]:
        src, dst = ENGINE / "skills" / name, skills_real / name
        plan.add("copy", f"skills/{name} -> {dst}",
                 lambda s=src, d=dst: (d.parent.mkdir(parents=True, exist_ok=True), copy_tree(s, d)))
    if cfg.get("hooks", True):
        for hf, event, matcher in HOOKS:
            hsrc, hdst = ENGINE / "hooks" / hf, base / "hooks" / hf
            if hsrc.exists():
                plan.add("hook", f"{hf} -> {hdst}",
                         lambda s=hsrc, d=hdst: (d.parent.mkdir(parents=True, exist_ok=True), shutil.copy2(s, d)))
    cmd = base / "CLAUDE.md"
    block = (ENGINE / "claude-md" / "ingestion-policy.md").read_text(encoding="utf-8")
    plan.add("edit", f"CLAUDE.md block refresh -> {cmd.resolve() if cmd.exists() else cmd}",
             lambda c=cmd, b=block: inject_block(c, b))
    print(plan.render())
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
    }
    if interactive:
        cfg = run_wizard(cfg)
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
