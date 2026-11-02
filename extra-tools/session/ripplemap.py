"""/ripple hooks for the session tools. Optional: silent unless the project has a consumer map or a "ripple" Profile key.

- /preflight: how stale is the map's sweep watermark (`watermark_block`).
- /sync: did this session change seam files without a ripple run (`seams_block`; `/ripple` stamps a run with
  `close.py ripple-done`).
- check-profile: is the "ripple" Profile key well-formed (`validate`).
"""
import datetime as dt
import fnmatch
import json
import re
from pathlib import Path

import lib

DEFAULT_MAP = "docs/DATA_CONSUMERS.md"
STALE_DAYS = 30  # same expiry the ripple skill gives a dated null
_SHA = re.compile(r"`([0-9a-f]{7,40})`")
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def validate(profile):
    """None when the "ripple" key is absent or well-formed, else the first problem as a short string."""
    r = profile.get("ripple")
    if r is None:
        return None
    if not isinstance(r, dict):
        return "ripple is not an object"
    for k in ("map", "partners", "branch"):
        if k in r and not isinstance(r[k], str):
            return f"ripple.{k} is not a string"
    if "seam_paths" in r and not (isinstance(r["seam_paths"], list) and all(isinstance(g, str) for g in r["seam_paths"])):
        return "ripple.seam_paths is not a list of strings"
    if "clones" in r and not (isinstance(r["clones"], dict)
                              and all(isinstance(k, str) and isinstance(v, str) for k, v in r["clones"].items())):
        return "ripple.clones is not an object of strings"
    for g in r.get("seam_paths") or []:  # same split as seams_block: a typo'd label would skip that seam silently
        label = g.rpartition(":")[0]
        if label and label not in (r.get("clones") or {}):
            return f"ripple.seam_paths: '{label}:' names no ripple.clones entry"
    return None


def _cfg(profile):
    r = profile.get("ripple")
    return r if isinstance(r, dict) else {}


def _local(root, p):
    p = Path(lib.expand(p))
    return p if p.is_absolute() else Path(root) / p


def map_path(root, profile):
    p = _local(root, _cfg(profile).get("map") or DEFAULT_MAP)
    return p if p.is_file() else None


def _upstream(repo, cfg):
    return f"origin/{cfg['branch']}" if cfg.get("branch") else lib.git(repo, "rev-parse", "--abbrev-ref", "@{u}")


def read_map(path, cfg):
    """The map as the branch the services run has it: a local mirror can be behind the remote."""
    top = lib.git(path.parent, "rev-parse", "--show-toplevel")
    up = _upstream(path.parent, cfg) if top else None
    if top and up:
        rel = path.resolve().relative_to(Path(top).resolve()).as_posix()
        text = lib.git(top, "show", f"{up}:{rel}")
        if text is not None:
            return text, up
    return path.read_text(encoding="utf-8"), "local file"


def parse_watermarks(text):
    """Rows of the first '# ... watermark' section's table, or None when the map has no such section."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("#") and "watermark" in ln.lower()), None)
    if start is None:
        return None
    rows = []
    for ln in lines[start + 1:]:
        if ln.startswith("#"):
            break
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if set(cells[0]) <= set("-: ") or cells[0].lower() == "repo":
            continue
        sha = _SHA.search(cells[1]) if len(cells) > 1 else None
        date = _DATE.search(cells[2]) if len(cells) > 2 else None
        name = cells[0].replace("`", "").split()
        rows.append({"repo": name[0] if name else "?", "sha": sha.group(1) if sha else None,
                     "date": date.group(1) if date else None,
                     "swept_by": cells[3] if len(cells) > 3 and cells[3] not in ("", "—", "-") else None})
    return rows


def _clone_for(name, root, cfg):
    """A local clone of the repo a watermark row names: the Profile's "clones", else the project root itself."""
    clones = cfg.get("clones") or {}
    if name in clones:
        return _local(root, clones[name])
    origin = lib.parse_remote(lib.git(root, "remote", "get-url", "origin") or "")  # "owner/name"
    tail = name.rstrip("/").split("/")[-1]
    return Path(root) if tail in (Path(root).name, origin.split("/")[-1] if origin else None) else None


