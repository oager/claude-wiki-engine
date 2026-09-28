# Regression tests for the final whole-branch review fix wave (2026-09-28, items A1-A11).
import io
import json
import subprocess
import sys

import close as cl
import inbox
import lib
import open as op
import procs
import pytest
import repohandoff as rh
from conftest import SAMPLE_HANDOFF, commit, sh
from test_procs import ME, ROOT, rows_for
from test_push import pushable  # noqa: F401  (fixture)

FENCE = "`" * 3
NOBODY = {"names": [], "emails": [], "hosts": {}}


def _user(vault, profile):
    (vault / "handoffs").mkdir(exist_ok=True)
    (vault / "handoffs/_USER.md").write_text(
        f"---\nkey: _user\n---\n# User handoff\n\n## Profile\n{FENCE}json\n{json.dumps(profile)}\n{FENCE}\n",
        encoding="utf-8")


def _project_handoff(vault):
    (vault / "handoffs").mkdir(exist_ok=True)
    (vault / "handoffs/alice-demo-proj.md").write_text(SAMPLE_HANDOFF, encoding="utf-8")


def _out(capsys):
    return json.loads(capsys.readouterr().out)


# A1: the repo handoff reports whether collaborators can see it.
def test_repo_handoff_uncommitted_after_write(vault, repo):
    _project_handoff(vault)
    _user(vault, {"identity": {"emails": ["alice@corp.example"]}})
    res = cl.write_repo_handoff(repo)
    assert res["written"] is True
    assert (res["uncommitted"], res["ignored"]) == (True, False)


def test_repo_handoff_ignored_when_claude_dir_is_gitignored(vault, repo):
    (repo / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    commit(repo, "ignore .claude")
    _project_handoff(vault)
    _user(vault, {"identity": {"emails": ["alice@corp.example"]}})
    res = cl.write_repo_handoff(repo)
    assert res["written"] is True and res["ignored"] is True


def test_repo_handoff_header_does_not_promise_a_merge():
    out = rh.render("## Next up\n1. x\n", "alice")
    assert "merges your changes" not in out
    assert "edits here are overwritten" in out


# A7: no identity strings means nothing to guard with: refuse.
def test_repo_handoff_refuses_without_needles(tmp_path):
    res = rh.write(tmp_path, "## Next up\n1. x\n", "alice", [])
    assert res == {"written": False, "refused": [],
                   "reason": "no identity strings to guard with; fill _USER.md identity first"}
    assert not (tmp_path / rh.REL).exists()


# A8: CLI shapes.
def test_repo_handoff_cli_refuses_without_identity(vault, repo, capsys):
    _project_handoff(vault)
    cl.main(["--cwd", str(repo), "repo-handoff"])
    res = _out(capsys)
    assert res["written"] is False and res["refused"] == [] and "identity" in res["reason"]
    assert not (repo / rh.REL).exists()


def test_inbox_done_cli_shape(vault, capsys):
    p = inbox.write_note("k", "s", "one", "b")
    cl.main(["inbox-done", "--files", str(p)])
    assert _out(capsys) == {"moved": 1, "stage": [str(p), str(p.parent / "done" / p.name)]}


def test_note_stdin_is_read_as_utf8(vault, pushable, monkeypatch, capsys):  # noqa: F811
    text = "café — naïve"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="latin-1"))
    cl.main(["note", "--to", "k", "--from", "tester", "--subject", "enc"])
    res = _out(capsys)
    assert res["status"] == "ok"
    [n] = inbox.list_notes("k")
    assert text in open(n["path"], encoding="utf-8").read()


def test_note_stdin_strips_a_leading_bom(vault, pushable, monkeypatch, capsys):  # noqa: F811
    text = "hello body"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\xef\xbb\xbf" + text.encode("utf-8")),
                                                         encoding="latin-1"))
    cl.main(["note", "--to", "k", "--from", "tester", "--subject", "bom"])
    res = _out(capsys)
    assert res["status"] == "ok"
    [n] = inbox.list_notes("k")
    written = open(n["path"], encoding="utf-8").read()
    assert "﻿" not in written and text in written


# A2: malformed user checks never break the briefing.
def test_user_checks_not_a_list(vault):
    [c] = op.user_checks({"checks": "oops"}, NOBODY)
    assert (c["status"], c["detail"], c["loud"]) == ("unknown", "bad checks: not a list", False)


