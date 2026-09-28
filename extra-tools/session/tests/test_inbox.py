# ~/.claude/tools/session/tests/test_inbox.py
import datetime as dt
import json

import close as cl
import inbox
import open as op
import pytest
from test_push import pushable  # noqa: F401  (fixture)

NOW = dt.datetime(2026, 9, 28, 12, 5, tzinfo=dt.UTC)


def test_write_and_list_round_trip(vault):
    p = inbox.write_note("alice-demo-proj", "windows-session", "fix #4: part\ntwo", "body text", now=NOW)
    assert p.name == "2026-09-28T1205Z-fix-4-part-two.md"
    [n] = inbox.list_notes("alice-demo-proj")
    assert (n["from"], n["subject"], n["created"]) == ("windows-session", "fix #4: part two", "2026-09-28T12:05Z")


def test_same_minute_same_subject_does_not_overwrite(vault):
    a = inbox.write_note("k", "s", "same", "1", now=NOW)
    b = inbox.write_note("k", "s", "same", "2", now=NOW)
    assert a != b and len(inbox.list_notes("k")) == 2


def test_bad_key_is_refused(vault):
    with pytest.raises(ValueError):
        inbox.write_note("../../etc", "s", "x", "y")


def test_unreadable_note_is_listed_not_dropped(vault):
    d = vault / "handoffs/inbox/k"
    d.mkdir(parents=True)
    (d / "bad.md").write_bytes(b"\xff\xfe not utf-8")
    assert inbox.list_notes("k")[0]["subject"] == "<unreadable>"


def test_done_notes_are_not_listed(vault):
    p = inbox.write_note("k", "s", "one", "b", now=NOW)
    staged = inbox.mark_done([str(p)])
    assert inbox.list_notes("k") == []
    assert staged == [str(p), str(p.parent / "done" / p.name)]


def test_push_stages_a_moved_note(vault, pushable):  # noqa: F811
    p = inbox.write_note("k", "s", "one", "b", now=NOW)
    assert cl.push([str(p)], "note")["status"] == "ok"
    res = cl.push(inbox.mark_done([str(p)]), "triage")
    assert res["status"] == "ok" and res["missing"] == []


def test_note_cli(vault, pushable, tmp_path, capsys):  # noqa: F811
    body = tmp_path / "b.md"
    body.write_text("see docs/specs/x.md", encoding="utf-8")
    cl.main(["note", "--to", "k", "--from", "tester", "--subject", "hello", "--file", str(body)])
    res = json.loads(capsys.readouterr().out)
    assert res["status"] == "ok" and res["path"].endswith("-hello.md")


def test_collect_lists_project_and_user_notes(vault, repo, fake):
    inbox.write_note("alice-demo-proj", "s", "for the project", "b", now=NOW)
    inbox.write_note("_user", "s", "for everyone", "b", now=NOW)
    assert op.collect(repo)["inbox"]["count"] == 2
    assert cl.collect_close(repo)["inbox_untriaged"] == 2