def _unswept(clone, sha, cfg):
    if lib.git(clone, "cat-file", "-e", f"{sha}^{{commit}}") is None:
        return None
    up = _upstream(clone, cfg)
    n = lib.git(clone, "rev-list", "--count", f"{sha}..{up}") if up else None
    return int(n) if n and n.isdigit() else None


def watermark_block(root, profile, today=None):
    """For /preflight. None when the project has no map. Counts use refs as of the last fetch, never a new one."""
    err = validate(profile)
    if err:
        return {"error": err, "stale": False}
    cfg = _cfg(profile)
    path = map_path(root, profile)
    if path is None:
        return None
    try:
        text, source = read_map(path, cfg)
    except (OSError, ValueError) as e:
        return {"map": str(path), "error": f"unreadable: {type(e).__name__}", "stale": False}
    rows = parse_watermarks(text)
    out = {"map": str(path), "source": source}
    if not rows:
        return {**out, "stale": True, "reason": "no sweep watermark rows", "repos": []}
    today = today or dt.datetime.now(dt.UTC).date()
    for r in rows:
        d = lib.parse_utc(r["date"]) if r["date"] else None
        r["age_days"] = (today - d.date()).days if d else None
        clone = _clone_for(r["repo"], root, cfg) if r["sha"] else None
        r["unswept"] = _unswept(clone, r["sha"], cfg) if clone and clone.is_dir() else None
        r["stale"] = r["sha"] is None or r["age_days"] is None or r["age_days"] > STALE_DAYS
    ages = [r["age_days"] for r in rows if r["age_days"] is not None]
    return {**out, "stale": any(r["stale"] for r in rows), "oldest_days": max(ages) if ages else None,
            "never_swept": [r["repo"] for r in rows if r["sha"] is None], "repos": rows}


# --- /sync: seam files changed without a ripple ------------------------------------------------------

def _stamp(key):
    return lib.vault() / "handoffs" / ".live" / f"{key}.ripple.json"  # local, never committed (like the registry)


def mark_rippled(key, now=None):
    p = _stamp(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    at = (now or dt.datetime.now(dt.UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.write_text(json.dumps({"at": at}), encoding="utf-8")
    return {"ok": True, "at": at, "path": str(p)}


def ripple_at(key):
    try:
        return lib.parse_utc(json.loads(_stamp(key).read_text(encoding="utf-8")).get("at"))
    except (OSError, ValueError, AttributeError):
        return None


def _changed(repo, since):
    files = set()
    if since:
        log = lib.git(repo, "log", f"--since={since.strftime('%Y-%m-%dT%H:%M:%SZ')}", "--name-only", "--format=")
        files.update(f for f in (log or "").splitlines() if f.strip())
    rc, out, _ = lib.RUN(["git", "-C", str(repo), "status", "--porcelain"])  # not lib.git: it strips the 1st line's
    for ln in (out if rc == 0 else "").splitlines():                         # leading status column
        if len(ln) > 3:
            files.add(ln[3:].split(" -> ")[-1].strip('"'))
    return files


def seams_block(root, profile, last_sync, key):
    """For /sync. None unless the Profile lists ripple.seam_paths. A plain glob applies to the project root;
    "<clones key>:<glob>" to that clone. Changed = committed since the last /sync, or dirty now."""
    cfg = _cfg(profile)
    globs = cfg.get("seam_paths")
    if validate(profile) or not globs:
        return None
    since = lib.parse_utc(last_sync)
    clones = cfg.get("clones") or {}
    by_repo = {}
    for g in globs:
        label, _, pat = g.rpartition(":")
        by_repo.setdefault(label, []).append(pat)
    touched = []
    for label, pats in by_repo.items():
        if label and label not in clones:
            continue  # names a clone the Profile does not map: nothing local to diff
        repo = _local(root, clones[label]) if label else Path(root)
        if lib.git(repo, "rev-parse", "--git-dir") is None:
            continue
        touched += [f"{label}:{f}" if label else f for f in sorted(_changed(repo, since))
                    if any(fnmatch.fnmatch(f, p) for p in pats)]
    at = ripple_at(key)
    rippled = at is not None and (since is None or at > since)
    return {"touched": touched, "rippled": rippled,
            "ripple_at": at.strftime("%Y-%m-%dT%H:%M:%SZ") if at else None}
