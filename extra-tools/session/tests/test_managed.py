# ~/.claude/tools/session/tests/test_managed.py
"""Optional "manages" / "managed_by" Profile keys: one session keeping track of another project's session."""
import json

import open as op
import sessions
from conftest import FENCE, SAMPLE_HANDOFF

CHILD = """---
key: alice-child
updated: 2026-09-27T20:49Z
updated_by: hostb
---
# Handoff: alice-child

## Next up
_Rewritten every /sync._
1. Alice answers the open questions
2. Second thing

## Warnings
- No site code yet

## Profile
FENCEjson
{PROFILE}
FENCE
""".replace("FENCE", FENCE)


def _handoff(vault, key, text):
    (vault / "handoffs").mkdir(exist_ok=True)
    (vault / "handoffs" / f"{key}.md").write_text(text, encoding="utf-8")


def _parent(vault, profile):
    _handoff(vault, "alice-demo-proj", SAMPLE_HANDOFF.replace(
        '{"gh": "alice/demo-proj", "services": [{"unit": "demo", "scope": "user"}]}', json.dumps(profile)))


def test_no_manages_key_adds_nothing(repo, vault, fake):
    _handoff(vault, "alice-demo-proj", SAMPLE_HANDOFF)
    res = op.collect(repo)
    assert "managed" not in res and "managed_by" not in res


def test_manages_reports_child_state(repo, vault, fake, monkeypatch):
    _parent(vault, {"manages": [{"key": "alice-child"}]})
    _handoff(vault, "alice-child", CHILD.replace("{PROFILE}", '{"managed_by": "alice-demo-proj"}'))
    monkeypatch.setattr(sessions, "others", lambda key: [{"id": "x"}] if key == "alice-child" else [])
    [m] = op.collect(repo)["managed"]
    assert m["key"] == "alice-child" and m["handoff"] is True
    assert m["next_up_1"] == "Alice answers the open questions"
    assert m["warnings"] == "- No site code yet"
    assert m["updated_by"] == "hostb" and isinstance(m["age_h"], float)
    assert m["linked_back"] is True and m["live"] == 1


def test_manages_child_without_handoff_or_back_link(repo, vault, fake):
    _parent(vault, {"manages": [{"key": "alice-child"}, {"key": "alice-other"}]})
    _handoff(vault, "alice-other", CHILD.replace("{PROFILE}", "{}"))
    first, second = op.collect(repo)["managed"]
    assert first == {"key": "alice-child", "handoff": False, "live": 0}
    assert second["linked_back"] is False and second["live"] == 0


def test_manages_bad_entries_never_crash(repo, vault, fake):
    _parent(vault, {"manages": [{"key": "../etc/passwd"}, "alice-child", {"nokey": 1}]})
    res = op.collect(repo)["managed"]
    assert [m["key"] for m in res] == ["?", "?", "?"]
    assert all(m["error"].startswith("bad entry") for m in res)
    _parent(vault, {"manages": "alice-child"})
    [m] = op.collect(repo)["managed"]
    assert m["error"] == "bad entry: manages is not a list"


def test_manages_unreadable_child_handoff(repo, vault, fake):
    _parent(vault, {"manages": [{"key": "alice-child"}]})
    (vault / "handoffs/alice-child.md").write_bytes(b"\xff\xfe not utf-8")
    [m] = op.collect(repo)["managed"]
    assert m == {"key": "alice-child", "handoff": True, "error": "unreadable: UnicodeDecodeError"}


def test_managed_by_reports_the_manager(repo, vault, fake, monkeypatch):
    _parent(vault, {"managed_by": "alice-boss"})
    _handoff(vault, "alice-boss", CHILD.replace("{PROFILE}", '{"manages": [{"key": "alice-demo-proj"}]}'))
    monkeypatch.setattr(sessions, "others", lambda key: [])
    assert op.collect(repo)["managed_by"] == {"key": "alice-boss", "handoff": True, "linked_back": True, "live": 0}


def test_managed_by_bad_key(repo, vault, fake):
    _parent(vault, {"managed_by": "../x"})
    assert op.collect(repo)["managed_by"]["error"].startswith("bad entry")


def test_standing_notes_returned(repo, vault, fake):
    _handoff(vault, "alice-demo-proj", SAMPLE_HANDOFF.replace("## Last session", "## Standing notes\n- rule one\n\n## Last session"))
    assert op.collect(repo)["handoff"]["standing_notes"] == "- rule one"