def test_user_checks_bad_entries_are_unknown(vault):
    bad = [{"kind": "queue", "name": "q"}, {"kind": "service", "name": "s"}, "oops", 7]
    res = op.user_checks({"checks": bad}, NOBODY)
    assert len(res) == 4
    assert all(c["status"] == "unknown" and c["source"] == "user" and c["loud"] is False for c in res)
    assert all(c["detail"].startswith("bad check:") for c in res)
    assert (res[0]["kind"], res[1]["kind"], res[2]["kind"]) == ("queue", "service", "?")


def test_collect_survives_bad_user_checks(vault, repo, fake):
    _user(vault, {"checks": [{"kind": "queue"}, "oops", {"kind": "port"}]})
    res = op.collect(repo)
    assert "fatal" not in res
    assert [c["status"] for c in res["global"]["user_checks"]] == ["unknown"] * 3


def test_collect_survives_checks_not_a_list(vault, repo, fake):
    _user(vault, {"checks": "oops"})
    assert op.collect(repo)["global"]["user_checks"][0]["detail"] == "bad checks: not a list"


def test_user_service_check(vault, fake):
    fake.on(["systemctl", "--user", "is-active", "good"], 0, "active\n")
    fake.on(["systemctl", "--user", "is-active", "bad"], 3, "failed\n")
    good, bad = op.user_checks({"checks": [{"kind": "service", "unit": "good"},
                                           {"kind": "service", "unit": "bad"}]}, NOBODY)
    assert (good["source"], good["status"], good["loud"]) == ("user", "ok", False)
    assert (bad["source"], bad["status"], bad["loud"]) == ("user", "fail", True)


def test_user_health_check(vault, fake):
    fake.on(["curl", "-s", "-m", "5", "http://localhost:1/ok"], 0, '{"ok": true}')
    ok, down = op.user_checks({"checks": [{"kind": "health", "url": "http://localhost:1/ok", "expect": "ok"},
                                          {"kind": "health", "url": "http://localhost:1/down"}]}, NOBODY)
    assert (ok["source"], ok["status"], ok["loud"]) == ("user", "ok", False)
    assert (down["source"], down["status"], down["loud"]) == ("user", "fail", True)


def test_user_port_check(vault, fake):
    fake.on(["ss"], 0, 'LISTEN 0 511 127.0.0.1:8080 0.0.0.0:* users:(("node",pid=1,fd=3))\n')
    ok, missing = op.user_checks({"checks": [{"kind": "port", "port": 8080}, {"kind": "port", "port": 9090}]},
                                 NOBODY)
    assert (ok["source"], ok["status"], ok["loud"]) == ("user", "ok", False)
    assert (missing["source"], missing["status"], missing["loud"]) == ("user", "fail", True)


def test_identity_types_are_coerced(vault, monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "HERE", tmp_path)
    _user(vault, {"identity": {"names": "alice", "emails": ["a@example.com", 5], "hosts": ["box"]}})
    ids = lib.load_self_ids()
    assert ids == {"names": [], "emails": ["a@example.com"], "hosts": {}}
    assert lib.is_self("alice", "a@example.com", ids) is True


# A3: a general runtime as EXECPATH never makes every process of that runtime "Claude".
@pytest.mark.parametrize("exe", ["/usr/bin/node", "C:\\Program Files\\nodejs\\node.exe", "/usr/bin/python3.12",
                                 "/usr/local/bin/bun", "/usr/bin/pwsh"])
def test_runtime_execpath_is_ignored(monkeypatch, exe):
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", exe)
    assert procs.is_claude(procs._comm(exe)) is False
    assert procs.is_claude("claude") is True and procs.is_claude("2.1.283") is True


# A4: terminal hosts and helper tools under the session shell are not running work.
def test_probe_skips_conhost_but_not_node():
    rows = rows_for(ROOT) + [
        {"pid": 56, "ppid": 30, "comm": "conhost", "cmdline": "\\??\\C:\\Windows\\system32\\conhost.exe 0x4"},
        {"pid": 57, "ppid": 30, "comm": "git", "cmdline": "git status"},
        {"pid": 58, "ppid": 30, "comm": "node", "cmdline": "node server.js"},
    ]
    pids = [p["pid"] for p in procs.running_in(ROOT, rows, ME)]
    assert 56 not in pids and 57 not in pids and 58 in pids


