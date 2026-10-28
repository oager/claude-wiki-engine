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


def test_dead_old_entry_is_ended_young_one_kept(vault, monkeypatch):
    old = _entry(vault, "d1", 910, age_s=3600)
    young = _entry(vault, "d2", 911)
    _alive(monkeypatch, {})
    assert sessions.others(KEY) == []
    assert "ended" in json.loads(old.read_text(encoding="utf-8"))  # kept, adoptable (Code-tab respawn), never listed
    assert "ended" not in json.loads(young.read_text(encoding="utf-8"))


def test_unknown_liveness_is_not_listed_and_kept_in_grace(vault, monkeypatch):
    young = _entry(vault, "e1", 920)
    _alive(monkeypatch, {920: (None, None)})
    assert sessions.others(KEY) == [] and young.exists()


def test_non_claude_process_is_dead(vault, monkeypatch):
    p = _entry(vault, "f1", 930, age_s=3600)
    _alive(monkeypatch, {930: (True, "nginx")})
    assert sessions.others(KEY) == [] and "ended" in json.loads(p.read_text(encoding="utf-8"))


def test_other_host_ignored_not_deleted(vault, monkeypatch):
    p = _entry(vault, "g1", 940, host="another-box", age_s=3600)
    _alive(monkeypatch, {940: CLAUDE})
    assert sessions.others(KEY) == [] and p.exists()


def test_expired_entry_ended_even_if_alive(vault, monkeypatch):
    p = _entry(vault, "h1", 950, age_s=8 * 86400)
    _alive(monkeypatch, {950: CLAUDE})
    assert sessions.others(KEY) == [] and "ended" in json.loads(p.read_text(encoding="utf-8"))


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


def test_unknown_liveness_past_grace_ended(vault, monkeypatch):
    p = _entry(vault, "u1", 999, age_s=GRACE_S + 1)
    _alive(monkeypatch, {999: (None, None)})
    assert sessions.others(KEY) == [] and "ended" in json.loads(p.read_text(encoding="utf-8"))


# Acceptance finding 2026-10-04: a clean /exit left its registry entry behind (only lazily pruned by a later
# session of the same project). SessionEnd now runs `close.py session end`, which marks this process's entries ended
# (never listed again; adoptable for ADOPT_S, see the Code-tab tests below).
def test_deregister_ends_own_entries_in_every_project(vault, me_env):
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
    assert all("ended" in json.loads(p.read_text(encoding="utf-8")) for p in (mine, old_id))
    for p in (keep_pid, keep_host):
        assert "ended" not in json.loads(p.read_text(encoding="utf-8"))


# Windows retest 2026-10-28: each new desktop Code-tab chat opens in its own scratch folder, so /preflight there
# registers under a fresh key that never runs others() again. Session end sweeps every key instead.
def test_deregister_sweeps_stale_ended_entries_and_empty_keys(vault, me_env):
    base = vault / "handoffs/.live"
    stale = _ended(vault, "old1", 900, sessions.ADOPT_S + 60)
    recent = _ended(vault, "new1", 901, 60)
    foreign = _ended(vault, "far1", 902, sessions.ADOPT_S + 60, host="another-box")
    live = _entry(vault, "live1", 903)
    scratch = base / "local-scratch-2026-10-27-f319dc"
    scratch.mkdir(parents=True)
    t = time.time() - sessions.ADOPT_S - 60
    os.utime(scratch, (t, t))
    fresh = base / "local-scratch-2026-10-28-a8d0bf"
    fresh.mkdir()
    sessions.deregister()
    assert not stale.exists() and recent.exists() and foreign.exists() and live.exists()
    # an empty key goes once it has stayed empty for ADOPT_S; a fresh one may be one /preflight is about to fill
    assert not scratch.exists() and fresh.exists()


