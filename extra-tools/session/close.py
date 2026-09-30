#!/usr/bin/env python3
"""/sync collector: what the next session must know that is not in the handoff yet.

    close.py [--cwd P] [--project KEY]        facts for writing the handoff (JSON)
    close.py trim <handoff.md>                 archive Last session entries older than 14 days
    close.py check-profile <handoff.md>        {"profile_error": null | "..."}: does the Profile json parse
    close.py push --message M --files F...     locked, stage-only-these-files vault push
    close.py note --to K --from F --subject S [--file P]   write + push a vault inbox note
    close.py inbox-done --files P...           move triaged inbox notes to done/ (stage, don't push)
    close.py repo-handoff                      write <repo>/.claude/HANDOFF.md (shared projects, leak-guarded)
    close.py session focus "<text>"            set this session's registry focus text
    close.py session refresh                   re-register this session in the live registry

Always exits 0 and prints one JSON object. Design: the "Session handoff" section of the claude-wiki-engine README.
"""
import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inbox  # noqa: E402
import leakguard  # noqa: E402
import lib  # noqa: E402
import procs  # noqa: E402
import repohandoff  # noqa: E402
import sessions  # noqa: E402
from procs import (  # noqa: E402
    SHELLS,
    TOOL_SHELLS,
)
from procs import ancestors as _ancestors
from procs import is_claude as _is_claude
from procs import proc_stat as _stat

SKIP_COMM = SHELLS | {"claude", "git", "ssh", "less"}
LIVE = "handoffs/.live"  # the per-machine session registry (vault-relative)

default_branch = lib.default_branch


