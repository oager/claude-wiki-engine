#!/usr/bin/env python3
"""/preflight collector: gather every mechanical fact in one call and print one JSON object.

Always exits 0 -- a failing check records its error in its own entry instead of
aborting the briefing. Spec: ~/.claude/docs/specs/2026-09-27-preflight-sync-redesign.md
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inbox  # noqa: E402
import lib  # noqa: E402
import procs  # noqa: E402
import repohandoff  # noqa: E402

UNMERGED = {"UU", "AA", "UD", "DU", "DD", "AU", "UA"}
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


# --- global block ----------------------------------------------------------------

def vault_state():
    v = str(lib.vault())
    _, out, _ = lib.RUN(["git", "-C", v, "status", "--porcelain"])
    stuck = ((lib.vault() / ".git" / "MERGE_HEAD").exists() or lib.rebase_in_progress(lib.vault())
             or any(line[:2] in UNMERGED for line in out.splitlines()))
    if stuck:
        return {"pull": "skipped", "stuck_merge": True}
    rc, out, err = lib.RUN(["git", "-C", v, "pull", "--ff-only", "-q"], timeout=20)
    if rc == 0:
        return {"pull": "ok", "stuck_merge": False}
    msg = (err or out).strip().splitlines()
    return {"pull": "failed: " + (msg[-1] if msg else f"rc={rc}"), "stuck_merge": False}


def clock():
    rc, out, _ = lib.RUN(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    synced = {"yes": True, "no": False}.get(out.strip()) if rc == 0 else None
    return {"utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "ntp_synced": synced}


def _vault_range(meta):
    sha = meta.get("vault_sha")
    if sha and lib.git(lib.vault(), "cat-file", "-e", f"{sha}^{{commit}}") is not None:
        return [f"{sha}..HEAD"], sha
    since = meta.get("updated") or "7 days ago"
    return [f"--since={since}", "HEAD"], f"since {since}"


def vault_changes(meta):
    """Skills and global knowledge changed in the vault since this project's last handoff."""
    v = str(lib.vault())
    rng, basis = _vault_range(meta)
    rc, out, _ = lib.RUN(["git", "-C", v, "log", *rng, "--name-only", "--format=", "--", "skills/"])
    skills = sorted({p.split("/")[1] for p in out.splitlines() if p.count("/") >= 2}) if rc == 0 else []
    rc, out, _ = lib.RUN(["git", "-C", v, "log", *rng, "--format=%x1e%s", "--name-only",
                          "--", "memory", "CLAUDE.md", "rules"])
    knowledge = {}
    for rec in out.split("\x1e")[1:] if rc == 0 else []:
        lines = [ln for ln in rec.strip().splitlines() if ln]
        for path in lines[1:]:
            knowledge.setdefault(path, lines[0])  # log is newest-first: first subject seen is the latest
    return {"basis": basis, "skills_changed": skills,
            "knowledge_changed": [{"path": p, "subject": s} for p, s in list(knowledge.items())[:50]]}


def _version_in_path(p):
    """Native Linux installs name the binary by version (versions/2.1.283); the Windows desktop app names its
    folder (…\\2.1.281\\claude.exe)."""
    p = Path(p)
    return next((part for part in (p.name, p.parent.name) if _VERSION.match(part)), None)


def cc_version():
    """The running session keeps the binary it launched with; `claude update` only changes the installed one."""
    run_path = os.environ.get("CLAUDE_CODE_EXECPATH")
    running = _version_in_path(run_path) if run_path else None
    which = shutil.which("claude")
    installed = _version_in_path(Path(which).resolve()) if which else None
    if which and not installed:  # an npm shim carries no version in its path: ask it
        rc, out, _ = lib.RUN([which, "--version"], timeout=5)
        m = re.match(r"\s*(\d+\.\d+\.\d+)", out or "")
        installed = m.group(1) if rc == 0 and m else None
    return {"running": running, "installed": installed,
            "relaunch_needed": bool(running and installed and running != installed)}