def test_deregister_outside_claude_is_a_no_op(vault, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_PID", raising=False)
    p = _entry(vault, "aaaa1111-bbbb", 4242)
    assert sessions.deregister() == []
    assert p.exists()


@pytest.mark.parametrize("reason,ended", [("clear", False), ("resume", False), ("prompt_input_exit", True),
                                          ("logout", True), ("other", True)])
def test_session_end_cli_keeps_entry_on_clear(vault, me_env, monkeypatch, capsys, reason, ended):
    import io

    import close as cl
    p = _entry(vault, "aaaa1111-bbbb", 4242)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "SessionEnd", "reason": reason})))
    cl.main(["session", "end"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    # /clear keeps it live: register() carries the focus over to the new id. Any other end marks it ended.
    assert ("ended" in json.loads(p.read_text(encoding="utf-8"))) is ended


# Pass 3 follow-up, 2026-10-27 (Windows desktop Code tab, hook log): /clear sends SessionEnd reason "other" (the same
# as an archive) and the new process starts with source "startup", a NEW session id and a NEW pid. The Code tab also
# restarts a long-lived session under the SAME id with a new pid. Nothing in the hook payload links old and new.
def _ended(vault, sid, pid, ago_s, by="exit", **kw):
    return _entry(vault, sid, pid, ended=int(time.time() - ago_s), ended_by=by, **kw)


def test_ended_entry_is_not_listed(vault, me_env, monkeypatch):
    sessions.register(KEY, "/x", "u")
    p = _ended(vault, "cccc2222", 900, 60)
    _alive(monkeypatch, {900: CLAUDE})
    assert sessions.others(KEY) == [] and p.exists()


def test_ended_entry_past_adopt_window_is_deleted(vault, monkeypatch):
    p = _ended(vault, "cccc2222", 900, sessions.ADOPT_S + 60)
    _alive(monkeypatch, {})
    assert sessions.others(KEY) == [] and not p.exists()


def test_refresh_adopts_recent_ended_entry_after_code_tab_clear(vault, me_env):
    old = _ended(vault, "old-id", 77, 30, focus="trading: marketscan", started="2026-10-27T20:00Z")
    res = sessions.register(KEY, "/x", "u", adopt_recent=True)
    assert res["registered"] is True and res["adopted"] == "old-id"
    data = json.loads(_mine(vault).read_text(encoding="utf-8"))
    assert (data["focus"], data["started"], data["updated_seen"]) == ("trading: marketscan", "2026-10-27T20:00Z", "u")
    assert "ended" not in data and not old.exists()


def test_refresh_adopts_the_newest_ended_entry(vault, me_env):
    _ended(vault, "older", 70, 600, focus="a")
    _ended(vault, "newer", 71, 30, focus="b")
    assert sessions.register(KEY, "/x", "u", adopt_recent=True)["adopted"] == "newer"


def test_preflight_register_never_adopts_another_ids_ended_entry(vault, me_env):
    """A new session's /preflight right after an archive must not inherit the archived session's focus."""
    old = _ended(vault, "old-id", 77, 30, focus="x")
    res = sessions.register(KEY, "/x", "u")
    assert "adopted" not in res and old.exists()
    assert json.loads(_mine(vault).read_text(encoding="utf-8"))["focus"] == ""


def test_refresh_ignores_ended_entries_past_window_and_other_hosts(vault, me_env):
    _ended(vault, "stale", 70, sessions.ADOPT_S + 60, focus="a")
    _ended(vault, "far", 71, 30, focus="b", host="another-box")
    res = sessions.register(KEY, "/x", "u", adopt_recent=True)
    assert "adopted" not in res
    assert json.loads(_mine(vault).read_text(encoding="utf-8"))["focus"] == ""


def test_refresh_never_adopts_another_ids_pruned_entry(vault, me_env, monkeypatch):
    """others() marks a dead entry ended when it first SEES it dead, maybe days after the process died."""
    old = _entry(vault, "crashed", 77, age_s=3 * 86400, focus="stale")
    _alive(monkeypatch, {})
    sessions.others(KEY)
    assert json.loads(old.read_text(encoding="utf-8"))["ended_by"] == "prune"
    assert "adopted" not in sessions.register(KEY, "/x", "u", adopt_recent=True) and old.exists()


def test_session_end_marks_exit(vault, me_env):
    p = _entry(vault, "aaaa1111-bbbb", 4242)
    sessions.deregister()
    assert json.loads(p.read_text(encoding="utf-8"))["ended_by"] == "exit"


def test_registered_session_never_adopts(vault, me_env):
    sessions.register(KEY, "/x", "u")
    sessions.set_focus(KEY, "mine")
    old = _ended(vault, "old-id", 77, 30, focus="theirs")
    assert "adopted" not in sessions.register(KEY, "/x", "u", adopt_recent=True)
    assert json.loads(_mine(vault).read_text(encoding="utf-8"))["focus"] == "mine" and old.exists()


@pytest.mark.parametrize("ended_ago", [None, 30])
def test_register_adopts_own_session_id_after_code_tab_respawn(vault, me_env, monkeypatch, ended_ago):
    """Same id, new pid, old pid gone: unambiguous, so /preflight adopts it too."""
    kw = {"ended": int(time.time() - ended_ago)} if ended_ago else {}
    old = _entry(vault, "aaaa1111-bbbb", 63740, focus="trading", started="2026-10-26T18:53Z", **kw)
    _alive(monkeypatch, {})
    res = sessions.register(KEY, "/x", "u")
    assert res["adopted"] == "aaaa1111-bbbb" and not old.exists()
    data = json.loads(_mine(vault).read_text(encoding="utf-8"))
    assert (data["focus"], data["started"]) == ("trading", "2026-10-26T18:53Z")


def test_register_never_adopts_a_live_fork_with_the_same_id(vault, me_env, monkeypatch):
    fork = _entry(vault, "aaaa1111-bbbb", 901, focus="fork lane")
    _alive(monkeypatch, {901: CLAUDE})
    assert "adopted" not in sessions.register(KEY, "/x", "u", adopt_recent=True)
    assert fork.exists() and json.loads(_mine(vault).read_text(encoding="utf-8"))["focus"] == ""


def test_own_pid_ended_entry_is_not_read_as_own_state(vault, me_env):
    """An ended entry under this pid is a finished process whose pid the OS reused, never this process."""
    _ended(vault, "gone", 4242, 30, focus="old")
    assert sessions.seen(KEY) is None
    sessions.register(KEY, "/x", "u")
    assert json.loads(_mine(vault).read_text(encoding="utf-8"))["focus"] == ""


@pytest.mark.parametrize("by", ["prune", "exit"])
def test_own_id_and_pid_ended_entry_is_revived_not_deleted(vault, me_env, by):
    """Review of #11: same id AND pid (others() pruned a long-lived entry; or a non-clear SessionEnd on a process that
    lives on). It is never read as live state, and register() must not delete the entry it just rewrote."""
    p = _ended(vault, "aaaa1111-bbbb", 4242, 30, by=by, focus="lane")
    assert p == _mine(vault)
    assert sessions.own(KEY) is None and sessions.seen(KEY) is None
    assert sessions.set_focus(KEY, "new")["ok"] is False
    res = sessions.register(KEY, "/x", "u")
    assert res["registered"] is True and p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["focus"] == "lane" and "ended" not in data and "ended_by" not in data
    assert sessions.own(KEY)["focus"] == "lane"


def test_concurrent_refresh_claims_an_ended_entry_once(vault, me_env, monkeypatch):
    """Two cleared sessions running refresh at once: only the one whose claim (unlink) succeeds adopts."""
    old = _ended(vault, "old-id", 77, 30, focus="lane")
    real = sessions._adoptable

    def raced(*a):
        found = real(*a)
        old.unlink()  # the other session claimed it between the scan and the claim
        return found
    monkeypatch.setattr(sessions, "_adoptable", raced)
    res = sessions.register(KEY, "/x", "u", adopt_recent=True)
    assert res["registered"] is True and "adopted" not in res
    assert json.loads(_mine(vault).read_text(encoding="utf-8"))["focus"] == ""


def test_session_refresh_cli_adopts_after_code_tab_clear(vault, me_env, monkeypatch, capsys, tmp_path):
    import close as cl
    monkeypatch.setattr(cl.lib, "resolve_identity", lambda cwd, project: {"key": KEY, "root": str(tmp_path)})
    _ended(vault, "old-id", 77, 30, focus="lane")
    cl.main(["session", "refresh"])
    assert json.loads(capsys.readouterr().out)["adopted"] == "old-id"
    assert json.loads(_mine(vault).read_text(encoding="utf-8"))["focus"] == "lane"
