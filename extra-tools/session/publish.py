#!/usr/bin/env python3
# ~/.claude/tools/session/publish.py
"""Copy the generic session skills and tools into a claude-wiki-engine checkout, after the leak guard passes.

    publish.py --engine <path> [--dry-run]

The vault is the source of truth. Personal files never ship (self_ids.json, _USER.md, project handoffs, caches).
Always exits 0 and prints one JSON object.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import leakguard  # noqa: E402
import lib  # noqa: E402

MAPPING = {
    "skills/preflight": "extra-skills/preflight",
    "skills/sync": "extra-skills/sync",
    "skills/ripple": "extra-skills/ripple",
    "tools/session": "extra-tools/session",
    "handoffs/_TEMPLATE.md": "templates/handoffs/_TEMPLATE.md",
    "handoffs/_USER.template.md": "templates/handoffs/_USER.template.md",
    "tools/session/claude-md-block.md": "claude-md/session-handoff.md",
}
EXCLUDE = shutil.ignore_patterns(
    "self_ids.json", "_USER.md", "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache", ".mypy_cache"
)
TAG = "source: claude-wiki-engine"


def _tag_skill(p):
    text = p.read_text(encoding="utf-8")
    if text.startswith("---\n") and TAG not in text.split("\n---", 1)[0]:
        p.write_text(text.replace("\n", f"\n{TAG}\n", 1), encoding="utf-8")  # right after the opening '---'


def _build(vault, stage, version):
    for src_rel, dst_rel in MAPPING.items():
        src, dst = vault / src_rel, stage / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=EXCLUDE)
        else:
            shutil.copy2(src, dst)
    for skill in stage.glob("extra-skills/*/SKILL.md"):
        _tag_skill(skill)
    (stage / "extra-tools/session/.engine").write_text(version + "\n", encoding="utf-8")


def publish(engine, vault=None, needles=None, dry_run=False):
    engine, vault = Path(engine), Path(vault or lib.vault())
    if needles is None:
        profile = lib.user_file()["profile"]
        # publish_deny alone is not enough to guard with: require at least one real identity needle
        # (name/email/host) so a profile with only publish_deny still refuses, rather than shipping
        # personal strings the guard was never actually told to look for.
        identity_needles = leakguard.needles({"identity": profile.get("identity") or {}})
        if not identity_needles:
            return {"status": "refused", "reason": "no identity strings to guard with; fill _USER.md identity first"}
        needles = leakguard.needles(profile)
    needles = sorted({n.strip().lower() for n in needles if n and n.strip()})
    if not needles:
        return {"status": "refused", "reason": "no identity strings to guard with; fill _USER.md identity first"}
    vf = engine / "VERSION"
    version = vf.read_text(encoding="utf-8").strip() if vf.is_file() else "0.0.0"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        _build(vault, stage, version)
        files = {p.relative_to(stage).as_posix(): p for p in stage.rglob("*") if p.is_file()}
        texts = {}
        for rel, p in files.items():
            try:
                texts[rel] = p.read_text(encoding="utf-8")
            except ValueError:  # nothing we publish is binary: refuse rather than ship unscanned bytes
                return {"status": "refused", "reason": f"binary file in publish set: {rel}"}
        hits = leakguard.find(texts, needles)
        if hits:
            return {"status": "refused", "hits": hits[:100]}
        if dry_run:
            return {"status": "dry-run", "files": sorted(files)}
        for dst_rel in MAPPING.values():
            target = engine / dst_rel
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            src = stage / dst_rel
            if src.is_dir():
                shutil.copytree(src, target)
            else:
                shutil.copy2(src, target)
        return {"status": "ok", "files": sorted(files)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--engine", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        res = publish(a.engine, dry_run=a.dry_run)
    except Exception as e:  # report, never crash
        res = {"status": "fatal", "reason": f"{type(e).__name__}: {e}"}
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
