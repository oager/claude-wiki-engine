# ~/.claude/tools/session/tests/test_identity.py
from pathlib import Path

import lib
import pytest
from conftest import _init, commit, sh


@pytest.mark.parametrize("url", [
    "git@github.com:alice/demo-hub.git",
    "https://github.com/alice/demo-hub.git",
    "https://github.com/alice/demo-hub",
    "https://github.com/alice/demo-hub/",
    "ssh://git@github.com/alice/demo-hub.git",
])
def test_parse_remote_forms(url):
    assert lib.parse_remote(url) == "alice/demo-hub"


def test_parse_remote_garbage():
    assert lib.parse_remote("") is None
    assert lib.parse_remote("not a url") is None


@pytest.mark.parametrize("path,expected", [
    ("/home/alice/.tool/workspace-sample", "-home-alice--tool-workspace-sample"),
    ("/home/alice/Desktop/gamma_bot", "-home-alice-Desktop-gamma-bot"),
    ("/home/alice/Sample Trading Bot", "-home-alice-Sample-Trading-Bot"),
    ("C:\\Users\\alice\\sample-projects", "C--Users-alice-sample-projects"),
])
def test_slug_matches_claude_code(path, expected):
    assert lib.slug(path) == expected


def test_identity_from_repo_subdir(repo):
    sub = repo / "templates" / "scaffold"
    sub.mkdir(parents=True)
    ident = lib.resolve_identity(sub)
    assert ident["key"] == "alice-demo-proj"
    assert ident["repo"] == "alice/demo-proj"
    assert Path(ident["root"]).resolve() == repo.resolve()
    assert ident["how"] == "git"


def test_identity_parent_with_one_repo(repo):
    ident = lib.resolve_identity(repo.parent)
    assert (ident["key"], ident["how"]) == ("alice-demo-proj", "git-child")


def _mkrepo(path, remote):
    _init(path)
    sh("git", "remote", "add", "origin", remote, cwd=path)
    commit(path, "init")


def test_identity_ambiguous_then_chosen(tmp_path):
    hub = tmp_path / "hub"
    _mkrepo(hub / "a", "git@github.com:alice/aaa.git")
    _mkrepo(hub / "b", "git@github.com:alice/bbb.git")
    ident = lib.resolve_identity(hub)
    assert ident["how"] == "ambiguous"
    assert [c["key"] for c in ident["candidates"]] == ["alice-aaa", "alice-bbb"]
    chosen = lib.resolve_identity(hub, project="alice-bbb")
    assert (chosen["key"], chosen["how"]) == ("alice-bbb", "chosen")
    assert chosen["root"].endswith("b")


def test_identity_plain_folder(tmp_path):
    d = tmp_path / "My Notes"
    d.mkdir()
    ident = lib.resolve_identity(d)
    assert (ident["key"], ident["how"], ident["repo"]) == ("local-my-notes", "folder", None)


def test_repo_without_origin_keys_by_folder(tmp_path):
    r = tmp_path / "NoRemote"
    _init(r)
    commit(r, "init")
    assert lib.resolve_identity(r)["key"] == "local-noremote"


def test_is_self():
    ids = {"names": ["alice"], "emails": ["alice@example.com"]}
    assert lib.is_self("alice", "x@y", ids)
    assert lib.is_self("Someone", "ALICE@example.com", ids)
    assert not lib.is_self("Richard", "r@example.com", ids)


def test_host_target(monkeypatch):
    ids = {"hosts": {"hosta": {"aliases": ["hosta"], "ssh": "ubuntu"}}}
    monkeypatch.setattr(lib.socket, "gethostname", lambda: "hosta")
    assert lib.host_target("hosta", ids) is None
    assert lib.host_target(None, ids) is None
    monkeypatch.setattr(lib.socket, "gethostname", lambda: "HOST-B")
    assert lib.host_target("hosta", ids) == "ubuntu"
    assert lib.host_target("otherbox", ids) == "otherbox"


def test_run_never_raises():
    assert lib._run(["definitely-not-a-binary-xyz"])[0] == 127
    assert lib._run(["sleep", "2"], timeout=0.5)[0] == 124


# Task 16 (2026-09-28): a hub of several repos that has its own handoff resolves to it instead of "ambiguous".
def test_identity_hub_with_own_handoff(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    _mkrepo(hub / "a", "git@github.com:alice/aaa.git")
    _mkrepo(hub / "b", "git@github.com:alice/bbb.git")
    vault = tmp_path / "vault"
    (vault / "handoffs").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_VAULT", str(vault))
    assert lib.resolve_identity(hub)["how"] == "ambiguous"          # no handoff yet: still ask
    (vault / "handoffs/local-hub.md").write_text("# Handoff: local-hub\n", encoding="utf-8")
    ident = lib.resolve_identity(hub)
    assert (ident["key"], ident["how"], ident["repo"]) == ("local-hub", "folder-handoff", None)
    assert lib.resolve_identity(hub, project="alice-aaa")["key"] == "alice-aaa"  # an explicit choice still wins
