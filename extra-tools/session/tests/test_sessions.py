# ~/.claude/tools/session/tests/test_sessions.py
import datetime as dt
import json
import os
import socket
import subprocess
import sys
import time

import pytest
import sessions
from sessions import GRACE_S

KEY = "demo-key"
CLAUDE = (True, "2.1.283")


@pytest.fixture
def me_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "aaaa1111-bbbb")
    monkeypatch.setenv("CLAUDE_PID", "4242")


def _entry(vault, sid, pid, host=None, age_s=0, **kw):
    d = vault / "handoffs/.live" / KEY
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sid}-{pid}.json"
    data = {"session_id": sid, "pid": pid, "host": host or socket.gethostname(), "started": "2026-09-28T10:00Z",
            "updated_seen": "2026-09-28T09:00Z", "focus": "docs", **kw}
    p.write_text(json.dumps(data), encoding="utf-8")
    if age_s:
        t = time.time() - age_s
        os.utime(p, (t, t))
    return p


def _alive(monkeypatch, table):
    monkeypatch.setattr(sessions, "alive_name", lambda pid: table.get(pid, (False, None)))


def _mine(vault):
    return vault / "handoffs/.live" / KEY / "aaaa1111-bbbb-4242.json"


def test_me_missing_env():
    assert sessions.me() is None


def test_me_sanitizes_id(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "../a b/c.d-1")
    monkeypatch.setenv("CLAUDE_PID", "77")
    assert sessions.me() == ("abcd-1", 77)


def test_register_writes_entry_and_gitignore(vault, me_env):
    assert sessions.register(KEY, "/x/proj", "2026-09-28T10:00Z")["registered"] is True
    data = json.loads(_mine(vault).read_text(encoding="utf-8"))
    assert (data["pid"], data["updated_seen"], data["focus"], data["root"]) == (4242, "2026-09-28T10:00Z", "", "/x/proj")
    assert (vault / "handoffs/.live/.gitignore").read_text(encoding="utf-8") == "*\n"
    assert not [p for p in (vault / "handoffs/.live" / KEY).iterdir() if p.name.startswith(".tmp-")]


def test_register_keeps_focus_and_started(vault, me_env):
    sessions.register(KEY, "/x", "u1")
    sessions.set_focus(KEY, "  the   installer ")
    first = json.loads(_mine(vault).read_text(encoding="utf-8"))
    sessions.register(KEY, "/x", "u2")
    data = json.loads(_mine(vault).read_text(encoding="utf-8"))
    assert (data["focus"], data["updated_seen"], data["started"]) == ("the installer", "u2", first["started"])
    assert sessions.seen(KEY) == "u2"


def test_register_without_session_id(vault):
    assert sessions.register(KEY, "/x", "u") == {"registered": False, "reason": "no session id"}
    assert sessions.seen(KEY) is None


def test_set_focus_unregistered(vault, me_env):
    assert sessions.set_focus(KEY, "x")["ok"] is False


def test_others_lists_live_claude_and_excludes_self(vault, me_env, monkeypatch):
    sessions.register(KEY, "/x", "u")
    _entry(vault, "cccc2222", 900)
    _alive(monkeypatch, {900: CLAUDE, 4242: CLAUDE})
    [o] = sessions.others(KEY)
    assert (o["id"], o["pid"], o["focus"], o["updated_seen"]) == ("cccc2222", 900, "docs", "2026-09-28T09:00Z")


def test_fork_same_id_other_pid_is_listed(vault, me_env, monkeypatch):
    sessions.register(KEY, "/x", "u")
    _entry(vault, "aaaa1111-bbbb", 901)
    _alive(monkeypatch, {901: CLAUDE})
    assert [o["pid"] for o in sessions.others(KEY)] == [901]


def test_dead_old_entry_is_deleted_young_one_kept(vault, monkeypatch):
    old = _entry(vault, "d1", 910, age_s=3600)
    young = _entry(vault, "d2", 911)
    _alive(monkeypatch, {})
    assert sessions.others(KEY) == []
    assert not old.exists() and young.exists()


def test_unknown_liveness_is_not_listed_and_kept_in_grace(vault, monkeypatch):
    young = _entry(vault, "e1", 920)
    _alive(monkeypatch, {920: (None, None)})
    assert sessions.others(KEY) == [] and young.exists()


def test_non_claude_process_is_dead(vault, monkeypatch):
    p = _entry(vault, "f1", 930, age_s=3600)
    _alive(monkeypatch, {930: (True, "nginx")})
    assert sessions.others(KEY) == [] and not p.exists()


def test_other_host_ignored_not_deleted(vault, monkeypatch):
    p = _entry(vault, "g1", 940, host="another-box", age_s=3600)
    _alive(monkeypatch, {940: CLAUDE})
    assert sessions.others(KEY) == [] and p.exists()


def test_expired_entry_removed_even_if_alive(vault, monkeypatch):
    p = _entry(vault, "h1", 950, age_s=8 * 86400)
    _alive(monkeypatch, {950: CLAUDE})
    assert sessions.others(KEY) == [] and not p.exists()


def test_corrupt_entry_old_deleted_young_kept(vault, monkeypatch):
    d = vault / "handoffs/.live" / KEY
    d.mkdir(parents=True)
    old, young = d / "x-1.json", d / "y-2.json"
    old.write_text("{not json", encoding="utf-8")
    young.write_text("{not json", encoding="utf-8")
    t = time.time() - 3600
    os.utime(old, (t, t))
    _alive(monkeypatch, {})
    assert sessions.others(KEY) == [] and not old.exists() and young.exists()


def test_alive_name_this_process():
    alive, name = sessions.alive_name(os.getpid())
    assert alive is True and isinstance(name, str) and name


