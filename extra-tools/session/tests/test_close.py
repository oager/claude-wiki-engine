# ~/.claude/tools/session/tests/test_close.py
import json
import subprocess
from pathlib import Path

import close as cl
import pytest
from conftest import commit, sh

LINUX_PROC = Path("/proc/self/cgroup").exists()


def test_git_close(repo, tmp_path, fake):
    bare = tmp_path / "origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh("git", "remote", "set-url", "origin", str(bare), cwd=repo)
    sh("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    sh("git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main", cwd=repo)
    sh("git", "checkout", "-q", "-b", "feat/merged", cwd=repo)
    commit(repo, "merged work")
    sh("git", "checkout", "-q", "-b", "feat/nopr", "main", cwd=repo)
    commit(repo, "orphan work")
    sh("git", "checkout", "-q", "main", cwd=repo)
    commit(repo, "unpushed")
    (repo / "d.txt").write_text("x", encoding="utf-8")
    fake.on(["gh", "pr"], 0, json.dumps([
        {"headRefName": "feat/merged", "number": 3, "state": "MERGED", "statusCheckRollup": []},
        {"headRefName": "feat/open", "number": 9, "state": "OPEN",
         "statusCheckRollup": [{"status": "IN_PROGRESS", "conclusion": ""}]}]))
    g = cl.git_close(repo, "alice/demo-proj")
    assert g["dirty_count"] == 1 and g["unpushed"] == 1
    assert g["no_pr_branches"] == ["feat/nopr"]
    assert g["ci_pending"] == [9]


def test_git_close_without_gh_lists_all_unmerged(repo, fake):
    sh("git", "checkout", "-q", "-b", "feat/x", cwd=repo)
    commit(repo, "x")
    sh("git", "checkout", "-q", "main", cwd=repo)
    g = cl.git_close(repo, "alice/demo-proj")
    assert g["no_pr_branches"] == ["feat/x"] and "error" in g


@pytest.mark.skipif(not LINUX_PROC, reason="Linux /proc only")
def test_running_work_same_cgroup_is_reported(repo):
    p = subprocess.Popen(["sleep", "30"], cwd=repo)
    try:
        procs = cl.running_work(repo)["procs"]
        assert any(x["pid"] == p.pid and x["cmd"].startswith("sleep") for x in procs)
    finally:
        p.kill()
        p.wait()


def test_running_work_unsupported(tmp_path):
    assert cl.running_work(tmp_path, proc=tmp_path / "noproc") == {"supported": False, "procs": []}


def test_deploy_drift(repo, fake):
    last = int(subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%ct"],
                              capture_output=True, text=True, encoding="utf-8").stdout)
    fake.on(["systemctl", "--user", "show", "old-svc"], 0, f"ActiveEnterTimestamp=@{last - 100}\n")
    fake.on(["systemctl", "--user", "show", "new-svc"], 0, f"ActiveEnterTimestamp=@{last + 100}\n")
    prof = {"services": [{"unit": "old-svc", "deploys_from_repo": True},
                         {"unit": "new-svc", "deploys_from_repo": True},
                         {"unit": "plain"}]}
    d = cl.deploy_drift(repo, prof, {})
    assert [(x["unit"], x["drift"]) for x in d] == [("old-svc", True), ("new-svc", False)]


def test_collect_close_shape(repo, vault, fake):
    res = cl.collect_close(repo)
    assert res["identity"]["key"] == "alice-demo-proj"
    assert res["handoff"]["exists"] is False
    assert res["repo_sha"] and res["vault_sha"]
    assert "procs" in res["running"]
