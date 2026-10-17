# ~/.claude/tools/session/tests/test_push_case.py
# push on a case-insensitive checkout (Windows, macOS): Path.resolve() returns the ON-DISK case
# (projects/C--Users-x-Claude-Workspaces/...) while git can track another spelling
# (projects/C--Users-x-claude-workspaces/...). Git pathspecs are case-sensitive, so add/diff matched
# nothing and push returned "nothing" for a file that had changed (Windows, 2026-10-17).
import os
import subprocess

import close as cl
import lib
import pytest
from conftest import sh

GIT_DIR = "projects/C--Users-x-claude-workspaces/memory"
DISK_DIR = "projects/C--Users-x-Claude-Workspaces/memory"


@pytest.fixture
def pushable(vault, tmp_path):
    bare = tmp_path / "vault-origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh("git", "remote", "add", "origin", str(bare), cwd=vault)
    sh("git", "push", "-q", "-u", "origin", "main", cwd=vault)
    return bare


def case_insensitive(d):
    probe = d / "CaseProbe"
    probe.write_text("x", encoding="utf-8")
    try:
        return (d / "caseprobe").exists()
    finally:
        probe.unlink()


def names(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8").stdout.split()


def test_git_spelling_maps_each_path_to_the_tracked_case():
    tracked = [f"{GIT_DIR}/note.md", "handoffs/k.md", ""]
    asked = [f"{DISK_DIR}/note.md", f"{DISK_DIR}/new.md", "Handoffs/k.md", "brand/new.md"]
    assert cl._git_spelling(asked, tracked) == [
        f"{GIT_DIR}/note.md",
        f"{GIT_DIR}/new.md",  # a new file joins the tracked folder, never a second-cased twin of it
        "handoffs/k.md",
        "brand/new.md",  # nothing tracked under it: left as given
    ]


def test_push_fails_loudly_when_a_changed_file_stages_nothing(vault, pushable, monkeypatch):
    # Any other way `add` ends up staging nothing must not read as "nothing to commit" either.
    real = lib.RUN

    def add_stages_nothing(cmd, cwd=None, timeout=8):
        if cmd[:2] == ["git", "--literal-pathspecs"] and cmd[4] == "add":
            return 0, "", ""
        return real(cmd, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(lib, "RUN", add_stages_nothing)
    (vault / "f0.txt").write_text("changed", encoding="utf-8")
    r = cl.push([str(vault / "f0.txt")], "sync: x")
    assert r["status"] == "stage_failed", r
    assert "nothing was staged" in r["detail"] and "f0.txt" in r["detail"]


def test_push_commits_under_gits_spelling_on_a_case_insensitive_disk(vault, pushable):
    if not case_insensitive(vault):
        pytest.skip("needs a case-insensitive filesystem (Windows, macOS)")
    (vault / GIT_DIR).mkdir(parents=True)
    (vault / GIT_DIR / "note.md").write_text("v1", encoding="utf-8")
    sh("git", "add", "-f", "--", f"{GIT_DIR}/note.md", cwd=vault)
    sh("git", "commit", "-qm", "track note", cwd=vault)
    sh("git", "push", "-q", cwd=vault)
    # The folder's on-disk case changes (two renames: a case-only rename is a no-op on some systems).
    proj = vault / "projects"
    os.rename(proj / "C--Users-x-claude-workspaces", proj / "tmp-rename")
    os.rename(proj / "tmp-rename", proj / "C--Users-x-Claude-Workspaces")

    (vault / DISK_DIR / "note.md").write_text("v2", encoding="utf-8")
    r = cl.push([str(vault / DISK_DIR / "note.md")], "sync: note")
    assert r["status"] == "ok", r
    assert names(pushable, "log", "-1", "--name-only", "--format=") == [f"{GIT_DIR}/note.md"]

    (vault / DISK_DIR / "new.md").write_text("new", encoding="utf-8")
    r = cl.push([str(vault / DISK_DIR / "new.md")], "sync: new")
    assert r["status"] == "ok", r
    assert names(pushable, "log", "-1", "--name-only", "--format=") == [f"{GIT_DIR}/new.md"]
    assert not [n for n in names(pushable, "ls-tree", "-r", "--name-only", "main") if "Claude-Workspaces" in n]
