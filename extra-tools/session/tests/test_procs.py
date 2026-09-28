import os

import close as cl
import open as op
import procs
import pytest
from test_review_fixes import _fake_proc

ME = os.getpid()
ROOT = "C:\\Users\\a\\proj"
nt_skip = pytest.mark.skipif(os.name == "nt", reason="needs symlinks; Windows Git Bash usually cannot create them")


def rows_for(root):
    return [
        {"pid": 10, "ppid": 1, "comm": "explorer", "cmdline": "explorer.exe"},
        {"pid": 20, "ppid": 10, "comm": "claude", "cmdline": "C:\\Users\\a\\claude-code\\2.1.281\\claude.exe"},
        {"pid": 30, "ppid": 20, "comm": "bash", "cmdline": "bash -c python close.py"},
        {"pid": ME, "ppid": 30, "comm": "python", "cmdline": "python close.py"},
        {"pid": 40, "ppid": 20, "comm": "node", "cmdline": f"node mcp-server --root {root}"},   # MCP under claude
        {"pid": 50, "ppid": 30, "comm": "node", "cmdline": f"node {root}\\server.js"},          # job via Bash tool
        {"pid": 60, "ppid": 1, "comm": "node", "cmdline": "node C:\\elsewhere\\x.js"},          # other folder
        {"pid": 70, "ppid": 1, "comm": "python", "cmdline": "python C:/Users/a/proj/tool.py"},  # forward slashes
        {"pid": 80, "ppid": 1, "comm": "node", "cmdline": "node /c/Users/a/proj/dev.js"},       # Git Bash form
        {"pid": 90, "ppid": 1, "comm": "node", "cmdline": "node C:\\Users\\a\\proj2\\x.js"},    # sibling prefix
    ]


def test_running_in_filters_and_matches_every_spelling():
    assert [p["pid"] for p in procs.running_in(ROOT, rows_for(ROOT), ME)] == [50, 70, 80]


def test_running_in_root_with_spaces():
    root = "C:\\Users\\a\\My Proj"
    rows = [{"pid": 5, "ppid": 1, "comm": "node", "cmdline": 'node "C:\\Users\\a\\My Proj\\s.js"'}]
    assert [p["pid"] for p in procs.running_in(root, rows, ME)] == [5]


def test_running_in_matches_non_ascii_root():
    root = "C:\\Users\\José\\proj"
    rows = [{"pid": 6, "ppid": 1, "comm": "node", "cmdline": "node C:\\Users\\José\\proj\\s.js"}]
    assert [p["pid"] for p in procs.running_in(root, rows, ME)] == [6]


def test_cim_forces_utf8_output_encoding():
    assert procs.CIM.startswith("[Console]::OutputEncoding=[Text.Encoding]::UTF8;")


def test_running_in_reports_relative_arg_job_under_session_claude():
    # pid 55 has no root in its command line but descends from the session's own claude (pid 20) through
    # the same shell (30) as pid ME — a `cd`'d "python -m http.server" job the old cmdline-only match missed.
    rows = rows_for(ROOT) + [{"pid": 55, "ppid": 30, "comm": "python", "cmdline": "python -m http.server"}]
    pids = [p["pid"] for p in procs.running_in(ROOT, rows, ME)]
    assert pids == [50, 70, 80, 55]
    assert 40 not in pids  # MCP-like row under claude (pid 20), first hop not a shell: still a harness child


def test_parse_cim_list_and_single():
    one = '{"ProcessId":4,"ParentProcessId":0,"Name":"System","CommandLine":null}'
    assert procs.parse_cim(one) == [{"pid": 4, "ppid": 0, "comm": "system", "cmdline": ""}]
    many = '[{"ProcessId":20,"ParentProcessId":10,"Name":"claude.exe","CommandLine":"C:\\\\x\\\\claude.exe"}]'
    assert procs.parse_cim(many)[0]["comm"] == "claude"


