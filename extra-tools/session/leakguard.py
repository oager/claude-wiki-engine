"""Refuse text that carries a user's personal strings (publishing the tools, writing a shared repo handoff).

Needles come from the user's own _USER.md Profile: identity (names, emails, hosts, aliases, ssh targets) plus
`publish_deny`, minus `publish_allow` (identity strings that are also ordinary words, e.g. an ssh alias "ubuntu").
"""


def needles(profile, names=True):
    ident = profile.get("identity") or {}
    raw = set(ident.get("emails") or [])
    if names:
        raw |= set(ident.get("names") or [])
    for host, h in (ident.get("hosts") or {}).items():
        h = h or {}
        raw |= {host, *(h.get("aliases") or []), h.get("ssh") or ""}
    raw |= set(profile.get("publish_deny") or [])
    allow = {a.strip().lower() for a in profile.get("publish_allow") or []}
    return sorted({n.strip().lower() for n in raw if n and len(n.strip()) >= 3} - allow)


def find(files, needles):
    """files: {name: text}. Every (file, line, needle) hit, case-insensitive, as "name:line: needle"."""
    hits = []
    for name, text in files.items():
        for i, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            hits += [f"{name}:{i}: {n}" for n in needles if n in low]
    return hits