# A5 + A11: close.py returns the note paths and the handoff's frontmatter `updated`.
def test_collect_close_inbox_notes_and_handoff_updated(vault, repo, fake):
    a = inbox.write_note("alice-demo-proj", "s", "for the project", "b")
    b = inbox.write_note("_user", "s", "for everyone", "b")
    res = cl.collect_close(repo)
    assert res["inbox_notes"] == [str(a), str(b)] and res["inbox_untriaged"] == 2
    assert res["handoff_updated"] is None
    _project_handoff(vault)
    assert cl.collect_close(repo)["handoff_updated"] == "2026-09-27T20:49Z"


# A6: a git vault without a remote commits locally and says so.
def test_push_without_upstream_commits_locally(vault):
    (vault / "handoffs").mkdir()
    h = vault / "handoffs/k.md"
    h.write_text("hand", encoding="utf-8")
    r = cl.push([str(h)], "sync: k")
    assert r["status"] == "committed_local" and r["missing"] == [] and r["sha"]
    assert r["reason"] == "no remote"
    log = subprocess.run(["git", "-C", str(vault), "log", "-1", "--format=%s"], capture_output=True, text=True,
                         encoding="utf-8").stdout.strip()
    assert log == "sync: k"
    assert cl.push([str(h)], "sync: k again")["status"] == "committed_local"


def test_push_with_remote_but_no_tracking_reports_reason(vault):
    sh("git", "remote", "add", "origin", "git@github.com:alice/vault.git", cwd=vault)
    (vault / "handoffs").mkdir()
    h = vault / "handoffs/k.md"
    h.write_text("hand", encoding="utf-8")
    r = cl.push([str(h)], "sync: k")
    assert r["status"] == "committed_local"
    assert r["reason"] == "no upstream (run: git push -u origin main)"


def test_push_on_detached_head_reports_reason(vault):
    sh("git", "checkout", "-q", "--detach", cwd=vault)
    (vault / "handoffs").mkdir()
    h = vault / "handoffs/k.md"
    h.write_text("hand", encoding="utf-8")
    r = cl.push([str(h)], "sync: k")
    assert r["status"] == "committed_local"
    assert r["reason"] == "detached HEAD"


def test_vault_state_without_upstream_skips_pull(vault, fake):
    assert op.vault_state() == {"pull": "skipped (no remote)", "stuck_merge": False}
    assert not any("pull" in c for c in fake.calls)


def test_vault_state_with_remote_but_no_tracking_skips_pull(vault, fake):
    sh("git", "remote", "add", "origin", "git@github.com:alice/vault.git", cwd=vault)
    assert op.vault_state() == {"pull": "skipped (no upstream (run: git push -u origin main))", "stuck_merge": False}
    assert not any("pull" in c for c in fake.calls)


def test_vault_state_on_detached_head_skips_pull(vault, fake):
    sh("git", "checkout", "-q", "--detach", cwd=vault)
    assert op.vault_state() == {"pull": "skipped (detached HEAD)", "stuck_merge": False}
    assert not any("pull" in c for c in fake.calls)


# A9: inbox hardening.
def test_inbox_key_rejects_trailing_newline(vault):
    with pytest.raises(ValueError):
        inbox.inbox_dir("k\n")


def test_note_from_is_one_line(vault):
    inbox.write_note("k", "a\nto: evil", "s", "b")
    [n] = inbox.list_notes("k")
    assert n["from"] == "a to: evil"


def test_mark_done_refuses_paths_outside_inbox(vault):
    stray = vault / "handoffs/alice-demo-proj.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        inbox.mark_done([str(stray)])
    assert stray.is_file()


def test_mark_done_never_overwrites(vault):
    p = inbox.write_note("k", "s", "one", "first")
    (p.parent / "done").mkdir()
    (p.parent / "done" / p.name).write_text("older", encoding="utf-8")
    staged = inbox.mark_done([str(p)])
    assert (p.parent / "done" / p.name).read_text(encoding="utf-8") == "older"
    assert staged[1].endswith(p.stem + "-2.md")
    assert "first" in open(staged[1], encoding="utf-8").read()


# A10: a root followed by a list separator is still the root.
def test_root_boundary_accepts_separators():
    rows = [{"pid": 5, "ppid": 1, "comm": "node", "cmdline": "node tool.js --roots=C:\\a\\proj,C:\\x"},
            {"pid": 6, "ppid": 1, "comm": "node", "cmdline": "node tool.js --roots=C:\\a\\proj2"}]
    assert [p["pid"] for p in procs.running_in("C:\\a\\proj", rows, ME)] == [5]
