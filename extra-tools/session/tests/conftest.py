# ~/.claude/tools/session/tests/conftest.py
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import lib  # noqa: E402

FENCE = "`" * 3
SAMPLE_HANDOFF = """---
key: alice-demo-proj
repo: alice/demo-proj
type: web-app            # trading-bot | web-app | static-site | workspace
updated: 2026-09-27T20:49Z
updated_by: hosta
repo_sha: abc1234
vault_sha: def5678
---
# Handoff — alice-demo-proj

## Next up
1. Ship the thing

## Warnings
none

## Profile
FENCEjson
{"gh": "alice/demo-proj", "services": [{"unit": "demo", "scope": "user"}]}
FENCE
Notes about the profile.

## Last session
- **2026-09-27** — did stuff
""".replace("FENCE", FENCE)


def sh(*cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def commit(repo, msg="c", email="alice@example.com", name="alice"):
    repo = Path(repo)
    n = len(list(repo.glob("f*.txt")))
    (repo / f"f{n}.txt").write_text(msg, encoding="utf-8")
    sh("git", "add", "-A", cwd=repo)
    sh("git", "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-qm", msg, cwd=repo)


def _init(path):
    path.mkdir(parents=True, exist_ok=True)
    sh("git", "init", "-q", "-b", "main", cwd=path)
    sh("git", "config", "user.name", "alice", cwd=path)
    sh("git", "config", "user.email", "alice@example.com", cwd=path)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "proj"
    _init(r)
    sh("git", "remote", "add", "origin", "git@github.com:alice/demo-proj.git", cwd=r)
    commit(r, "init")
    return r


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    _init(v)
    commit(v, "vault init")
    monkeypatch.setenv("CLAUDE_VAULT", str(v))
    return v


class FakeRun:
    """Answer chosen command prefixes; delegate everything else to the real runner.

    The newest rule wins, so a test can override the fixture's defaults.
    """

    def __init__(self):
        self.rules = []
        self.calls = []

    def on(self, prefix, rc=0, out="", err=""):
        self.rules.insert(0, (list(prefix), (rc, out, err)))
        return self

    def __call__(self, cmd, cwd=None, timeout=8):
        self.calls.append(list(cmd))
        for prefix, res in self.rules:
            if list(cmd[: len(prefix)]) == prefix:
                return res
        return lib._run(cmd, cwd=cwd, timeout=timeout)


@pytest.fixture
def fake(monkeypatch):
    f = FakeRun()
    f.on(["gh"], 127, "", "gh: not found")
    f.on(["ssh"], 255, "", "no ssh in tests")
    f.on(["timedatectl"], 0, "yes\n")
    f.on(["systemctl"], 1, "", "")
    f.on(["curl"], 7, "", "")
    f.on(["ss"], 1, "", "")
    f.on(["git", "fetch"], 0)
    monkeypatch.setattr(lib, "RUN", f)
    monkeypatch.setattr(lib, "has_systemctl", lambda: True)  # unit-guessing tests must not depend on the host OS
    return f


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    """Tests run inside Claude sessions; never let them register the real session anywhere."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_PID", raising=False)
