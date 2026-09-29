import json
import os
import socket

import close as cl
import inbox
import open as op
import procs
import pytest
import sessions
from test_push import pushable  # noqa: F401  (fixture)
from test_review_fixes import _fake_proc

KEY = "alice-demo-proj"  # the fixture repo's handoff key (tests/conftest.py)
nt_skip = pytest.mark.skipif(os.name == "nt", reason="needs symlinks; Windows Git Bash usually cannot create them")


@pytest.fixture
def me_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "aaaa1111-bbbb")
    monkeypatch.setenv("CLAUDE_PID", "4242")


def _other(vault, key, pid=900, focus="docs"):
    d = vault / "handoffs/.live" / key
    d.mkdir(parents=True, exist_ok=True)
    (d / f"cccc2222-{pid}.json").write_text(json.dumps({
        "session_id": "cccc2222", "pid": pid, "host": socket.gethostname(), "started": "2026-09-28T10:00Z",
        "updated_seen": "2026-09-28T09:00Z", "focus": focus}), encoding="utf-8")


def test_collect_registers_and_reports_others(vault, repo, fake, me_env, monkeypatch):
    _other(vault, KEY)
    monkeypatch.setattr(sessions, "alive_name", lambda pid: (True, "2.1.283") if pid == 900 else (False, None))
    res = op.collect(repo)
    s = res["sessions"]
    assert s["me"] == "aaaa1111" and [o["pid"] for o in s["others"]] == [900]
    assert res["concurrent"] == s["others"]
    assert (vault / "handoffs/.live" / KEY / "aaaa1111-bbbb-4242.json").is_file()


def test_collect_without_session_env(vault, repo, fake):
    s = op.collect(repo)["sessions"]
    assert s["me"] is None and s["reason"] == "no session id"


def test_collect_close_reports_updated_seen(vault, repo, fake, me_env):
    sessions.register(KEY, str(repo), "2026-09-28T08:00Z")
    res = cl.collect_close(repo)
    assert res["updated_seen"] == "2026-09-28T08:00Z" and res["sessions"]["me"] == "aaaa1111"


def test_session_cli_focus_and_refresh(vault, repo, fake, me_env, capsys):
    cl.main(["--cwd", str(repo), "session", "refresh"])
    assert json.loads(capsys.readouterr().out)["registered"] is True
    cl.main(["--cwd", str(repo), "session", "focus", "the installer"])
    assert json.loads(capsys.readouterr().out) == {"ok": True, "focus": "the installer"}


def test_push_never_stages_registry(vault, pushable, me_env):  # noqa: F811
    sessions.register("k", "/x", "u")
    entry = vault / "handoffs/.live/k/aaaa1111-bbbb-4242.json"
    other = vault / "handoffs/k.md"
    other.write_text("hand", encoding="utf-8")
    res = cl.push([str(entry), str(other)], "m")
    assert res["status"] == "ok" and res["dropped"] == ["handoffs/.live/k/aaaa1111-bbbb-4242.json"]


def test_mark_done_twice_is_already_done(vault, capsys):
    p = inbox.write_note("k", "s", "one", "b")
    inbox.mark_done([str(p)])
    assert inbox.mark_done([str(p)]) == []
    cl.main(["inbox-done", "--files", str(p)])
    res = json.loads(capsys.readouterr().out)
    assert res["moved"] == 0 and res["already_done"] == [str(p)]


@nt_skip
def test_linux_related(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    _fake_proc(proc, 700, "bash", 1, str(tmp_path))
    _fake_proc(proc, 701, "claude", 700, str(tmp_path))   # launcher found by the /proc scan
    _fake_proc(proc, 702, "2.1.283", 701, str(tmp_path))  # CLAUDE_PID of that session (registered)
    _fake_proc(proc, 703, "claude", 700, str(tmp_path))   # an unrelated launcher
    assert procs.linux_related(701, [702], proc) is True
    assert procs.linux_related(703, [702], proc) is False
    assert procs.linux_related(701, [], proc) is False


ME = os.getpid()


def test_probe_path_moves_other_sessions_job(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
    root = "C:\\Users\\a\\proj"
    rows = [
        {"pid": 120, "ppid": 1, "comm": "claude", "cmdline": "claude.exe"},                  # the other session
        {"pid": 130, "ppid": 120, "comm": "bash", "cmdline": "bash"},
        {"pid": 140, "ppid": 130, "comm": "node", "cmdline": f"node {root}\\server.js"},     # its dev server
        {"pid": ME, "ppid": 1, "comm": "python", "cmdline": "python close.py"},
        {"pid": 150, "ppid": 1, "comm": "node", "cmdline": f"node {root}\\other.js"},        # nobody's session
    ]
    res = cl.running_work(root, proc=tmp_path / "noproc", probe=lambda: {"supported": True, "procs": rows},
                          other_pids={120: {"id": "cccc2222", "focus": "docs"}})
    assert [p["pid"] for p in res["procs"]] == [150]
    assert res["others_procs"] == [{"pid": 140, "cmd": f"node {root}\\server.js", "session": "cccc2222", "focus": "docs"}]


@nt_skip
def test_linux_path_moves_other_sessions_job(tmp_path, repo):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self/cgroup").write_text("0::/user.slice/user-1000.slice/session-9.scope\n", encoding="utf-8")
    _fake_proc(proc, 800, "2.1.283", 1, str(tmp_path))   # the other session (its CLAUDE_PID)
    _fake_proc(proc, 801, "bash", 800, str(tmp_path))
    _fake_proc(proc, 802, "sleep", 801, str(repo))       # its job in this repo
    _fake_proc(proc, 803, "node", 1, str(repo))          # an orphan dev server
    res = cl.running_work(repo, proc=proc, other_pids={800: {"id": "cccc2222", "focus": "docs"}})
    assert sorted(p["pid"] for p in res["procs"]) == [803]
    assert sorted(p["pid"] for p in res["others_procs"]) == [802]


def test_no_other_sessions_keeps_everything(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
    rows = [{"pid": ME, "ppid": 1, "comm": "python", "cmdline": "python"},
            {"pid": 5, "ppid": 1, "comm": "node", "cmdline": "node C:/p/x.js"}]
    res = cl.running_work("C:/p", proc=tmp_path / "noproc", probe=lambda: {"supported": True, "procs": rows})
    assert [p["pid"] for p in res["procs"]] == [5] and res["others_procs"] == []
