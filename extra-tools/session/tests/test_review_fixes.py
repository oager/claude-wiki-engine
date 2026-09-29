# Regression tests for the final-review findings (2026-09-27).
import os
import subprocess
from pathlib import Path

import close as cl
import lib
import open as op
import pytest
from conftest import SAMPLE_HANDOFF, sh


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def remote(vault, tmp_path):
    """The temp vault pushed to a bare remote, plus a second clone playing the other machine."""
    bare = tmp_path / "vault-origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh("git", "remote", "add", "origin", str(bare), cwd=vault)
    sh("git", "push", "-q", "-u", "origin", "main", cwd=vault)
    other = tmp_path / "other"
    sh("git", "clone", "-q", str(bare), str(other))
    sh("git", "config", "user.name", "alice", cwd=other)
    sh("git", "config", "user.email", "alice@example.com", cwd=other)
    return bare, other


def _other_commits(other, rel, text):
    p = other / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    sh("git", "add", rel, cwd=other)
    sh("git", "commit", "-qm", f"other: {rel}", cwd=other)
    sh("git", "push", "-q", cwd=other)


# Critical 1: a rebase conflict must not leave the shared vault mid-rebase.
def test_push_rebase_conflict_aborts_cleanly(vault, remote):
    _, other = remote
    _other_commits(other, "memory/log.md", "remote line\n")
    (vault / "memory").mkdir()
    (vault / "memory/log.md").write_text("local line\n", encoding="utf-8")
    r = cl.push([str(vault / "memory/log.md")], "sync: local")
    assert r["status"] == "rebase_conflict"
    assert not (vault / ".git/rebase-merge").exists() and not (vault / ".git/rebase-apply").exists()
    assert _git(vault, "log", "-1", "--format=%s") == "sync: local"  # local commit kept, on the branch
    assert not (vault / ".sync.lock").exists()


# Critical 1: an autostash pop conflict must name the exact stash, not stash@{0} by position.
def test_push_autostash_conflict_names_the_stash(vault, remote):
    _, other = remote
    _other_commits(other, "f0.txt", "remote edit\n")
    (vault / "f0.txt").write_text("another session's unstaged edit\n", encoding="utf-8")
    (vault / "handoffs").mkdir()
    (vault / "handoffs/k.md").write_text("hand", encoding="utf-8")
    r = cl.push([str(vault / "handoffs/k.md")], "sync: k")
    assert r["status"] == "autostash_conflict"
    assert r["stash"] in _git(vault, "stash", "list", "--format=%H").split()
    assert not (vault / ".git/rebase-merge").exists()


# Important 2: a bad path (never committed, and gone) must not be reported as "nothing to commit".
def test_push_stage_failure_is_reported(vault, remote):
    (vault / "handoffs").mkdir()
    r = cl.push([str(vault / "handoffs/k.archive.md")], "sync: k")
    assert r["status"] == "stage_failed"
    assert r["dropped"] == ["handoffs/k.archive.md"]
    assert not (vault / ".sync.lock").exists()


# Important 2 (follow-up): a real change alongside a never-existing path still pushes the real file,
# but the caller must be told a listed path was silently skipped (typo, not "nothing to commit").
def test_push_reports_dropped_alongside_ok(vault, remote):
    bare, _ = remote
    (vault / "handoffs").mkdir()
    (vault / "handoffs/k.md").write_text("hand", encoding="utf-8")
    r = cl.push([str(vault / "handoffs/k.md"), str(vault / "handoffs/k.archive.md")], "sync: k")
    assert r["status"] == "ok"
    assert _git(bare, "log", "-1", "--name-only", "--format=").split() == ["handoffs/k.md"]
    assert r["dropped"] == ["handoffs/k.archive.md"]


# Important 2 (follow-up): an unchanged tracked file plus a never-existing path must not read as a clean "nothing".
def test_push_reports_dropped_alongside_nothing(vault, remote):
    r = cl.push([str(vault / "f0.txt"), str(vault / "handoffs/k.archive.md")], "sync: k")
    assert r["status"] == "nothing"
    assert r["dropped"] == ["handoffs/k.archive.md"]


# Important 3: a re-run after push_failed must push the commit already made locally.
def test_push_rerun_pushes_existing_local_commit(vault, remote):
    bare, _ = remote
    (vault / "handoffs").mkdir()
    (vault / "handoffs/k.md").write_text("hand", encoding="utf-8")
    sh("git", "add", "handoffs/k.md", cwd=vault)
    sh("git", "commit", "-qm", "sync: committed but never pushed", cwd=vault)
    r = cl.push([str(vault / "handoffs/k.md")], "sync: k")
    assert r["status"] == "ok"
    assert _git(bare, "log", "-1", "--format=%s") == "sync: committed but never pushed"


# Critical 1 (open side): a vault stuck mid-rebase is reported and not pulled.
def test_vault_state_detects_rebase_in_progress(vault):
    (vault / ".git/rebase-merge").mkdir()
    assert op.vault_state() == {"pull": "skipped", "stuck_merge": True}