def test_alive_name_exited_child():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert sessions.alive_name(p.pid)[0] is False


@pytest.mark.parametrize("bad", [None, "x", -1, 0, True])
def test_alive_name_bad_input(bad):
    assert sessions.alive_name(bad) == (False, None)


def test_others_bad_key_tmp_dir(vault, monkeypatch, tmp_path):
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    corrupt = bad_dir / "old-1.json"
    corrupt.write_text("{not json", encoding="utf-8")
    t = time.time() - 3600
    os.utime(corrupt, (t, t))
    assert sessions.others(str(bad_dir)) == [] and corrupt.exists()


def test_others_bad_key_relative(vault):
    assert sessions.others("../x") == []


def test_others_bad_key_none(vault):
    assert sessions.others(None) == []


def test_register_bad_key(vault):
    assert sessions.register(None, "/x", "u") == {"registered": False, "reason": "bad registry key"}
    assert sessions.register("/tmp", "/x", "u") == {"registered": False, "reason": "bad registry key"}


def test_alive_name_darwin_space_in_path(monkeypatch):
    monkeypatch.setattr(sessions.procs, "_platform", lambda: "darwin")
    monkeypatch.setattr(sessions.lib, "RUN", lambda cmd: (0, "/path with spaces/python3", ""))
    alive, name = sessions.alive_name(123)
    assert alive is True and name == "python3"


def test_alive_name_darwin_rc_1(monkeypatch):
    monkeypatch.setattr(sessions.procs, "_platform", lambda: "darwin")
    monkeypatch.setattr(sessions.lib, "RUN", lambda cmd: (1, "", ""))
    assert sessions.alive_name(456) == (False, None)


def test_alive_name_darwin_rc_127(monkeypatch):
    monkeypatch.setattr(sessions.procs, "_platform", lambda: "darwin")
    monkeypatch.setattr(sessions.lib, "RUN", lambda cmd: (127, "", ""))
    assert sessions.alive_name(789) == (None, None)


def test_register_drops_stale_own_pid_entry(vault, me_env):
    """P2 (2026-09-28): a *-<pid>.json entry of this host, >= EXPIRE_S old, is a dead session whose pid the
    OS reused — register() must not adopt its focus/started, and must delete it (it is not this process's)."""
    stale = _entry(vault, "old-session", 4242, age_s=8 * 86400, focus="old")
    assert sessions.seen(KEY) is None  # the stale entry must never be read as this process's own state
    res = sessions.register(KEY, "/x", "u")
    assert res["registered"] is True
    assert not stale.exists()
    data = json.loads(_mine(vault).read_text(encoding="utf-8"))
    assert data["focus"] == ""
    started = dt.datetime.strptime(data["started"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.UTC)
    assert (dt.datetime.now(dt.UTC) - started).total_seconds() < 120


def test_own_entry_old_dead_survives(vault, me_env, monkeypatch):
    sessions.register(KEY, "/x", "u")
    _alive(monkeypatch, {4242: (False, None)})
    age = 3600
    mine = _mine(vault)
    t = time.time() - age
    os.utime(mine, (t, t))
    assert sessions.others(KEY) == [] and mine.exists()


def test_tmp_file_ignored_and_not_deleted(vault, me_env, monkeypatch):
    sessions.register(KEY, "/x", "u")
    d = vault / "handoffs/.live" / KEY
    tmp = d / ".tmp-old.json"
    tmp.write_text("x", encoding="utf-8")
    t = time.time() - 3600
    os.utime(tmp, (t, t))
    _alive(monkeypatch, {})
    assert sessions.others(KEY) == [] and tmp.exists()


def test_unknown_liveness_past_grace_deleted(vault, monkeypatch):
    p = _entry(vault, "u1", 999, age_s=GRACE_S + 1)
    _alive(monkeypatch, {999: (None, None)})
    assert sessions.others(KEY) == [] and not p.exists()


# Acceptance finding 2026-10-04: a clean /exit left its registry entry behind (only lazily pruned by a later
# session of the same project). SessionEnd now runs `close.py session end`, which removes this process's entries.
def test_deregister_removes_own_entries_in_every_project(vault, me_env):
    mine = _mine(vault)
    _entry(vault, "aaaa1111-bbbb", 4242)
    other_dir = vault / "handoffs/.live/other-key"
    other_dir.mkdir(parents=True)
    old_id = other_dir / "old0-4242.json"  # same process under an id it had before a /clear
    old_id.write_text(json.dumps({"session_id": "old0", "pid": 4242, "host": socket.gethostname()}), encoding="utf-8")
    keep_pid = _entry(vault, "cccc", 5555)
    keep_host = _entry(vault, "dddd", 4242, host="another-box")
    gone = sessions.deregister()
    assert sorted(gone) == sorted([str(mine), str(old_id)])
    assert not mine.exists() and not old_id.exists()
    assert keep_pid.exists() and keep_host.exists()


def test_deregister_outside_claude_is_a_no_op(vault, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_PID", raising=False)
    p = _entry(vault, "aaaa1111-bbbb", 4242)
    assert sessions.deregister() == []
    assert p.exists()


@pytest.mark.parametrize("reason,removed", [("clear", False), ("prompt_input_exit", True), ("logout", True)])
def test_session_end_cli_keeps_entry_on_clear(vault, me_env, monkeypatch, capsys, reason, removed):
    import io

    import close as cl
    p = _entry(vault, "aaaa1111-bbbb", 4242)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "SessionEnd", "reason": reason})))
    cl.main(["session", "end"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert p.exists() is not removed  # /clear keeps it: register() carries the focus over to the new id
