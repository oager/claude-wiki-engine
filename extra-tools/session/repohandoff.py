"""A shared project's public handoff, <repo>/.claude/HANDOFF.md.

Design: claude-wiki-engine README, "Session handoff" ("Shared projects").
Only public sections are copied from the vault handoff; the leak guard refuses identity strings.
"""
import datetime as dt
import os
import tempfile
from pathlib import Path

import leakguard
import lib

REL = ".claude/HANDOFF.md"
PUBLIC = ["Next up", "Current state", "Warnings", "Open items"]


def render(private_text, author, now=None):
    h = lib.parse_handoff(private_text)
    now = now or dt.datetime.now(dt.UTC)
    parts = [f"---\nupdated: {now:%Y-%m-%dT%H:%MZ}\nupdated_by: {author}\n---\n"
             "# Handoff (shared)\n\n_Written by /sync from its author's handoff; edits here are overwritten — "
             "leave notes in a PR or issue instead._\n"]
    parts += [f"## {s}\n{h['sections'].get(s, '').strip() or 'none'}\n" for s in PUBLIC]
    return "\n".join(parts)


def write(root, private_text, author, needles):
    if not needles:  # an empty guard passes everything: never publish unguarded
        return {"written": False, "refused": [], "reason": "no identity strings to guard with; fill _USER.md identity first"}
    text = render(private_text, author)
    body = text.split("\n---\n", 1)[-1]  # the author line is allowed; scan everything after the frontmatter
    hits = leakguard.find({REL: body}, needles)
    if hits:
        return {"written": False, "refused": hits}
    p = Path(root) / REL
    # Security: a collaborator can commit .claude or HANDOFF.md as a symlink; following it would let /sync
    # overwrite any file the user can write (e.g. ~/.bashrc). Refuse, and never write through a link.
    if p.parent.is_symlink() or p.is_symlink():
        return {"written": False, "reason": f"{REL} or its folder is a symlink; not written"}
    p.parent.mkdir(parents=True, exist_ok=True)
    real_root = os.path.realpath(root)
    try:
        inside = os.path.commonpath([real_root, os.path.realpath(p)]) == real_root
    except ValueError:  # different drives (Windows)
        inside = False
    if not inside:
        return {"written": False, "reason": f"{REL} resolves outside the repo; not written"}
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".HANDOFF.", suffix=".tmp")  # O_EXCL: never a planted file
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)  # replaces the name itself; a link swapped in meanwhile is replaced, not followed
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"written": True, "path": str(p)}


def read_origin(root, ids, repo_sha):
    ref = f"origin/{lib.default_branch(root)}"
    text = lib.git(root, "show", f"{ref}:{REL}")
    if text is None:
        return {"exists": False}
    h = lib.parse_handoff(text)
    last = lib.git(root, "log", "-1", "--format=%H%x09%an%x09%ae", ref, "--", REL) or ""
    sha, _, rest = last.partition("\t")
    name, _, email = rest.partition("\t")
    new = not repo_sha or lib.RUN(["git", "-C", str(root), "merge-base", "--is-ancestor", sha, repo_sha])[0] != 0
    return {"exists": True, "updated": h["meta"].get("updated"), "updated_by": h["meta"].get("updated_by"),
            "changed_by_other": bool(sha) and new and not lib.is_self(name, email, ids),
            "next_up": h["sections"].get("Next up", "")}
