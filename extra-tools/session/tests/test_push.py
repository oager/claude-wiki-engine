# ~/.claude/tools/session/tests/test_push.py
import json
import os
import subprocess

import close as cl
import pytest
from conftest import sh


@pytest.fixture
def pushable(vault, tmp_path):
    bare = tmp_path / "vault-origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh("git", "remote", "add", "origin", str(bare), cwd=vault)
    sh("git", "push", "-q", "-u", "origin", "main", cwd=vault)
    return bare


def test_push_only_listed_files(vault, pushable):
    (vault / "handoffs").mkdir()
    h = vault / "handoffs/k.md"
    h.write_text("hand", encoding="utf-8")
    (vault / "other.md").write_text("another session's half-write", encoding="utf-8")
    r = cl.push([str(h)], "sync: k")
    assert r["status"] == "ok" and r["missing"] == []
    pushed = subprocess.run(["git", "-C", str(pushable), "log", "-1", "--name-only", "--format="],
                            capture_output=True, text=True, encoding="utf-8").stdout.split()
    assert pushed == ["handoffs/k.md"]
    assert not (vault / ".sync.lock").exists()
    status = subprocess.run(["git", "-C", str(vault), "status", "--porcelain"],
                            capture_output=True, text=True, encoding="utf-8").stdout
    assert "?? other.md" in status


def test_push_nothing(vault, pushable):
    assert cl.push([str(vault / "f0.txt")], "noop")["status"] == "nothing"


def test_push_lock_busy_then_stale(vault, pushable, monkeypatch):
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    lock = vault / ".sync.lock"
    lock.mkdir()
    assert cl.push([str(vault / "f0.txt")], "x", retries=2)["status"] == "locked"
    assert lock.exists()  # a live lock is never stolen
    os.utime(lock, (1, 1))  # now stale (> 5 min)
    assert cl.push([str(vault / "f0.txt")], "x", retries=2)["status"] == "nothing"
    assert not lock.exists()


def test_main_trim_and_never_crash(tmp_path, capsys):
    p = tmp_path / "k.md"
    p.write_text("## Next up\n1. x\n", encoding="utf-8")
    assert cl.main(["trim", str(p)]) == 0
    assert json.loads(capsys.readouterr().out)["moved"] == 0
    assert cl.main(["trim", str(tmp_path / "missing.md")]) == 0
    assert "FileNotFoundError" in json.loads(capsys.readouterr().out)["fatal"]
