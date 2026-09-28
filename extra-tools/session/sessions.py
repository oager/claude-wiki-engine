# ~/.claude/tools/session/sessions.py
"""Per-machine registry of live Claude sessions per project: <vault>/handoffs/.live/<key>/<session-id>-<pid>.json.

Never committed (the folder ignores itself). Lets /preflight name other sessions on Linux, Windows and macOS, and lets
/sync see which handoff version this session last read. Design: claude-wiki-engine README, "Session handoff".
"""
import datetime as dt
import json
import os
import re
import socket
import tempfile
import time
from pathlib import Path

import lib
import procs

EXPIRE_S = 7 * 86400  # an entry not rewritten for a week is stale whatever its pid says
GRACE_S = 600  # never delete an entry written in the last 10 minutes (a slow probe must not erase a new session)


def me():
    """(session_id, pid) of this Claude session, or None outside Claude / on builds without the variables."""
    sid = re.sub(r"[^A-Za-z0-9-]", "", os.environ.get("CLAUDE_CODE_SESSION_ID") or "")[:64]
    pid = os.environ.get("CLAUDE_PID") or ""
    return (sid, int(pid)) if sid and pid.isdigit() else None


def live_dir(key):
    if not (isinstance(key, str) and re.fullmatch(r"[a-z0-9][a-z0-9._-]*", key)):
        raise ValueError(f"bad registry key: {key!r}")
    return lib.vault() / "handoffs" / ".live" / key


def _own_entries(d, pid, host):
    """This process's entries, newest first. /clear gives a running session a new id but keeps its pid, so
    identity is (host, pid): every `*-<pid>.json` written from this host is this process under some id."""
    found = []
    for p in d.glob(f"*-{pid}.json") if d.is_dir() else []:
        data = None if p.name.startswith(".") else _read(p)
        if data and data.get("host") == host and data.get("pid") == pid:
            try:
                found.append((p.stat().st_mtime, p, data))
            except OSError:
                pass
    return [(p, data) for _, p, data in sorted(found, key=lambda t: t[0], reverse=True)]


def _mine_path(key):
    """This process's newest entry, or the path it would be written to under the current session id."""
    m = me()
    if not m:
        return None
    try:
        d = live_dir(key)
    except ValueError:
        return None
    own = _own_entries(d, m[1], socket.gethostname())
    return own[0][0] if own else d / f"{m[0]}-{m[1]}.json"


def _read(p):
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write(p, data):
    """Atomic: a reader never sees half a file."""
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _unlink(p):
    try:
        p.unlink()
    except OSError:
        pass


def _should_delete(p):
    """Return True if file is old enough to delete (past grace period)."""
    try:
        age = time.time() - p.stat().st_mtime
        return age > GRACE_S
    except OSError:
        return False


def register(key, root, updated_seen, focus=None):
    try:
        d = live_dir(key)
    except ValueError:
        return {"registered": False, "reason": "bad registry key"}
    m = me()
    if m is None:
        return {"registered": False, "reason": "no session id"}
    p = d / f"{m[0]}-{m[1]}.json"
    try:
        d.mkdir(parents=True, exist_ok=True)
        gi = d.parent / ".gitignore"
        if not gi.exists():
            gi.write_text("*\n", encoding="utf-8")
        host = socket.gethostname()
        own = _own_entries(d, m[1], host)  # this process under its current id or one it had before a /clear
        old = own[0][1] if own else {}
        now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%MZ")
        _write(p, {"session_id": m[0], "pid": m[1], "host": host,
                   "started": old.get("started") or now, "updated_seen": updated_seen,
                   "focus": old.get("focus", "") if focus is None else focus,
                   "root": str(root), "platform": procs._platform()})
        for q, _ in own:
            if q != p:
                _unlink(q)  # this process's older ids: one entry per process
    except OSError as e:
        return {"registered": False, "reason": f"registry not writable: {e}"[:160]}
    return {"registered": True, "path": str(p)}


def set_focus(key, text):
    p = _mine_path(key)
    data = _read(p) if p else None
    if data is None:
        return {"ok": False, "reason": "not registered; run /preflight first"}
    data["focus"] = " ".join(str(text).split())[:120]
    try:
        _write(p, data)
    except OSError as e:
        return {"ok": False, "reason": f"registry not writable: {e}"[:160]}
    return {"ok": True, "focus": data["focus"]}


def own(key):
    """This session's registry entry (dict), or None when it is not registered."""
    p = _mine_path(key)
    return _read(p) if p else None


def seen(key):
    data = own(key)
    return data.get("updated_seen") if data else None


def others(key):
    """Other live sessions of this project on this machine; removes dead or expired entries past the grace period."""
    try:
        d = live_dir(key)
    except ValueError:
        return []
    m = me()
    mine, host, out = _mine_path(key), socket.gethostname(), []
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        if p.name.startswith(".") or p == mine:
            continue
        try:
            age = time.time() - p.stat().st_mtime
        except OSError:
            continue
        data = _read(p)
        if data is None:
            if _should_delete(p):
                _unlink(p)
            continue
        if data.get("host") != host:
            continue  # another machine's entry in a shared folder: not ours to judge
        if m and data.get("pid") == m[1]:
            continue  # this process under an id it had before a /clear
        alive, name = alive_name(data.get("pid"))
        if not (alive is True and name and procs.is_claude(name) and age < EXPIRE_S):
            if _should_delete(p):
                _unlink(p)
            continue
        out.append({"id": str(data.get("session_id", ""))[:8], "pid": data["pid"], "focus": data.get("focus") or "",
                    "started": data.get("started"), "updated_seen": data.get("updated_seen"),
                    "age_h": round(age / 3600, 1)})
    return out


# --- liveness, per OS (never os.kill: on Windows it terminates the process) -------------

def alive_name(pid):
    """(True, name) alive; (False, None) gone or invalid; (None, None) unknown (probe error, access denied)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False, None
    plat = procs._platform()
    if plat == "nt":
        return _alive_windows(pid)
    if plat == "darwin":
        rc, out, _ = lib.RUN(["ps", "-p", str(pid), "-o", "comm="])
        if rc == 0 and out.strip():
            return True, procs._comm(out.strip())
        return (False, None) if rc == 1 else (None, None)
    p = Path(f"/proc/{pid}")
    if not p.exists():
        return False, None
    try:
        return True, (p / "comm").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None, None


def _alive_windows(pid):
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return (False, None) if ctypes.get_last_error() == 87 else (None, None)  # 87: no such process
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)):
            return None, None
        if code.value != 259:  # STILL_ACTIVE
            return False, None
        buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        if not k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None, None
        name = procs._comm(buf.value)
        return True, name
    finally:
        k.CloseHandle(h)
