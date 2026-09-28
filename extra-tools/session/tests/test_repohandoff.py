import datetime as dt
import subprocess

import open as op
import repohandoff as rh
from conftest import SAMPLE_HANDOFF, sh

SELF = {"names": ["alice"], "emails": ["alice@example.com"], "hosts": {}}
FENCE = "`" * 3
PRIVATE = f"""---
key: acme-proj
updated: 2026-09-28T10:00Z
---
# Handoff: acme-proj

## Next up
1. Ship it

## Warnings
none

## Current state
- live on main

## Open items
- flaky test

## Profile
{FENCE}json
{{"services": [{{"unit": "acme", "host": "box1"}}]}}
{FENCE}

## Standing notes
- private rule

## Last session
- **2026-09-28** — private diary
"""


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def test_render_keeps_only_public_sections():
    out = rh.render(PRIVATE, "alice", now=dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.UTC))
    assert "updated_by: alice" in out and "## Next up\n1. Ship it" in out and "## Open items\n- flaky test" in out
    for secret in ("Standing notes", "Profile", "Last session", "box1", "private"):
        assert secret not in out


def test_write_refuses_a_leak(tmp_path):
    res = rh.write(tmp_path, PRIVATE.replace("live on main", "ssh bob@corp.example"), "alice", ["bob@corp.example"])
    assert res["written"] is False and res["refused"]
    assert all(h.endswith("bob@corp.example") for h in res["refused"])
    assert not (tmp_path / ".claude/HANDOFF.md").exists()


def test_write_ok(tmp_path):
    res = rh.write(tmp_path, PRIVATE, "alice", ["bob@corp.example"])
    assert res["written"] is True and (tmp_path / ".claude/HANDOFF.md").is_file()


def _origin_with_handoff(tmp_path, repo, author, email):
    bare = tmp_path / "origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh("git", "remote", "set-url", "origin", str(bare), cwd=repo)
    sh("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    other = tmp_path / "other"
    sh("git", "clone", "-q", str(bare), str(other))
    (other / ".claude").mkdir(exist_ok=True)
    (other / ".claude/HANDOFF.md").write_text(rh.render(PRIVATE, author), encoding="utf-8")
    sh("git", "add", ".claude/HANDOFF.md", cwd=other)
    sh("git", "-c", f"user.name={author}", "-c", f"user.email={email}", "commit", "-qm", "handoff", cwd=other)
    sh("git", "push", "-q", "origin", "main", cwd=other)
    sh("git", "fetch", "-q", "origin", cwd=repo)


def test_read_origin_changed_by_other(tmp_path, repo):
    _origin_with_handoff(tmp_path, repo, "bob", "bob@example.com")
    r = rh.read_origin(repo, SELF, None)
    assert r["exists"] and r["changed_by_other"] is True and r["updated_by"] == "bob"
    assert r["next_up"] == "1. Ship it"


def test_read_origin_by_self_is_not_news(tmp_path, repo):
    _origin_with_handoff(tmp_path, repo, "alice", "alice@example.com")
    assert rh.read_origin(repo, SELF, None)["changed_by_other"] is False


def test_read_origin_already_seen_is_not_news(tmp_path, repo):
    _origin_with_handoff(tmp_path, repo, "bob", "bob@example.com")
    sh("git", "merge", "-q", "--ff-only", "origin/main", cwd=repo)
    assert rh.read_origin(repo, SELF, _head(repo))["changed_by_other"] is False


def test_read_origin_absent(repo):
    assert rh.read_origin(repo, SELF, None) == {"exists": False}


def test_collect_shared_with_unreachable_origin(vault, repo, fake):
    (vault / "handoffs").mkdir(exist_ok=True)
    (vault / "handoffs/alice-demo-proj.md").write_text(
        SAMPLE_HANDOFF.replace('"gh": "alice/demo-proj"', '"gh": "alice/demo-proj", "shared": true'),
        encoding="utf-8")
    fake.on(["git", "fetch"], 1, "", "could not read from remote")
    assert op.collect(repo)["repo_handoff"] == {"exists": None, "reason": "origin unreachable; repo handoff not read"}
