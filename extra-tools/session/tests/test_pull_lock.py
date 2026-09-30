# ~/.claude/tools/session/tests/test_pull_lock.py
"""/preflight's vault pull takes the same .sync.lock as /sync's push, so it never pulls into a push mid-rebase
(and never reads a push's in-progress rebase as a stuck merge)."""
import os
import time

import close as cl
import lib
import open as op
from test_push import pushable  # noqa: F401  (fixture)


def _held_by_other(vault):
    lock = vault / ".sync.lock"
    lock.mkdir()
    (lock / cl.OWNER).write_text("4242 other", encoding="utf-8")
    return lock


def test_pull_holds_the_lock_and_releases_it(vault, pushable, monkeypatch):  # noqa: F811
    seen = []
    real = lib.RUN

    def spy(cmd, *a, **k):
        if "pull" in cmd:
            seen.append((vault / ".sync.lock" / cl.OWNER).exists())
        return real(cmd, *a, **k)

    monkeypatch.setattr(lib, "RUN", spy)
    assert op.vault_state() == {"pull": "ok", "stuck_merge": False}
    assert seen == [True] and not (vault / ".sync.lock").exists()


def test_pull_waits_out_a_short_push(vault, pushable, monkeypatch):  # noqa: F811
    lock = _held_by_other(vault)
    naps = []

    def nap(s):  # the push finishes while /preflight waits
        naps.append(s)
        (lock / cl.OWNER).unlink()
        lock.rmdir()

    monkeypatch.setattr(cl.time, "sleep", nap)
    assert op.vault_state() == {"pull": "ok", "stuck_merge": False}
    assert naps and not lock.exists()


def test_pull_skipped_while_a_push_holds_the_lock(vault, pushable, monkeypatch):  # noqa: F811
    lock = _held_by_other(vault)
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    calls = []
    real = lib.RUN
    monkeypatch.setattr(lib, "RUN", lambda cmd, *a, **k: calls.append(cmd) or real(cmd, *a, **k))
    res = op.vault_state()
    assert res["stuck_merge"] is False and res["pull"].startswith("skipped (a /sync push is in progress")
    assert not any("pull" in c for c in calls)
    assert (lock / cl.OWNER).read_text(encoding="utf-8") == "4242 other"  # someone else's lock: untouched


def test_push_mid_rebase_is_not_reported_as_a_stuck_merge(vault, pushable, monkeypatch):  # noqa: F811
    _held_by_other(vault)
    (vault / ".git" / "rebase-merge").mkdir()  # a /sync push is between pull --rebase and push
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    res = op.vault_state()
    assert res["stuck_merge"] is False and res["pull"].startswith("skipped (a /sync push is in progress")


def test_stale_lock_is_broken_and_pull_proceeds(vault, pushable, monkeypatch):  # noqa: F811
    lock = vault / ".sync.lock"
    lock.mkdir()
    old = time.time() - 3600
    os.utime(lock, (old, old))
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    assert op.vault_state() == {"pull": "ok", "stuck_merge": False}
    assert not lock.exists()


def test_unwritable_lock_never_crashes_the_collector(vault, pushable, monkeypatch):  # noqa: F811
    def boom(self, *a, **k):
        raise PermissionError("read-only vault")

    monkeypatch.setattr(cl.Path, "mkdir", boom)
    res = op.vault_state()
    assert res["stuck_merge"] is False and res["pull"].startswith("skipped (")
