# ~/.claude/tools/session/inbox.py
"""Notes addressed to a project (or `_user`), carried across machines by the vault: handoffs/inbox/<key>/."""
import datetime as dt
import re
from pathlib import Path

import lib

_KEY = re.compile(r"^[a-z0-9_][a-z0-9._-]*$")


def inbox_dir(key):
    if not _KEY.match(key or ""):
        raise ValueError(f"bad inbox key: {key!r}")
    return lib.vault() / "handoffs" / "inbox" / key


def write_note(to, from_, subject, body, now=None):
    now = now or dt.datetime.now(dt.UTC)
    subject = " ".join(str(subject).split())
    slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")[:40] or "note"
    d = inbox_dir(to)
    d.mkdir(parents=True, exist_ok=True)
    stem, n = f"{now:%Y-%m-%dT%H%MZ}-{slug}", 2
    p = d / f"{stem}.md"
    while p.exists():
        p, n = d / f"{stem}-{n}.md", n + 1
    p.write_text(f"---\nfrom: {from_}\nto: {to}\ncreated: {now:%Y-%m-%dT%H:%MZ}\nsubject: {subject}\n---\n\n"
                 f"{body.rstrip()}\n", encoding="utf-8")
    return p


def _front(text):
    """Frontmatter as raw strings (not lib.parse_handoff: that cuts values at ' #', which subjects may contain)."""
    meta = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        for line in text[4:end].splitlines() if end != -1 else []:
            k, sep, v = line.partition(":")
            if sep:
                meta[k.strip()] = v.strip()
    return meta


def list_notes(key):
    try:
        d = inbox_dir(key)
    except ValueError:
        return []
    notes = []
    for p in sorted(d.glob("*.md")) if d.is_dir() else []:
        try:
            meta = _front(p.read_text(encoding="utf-8").replace("\r\n", "\n"))
        except (OSError, ValueError):
            meta = {}
        notes.append({"path": str(p), "from": meta.get("from", "?"),
                      "subject": meta.get("subject") or "<unreadable>", "created": meta.get("created")})
    return notes


def mark_done(paths):
    """Move triaged notes to done/; return every path the vault push must stage (the old and the new)."""
    staged = []
    for s in paths:
        p = Path(s)
        dst = p.parent / "done" / p.name
        dst.parent.mkdir(exist_ok=True)
        p.replace(dst)
        staged += [str(p), str(dst)]
    return staged