def test_parse_ps():
    text = ("    1     0 /sbin/launchd\n"
            "  501     1 /Users/a/.local/share/claude/versions/2.1.283 --resume\n"
            "  502   501 -zsh\n")
    assert [(r["pid"], r["ppid"], r["comm"]) for r in procs.parse_ps(text)] == [
        (1, 0, "launchd"), (501, 1, "2.1.283"), (502, 501, "zsh")]


def test_table_macos(fake, monkeypatch):
    monkeypatch.setattr(procs, "_platform", lambda: "darwin")
    fake.on(["ps"], 0, "  1 0 /sbin/launchd\n")
    assert procs.table() == {"supported": True, "procs": [
        {"pid": 1, "ppid": 0, "comm": "launchd", "cmdline": "/sbin/launchd"}]}


def test_table_probe_failure_is_unsupported_with_reason(fake, monkeypatch):
    monkeypatch.setattr(procs, "_platform", lambda: "nt")
    fake.on(["powershell"], 124, "", "timeout after 8s")
    t = procs.table()
    assert t["supported"] is False and "rc=124" in t["reason"]


def test_table_unreadable_output(fake, monkeypatch):
    monkeypatch.setattr(procs, "_platform", lambda: "nt")
    fake.on(["powershell"], 0, "not json")
    t = procs.table()
    assert t["supported"] is False and "unreadable" in t["reason"]


def test_running_work_uses_probe_off_linux(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "C:\\Users\\a\\claude-code\\2.1.281\\claude.exe")
    res = cl.running_work(ROOT, proc=tmp_path / "noproc",
                          probe=lambda: {"supported": True, "procs": rows_for(ROOT)})
    assert res["supported"] is True and res["via"] == "cmdline"
    assert [p["pid"] for p in res["procs"]] == [50, 70, 80]


def test_running_work_probe_unrecognized_claude_is_unchecked(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/opt/claude/cli.js")
    rows = [dict(r, comm="node") if r["pid"] == 20 else r for r in rows_for(ROOT)]
    res = cl.running_work(ROOT, proc=tmp_path / "noproc", probe=lambda: {"supported": True, "procs": rows})
    assert res["supported"] is False and "not recognized" in res["reason"]


def test_running_work_probe_failure_passes_reason(tmp_path):
    res = cl.running_work(ROOT, proc=tmp_path / "noproc",
                          probe=lambda: {"supported": False, "procs": [], "reason": "process probe failed (rc=1)"})
    assert res == {"supported": False, "procs": [], "reason": "process probe failed (rc=1)"}


def test_is_claude_windows_execpath(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "C:\\x\\claude-code\\2.1.281\\claude-next.exe")
    assert procs.is_claude("claude-next") and procs.is_claude("2.1.281") and procs.is_claude("claude")
    assert not procs.is_claude("node")


@nt_skip
def test_concurrent_session_counted_once(tmp_path, repo, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(procs, "ancestors", lambda proc=None: set())
    _fake_proc(proc, 700, "bash", 1, str(tmp_path))
    _fake_proc(proc, 701, "claude", 700, str(repo))     # launcher
    _fake_proc(proc, 702, "2.1.283", 701, str(repo))    # its native child: the same session
    _fake_proc(proc, 703, "2.1.283", 1, str(tmp_path))  # a session in another folder
    assert [s["pid"] for s in procs.claude_sessions_in(repo, proc)] == [701]


@nt_skip
def test_concurrent_excludes_own_session(tmp_path, repo, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(procs, "ancestors", lambda proc=None: {701, 702})
    _fake_proc(proc, 700, "bash", 1, str(tmp_path))
    _fake_proc(proc, 701, "claude", 700, str(repo))
    _fake_proc(proc, 702, "2.1.283", 701, str(repo))
    assert procs.claude_sessions_in(repo, proc) == []


def test_concurrent_unsupported(tmp_path):
    assert procs.claude_sessions_in(tmp_path, tmp_path / "noproc") is None


@pytest.mark.skipif(not os.path.isdir("/proc"), reason="Linux /proc only")
def test_collect_reports_concurrent(vault, repo, fake):
    assert isinstance(op.collect(repo)["concurrent"], list)
