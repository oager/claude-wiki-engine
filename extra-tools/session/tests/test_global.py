# ~/.claude/tools/session/tests/test_global.py
import json
import os
import shutil
import subprocess

import open as op
import pytest
from conftest import sh


def _commit_file(repo, rel, text, msg):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    sh("git", "add", "-f", rel, cwd=repo)
    sh("git", "commit", "-qm", msg, cwd=repo)


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


def test_vault_changes_since_sha(vault):
    sha = _head(vault)
    _commit_file(vault, "skills/preflight/SKILL.md", "x", "preflight: new flow")
    _commit_file(vault, "memory/concepts/new-lesson.md", "y", "wiki: new lesson")
    _commit_file(vault, "handoffs/alice-demo-proj.md", "z", "sync: demo")
    ch = op.vault_changes({"vault_sha": sha})
    assert ch["basis"] == sha
    assert ch["skills_changed"] == ["preflight"]
    assert ch["knowledge_changed"] == [{"path": "memory/concepts/new-lesson.md", "subject": "wiki: new lesson"}]


def test_vault_changes_unknown_sha_falls_back(vault):
    ch = op.vault_changes({"vault_sha": "deadbee", "updated": "2020-01-01T00:00Z"})
    assert ch["basis"] == "since 2020-01-01T00:00Z"
    assert isinstance(ch["skills_changed"], list)


def test_vault_state_stuck_merge_skips_pull(vault, fake):
    (vault / ".git" / "MERGE_HEAD").write_text("0" * 40, encoding="utf-8")
    assert op.vault_state() == {"pull": "skipped", "stuck_merge": True}


def test_vault_state_pull_failure_is_reported(vault, tmp_path):
    bare = tmp_path / "gone.git"  # an upstream that disappears: the pull fails
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh("git", "remote", "add", "origin", str(bare), cwd=vault)
    sh("git", "push", "-q", "-u", "origin", "main", cwd=vault)
    shutil.rmtree(bare)
    res = op.vault_state()
    assert res["stuck_merge"] is False and res["pull"].startswith("failed")


def test_clock(fake):
    c = op.clock()
    assert c["ntp_synced"] is True and c["utc"].endswith("Z")


@pytest.mark.skipif(os.name == "nt", reason="needs symlinks; Windows Git Bash usually cannot create them")
def test_cc_version_relaunch(tmp_path, monkeypatch):
    vers = tmp_path / "versions"
    vers.mkdir()
    (vers / "2.1.283").write_text("#!/bin/sh\n", encoding="utf-8")
    (vers / "2.1.283").chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").symlink_to(vers / "2.1.283")
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(vers / "2.1.282"))
    assert op.cc_version() == {"running": "2.1.282", "installed": "2.1.283", "relaunch_needed": True}


def test_cc_version_unknown(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert op.cc_version() == {"running": None, "installed": None, "relaunch_needed": False}


def test_plugin_updates(vault):
    p = vault / "plugins"
    (p / "marketplaces/mk/.claude-plugin").mkdir(parents=True)
    (p / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        "a@mk": [{"version": "1.0.0", "gitCommitSha": "aaa"}],
        "b@mk": [{"version": "2.0.0"}],
        "c@mk": [{"version": "3.0.0"}],
        "gone@other": [{"version": "1"}]}}), encoding="utf-8")
    (p / "marketplaces/mk/.claude-plugin/marketplace.json").write_text(json.dumps({"plugins": [
        {"name": "a", "source": {"source": "url", "sha": "bbb"}},
        {"name": "b", "version": "2.1.0", "source": "./b"},
        {"name": "c", "version": "3.0.0", "source": "./c"}]}), encoding="utf-8")
    assert op.plugin_updates() == {"updates": ["a@mk", "b@mk"], "checked": 3}


def test_plugin_updates_missing_file(vault):
    assert "error" in op.plugin_updates()


# Task 16 (2026-09-28): the Windows desktop app keeps the version in the parent folder (…\2.1.281\claude.exe).
def test_cc_version_windows_layout(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(tmp_path / "claude-code" / "2.1.281" / "claude.exe"))
    assert op.cc_version()["running"] == "2.1.281"


# Task 16: an npm shim on PATH has no version in its path; ask it.
@pytest.mark.skipif(os.name == "nt", reason="the fake shim is a sh script")
def test_cc_version_installed_from_shim(monkeypatch, tmp_path):
    shim = tmp_path / "claude"
    shim.write_text('#!/bin/sh\necho "2.1.283 (Claude Code)"\n', encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(tmp_path / "claude-code" / "2.1.281" / "claude.exe"))
    assert op.cc_version() == {"running": "2.1.281", "installed": "2.1.283", "relaunch_needed": True}
