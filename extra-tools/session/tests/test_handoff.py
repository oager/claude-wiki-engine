# ~/.claude/tools/session/tests/test_handoff.py
import os

import lib
from conftest import SAMPLE_HANDOFF


def test_parse_handoff_full():
    h = lib.parse_handoff(SAMPLE_HANDOFF)
    assert h["meta"]["type"] == "web-app"  # inline comment stripped
    assert h["meta"]["updated"] == "2026-09-27T20:49Z"
    assert h["sections"]["Next up"] == "1. Ship the thing"
    assert h["sections"]["Warnings"] == "none"
    assert h["profile"]["gh"] == "alice/demo-proj"
    assert h["profile_error"] is None


def test_parse_handoff_malformed_profile():
    h = lib.parse_handoff(SAMPLE_HANDOFF.replace('"gh": "alice/demo-proj",', '"gh": oops,'))
    assert h["profile"] == {}
    assert "Profile json invalid" in h["profile_error"]
    assert h["sections"]["Next up"] == "1. Ship the thing"  # the rest stays usable


def test_parse_handoff_crlf_and_no_frontmatter():
    h = lib.parse_handoff("## Next up\r\n1. a\r\n")
    assert h["meta"] == {}
    assert h["sections"]["Next up"] == "1. a"


def test_parse_utc():
    assert lib.parse_utc("2026-09-27T20:49Z").hour == 20
    assert lib.parse_utc("garbage") is None
    assert lib.parse_utc(None) is None


def test_handoff_path(vault):
    assert lib.handoff_path("alice-x") == vault / "handoffs" / "alice-x.md"


def test_find_legacy_newest_wins(tmp_path, vault):
    root = tmp_path / "proj"
    (root / ".claude/memory").mkdir(parents=True)
    repo_copy = root / ".claude/memory/SESSION_RESUME.md"
    repo_copy.write_text("old", encoding="utf-8")
    vdir = vault / "projects" / lib.slug(str(root)) / "memory"
    vdir.mkdir(parents=True)
    vault_copy = vdir / "SESSION_RESUME.md"
    vault_copy.write_text("new", encoding="utf-8")
    os.utime(repo_copy, (1_700_000_000, 1_700_000_000))
    leg = lib.find_legacy(root, root)
    assert leg["path"] == str(vault_copy)
    assert leg["age_days"] >= 0


def test_find_legacy_uses_start_folder_slug(tmp_path, vault):
    start, root = tmp_path / "hub", tmp_path / "hub" / "app"
    root.mkdir(parents=True)
    vdir = vault / "projects" / lib.slug(str(start)) / "memory"
    vdir.mkdir(parents=True)
    (vdir / "SESSION_RESUME.md").write_text("x", encoding="utf-8")
    assert lib.find_legacy(root, start)["path"].endswith("SESSION_RESUME.md")


def test_find_legacy_none(tmp_path, vault):
    assert lib.find_legacy(tmp_path / "nothing", tmp_path / "nothing") is None
