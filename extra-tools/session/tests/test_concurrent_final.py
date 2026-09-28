# Regression tests for the concurrent-sessions final review fix wave (2026-09-28, items F1-F5).
import json
import subprocess
from pathlib import Path

import close as cl
import inbox
import open as op
import sessions
from test_push import pushable  # noqa: F401  (fixture)

KEY = "alice-demo-proj"  # the fixture repo's handoff key (tests/conftest.py)
CLAUDE = (True, "2.1.283")


def _as(monkeypatch, sid, pid=4242):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
    monkeypatch.setenv("CLAUDE_PID", str(pid))


def _live(vault):
    return vault / "handoffs/.live" / KEY


def _git(vault, *args):
    return subprocess.run(["git", "-C", str(vault), *args], capture_output=True, text=True,
                          encoding="utf-8").stdout


# F1: /clear gives the same process a new session id; identity is (host, pid).
def test_session_id_change_keeps_identity(vault, monkeypatch):
    monkeypatch.setattr(sessions, "alive_name", lambda pid: CLAUDE)
    _as(monkeypatch, "aaaa1111-a")
    sessions.register(KEY, "/x", "2026-09-28T08:00Z")
    sessions.set_focus(KEY, "the installer")
    started = json.loads((_live(vault) / "aaaa1111-a-4242.json").read_text(encoding="utf-8"))["started"]
    _as(monkeypatch, "bbbb2222-b")  # after /clear: new id, same pid
    assert sessions.seen(KEY) == "2026-09-28T08:00Z"
    assert sessions.others(KEY) == []
    sessions.register(KEY, "/x", "2026-09-28T09:00Z")
    own = sorted(p.name for p in _live(vault).glob("*-4242.json"))
    assert own == ["bbbb2222-b-4242.json"]
    data = json.loads((_live(vault) / own[0]).read_text(encoding="utf-8"))
    assert (data["session_id"], data["focus"], data["started"]) == ("bbbb2222-b", "the installer", started)
    assert sessions.seen(KEY) == "2026-09-28T09:00Z"


def test_set_focus_after_id_change_updates_own_entry(vault, monkeypatch):
    _as(monkeypatch, "aaaa1111-a")
    sessions.register(KEY, "/x", "u1")
    _as(monkeypatch, "bbbb2222-b")
    assert sessions.set_focus(KEY, "docs")["ok"] is True
    assert json.loads((_live(vault) / "aaaa1111-a-4242.json").read_text(encoding="utf-8"))["focus"] == "docs"


def test_same_pid_on_another_host_is_not_mine(vault, monkeypatch):
    monkeypatch.setattr(sessions, "alive_name", lambda pid: CLAUDE)
    d = _live(vault)
    d.mkdir(parents=True)
    theirs = d / "xxxx9999-4242.json"
    theirs.write_text(json.dumps({"session_id": "xxxx9999", "pid": 4242, "host": "another-box",
                                  "updated_seen": "theirs", "focus": "far away"}), encoding="utf-8")
    _as(monkeypatch, "bbbb2222-b")
    assert sessions.seen(KEY) is None
    sessions.register(KEY, "/x", "mine")
    assert theirs.exists()
    data = json.loads((d / "bbbb2222-b-4242.json").read_text(encoding="utf-8"))
    assert (data["focus"], data["updated_seen"]) == ("", "mine")
    assert sessions.seen(KEY) == "mine"


def test_other_pid_same_host_still_listed(vault, monkeypatch):
    monkeypatch.setattr(sessions, "alive_name", lambda pid: CLAUDE)
    _as(monkeypatch, "aaaa1111-a", pid=900)
    sessions.register(KEY, "/x", "u")
    _as(monkeypatch, "aaaa1111-a", pid=4242)  # a fork: same id, other pid
    assert [o["pid"] for o in sessions.others(KEY)] == [900]


