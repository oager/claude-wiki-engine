# ~/.claude/tools/session/lib.py
"""Shared helpers for the /preflight (open.py) and /sync (close.py) collectors.

Spec: ~/.claude/docs/specs/2026-09-27-preflight-sync-redesign.md
Stdlib only: this must run under Windows Git Bash python as well as Linux.
"""
import datetime as dt
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def vault():
    return Path(os.environ.get("CLAUDE_VAULT") or Path.home() / ".claude")


def _run(cmd, cwd=None, timeout=8):
    """Run cmd and never raise. Returns (rc, stdout, stderr); rc 124 = timeout, 127 = not found."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except (FileNotFoundError, NotADirectoryError) as e:
        return 127, "", str(e)


RUN = _run  # tests replace this; always call it as lib.RUN(...) / RUN(...) at call time


def git(root, *args, timeout=8):
    rc, out, _ = RUN(["git", "-C", str(root), *args], timeout=timeout)
    return out.strip() if rc == 0 else None


def slug(path):
    """Claude Code's project-dir slug: every character outside [A-Za-z0-9-] becomes '-'."""
    return re.sub(r"[^A-Za-z0-9-]", "-", str(path))


_REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


def parse_remote(url):
    m = _REMOTE.search(url.strip()) if url else None
    return f"{m.group(1)}/{m.group(2)}" if m else None


def key_for(repo, root):
    if repo:
        return repo.replace("/", "-").lower()
    return "local-" + Path(root).name.lower().replace(" ", "-")


def _origin(root):
    return parse_remote(git(root, "remote", "get-url", "origin") or "")


def _children(d):
    try:
        return list(d.iterdir()) if d.is_dir() else []
    except OSError:
        return []


def _is_repo_dir(p):
    try:  # an unreadable child (Windows junctions, chmod 000) must not crash the whole briefing
        return p.is_dir() and (p / ".git").exists()
    except OSError:
        return False


def rebase_in_progress(root):
    git_dir = Path(root) / ".git"
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def default_branch(root):
    ref = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return ref.split("/", 1)[1] if ref and "/" in ref else "main"


def vault_is_git():
    """True only when the vault folder is itself a git work tree (not merely inside one)."""
    top = git(vault(), "rev-parse", "--show-toplevel")
    return bool(top) and Path(top).resolve() == vault().resolve()


def has_systemctl():
    return shutil.which("systemctl") is not None


def resolve_identity(cwd, project=None):
    """Which project is this session about? Repo root first, then child repos, then the folder."""
    cwd = Path(cwd).resolve()
    top = git(cwd, "rev-parse", "--show-toplevel")
    if top:
        root = Path(top)
        repo = _origin(root)
        return {"key": key_for(repo, root), "repo": repo, "root": str(root), "how": "git", "candidates": []}
    subs = sorted(p for p in _children(cwd) if _is_repo_dir(p))
    cands = []
    for p in subs:
        repo = _origin(p)
        cands.append({"key": key_for(repo, p), "repo": repo, "root": str(p)})
    if project:
        for c in cands:
            if c["key"] == project:
                return {**c, "how": "chosen", "candidates": []}
        return {"key": project, "repo": None, "root": str(cwd), "how": "chosen", "candidates": []}
    if len(cands) == 1:
        return {**cands[0], "how": "git-child", "candidates": []}
    if len(cands) > 1:
        own = key_for(None, cwd)  # a hub that already has its own handoff opted in: use it instead of asking
        if handoff_path(own).is_file():
            return {"key": own, "repo": None, "root": str(cwd), "how": "folder-handoff", "candidates": cands}
        return {"key": None, "repo": None, "root": str(cwd), "how": "ambiguous", "candidates": cands}
    return {"key": key_for(None, cwd), "repo": None, "root": str(cwd), "how": "folder", "candidates": []}


def _no_ids():
    return {"names": [], "emails": [], "hosts": {}}


