# ~/.claude/tools/session/tests/test_collect.py
import json
import os

import open as op
from conftest import SAMPLE_HANDOFF, _init, commit, sh


def test_collect_end_to_end(repo, vault, fake):
    (vault / "handoffs").mkdir()
    (vault / "handoffs/alice-demo-proj.md").write_text(SAMPLE_HANDOFF, encoding="utf-8")
    res = op.collect(repo)
    expected = {"identity", "handoff", "inbox", "global", "git", "collab", "type", "checks"}
    if os.path.isdir("/proc"):  # Linux: concurrent sessions field is included
        expected.add("concurrent")
    assert set(res) == expected
    assert res["handoff"]["exists"] is True
    assert res["handoff"]["next_up"] == "1. Ship the thing"
    assert res["handoff"]["warnings"] == "none"
    assert res["type"] == {"type": "web-app", "signals": ["handoff frontmatter"]}
    assert res["git"]["prs"] is None  # gh is faked as missing
    assert [c["target"] for c in res["checks"]] == ["demo"]
    json.dumps(res)


def test_collect_no_handoff_reports_legacy(repo, vault, fake):
    (repo / ".claude/memory").mkdir(parents=True)
    (repo / ".claude/memory/SESSION_RESUME.md").write_text("old", encoding="utf-8")
    res = op.collect(repo)
    assert res["handoff"]["exists"] is False
    assert res["handoff"]["legacy"]["path"].endswith("SESSION_RESUME.md")


def test_collect_ambiguous_stops_early(tmp_path, vault):
    hub = tmp_path / "hub"
    for name in ("a", "b"):
        _init(hub / name)
        sh("git", "remote", "add", "origin", f"git@github.com:alice/{name}.git", cwd=hub / name)
        commit(hub / name, "init")
    assert set(op.collect(hub)) == {"identity"}


def test_collect_plain_folder_has_no_git_block(tmp_path, vault, fake):
    d = tmp_path / "notes"
    d.mkdir()
    res = op.collect(d)
    assert "git" not in res and res["type"]["type"] == "workspace"


def test_main_never_crashes(monkeypatch, capsys):
    def boom(*a, **k):
        raise ZeroDivisionError("x")
    monkeypatch.setattr(op, "collect", boom)
    assert op.main(["--cwd", "."]) == 0
    assert "ZeroDivisionError" in json.loads(capsys.readouterr().out)["fatal"]