# Important 4: the handoff /sync pushed from the other machine is read after the pull brings it.
def test_collect_reads_handoff_after_pull(repo, vault, remote, fake):
    _, other = remote
    _other_commits(other, "handoffs/alice-demo-proj.md", SAMPLE_HANDOFF)
    res = op.collect(repo)
    assert res["global"]["pull"] == "ok"
    assert res["handoff"]["exists"] is True
    assert res["handoff"]["next_up"] == "1. Ship the thing"


# Important 5: MCP servers a Claude session spawned are not "running work"; shell-launched jobs are.
def _fake_proc(root, pid, comm, ppid, cwd):
    d = root / str(pid)
    d.mkdir()
    (d / "stat").write_text(f"{pid} ({comm}) S {ppid} 0 0 0\n", encoding="utf-8")
    (d / "comm").write_text(comm + "\n", encoding="utf-8")
    (d / "cmdline").write_bytes(comm.encode() + b"\0")
    (d / "cgroup").write_text("0::/user.slice/user-1000.slice/session-9.scope\n", encoding="utf-8")
    os.symlink(cwd, d / "cwd")


@pytest.mark.skipif(os.name == "nt", reason="needs symlinks; Windows Git Bash usually cannot create them")
def test_running_work_skips_harness_children(tmp_path, repo):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self/cgroup").write_text("0::/user.slice/user-1000.slice/session-9.scope\n", encoding="utf-8")
    _fake_proc(proc, 900100, "claude", 1, str(tmp_path))
    _fake_proc(proc, 900101, "npm exec chrome", 900100, str(repo))  # MCP server under claude
    _fake_proc(proc, 900102, "bash", 900100, str(tmp_path))         # Bash tool shell
    _fake_proc(proc, 900103, "sleep", 900102, str(repo))            # job launched through the shell
    _fake_proc(proc, 900104, "node", 1, str(repo))                  # orphaned dev server
    pids = sorted(p["pid"] for p in cl.running_work(repo, proc=proc)["procs"])
    assert pids == [900103, 900104]


# Important 6: the 100 KB guard reports even when nothing was moved.
def test_trim_flags_oversize_without_dated_entries(tmp_path):
    p = tmp_path / "k.md"
    p.write_text("## Last session\n" + ("legacy diary line\n" * 7000), encoding="utf-8")
    r = cl.trim(p)
    assert r["moved"] == 0 and r["over_100kb"] is True


# Important 8: an unreadable child folder must not crash identity resolution.
@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs POSIX permissions, non-root")
def test_identity_survives_unreadable_child(tmp_path):
    locked = tmp_path / "locked"
    (locked / "inner").mkdir(parents=True)
    locked.chmod(0)
    try:
        ident = lib.resolve_identity(tmp_path)
        assert ident["how"] == "folder"
    finally:
        locked.chmod(0o755)


# Re-graded minor: curl missing or timing out is "unknown", never a false "down".
def test_health_check_tool_failure_is_unknown(fake):
    fake.on(["curl"], 127, "", "curl: not found")
    c = op.health_check({"url": "http://localhost:8080/api/health"}, {})
    assert c["status"] == "unknown"


# 2026-09-28: the native binary is versions/<ver>, so the session process is named "2.1.283", not "claude";
# the walk skipped it, reached the "claude" launcher above, and dropped every Bash-tool job as a harness child.
@pytest.mark.skipif(os.name == "nt", reason="needs symlinks; Windows Git Bash usually cannot create them")
def test_running_work_native_binary_named_by_version(tmp_path, repo):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self/cgroup").write_text("0::/user.slice/user-1000.slice/session-9.scope\n", encoding="utf-8")
    _fake_proc(proc, 900200, "claude", 1, str(tmp_path))            # launcher
    _fake_proc(proc, 900201, "2.1.283", 900200, str(tmp_path))      # the session (native binary)
    _fake_proc(proc, 900202, "node", 900201, str(repo))             # MCP server under the session
    _fake_proc(proc, 900203, "bash", 900201, str(tmp_path))         # Bash tool shell
    _fake_proc(proc, 900204, "sleep", 900203, str(repo))            # job launched through the shell
    _fake_proc(proc, 900205, "2.1.283", 1, str(repo))               # another session open in this repo
    pids = sorted(p["pid"] for p in cl.running_work(repo, proc=proc)["procs"])
    assert pids == [900204]


# Hardening (2026-09-28): if Claude's process naming changes again, say "unchecked" instead of silently finding nothing.
@pytest.mark.skipif(not Path("/proc").is_dir(), reason="Linux /proc only")
def test_running_work_unrecognized_claude_is_unchecked(monkeypatch, repo):
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/opt/claude/cli.js")
    monkeypatch.setattr(cl, "_self_chain", lambda: ["python3", "bash", "node", "systemd"])
    res = cl.running_work(repo)
    assert res["supported"] is False and "not recognized" in res["reason"]


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="Linux /proc only")
def test_running_work_recognizes_execpath_name(monkeypatch, repo):
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/opt/claude/claude-next")
    monkeypatch.setattr(cl, "_self_chain", lambda: ["python3", "bash", "claude-next"])
    assert cl.running_work(repo)["supported"] is True