def git_close(root, gh):
    status = lib.git(root, "status", "--porcelain") or ""
    unpushed = lib.git(root, "rev-list", "--count", "@{u}..HEAD")
    base = default_branch(root)
    local = (lib.git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads") or "").splitlines()
    unmerged = [b for b in local
                if b != base and (lib.git(root, "rev-list", "--count", f"{base}..{b}") or "0") != "0"]
    res = {"dirty": status.splitlines()[:20], "dirty_count": len(status.splitlines()),
           "unpushed": int(unpushed) if unpushed else None, "no_pr_branches": unmerged, "ci_pending": []}
    if not gh:
        return res
    prs, err = lib.gh_json(["pr", "list", "-R", gh, "--state", "all", "--limit", "300",
                            "--json", "headRefName,number,state,statusCheckRollup"])
    if prs is None:
        res["error"] = err  # without PR data every unmerged branch stays listed
        return res
    heads = {p["headRefName"] for p in prs}  # squash-merged branches have a PR, so they drop out here
    res["no_pr_branches"] = [b for b in unmerged if b not in heads]
    res["ci_pending"] = [p["number"] for p in prs
                         if p["state"] == "OPEN" and lib.ci_state(p.get("statusCheckRollup")) == "pending"]
    return res


def _cgroup(pid_dir):
    return (pid_dir / "cgroup").read_text(encoding="utf-8").strip().splitlines()[-1].rsplit("/", 1)[-1]


def _self_chain(proc=Path("/proc")):
    """Process names from this process up to init."""
    names = []
    for pid in _ancestors(proc):
        try:
            names.append(_stat(proc, pid)[0])
        except (OSError, ValueError, IndexError):
            pass
    return names


def _harness_child(proc, pid):
    """True when pid descends from a `claude` process through a non-shell first hop: an MCP server
    or other harness helper. Jobs a session starts through its Bash tool pass through a shell and stay."""
    chain = []
    while pid > 1:
        try:
            comm, ppid = _stat(proc, pid)
        except (OSError, ValueError, IndexError):
            return False
        if _is_claude(comm):
            return bool(chain) and chain[-1] not in TOOL_SHELLS
        chain.append(comm)
        pid = ppid
    return False


def _split_others(res, other_pids, chain):
    """Processes started by another live session are that session's work, not this one's leftovers."""
    res["others_procs"] = []
    if not other_pids:
        return res
    mine = []
    for p in res["procs"]:
        owner = next((other_pids[a] for a in chain(p["pid"]) if a in other_pids), None)
        if owner is None:
            mine.append(p)
        else:
            res["others_procs"].append({**p, "session": owner.get("id"), "focus": owner.get("focus", "")})
    res["procs"] = mine
    return res


def running_work(root, proc=Path("/proc"), probe=None, other_pids=None):
    """Processes working inside the repo that no systemd unit manages (dev servers, stray jobs).

    A process in ANOTHER .service cgroup is managed (e.g. webapp-dashboard). One in OUR cgroup is
    not dismissed even if that cgroup is a service: a long-running channel session runs inside one,
    and what it launched is exactly the running work the next session must hear about.
    """
    if not proc.is_dir():
        if probe is None and proc != Path("/proc"):
            return {"supported": False, "procs": [], "others_procs": []}  # a test's missing fake /proc
        t = (probe or procs.table)()  # Windows / macOS: match the project path in command lines
        if not t["supported"]:
            return {"supported": False, "procs": [], "others_procs": [], "reason": t.get("reason", "no process probe")}
        rows = t["procs"]
        if os.environ.get("CLAUDE_CODE_EXECPATH") and not any(map(_is_claude, procs.chain_comms(rows, os.getpid()))):
            return {"supported": False, "procs": [], "others_procs": [], "reason": "claude process not recognized; update procs._CLAUDE_BIN"}
        by = {r["pid"]: r for r in rows}
        return _split_others({"supported": True, "procs": procs.running_in(root, rows, os.getpid()), "via": "cmdline"},
                             other_pids, lambda pid: list(procs._ancestor_pids(by, pid)))
    # Under Claude but no ancestor looks like Claude: its process naming changed again, and the harness filter
    # would silently drop every Bash-tool job. Report "unchecked" rather than a false "nothing running".
    if proc == Path("/proc") and os.environ.get("CLAUDE_CODE_EXECPATH") and not any(map(_is_claude, _self_chain())):
        return {"supported": False, "procs": [], "others_procs": [], "reason": "claude process not recognized; update procs._CLAUDE_BIN"}
    root = os.path.realpath(root)
    mine = _ancestors()
    try:
        my_cg = _cgroup(proc / "self")
    except OSError:
        my_cg = None
    found = []
    for d in proc.iterdir():
        if not d.name.isdigit() or int(d.name) in mine:
            continue
        try:
            cwd = os.readlink(d / "cwd")
            if cwd != root and not cwd.startswith(root + os.sep):
                continue
            cg = _cgroup(d)
            comm = (d / "comm").read_text(encoding="utf-8").strip()
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            continue
        if (cg.endswith(".service") and cg != my_cg) or comm in SKIP_COMM or _is_claude(comm) or _harness_child(proc, int(d.name)):
            continue
        found.append({"pid": int(d.name), "cmd": cmd[:160]})
    return _split_others({"supported": True, "procs": found}, other_pids, lambda pid: procs.linux_chain(pid, proc))


def deploy_drift(root, profile, ids):
    """A service that deploys from this repo but started before the latest commit = pulled, not restarted."""
    out = []
    last = lib.git(root, "log", "-1", "--format=%ct")
    services = profile.get("services") or []
    if not isinstance(services, list):
        return [{"unit": "?", "drift": None, "detail": "bad check: services is not a list"}]
    for s in services:
        try:  # a malformed Profile entry is skipped with its reason, never a crashed /sync
            if not isinstance(s, dict):
                raise TypeError("not an object")
            if s.get("deploys_from_repo"):
                out.append(_drift_one(s, ids, last))
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            unit = s.get("unit", "?") if isinstance(s, dict) else "?"
            out.append({"unit": str(unit), "drift": None, "detail": f"bad check: {e}"[:120]})
    return out


def _drift_one(s, ids, last):
    unit = lib.safe_arg(s["unit"], "unit")
    if lib.host_target(s.get("host"), ids) is not None:
        return {"unit": unit, "drift": None, "detail": "remote host — not checked"}
    scope = ["--user"] if s.get("scope", "user") == "user" else []
    rc, o, _ = lib.RUN(["systemctl", *scope, "show", "-p", "ActiveEnterTimestamp", "--timestamp=unix", "--", unit])
    m = re.search(r"@(\d+)", o)
    if rc != 0 or not m or not last:
        return {"unit": unit, "drift": None, "detail": "start time unavailable"}
    started = int(m.group(1))
    return {"unit": unit, "drift": started < int(last), "started": started, "last_commit": int(last)}


def collect_close(cwd, project=None):
    ident = lib.resolve_identity(cwd, project)
    if ident["how"] == "ambiguous":
        return {"identity": ident}
    ids = lib.load_self_ids()
    (lib.vault() / "handoffs").mkdir(parents=True, exist_ok=True)
    p = lib.handoff_path(ident["key"])
    h = lib.parse_handoff(p.read_text(encoding="utf-8")) if p.is_file() else {"profile": {}, "meta": {}}
    profile = h["profile"]
    root = ident["root"]
    is_repo = lib.git(root, "rev-parse", "--git-dir") is not None
    notes = inbox.list_notes(ident["key"]) + inbox.list_notes("_user")
    others = sessions.others(ident["key"])
    m, own = sessions.me(), sessions.own(ident["key"])
    return {
        "identity": ident,
        "sessions": {"me": m[0][:8] if m else None, "registered": own is not None,
                     "focus": (own or {}).get("focus") or "", "others": others},
        "updated_seen": sessions.seen(ident["key"]),  # the handoff 'updated' this session last read or wrote
        "handoff": {"path": str(p), "exists": p.is_file(),
                    "size_kb": round(p.stat().st_size / 1024, 1) if p.is_file() else 0},
        "handoff_updated": h["meta"].get("updated"),  # the concurrent-merge check compares this with /preflight's
        "legacy": None if p.is_file() else lib.find_legacy(root, cwd),
        "git": git_close(root, profile.get("gh") or ident["repo"]) if is_repo else None,
        "running": running_work(root, other_pids={o["pid"]: o for o in others}),
        "drift": deploy_drift(root, profile, ids) if is_repo else [],
        "repo_handoff": ({"uncommitted": bool(lib.git(root, "status", "--porcelain", "--", repohandoff.REL))}
                         if profile.get("shared") and is_repo else None),
        "repo_sha": lib.git(root, "rev-parse", "--short", "HEAD") if is_repo else None,
        "vault_sha": lib.git(lib.vault(), "rev-parse", "--short", "HEAD"),  # recorded BEFORE this session's push
        "inbox_untriaged": len(notes),
        "inbox_notes": [n["path"] for n in notes],
    }


# --- trim ------------------------------------------------------------------------------

ENTRY = re.compile(r"^- \*\*(\d{4}-\d{2}-\d{2})", re.M)
ARC_MARK = "## Last session (archived)\n"
ARC_HEAD = ("---\nkey: {key}\narchive: true\n"
            "note: NOT live state. Older Last session entries, moved here by close.py trim.\n"
            "---\n# Archive: {key}\n\n" + ARC_MARK)


def trim(path, today=None, keep_days=14):
    """Move `## Last session` entries older than keep_days into <key>.archive.md. Undated text stays."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    def size(t):  # the 100 KB guard reports on every path, including when nothing moved
        kb = len(t.encode()) / 1024
        return {"live_kb": round(kb, 1), "over_100kb": kb > 100}

    m = re.search(r"^## Last session[^\n]*\n", text, re.M)
    if not m:
        return {"moved": 0, "note": "no Last session section", **size(text)}
    start = m.end()
    nxt = re.search(r"^## ", text[start:], re.M)
    end = start + nxt.start() if nxt else len(text)
    body = text[start:end]
    starts = [e.start() for e in ENTRY.finditer(body)]
    if not starts:
        return {"moved": 0, **size(text)}
    cutoff = (today or dt.date.today()) - dt.timedelta(days=keep_days)
    entries = [body[a:b] for a, b in zip(starts, starts[1:] + [len(body)])]
    old = [e for e in entries if dt.date.fromisoformat(ENTRY.match(e).group(1)) < cutoff]
    if not old:
        return {"moved": 0, **size(text)}
    keep = [e for e in entries if e not in old]
    new_text = text[:start] + body[:starts[0]] + "".join(keep) + text[end:]
    moved = "".join(old)
    if len(new_text) + len(moved) != len(text):
        raise RuntimeError("trim would lose content; nothing written")
    arc = p.with_name(p.stem + ".archive.md")
    if arc.is_file():
        a = arc.read_text(encoding="utf-8")
        k = a.find(ARC_MARK)
        a = a[:k + len(ARC_MARK)] + moved + a[k + len(ARC_MARK):] if k != -1 else a + "\n" + ARC_MARK + moved
    else:
        a = ARC_HEAD.format(key=p.stem) + moved
    arc.write_text(a, encoding="utf-8")        # archive first: a crash in between duplicates, never loses
    p.write_text(new_text, encoding="utf-8")
    return {"moved": len(old), "archive": str(arc), **size(new_text)}


# --- push ------------------------------------------------------------------------------

SECRET_NAMES = (".credentials.json", ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*")


def _secret_shaped(rel):
    name = rel.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(name, pat) for pat in SECRET_NAMES)


def _under_project_memory(rel):
    parts = rel.split("/")  # projects/<x>/memory/... is the one ignored place `add -f` is meant for
    return len(parts) >= 4 and parts[0] == "projects" and parts[2] == "memory"


OWNER = "owner"  # file inside the lock dir: a held lock is never empty, so no rename can land on top of it
LOCK_IGNORE = ".gitignore"  # "*" inside the lock dir: a held or leftover lock never shows in `git status`


def _claim(lock, token):
    """After mkdir: mark the lock ours. O_EXCL fails when a stale-breaker's rename-back swapped another holder's
    lock in over our still-empty dir (Linux rename replaces an EMPTY directory): then it is not ours."""
    try:
        fd = os.open(lock / OWNER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False  # someone else's lock now sits at the path: never touch it
    except OSError:
        _drop_empty(lock)  # our own dir, still empty: don't leave it to block everyone for 300 s
        return False
    ino = os.fstat(fd).st_ino
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token)
    except OSError:
        try:  # only OUR owner file: a stale-breaker may have moved our dir aside and another waiter taken the path
            if os.stat(lock / OWNER).st_ino == ino:
                (lock / OWNER).unlink()
                _drop_empty(lock)
        except OSError:
            pass
        return False
    try:
        (lock / LOCK_IGNORE).write_text("*\n", encoding="utf-8")
    except OSError:
        pass  # cosmetic: the lock still works, it just shows as untracked
    return True


def _drop_empty(lock):
    try:
        lock.rmdir()  # only succeeds on an empty dir, so it can never remove a claimed lock
    except OSError:
        pass


def _held(lock, token):
    try:
        return (lock / OWNER).read_text(encoding="utf-8") == token
    except OSError:
        return False


def _release(lock, token):
    """Remove the lock only while it still carries our owner token."""
    if not _held(lock, token):
        return
    try:
        (lock / OWNER).unlink()
        (lock / LOCK_IGNORE).unlink(missing_ok=True)
        lock.rmdir()
    except OSError:
        pass


def _break_stale(lock, st):
    """Remove a lock judged stale from `st`, unless another waiter replaced it with a fresh one meanwhile.

    rmdir-by-name would race: two waiters both see the stale lock, the first rmdirs + mkdirs its own, the second
    then rmdirs the first one's FRESH lock. Instead rename it aside (atomic, one winner), then check the renamed
    dir is still the one judged stale (inode + mtime: inodes are reused at once after rmdir); if not, put it back.
    A put-back that fails (the path is taken again: a held lock is never empty, so rename refuses) leaves the
    aside dir where it is: it is someone's lock, never ours to delete.
    """
    aside = lock.with_name(f"{lock.name}.stale-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        os.rename(lock, aside)
    except OSError:
        return False  # gone already, or another waiter moved it first
    try:
        now = aside.stat()
        if (now.st_ino, now.st_mtime_ns) != (st.st_ino, st.st_mtime_ns):
            os.rename(aside, lock)  # someone's fresh lock: give it back and keep waiting
            return False
        (aside / OWNER).unlink(missing_ok=True)
        (aside / LOCK_IGNORE).unlink(missing_ok=True)
        aside.rmdir()
    except OSError:
        return False
    return True


def lock_token():
    return f"{os.getpid()} {secrets.token_hex(8)}"


def acquire_lock(lock, token, retries=15, wait=2):
    """Take the vault's `.sync.lock` (mkdir + owner file), breaking a lock older than 300 s. True when held.

    Shared by /sync's push and /preflight's pull: every git operation that moves the vault's HEAD or working tree
    goes through it. A mkdir error other than "exists" (read-only vault) propagates to the caller."""
    for _ in range(retries):
        try:
            lock.mkdir()
        except FileExistsError:
            try:
                st = lock.stat()
                if time.time() - st.st_mtime > 300 and _break_stale(lock, st):  # stale: its owner died mid-sync
                    continue
            except OSError:
                pass
        else:
            if _claim(lock, token):
                return True
        time.sleep(wait)
    return False


def push(files, message, retries=15):
    """Concurrency-safe vault push: mkdir lock, stage ONLY `files`, pathspec commit, rebase, push, verify.

    The vault is a shared working tree (every session plus any auto-commit tool): never `add -A`, never
    reset/force.
    """
    if not lib.vault_is_git():
        return {"status": "local"}  # a plain vault: the files are written; there is nothing to commit or push
    v = lib.vault().resolve()
    lock = v / ".sync.lock"
    token = lock_token()
    if not acquire_lock(lock, token, retries):
        return {"status": "locked"}
    try:
        def g(*args, t=8, literal=True):
            # --literal-pathspecs: without it git treats *, ?, [...] in a listed path as its OWN glob magic
            # (independent of the shell), so an unmatched shell glob like "$V/*" reaches git as a literal
            # wildcard and `add -f` sweeps in ignored files (.credentials.json, the .live registry) and
            # other sessions' half-writes. Security fix, 2026-09-28.
            # literal=False only for check-ignore: it takes plain pathnames (no glob magic) and dies with
            # "pathspec magic not supported" (rc 128) under --literal-pathspecs.
            return lib.RUN(["git", *(["--literal-pathspecs"] if literal else []), "-C", str(v), *args], timeout=t)

        resolved, outside = [], []
        for f in files:
            try:
                resolved.append(Path(f).resolve().relative_to(v).as_posix())
            except ValueError:  # a symlink (or any path) that resolves outside the vault
                outside.append(f)
        if outside:
            return {"status": "stage_failed", "detail": "outside the vault: " + ", ".join(outside)}
        rel = asked = resolved
        # Security: a directory (especially the vault root) would silently commit ignored files
        # (.credentials.json, projects/**) and other sessions' half-writes. push accepts files only.
        dirs = [r for r in asked if r in ("", ".") or (v / r).is_dir()]
        if dirs:
            res = {"status": "stage_failed",
                   "detail": "directories are not accepted (list files): " + ", ".join(dirs)}
            other = [r for r in asked if r not in dirs and (r == LIVE or r.startswith(LIVE + "/"))]
            if other:
                res["dropped"] = other
            return res
        # The session registry is per machine: never committed, whether named directly or inside a listed folder.
        rel = [r for r in rel if r != LIVE and not r.startswith(LIVE + "/")]

        def tracked_as_one_file(r):
            # A missing path is accepted only when git still tracks it as exactly this one file. A deleted
            # TRACKED DIRECTORY (e.g. a removed handoffs/inbox) would otherwise pass (ls-files matches every
            # file under the prefix) and `add`/`commit` would stage the deletion of everything under it.
            # -z: plain `ls-files` quotes/escapes names with core.quotePath=true (the default) whenever they
            # contain non-ASCII, '"', or '\' (e.g. a curly apostrophe), so the printed name never equals the
            # raw `r` and a legitimate move/delete of such a file was silently dropped. -z prints raw bytes,
            # NUL-terminated, unquoted.
            rc, out, _ = g("ls-files", "-z", "--", r)
            return rc == 0 and out.split("\0") == [r, ""]

        # A moved/deleted file is staged as a deletion when git tracks it; a never-committed file that is gone is dropped.
        rel = [r for r in rel if (v / r).exists() or tracked_as_one_file(r)]
        dropped = [r for r in asked if r not in rel]  # never merged into `missing`: /sync retries on `missing`

        def done(status, **extra):
            res = {"status": status, **extra}
            if dropped:
                res["dropped"] = dropped
            return res

        if not rel:  # an empty pathspec would sweep other sessions' staged files into add/diff/commit
            return done("stage_failed", detail="no listed file exists or is tracked")
        # Security: `add -f` stages ignored files too, so a listed secret (.credentials.json, .env) would be
        # committed. -f is meant only for new files under projects/<x>/memory/ (ignored parent, re-included).
        existing = [r for r in rel if (v / r).exists()]
        bad = []
        for r in existing:
            if _secret_shaped(r):  # tracked or not
                bad.append(r)
                continue
            if g("ls-files", "--error-unmatch", "--", r)[0] == 0:
                continue  # tracked: a later ignore pattern does not make an already-committed file a leak
            rc = g("check-ignore", "-q", "--no-index", "--", r, literal=False)[0]
            if rc not in (0, 1):  # cannot tell: refuse rather than force-add blind
                bad.append(f"{r} (ignore state unknown, rc={rc})")
            elif rc == 0 and not _under_project_memory(r):
                bad.append(r)
        if bad:
            return done("stage_failed", detail="ignored or secret-shaped files are not accepted: " + ", ".join(bad))
        if not _held(lock, token):  # a stale-breaker moved our fresh lock aside and a third waiter took the path
            return done("locked")
        rc, out, err = g("add", "-f", "--", *rel)  # -f: NEW files under an ignored parent are silently skipped otherwise
        if rc != 0:  # all-or-nothing: one bad path stages nothing, which must not read as "nothing to commit"
            return done("stage_failed", detail=(err or out)[-300:])
        # `add` exits 0 yet stages nothing for a file inside a nested repository: verify every existing path
        # landed in the index, else unstage what this call staged (all-or-nothing) and say which path.
        rc, out, _ = g("ls-files", "-z", "--", *existing) if existing else (0, "", "")
        unstaged = [r for r in existing if r not in set(out.split("\0"))] if rc == 0 else existing
        if unstaged:
            staged_now = [r for r in rel if r not in unstaged]
            if staged_now:
                g("restore", "--staged", "--", *staged_now)
            return done("stage_failed", detail="not stageable (e.g. inside a nested repository): "
                        + ", ".join(unstaged))

        def missing():
            return [r for r in rel if (v / r).exists() and g("cat-file", "-e", f"HEAD:{r}")[0] != 0]

        new = g("diff", "--cached", "--quiet", "--", *rel)[0] != 0
        if new:
            rc, out, err = g("commit", "-q", "-m", message, "--", *rel)  # pathspec commit: others' staged files stay out
            if rc != 0:
                return done("commit_failed", detail=(err or out)[-300:])
        if g("rev-parse", "--abbrev-ref", "@{u}")[0] != 0:  # no upstream: nothing to pull or push
            return done("committed_local", sha=g("rev-parse", "--short", "HEAD")[1].strip(), missing=missing(),
                        reason=lib.no_upstream_reason(v))
        if not new and g("rev-list", "--count", "@{u}..HEAD")[1].strip() in ("", "0"):
            return done("nothing")  # nothing new AND nothing left unpushed by an earlier failed run
        stash = None
        for _attempt in range(2):
            rc, out, err = g("pull", "--rebase", "--autostash", t=60)
            if lib.rebase_in_progress(v):
                # Never leave the shared vault mid-rebase: abort restores the local commit and the autostash.
                g("rebase", "--abort", t=60)
                return {"status": "rebase_conflict", "detail": (out + err)[-500:]}
            text = (out + err).lower()
            if "autostash" in text and "conflict" in text:
                # The rebase landed; popping other sessions' uncommitted work conflicted. Git kept it as
                # the newest stash entry: name it by sha so recovery never touches an older stash.
                stash = g("rev-parse", "stash@{0}")[1].strip()
            rc, out, err = g("push", "-q", t=60)
            if rc == 0:
                break
        else:
            res = done("push_failed", detail=(err or out)[-300:])
            return {**res, "stash": stash} if stash else res
        res = done("autostash_conflict" if stash else "ok",
                    sha=g("rev-parse", "--short", "HEAD")[1].strip(), missing=missing())
        return {**res, "stash": stash} if stash else res
    finally:
        _release(lock, token)


def write_repo_handoff(cwd, project=None):
    ident = lib.resolve_identity(cwd, project)
    p = lib.handoff_path(ident["key"]) if ident.get("key") else None
    if not p or not p.is_file():
        return {"written": False, "reason": "no project handoff to publish"}
    names = lib.load_self_ids().get("names") or ["unknown"]
    needles = leakguard.needles(lib.user_file()["profile"], names=False)  # the author name is public by design
    res = repohandoff.write(ident["root"], p.read_text(encoding="utf-8"), names[0], needles)
    if res["written"]:  # collaborators see the file only once it is committed and not ignored
        root = ident["root"]
        res["uncommitted"] = bool(lib.git(root, "status", "--porcelain", "--", repohandoff.REL))
        res["ignored"] = lib.git(root, "check-ignore", "-q", repohandoff.REL) is not None  # rc 0 = ignored
    return res


def check_profile(path):
    """Does this handoff's Profile json still parse? /sync runs it after every handoff write."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        return {"profile_error": f"unreadable: {type(e).__name__}: {e}"}
    return {"profile_error": lib.parse_handoff(text)["profile_error"]}


def session_cmd(cwd, project, action, text):
    ident = lib.resolve_identity(cwd, project)
    if not ident.get("key"):
        return {"ok": False, "reason": "ambiguous project; pass --project"}
    if action == "focus":
        return sessions.set_focus(ident["key"], text)
    p = lib.handoff_path(ident["key"])
    updated = lib.parse_handoff(p.read_text(encoding="utf-8"))["meta"].get("updated") if p.is_file() else None
    return sessions.register(ident["key"], ident["root"], updated)


def main(argv=None):
    ap = argparse.ArgumentParser(description="/sync collector")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--project", help="handoff key, when the start folder holds several projects")
    sub = ap.add_subparsers(dest="cmd")
    t = sub.add_parser("trim")
    t.add_argument("path")
    cp = sub.add_parser("check-profile")
    cp.add_argument("path")
    pu = sub.add_parser("push")
    pu.add_argument("--message", required=True)
    pu.add_argument("--files", nargs="+", required=True)
    n = sub.add_parser("note")
    n.add_argument("--to", required=True)
    n.add_argument("--from", dest="from_", required=True)
    n.add_argument("--subject", required=True)
    n.add_argument("--file")
    d = sub.add_parser("inbox-done")
    d.add_argument("--files", nargs="+", required=True)
    sub.add_parser("repo-handoff")
    se = sub.add_parser("session")
    se.add_argument("action", choices=["focus", "refresh"])
    se.add_argument("text", nargs="?", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "trim":
            res = trim(a.path)
        elif a.cmd == "check-profile":
            res = check_profile(a.path)
        elif a.cmd == "push":
            res = push(a.files, a.message)
        elif a.cmd == "note":
            body = (
                Path(a.file).read_text(encoding="utf-8")
                if a.file
                else sys.stdin.buffer.read().decode("utf-8-sig", "replace")
            )
            p = inbox.write_note(a.to, a.from_, a.subject, body)
            res = {"path": str(p), **push([str(p)], f"note: {a.to} — {a.subject}"[:120])}
        elif a.cmd == "inbox-done":
            refused = []
            staged = inbox.mark_done(a.files, refused)
            moved = set(staged[0::2])
            res = {"moved": len(moved), "stage": staged, "refused": refused,
                   "already_done": [f for f in a.files if str(Path(f)) not in moved and f not in refused]}
        elif a.cmd == "repo-handoff":
            res = write_repo_handoff(a.cwd, a.project)
        elif a.cmd == "session":
            res = session_cmd(a.cwd, a.project, a.action, a.text)
        else:
            res = collect_close(a.cwd, a.project)
    except Exception as e:  # /sync must still be able to report: surface the failure as data
        res = {"fatal": f"{type(e).__name__}: {e}"}
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