def plugin_updates():
    """Installed plugins whose record differs from the local marketplace catalog (no network)."""
    p = lib.vault() / "plugins"
    try:
        installed = json.loads((p / "installed_plugins.json").read_text(encoding="utf-8"))["plugins"]
    except (OSError, ValueError, KeyError) as e:
        return {"error": f"installed_plugins.json unreadable: {e}"}
    updates, checked = [], 0
    for pid, recs in installed.items():
        name, _, market = pid.partition("@")
        try:
            cat = json.loads((p / "marketplaces" / market / ".claude-plugin" / "marketplace.json")
                             .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entry = next((e for e in cat.get("plugins", []) if e.get("name") == name), None)
        if not entry:
            continue
        checked += 1
        rec = recs[0] if isinstance(recs, list) and recs else {}
        src = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        if src.get("sha") and rec.get("gitCommitSha"):
            if src["sha"] != rec["gitCommitSha"]:
                updates.append(pid)
        elif entry.get("version") and rec.get("version") and entry["version"] != rec["version"]:
            updates.append(pid)
    return {"updates": updates, "checked": checked}


# --- git block -------------------------------------------------------------------

def prs_and_issues(gh):
    if not gh:
        return {"error": "no GitHub repo (no origin remote)"}
    prs, e1 = lib.gh_json(["pr", "list", "-R", gh, "--state", "open", "--json", "number,title,statusCheckRollup"])
    issues, e2 = lib.gh_json(["issue", "list", "-R", gh, "--state", "open", "--limit", "200", "--json", "number"])
    out = {"prs": None if prs is None else
           [{"number": p["number"], "title": p["title"], "ci": lib.ci_state(p.get("statusCheckRollup"))} for p in prs],
           "issues_open": None if issues is None else len(issues)}
    errors = [e for e in (e1, e2) if e]
    if errors:
        out["error"] = "; ".join(errors)
    return out


def git_local(root):
    status = lib.git(root, "status", "--porcelain")
    ab = lib.git(root, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    ahead, behind = (int(x) for x in ab.split()) if ab else (None, None)
    stash = lib.git(root, "stash", "list")
    return {"branch": lib.git(root, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": len(status.splitlines()) if status else 0,
            "ahead": ahead, "behind": behind,
            "stashes": len(stash.splitlines()) if stash else 0}


def collab_block(root, meta, ids, profile):
    """Non-self authors since the last handoff, on local branches and origin only (not upstream forks)."""
    sha = meta.get("repo_sha")
    if sha and lib.git(root, "cat-file", "-e", f"{sha}^{{commit}}") is not None:
        rng, basis = [f"^{sha}"], sha
    else:
        rng, basis = ["--since=14 days ago"], "14 days"
    out = lib.git(root, "log", "--branches", "--remotes=origin", *rng, "--format=%an%x09%ae") or ""
    others = Counter(line.split("\t")[0] for line in out.splitlines()
                     if "\t" in line and not lib.is_self(*line.split("\t", 1), ids))
    return {"since": basis, "shared": bool(profile.get("shared")),
            "others": [{"author": a, "commits": n} for a, n in others.most_common()]}


# --- type detection ------------------------------------------------------------------

def detect_type(root, meta):
    if meta.get("type"):
        return {"type": meta["type"], "signals": ["handoff frontmatter"]}
    r = Path(root)

    def has(*patterns):
        return [str(p.relative_to(r)) for pat in patterns for p in r.glob(pat)
                if "node_modules" not in p.parts][:3]

    bot = has("state/*position*.json", "logs/live_status.json", ".claude/memory/status.json")
    if bot:
        return {"type": "trading-bot", "signals": bot}
    server = has("server.js", "*/server.js", "*/*/server.js")
    site = has("wrangler.toml", "wrangler.jsonc", "vercel.json", "astro.config.*")
    if site and not server:
        return {"type": "static-site", "signals": site}
    web = server or has("package.json")
    if web:
        return {"type": "web-app", "signals": web}
    return {"type": "workspace", "signals": []}


# --- checks --------------------------------------------------------------------------

def unit_token(root):
    """Repo folder name -> the fragment its systemd units probably share (alpha_beta_bot_v5 -> alpha-beta)."""
    words = [w for w in re.split(r"[-_ ]+", Path(root).name.lower()) if w]
    if "bot" in words:
        words = words[:words.index("bot")] or words
    return "-".join(w for w in words if not re.fullmatch(r"v\d+", w))


def list_units(host, ids):
    units = []
    for scope in ("user", "system"):
        cmd = ["systemctl", *(["--user"] if scope == "user" else []),
               "list-units", "--type=service", "--all", "--no-legend", "--plain"]
        rc, out, _ = lib.on_host(host, cmd, ids)
        if rc != 0:
            continue
        for line in out.splitlines():
            f = line.split()
            if f:
                units.append({"unit": f[0].removesuffix(".service"), "scope": scope,
                              "active": f[2] if len(f) > 2 else "?"})
    return units


def _check(source, kind, target, status, detail, **extra):
    return {"source": source, "kind": kind, "target": target, "status": status, "detail": detail, **extra}


def service_check(s, ids, source):
    scope = ["--user"] if s.get("scope", "user") == "user" else []
    rc, out, err = lib.on_host(s.get("host"), ["systemctl", *scope, "is-active", s["unit"]], ids)
    if rc == 127:
        return _check(source, "service", s["unit"], "unknown", "systemctl unavailable")
    state = out.strip() or err.strip()[:80] or f"rc={rc}"
    if state == "active":
        status = "ok"
    elif rc in (124, 127, 255):
        status = "unknown"
    else:
        status = "fail"
    return _check(source, "service", s["unit"], status, state)


def _path(root, p):
    p = os.path.expanduser(p)
    return Path(p) if os.path.isabs(p) else Path(root) / p


def health_check(h, ids):
    rc, body, _ = lib.on_host(h.get("host"), ["curl", "-s", "-m", "5", h["url"]], ids)
    if rc in (124, 127, 255):  # curl/ssh missing or timed out: we learned nothing about the service
        return _check("profile", "health", h["url"], "unknown", f"check unavailable (rc={rc})")
    ok = rc == 0 and (h.get("expect") is None or h["expect"] in body)
    return _check("profile", "health", h["url"], "ok" if ok else "fail", body.strip()[:120] or f"curl rc={rc}")


def port_check(p, ids):
    rc, out, _ = lib.on_host(p.get("host"), ["ss", "-ltnp"], ids)
    if rc != 0:
        return _check("profile", "port", str(p["port"]), "unknown", "ss unavailable")
    lines = [line for line in out.splitlines() if re.search(rf":{p['port']}\s", line)]
    owner = p.get("owner")
    ok = bool(lines) and (not owner or any(owner in line for line in lines))
    return _check("profile", "port", str(p["port"]), "ok" if ok else "fail",
                  (lines[0].split()[-1] if lines else "not listening")[:120])


def queue_check(q, root):
    try:
        text = _path(root, q["file"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _check("profile", "queue", q["name"], "unknown", f"missing: {q['file']}")
    n = len(re.findall(q.get("count", r"^- "), text, re.M))
    return _check("profile", "queue", q["name"], "ok", f"{n} open", count=n)


def log_check(lg, root):
    p = _path(root, lg["path"])
    if not p.exists():
        return _check("profile", "log", lg["path"], "fail", "missing")
    age_h = (time.time() - p.stat().st_mtime) / 3600
    return _check("profile", "log", lg["path"], "ok" if age_h <= lg.get("max_age_h", 24) else "warn",
                  f"{age_h:.1f}h old")


def metric_check(m, root):
    try:
        v = json.loads(_path(root, m["file"]).read_text(encoding="utf-8"))
        for part in str(m["key"]).split("."):
            v = v[part]
        return _check("profile", "metric", m["name"], "ok", str(v)[:60])
    except (OSError, ValueError, KeyError, TypeError) as e:
        return _check("profile", "metric", m["name"], "unknown", f"unreadable: {e}"[:120])


def command_check(c):
    """A user-declared command that prints {count, oldest_h, label} JSON (field names mappable)."""
    cmd = [lib.expand(x) for x in c.get("cmd") or []]
    name = c.get("name") or (cmd[0] if cmd else "?")
    rc, out, err = lib.RUN(cmd, timeout=c.get("timeout_s", 8)) if cmd else (127, "", "no cmd")
    if rc in (124, 127):  # timeout or missing binary: we learned nothing
        return _check("user", "command", name, "unknown", (err or f"rc={rc}").strip()[:120], loud=False)
    f = {"count": "count", "oldest_h": "oldest_h", "label": "label", **(c.get("fields") or {})}
    try:  # the exit code is ignored on purpose: queue scripts exit 1 when non-empty
        data = json.loads(out)
        count, oldest, label = int(data.get(f["count"]) or 0), data.get(f["oldest_h"]), data.get(f["label"])
    except (ValueError, TypeError, AttributeError) as e:
        return _check("user", "command", name, "unknown", f"output not JSON: {e}"[:120], loud=False)
    aged = not isinstance(oldest, (int, float)) or oldest > c.get("loud_after_h", 24)
    loud = count > 0 and aged
    detail = f"{count} queued" + (f", oldest {oldest:.0f}h" if isinstance(oldest, (int, float)) else "")
    detail += f" ({label})" if label else ""
    return _check("user", "command", name, "warn" if loud else "ok", detail, loud=loud, count=count)


def user_checks(profile, ids):
    """_USER.md Profile checks: they run for every project; paths may use <vault>."""
    v, res = lib.vault(), []
    for c in profile.get("checks") or []:
        kind = c.get("kind")
        if kind == "command":
            r = command_check(c)
        elif kind == "queue":
            r = queue_check({**c, "file": lib.expand(c["file"])}, v)
            r["loud"] = r.get("count", 0) > c.get("loud_over", 0)
        elif kind == "log":
            r = log_check({**c, "path": lib.expand(c["path"])}, v)
        elif kind == "metric":
            r = metric_check({**c, "file": lib.expand(c["file"])}, v)
        elif kind == "service":
            r = service_check(c, ids, "user")
        elif kind == "health":
            r = health_check(c, ids)
        elif kind == "port":
            r = port_check(c, ids)
        else:
            r = _check("user", kind or "?", c.get("name", "?"), "unknown", f"unknown check kind: {kind}")
        r["source"] = "user"
        r.setdefault("loud", r["status"] not in ("ok", "unknown"))
        res.append(r)
    return res


def freshness_check(root):
    r = Path(root)
    files = [p for pat in ("state/*.json", "logs/*.log", "logs/*.json") for p in r.glob(pat)]
    if not files:
        return _check("type", "freshness", "state/, logs/", "unknown", "no state or log files found")
    newest = max(files, key=lambda p: p.stat().st_mtime)
    age_h = (time.time() - newest.stat().st_mtime) / 3600
    return _check("type", "freshness", newest.relative_to(r).as_posix(), "ok" if age_h <= 24 else "warn",
                  f"{age_h:.1f}h old")


def run_checks(type_, root, profile, ids):
    checks = []
    services = profile.get("services") or []
    if services:
        checks += [service_check(s, ids, "profile") for s in services]
    elif type_ in ("trading-bot", "web-app") and lib.has_systemctl():
        tok = unit_token(root)
        matched = [u for u in list_units(None, ids) if tok and tok in u["unit"]]
        for u in matched:
            c = service_check(u, ids, "guessed")
            if c["status"] != "ok":
                c["status"], c["detail"] = "unknown", f"{c['detail']} (guessed match — unverified)"
            checks.append(c)
        if not matched:
            checks.append(_check("guessed", "service", f"*{tok}*", "unknown",
                                 "no unit matched the repo name — unverified; declare services in the Profile"))
    checks += [health_check(h, ids) for h in profile.get("health", [])]
    checks += [port_check(p, ids) for p in profile.get("ports", [])]
    checks += [queue_check(q, root) for q in profile.get("queues", [])]
    checks += [log_check(lg, root) for lg in profile.get("logs", [])]
    checks += [metric_check(m, root) for m in profile.get("metrics", [])]
    if type_ == "trading-bot" and not profile.get("logs"):
        checks.append(freshness_check(root))
    return checks


# --- assembly --------------------------------------------------------------------------

def handoff_block(ident, cwd):
    p = lib.handoff_path(ident["key"])
    if not p.is_file():
        return {"path": str(p), "exists": False, "legacy": lib.find_legacy(ident["root"], cwd)}, {}, {}
    h = lib.parse_handoff(p.read_text(encoding="utf-8"))
    m = h["meta"]
    t = lib.parse_utc(m.get("updated"))
    age = round((dt.datetime.now(dt.UTC) - t).total_seconds() / 3600, 1) if t else None
    block = {"path": str(p), "exists": True, "legacy": None, "updated": m.get("updated"), "age_h": age,
             "updated_by": m.get("updated_by"), "repo_sha": m.get("repo_sha"), "vault_sha": m.get("vault_sha"),
             "next_up": h["sections"].get("Next up", ""), "warnings": h["sections"].get("Warnings", ""),
             "profile_error": h["profile_error"]}
    return block, m, h["profile"]


def collect(cwd, project=None):
    ident = lib.resolve_identity(cwd, project)
    out = {"identity": ident}
    if ident["how"] == "ambiguous":
        return out
    ids = lib.load_self_ids()
    if lib.vault_is_git():  # pull BEFORE reading the handoff: /sync on the other machine may have just pushed it
        vstate = {"vault": "git", **vault_state()}
    else:  # a plain local vault: nothing to pull, no history to diff
        vstate = {"vault": "local", "pull": "skipped", "stuck_merge": False}
    hand, meta, profile = handoff_block(ident, cwd)
    out["handoff"] = hand
    notes = inbox.list_notes(ident["key"]) + inbox.list_notes("_user")
    out["inbox"] = {"count": len(notes), "notes": notes}
    root = ident["root"]
    is_repo = lib.git(root, "rev-parse", "--git-dir") is not None
    with ThreadPoolExecutor(max_workers=2) as pool:  # remaining network calls in parallel, 8 s timeout each
        f_fetch = pool.submit(lib.RUN, ["git", "fetch", "-q", "origin"], root, 8) if is_repo else None
        f_gh = pool.submit(prs_and_issues, profile.get("gh") or ident["repo"]) if is_repo else None
        fetch_rc = f_fetch.result()[0] if f_fetch else None
        gh_info = f_gh.result() if f_gh else {}
    u = lib.user_file()
    out["global"] = {**vstate, "clock": clock(), **(vault_changes(meta) if vstate["vault"] == "git"
                        else {"basis": None, "skills_changed": [], "knowledge_changed": []}), "claude_code": cc_version(),
                     "plugins": plugin_updates(), "user": {k: u[k] for k in ("path", "exists", "profile_error", "size_kb", "over_max")},
                     "user_checks": [] if u["profile_error"] else user_checks(u["profile"], ids)}
    if is_repo:
        out["git"] = {**git_local(root), **gh_info}
        out["collab"] = collab_block(root, meta, ids, profile)
    if is_repo and profile.get("shared"):
        out["repo_handoff"] = (repohandoff.read_origin(root, ids, meta.get("repo_sha")) if fetch_rc == 0 else
                               {"exists": None, "reason": "origin unreachable; repo handoff not read"})
    out["type"] = detect_type(root, meta)
    out["checks"] = run_checks(out["type"]["type"], root, profile, ids)
    sessions = procs.claude_sessions_in(root)
    if sessions is not None:
        out["concurrent"] = sessions
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--project", help="handoff key, when the start folder holds several projects")
    a = ap.parse_args(argv)
    try:
        res = collect(a.cwd, a.project)
    except Exception as e:  # the briefing must still render: report the failure instead of crashing
        res = {"fatal": f"{type(e).__name__}: {e}"}
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
