"""Refuse text that carries a user's personal strings (publishing the tools, writing a shared repo handoff).

Needles come from the user's own _USER.md Profile: identity (names, emails, hosts, aliases, ssh targets) plus
`publish_deny`, minus `publish_allow` (identity strings that are also ordinary words, e.g. an ssh alias "ubuntu").
find() also always looks for the user's home directory path. Needles and text are compared after NFKC + casefold
with zero-width characters removed, so fullwidth, decomposed or zero-width-split spellings still match.
"""
import bisect
import unicodedata
from pathlib import Path

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))


def _norm(s):
    return unicodedata.normalize("NFKC", str(s).translate(_ZERO_WIDTH)).casefold().translate(_ZERO_WIDTH)


def _home_needles():
    home = str(Path.home())  # not the bare user name: that is an ordinary word too often
    return {_norm(h) for h in (home.replace("\\", "/"), home.replace("/", "\\")) if len(h) >= 3}


def needles(profile, names=True):
    ident = profile.get("identity") or {}
    raw = set(ident.get("emails") or [])
    if names:
        raw |= set(ident.get("names") or [])
    for host, h in (ident.get("hosts") or {}).items():
        h = h or {}
        raw |= {host, *(h.get("aliases") or []), h.get("ssh") or ""}
    raw |= set(profile.get("publish_deny") or [])
    allow = {" ".join(_norm(a).split()) for a in profile.get("publish_allow") or []}
    return sorted({" ".join(_norm(n).split()) for n in raw if n and len(n.strip()) >= 3} - allow)


def find(files, needles):
    """files: {name: text}. Every (file, line, needle) hit, case-insensitive, as "name:line: needle".

    The user's home directory path is always a needle (added here, not in needles(): callers treat an empty
    needles() as "nothing to guard with" and refuse). Each line is scanned, and so is the whole text with
    whitespace runs collapsed to one space, which catches a name wrapped across lines (reported at the line
    where it starts)."""
    needles = sorted({" ".join(_norm(n).split()) for n in needles if n and n.strip()} | _home_needles())
    hits = []
    for name, text in files.items():
        seen, parts, starts, pos = set(), [], [], 0
        for i, line in enumerate(text.splitlines(), 1):
            low = _norm(line)
            for n in needles:
                if n in low:
                    hits.append(f"{name}:{i}: {n}")
                    seen.add((i, n))
            flat = " ".join(low.split())
            if flat:
                parts.append(flat)
                starts.append((pos, i))
                pos += len(flat) + 1
        whole = " ".join(parts)
        offsets = [o for o, _ in starts]
        for n in needles:
            k = whole.find(n)
            while k != -1:
                i = starts[bisect.bisect_right(offsets, k) - 1][1]
                if (i, n) not in seen:
                    hits.append(f"{name}:{i}: {n}")
                    seen.add((i, n))
                k = whole.find(n, k + 1)
    return hits