def load_self_ids():
    """Who "self" is: the _USER.md Profile identity, else the legacy self_ids.json, else nobody."""
    ident = user_file()["profile"].get("identity")
    if isinstance(ident, dict):
        return {**_no_ids(), **ident}
    try:
        return {**_no_ids(), **json.loads((HERE / "self_ids.json").read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return _no_ids()


def is_self(name, email, ids):
    names = {n.lower() for n in ids.get("names", [])}
    emails = {e.lower() for e in ids.get("emails", [])}
    return (name or "").lower() in names or (email or "").lower() in emails


def host_target(host, ids):
    """None means run locally; otherwise the ssh target for that logical host."""
    if not host:
        return None
    h = ids.get("hosts", {}).get(host, {})
    names = {host.lower(), *(a.lower() for a in h.get("aliases", []))}
    if socket.gethostname().lower() in names:
        return None
    return h.get("ssh", host)


def on_host(host, cmd, ids, timeout=8):
    t = host_target(host, ids)
    if t is None:
        return RUN(cmd, timeout=timeout)
    return RUN(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", t, shlex.join(cmd)], timeout=timeout)


# --- handoff files -------------------------------------------------------------

def handoff_path(key):
    return vault() / "handoffs" / f"{key}.md"


_PROFILE_JSON = re.compile(r"```json\s*\n(.*?)\n```", re.S)


def parse_handoff(text):
    """Split a handoff into frontmatter, `## ` sections and the Profile json block."""
    text = text.replace("\r\n", "\n")
    meta, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                k, sep, v = line.partition(":")
                if sep and k.strip() and not k.startswith(" "):
                    meta[k.strip()] = v.split(" #")[0].strip()
            body = text[end + 4:]
    sections, name = {}, None
    for line in body.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            sections[name] = []
        elif name is not None:
            sections[name].append(line)
    sections = {k: "\n".join(v).strip() for k, v in sections.items()}
    profile, err = {}, None
    m = _PROFILE_JSON.search(sections.get("Profile", ""))
    if m:
        try:
            profile = json.loads(m.group(1))
            if not isinstance(profile, dict):
                profile, err = {}, "Profile json is not an object"
        except ValueError as e:
            profile, err = {}, f"Profile json invalid: {e}"
    return {"meta": meta, "sections": sections, "profile": profile, "profile_error": err}


def expand(s):
    """`<vault>` becomes the vault path and `~` the home folder, so one _USER.md works on every machine."""
    return os.path.expanduser(str(s).replace("<vault>", str(vault())))


def user_file():
    """The per-user handoff, handoffs/_USER.md: identity, user-wide checks and conventions for every project."""
    p = handoff_path("_USER")
    res = {"path": str(p), "exists": p.is_file(), "profile": {}, "profile_error": None,
           "size_kb": 0, "over_max": False}
    if not res["exists"]:
        return res
    text = p.read_text(encoding="utf-8")
    h = parse_handoff(text)
    kb = len(text.encode("utf-8")) / 1024
    max_kb = h["profile"].get("max_kb", 8)
    if isinstance(max_kb, bool) or not isinstance(max_kb, (int, float)):
        max_kb = 8
    return {**res, "profile": h["profile"], "profile_error": h["profile_error"],
            "size_kb": round(kb, 1), "over_max": kb > max_kb}


def parse_utc(s):
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=dt.UTC)
        except (TypeError, ValueError):
            pass
    return None


def find_legacy(root, cwd):
    """Newest pre-redesign SESSION_RESUME.md for this project (repo copy or vault copy), or None."""
    paths = [Path(root) / ".claude" / "memory" / "SESSION_RESUME.md"]
    for p in dict.fromkeys([str(root), str(cwd)]):
        paths.append(vault() / "projects" / slug(p) / "memory" / "SESSION_RESUME.md")
    found = [p for p in paths if p.is_file()]
    if not found:
        return None
    newest = max(found, key=lambda p: p.stat().st_mtime)
    age_days = (dt.datetime.now().timestamp() - newest.stat().st_mtime) / 86400
    return {"path": str(newest), "age_days": round(age_days, 1)}


# --- GitHub ------------------------------------------------------------------------

def gh_json(args, timeout=8):
    """Run `gh <args>`; return (data, None) or (None, error). Never raises."""
    rc, out, err = RUN(["gh", *args], timeout=timeout)
    if rc != 0:
        return None, (err or out).strip()[:200] or f"gh rc={rc}"
    try:
        return json.loads(out), None
    except ValueError as e:
        return None, f"gh output not json: {e}"


_CI_FAIL = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
_CI_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}


def ci_state(rollup):
    states = {(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in rollup or []}
    if not states:
        return "none"
    if states & _CI_FAIL:
        return "fail"
    if states - _CI_OK:
        return "pending"
    return "pass"
