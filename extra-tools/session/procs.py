"""Process facts for the session collectors: which processes are Claude, and what else runs in a project.

Linux reads /proc, which exposes each process's working directory. Windows and macOS have no cheap cwd, so their
probe lists command lines and matches the project path inside them.
Design: claude-wiki-engine README, "Session handoff". Stdlib only.
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import lib

SHELLS = {"bash", "sh", "zsh", "fish", "dash", "pwsh", "powershell", "cmd"}
_CLAUDE_BIN = re.compile(r"^(claude|\d+\.\d+\.\d+)$")  # native installs run versions/<ver>
# General runtimes: an npm install's EXECPATH may be `node`, and counting every node process as Claude would hide
# a node dev server (a false clean close). Such an install is then unrecognized and reported "unchecked".
_RUNTIMES = re.compile(r"^(node|nodejs|bun|deno|python|python\d(\.\d+)?|pythonw|pwsh|powershell)$")
# Helpers the command-line probe skips: terminal hosts and short-lived tools under the session's shell.
PROBE_SKIP = {"conhost", "git", "ssh", "less", "openconsole", "windowsterminal"}
CIM = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
       "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine"
       " | ConvertTo-Json -Compress")


def _basename(s):
    return re.split(r"[\\/]", s)[-1] if s else ""


def _comm(name):
    """Normalize a process name across platforms: lower case, no .exe, no login-shell dash."""
    name = _basename(name).lstrip("-").lower()
    return name[:-4] if name.endswith(".exe") else name


def is_claude(comm):
    """Claude's process name: "claude", a version (native installs run versions/<ver>), or whatever binary this
    session was launched as (Linux caps comm at 15 characters), unless that is a general runtime such as node."""
    exe = _comm(os.environ.get("CLAUDE_CODE_EXECPATH", ""))
    if _RUNTIMES.match(exe):
        exe = ""
    return bool(_CLAUDE_BIN.match(comm)) or bool(exe) and comm in (exe, exe[:15])


# --- Linux /proc -------------------------------------------------------------------

def proc_stat(proc, pid):
    """(comm, ppid) from /proc/<pid>/stat; comm may contain spaces, so split on the last ')'."""
    text = (proc / str(pid) / "stat").read_text(encoding="utf-8")
    return text[text.index("(") + 1:text.rindex(")")], int(text.rsplit(")", 1)[1].split()[1])


def ancestors(proc=Path("/proc")):
    pids, pid = set(), os.getpid()
    while pid > 1:
        pids.add(pid)
        try:
            pid = proc_stat(proc, pid)[1]
        except (OSError, ValueError, IndexError):
            break
    return pids


def claude_sessions_in(root, proc=Path("/proc")):
    """Other Claude sessions whose working directory is inside root; None where /proc is missing."""
    if not proc.is_dir():
        return None
    root = os.path.realpath(root)
    mine = ancestors(proc)
    found = []
    for d in proc.iterdir():
        if not d.name.isdigit() or int(d.name) in mine:
            continue
        try:
            comm, ppid = proc_stat(proc, int(d.name))
            if not is_claude(comm):
                continue
            cwd = os.readlink(d / "cwd")
            parent = proc_stat(proc, ppid)[0] if ppid > 1 else ""
            started = d.stat().st_mtime
        except (OSError, ValueError, IndexError):
            continue
        if (cwd != root and not cwd.startswith(root + os.sep)) or is_claude(parent):
            continue  # outside the project, or the native child of a launcher already counted
        found.append({"pid": int(d.name),
                      "started": dt.datetime.fromtimestamp(started, dt.UTC).strftime("%Y-%m-%dT%H:%MZ")})
    return sorted(found, key=lambda s: s["pid"])


# --- Windows / macOS command-line probe --------------------------------------------

def _platform():
    return "nt" if os.name == "nt" else sys.platform


def parse_cim(text):
    data = json.loads(text or "[]")
    if isinstance(data, dict):
        data = [data]
    return [{"pid": int(d["ProcessId"]), "ppid": int(d.get("ParentProcessId") or 0),
             "comm": _comm(d.get("Name") or ""), "cmdline": d.get("CommandLine") or ""}
            for d in data if d.get("ProcessId") is not None]


def parse_ps(text):
    rows = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)$", line)
        if m:
            cmd = m.group(3).strip()
            rows.append({"pid": int(m.group(1)), "ppid": int(m.group(2)),
                         "comm": _comm(cmd.split(" ", 1)[0]), "cmdline": cmd})
    return rows


def table(timeout=8):
    """Every process as {pid, ppid, comm, cmdline}, for platforms without /proc."""
    plat = _platform()
    if plat == "nt":
        rc, out, err = lib.RUN(["powershell", "-NoProfile", "-Command", CIM], timeout=timeout)
        parse = parse_cim
    elif plat == "darwin":
        rc, out, err = lib.RUN(["ps", "-axo", "pid=,ppid=,command="], timeout=timeout)
        parse = parse_ps
    else:
        return {"supported": False, "procs": [], "reason": f"no process probe for {plat}"}
    if rc != 0:
        return {"supported": False, "procs": [],
                "reason": f"process probe failed (rc={rc}): {(err or out).strip()[:120]}"}
    try:
        return {"supported": True, "procs": parse(out)}
    except (ValueError, KeyError, TypeError) as e:
        return {"supported": False, "procs": [], "reason": f"process probe output unreadable: {e}"[:160]}


def chain_comms(rows, pid):
    by, names, seen = {r["pid"]: r for r in rows}, [], set()
    while pid in by and pid not in seen:
        seen.add(pid)
        names.append(by[pid]["comm"])
        pid = by[pid]["ppid"]
    return names


def _harness_child(by, pid):
    """True when pid descends from Claude through a non-shell first hop (an MCP server or harness helper)."""
    chain, seen = [], set()
    while pid in by and pid not in seen:
        seen.add(pid)
        r = by[pid]
        if is_claude(r["comm"]):
            return bool(chain) and chain[-1] not in SHELLS
        chain.append(r["comm"])
        pid = r["ppid"]
    return False


def _root_patterns(root):
    """Every spelling of root a command line may use, each ending at a path boundary (never a prefix match)."""
    k = str(root).replace("\\", "/").rstrip("/").lower()
    forms = {k}
    if re.match(r"^[a-z]:/", k):
        forms.add("/" + k[0] + k[2:])  # Git Bash spells C:/x as /c/x
    return [re.compile(re.escape(f) + r"(?=$|[/\"'\s;,)=:])") for f in forms]


def _ancestor_pids(by, pid):
    """pid then its ppid chain, stopping at a boundary (pid not in by) or a repeat (cycle guard)."""
    seen, p = set(), pid
    while p in by and p not in seen:
        seen.add(p)
        yield p
        p = by[p]["ppid"]


def running_in(root, rows, my_pid):
    """Processes whose command line names root, or that descend from this session's own Claude process (a `cd`'d
    shell's relative-arg jobs, invisible on the command line), minus this session's own chain, Claude itself,
    shells, PROBE_SKIP helpers and harness helpers (MCP servers and other non-shell children Claude spawned
    directly)."""
    by = {r["pid"]: r for r in rows}
    mine = list(_ancestor_pids(by, my_pid))
    claude_pid = next((pid for pid in mine if is_claude(by[pid]["comm"])), None)
    mine = set(mine)
    pats = _root_patterns(root)
    found = []
    for r in rows:
        pid = r["pid"]
        if (pid in mine or is_claude(r["comm"]) or r["comm"] in SHELLS or r["comm"] in PROBE_SKIP
                or _harness_child(by, pid)):
            continue
        cmd = r["cmdline"].replace("\\", "/").lower()
        by_cmdline = any(p.search(cmd) for p in pats)
        by_descent = claude_pid is not None and claude_pid in _ancestor_pids(by, pid)
        if not (by_cmdline or by_descent):
            continue
        found.append({"pid": pid, "cmd": r["cmdline"][:160]})
    return found
