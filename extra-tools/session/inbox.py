# ~/.claude/tools/session/inbox.py
"""Notes addressed to a project (or `_user`), carried across machines by the vault: handoffs/inbox/<key>/."""
import datetime as dt
import re
from pathlib import Path

import lib

_KEY = re.compile(r"[a-z0-9_][a-z0-9._-]*")


def inbox_dir(key):
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError(f"bad inbox key: {key!r}")
    return lib.vault() / "handoffs" / "inbox" / key


def write_note(to, from_, subject, body, now=None):
    now = now or dt.datetime.now(dt.UTC)
    subject = " ".join(str(subject).split())  # one line each: a newline would forge frontmatter fields
    from_ = " ".join(str(from_).split())
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
    """Move triaged notes to done/; return every path the vault push must stage (the old and the new).

    Only notes inside the vault inbox are moved (all paths are checked before any moves), and an earlier
    done/<name> is never overwritten: the new one gets a -2, -3... suffix."""
    base = (lib.vault() / "handoffs" / "inbox").resolve()
    notes = [Path(s) for s in paths]
    for p in notes:
        if not p.resolve().is_relative_to(base):
            raise ValueError(f"not an inbox note: {p}")
    staged = []
    for p in notes:
        if not p.exists():
            continue  # another session already triaged it
        dst, n = p.parent / "done" / p.name, 2
        while dst.exists():
            dst, n = p.parent / "done" / f"{p.stem}-{n}{p.suffix}", n + 1
        dst.parent.mkdir(exist_ok=True)
        try:
            p.replace(dst)
        except FileNotFoundError:
            continue  # another session moved it between the check and the move
        staged += [str(p), str(dst)]
    return staged
