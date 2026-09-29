# ~/.claude/tools/session/tests/test_git.py
import json
import subprocess

import lib
import open as op
from conftest import commit, sh

IDS = {"names": ["alice"], "emails": ["alice@example.com"]}


def _sha(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


def test_ci_state():
    assert lib.ci_state(None) == "none"
    assert lib.ci_state([{"conclusion": "SUCCESS"}, {"state": "SUCCESS"}]) == "pass"
    assert lib.ci_state([{"conclusion": "", "status": "IN_PROGRESS"}]) == "pending"
    assert lib.ci_state([{"conclusion": "FAILURE"}, {"status": "IN_PROGRESS"}]) == "fail"


def test_prs_and_issues(fake):
    fake.on(["gh", "pr"], 0, json.dumps([{"number": 7, "title": "feat",
                                          "statusCheckRollup": [{"conclusion": "SUCCESS"}]}]))
    fake.on(["gh", "issue"], 0, json.dumps([{"number": 4}, {"number": 5}]))
    assert op.prs_and_issues("alice/demo-proj") == {
        "prs": [{"number": 7, "title": "feat", "ci": "pass"}], "issues_open": 2}
    gh_calls = [c for c in fake.calls if c[0] == "gh"]
    assert gh_calls[0][:5] == ["gh", "pr", "list", "-R", "alice/demo-proj"]


def test_prs_gh_missing_does_not_crash(fake):
    res = op.prs_and_issues("alice/demo-proj")
    assert res["prs"] is None and res["issues_open"] is None
    assert "not found" in res["error"]


def test_prs_no_repo():
    assert op.prs_and_issues(None) == {"error": "no GitHub repo (no origin remote)"}


def test_git_local_dirty_ahead(repo, tmp_path):
    bare = tmp_path / "origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh("git", "remote", "set-url", "origin", str(bare), cwd=repo)
    sh("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    commit(repo, "local only")
    (repo / "dirty.txt").write_text("x", encoding="utf-8")
    g = op.git_local(repo)
    assert (g["branch"], g["dirty"], g["ahead"], g["behind"], g["stashes"]) == ("main", 1, 1, 0, 0)


def test_git_local_no_upstream(repo):
    g = op.git_local(repo)
    assert g["ahead"] is None and g["behind"] is None


def test_collab_others_since_sha(repo):
    since = _sha(repo)
    commit(repo, "mine")
    commit(repo, "his", name="Richard", email="richard@example.com")
    commit(repo, "his2", name="Richard", email="richard@example.com")
    c = op.collab_block(repo, {"repo_sha": since}, IDS, {})
    assert c == {"since": since, "shared": False, "others": [{"author": "Richard", "commits": 2}]}


def test_collab_unknown_sha_uses_window(repo):
    commit(repo, "his", name="Richard", email="richard@example.com")
    c = op.collab_block(repo, {"repo_sha": "deadbee"}, IDS, {"shared": True})
    assert c["since"] == "14 days" and c["shared"] is True
    assert c["others"] == [{"author": "Richard", "commits": 1}]


def test_collab_ignores_upstream_only_commits(repo):
    since = _sha(repo)
    sh("git", "checkout", "-q", "-b", "side", cwd=repo)
    commit(repo, "upstream work", name="Mads", email="mads@example.com")
    sh("git", "update-ref", "refs/remotes/upstream/main", "HEAD", cwd=repo)
    sh("git", "checkout", "-q", "main", cwd=repo)
    sh("git", "branch", "-q", "-D", "side", cwd=repo)
    assert op.collab_block(repo, {"repo_sha": since}, IDS, {})["others"] == []