# F2: a directory path must not commit the per-machine registry.
def _registry(vault):
    d = _live(vault)
    d.mkdir(parents=True, exist_ok=True)
    (d.parent / ".gitignore").write_text("*\n", encoding="utf-8")
    (d / "aaaa1111-4242.json").write_text("{}", encoding="utf-8")


def test_push_registry_dir_is_never_staged(vault, pushable):  # noqa: F811
    _registry(vault)
    res = cl.push([str(vault / "handoffs/.live")], "m")
    assert res["status"] == "stage_failed"
    assert _git(vault, "ls-files", "handoffs/.live") == ""
    assert _git(vault, "diff", "--cached", "--name-only") == ""


def test_push_ancestor_dir_commits_handoff_not_registry(vault, pushable):  # noqa: F811
    _registry(vault)
    (vault / "handoffs/k.md").write_text("hand", encoding="utf-8")
    res = cl.push([str(vault / "handoffs")], "m")
    assert res["status"] == "ok"
    assert _git(vault, "ls-files", "handoffs").split() == ["handoffs/k.md"]
    assert _git(vault, "diff", "--cached", "--name-only") == ""


def test_push_ancestor_dir_with_moved_note(vault, pushable):  # noqa: F811
    note = inbox.write_note("k", "s", "one", "b")
    assert cl.push([str(note)], "note")["status"] == "ok"
    _registry(vault)
    inbox.mark_done([str(note)])
    res = cl.push([str(note), str(vault / "handoffs")], "triage")
    assert res["status"] == "ok" and res["missing"] == []
    assert _git(vault, "ls-files", "handoffs").split() == [f"handoffs/inbox/k/done/{note.name}"]


def test_push_excluded_only_leaves_other_staged_files_alone(vault, pushable):  # noqa: F811
    _registry(vault)
    (vault / "other.md").write_text("another session's staged work", encoding="utf-8")
    subprocess.run(["git", "-C", str(vault), "add", "other.md"], check=True)
    head = _git(vault, "rev-parse", "HEAD")
    assert cl.push([str(vault / "handoffs/.live/aaaa1111-4242.json")], "m")["status"] == "stage_failed"
    assert cl.push([str(vault / "handoffs/.live")], "m")["status"] == "stage_failed"
    assert _git(vault, "rev-parse", "HEAD") == head
    assert _git(vault, "diff", "--cached", "--name-only").split() == ["other.md"]


# F3 + F4: this session's own focus and registration are visible to /preflight and /sync.
def test_open_and_close_show_own_focus(vault, repo, fake, monkeypatch):
    _as(monkeypatch, "aaaa1111-a")
    assert op.collect(repo)["sessions"]["focus"] == ""
    sessions.set_focus(KEY, "the installer")
    assert op.collect(repo)["sessions"]["focus"] == "the installer"
    s = cl.collect_close(repo)["sessions"]
    assert (s["focus"], s["registered"]) == ("the installer", True)


def test_collect_close_unregistered(vault, repo, fake, monkeypatch):
    _as(monkeypatch, "aaaa1111-a")
    res = cl.collect_close(repo)
    assert (res["sessions"]["registered"], res["sessions"]["focus"], res["updated_seen"]) == (False, "", None)


def test_collect_close_without_session_env(vault, repo, fake):
    s = cl.collect_close(repo)["sessions"]
    assert (s["me"], s["registered"], s["focus"]) == (None, False, "")


# F5: a note another session moved between the exists() check and the move is skipped.
def test_mark_done_skips_note_moved_meanwhile(vault, monkeypatch):
    a = inbox.write_note("k", "s", "one", "b")
    b = inbox.write_note("k", "s", "two", "b")
    real, calls = Path.replace, []

    def flaky(self, target):
        calls.append(self)
        if len(calls) == 1:
            raise FileNotFoundError(str(self))
        return real(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    assert inbox.mark_done([str(a), str(b)]) == [str(b), str(b.parent / "done" / b.name)]
