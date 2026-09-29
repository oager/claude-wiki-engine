# P1 (security, 2026-09-28): push must refuse directories — a directory path (especially the vault root)
# would silently commit ignored files (.credentials.json, projects/**) and other sessions' half-writes.
import os
import subprocess

import close as cl
import pytest
from test_push import pushable  # noqa: F401  (fixture)


def _git(vault, *args):
    return subprocess.run(["git", "-C", str(vault), *args], capture_output=True, text=True,
                          encoding="utf-8").stdout


def test_push_vault_root_refused_and_credentials_never_tracked(vault, pushable):  # noqa: F811
    (vault / ".gitignore").write_text("*.credentials.json\n", encoding="utf-8")
    (vault / ".credentials.json").write_text('{"secret": "x"}', encoding="utf-8")
    head = _git(vault, "rev-parse", "HEAD")
    res = cl.push([str(vault)], "m")
    assert res["status"] == "stage_failed"
    assert _git(vault, "diff", "--cached", "--name-only") == ""
    assert _git(vault, "rev-parse", "HEAD") == head
    assert ".credentials.json" not in _git(vault, "ls-files")
    assert not (vault / ".sync.lock").exists()


def test_push_handoffs_dir_refused(vault, pushable):  # noqa: F811
    (vault / "handoffs").mkdir()
    (vault / "handoffs/k.md").write_text("hand", encoding="utf-8")
    res = cl.push([str(vault / "handoffs")], "m")
    assert res["status"] == "stage_failed"
    assert _git(vault, "ls-files", "handoffs") == ""


def test_push_live_registry_dir_refused(vault, pushable):  # noqa: F811
    d = vault / "handoffs/.live"
    d.mkdir(parents=True)
    (d.parent / ".gitignore").write_text("*\n", encoding="utf-8")
    (d / "k").mkdir()
    (d / "k/aaaa1111-4242.json").write_text("{}", encoding="utf-8")
    res = cl.push([str(d)], "m")
    assert res["status"] == "stage_failed"


def test_push_file_and_directory_refuses_the_file_too(vault, pushable):  # noqa: F811
    (vault / "handoffs").mkdir()
    real = vault / "handoffs/k.md"
    real.write_text("hand", encoding="utf-8")
    res = cl.push([str(real), str(vault / "handoffs")], "m")
    assert res["status"] == "stage_failed"
    assert _git(vault, "ls-files", "handoffs") == ""
    assert _git(vault, "diff", "--cached", "--name-only") == ""


def test_push_dot_path_refused(vault, pushable):  # noqa: F811
    res = cl.push([str(vault) + "/."], "m")
    assert res["status"] == "stage_failed"


def test_push_two_real_files_still_ok(vault, pushable):  # noqa: F811
    (vault / "handoffs").mkdir()
    a = vault / "handoffs/k.md"
    a.write_text("hand", encoding="utf-8")
    b = vault / "f0.txt"
    b.write_text("changed", encoding="utf-8")
    res = cl.push([str(a), str(b)], "m")
    assert res["status"] == "ok"
    assert sorted(_git(pushable, "log", "-1", "--name-only", "--format=").split()) == ["f0.txt", "handoffs/k.md"]


# --- round 1 fixes (2026-09-28): git pathspec-glob leak, deleted tracked dir, symlink escape ---

def _rigged(vault):
    """A tracked handoffs/k.md (so a git-glob pathspec has something to latch onto), plus what it must
    never sweep in: .credentials.json (gitignored), a .live registry entry, and another session's dirty file."""
    (vault / "handoffs").mkdir()
    (vault / "handoffs/k.md").write_text("hand", encoding="utf-8")
    subprocess.run(["git", "-C", str(vault), "add", "handoffs/k.md"], check=True)
    subprocess.run(["git", "-C", str(vault), "commit", "-qm", "add handoffs/k.md"], check=True)
    (vault / ".gitignore").write_text("*.credentials.json\n", encoding="utf-8")
    (vault / ".credentials.json").write_text('{"secret": "x"}', encoding="utf-8")
    live = vault / "handoffs/.live/k"
    live.mkdir(parents=True)
    (live.parent / ".gitignore").write_text("*\n", encoding="utf-8")
    (live / "aaaa1111-4242.json").write_text("{}", encoding="utf-8")
    (vault / "other.md").write_text("another session's half-write", encoding="utf-8")


def test_push_unmatched_glob_at_vault_root_refused(vault, pushable):  # noqa: F811
    _rigged(vault)
    head = _git(vault, "rev-parse", "HEAD")
    res = cl.push([str(vault) + "/*"], "m")
    assert res["status"] != "ok"
    assert _git(vault, "diff", "--cached", "--name-only") == ""
    assert _git(vault, "rev-parse", "HEAD") == head
    tracked = _git(vault, "ls-files")
    for leak in (".credentials.json", "handoffs/.live", "other.md"):
        assert leak not in tracked
    assert not (vault / ".sync.lock").exists()


def test_push_unmatched_glob_under_handoffs_refused(vault, pushable):  # noqa: F811
    _rigged(vault)
    head = _git(vault, "rev-parse", "HEAD")
    res = cl.push([str(vault / "handoffs") + "/*"], "m")
    assert res["status"] != "ok"
    assert _git(vault, "diff", "--cached", "--name-only") == ""
    assert _git(vault, "rev-parse", "HEAD") == head
    assert "handoffs/.live" not in _git(vault, "ls-files")


def test_push_deleted_tracked_directory_refused(vault, pushable):  # noqa: F811
    d = vault / "handoffs/inbox"
    d.mkdir(parents=True)
    (d / "a.md").write_text("a", encoding="utf-8")
    (d / "b.md").write_text("b", encoding="utf-8")
    subprocess.run(["git", "-C", str(vault), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(vault), "commit", "-qm", "add inbox"], check=True)
    import shutil
    shutil.rmtree(d)
    res = cl.push([str(d)], "m")
    assert res["status"] == "stage_failed"
    assert _git(vault, "diff", "--cached", "--name-only") == ""
    assert sorted(_git(vault, "ls-files", "handoffs/inbox").split()) == \
        ["handoffs/inbox/a.md", "handoffs/inbox/b.md"]


def test_push_symlink_outside_vault_refused(vault, pushable, tmp_path):  # noqa: F811
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("s", encoding="utf-8")
    link = vault / "escape.txt"
    link.symlink_to(target)
    res = cl.push([str(link)], "m")
    assert res["status"] == "stage_failed"
    assert "outside the vault" in res["detail"]
    assert _git(vault, "diff", "--cached", "--name-only") == ""
    assert not (vault / ".sync.lock").exists()


# --- round 2 fixes (2026-09-28): core.quotePath breaks the exact-match check for non-ASCII / quote /
# backslash filenames; add a regression guard for --literal-pathspecs itself. ---

def _commit_new(vault, rel, content="x"):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(vault), "add", "--", rel], check=True)
    subprocess.run(["git", "-C", str(vault), "commit", "-qm", f"add {rel}"], check=True)


def test_push_moves_tracked_note_with_curly_apostrophe(vault, pushable):  # noqa: F811
    old_rel, new_rel = "memory/raw/Can’t Stop.md", "memory/archive/Can’t Stop.md"
    _commit_new(vault, old_rel, "lyrics")
    (vault / new_rel).parent.mkdir(parents=True, exist_ok=True)
    (vault / old_rel).replace(vault / new_rel)
    res = cl.push([str(vault / old_rel), str(vault / new_rel)], "m")
    assert res["status"] == "ok"
    assert not res.get("dropped")
    status = _git(pushable, "log", "-1", "--name-status", "--format=")
    assert any(line.startswith("R100") for line in status.splitlines()), status
    assert _git(vault, "ls-files", "--", old_rel) == ""
    assert _git(vault, "ls-files", "--", new_rel) != ""


def test_push_deletes_tracked_note_with_accent_and_emdash(vault, pushable):  # noqa: F811
    rel = "notes/café—x.md"
    _commit_new(vault, rel)
    (vault / rel).unlink()
    res = cl.push([str(vault / rel)], "m")
    assert res["status"] == "ok"
    assert not res.get("dropped")
    status = _git(pushable, "log", "-1", "--name-status", "--format=")
    assert status.strip().startswith("D"), status
    assert _git(vault, "ls-files", "--", rel) == ""


@pytest.mark.skipif(os.name == "nt", reason='" is not allowed in file names on Windows')
def test_push_deletes_tracked_note_with_double_quote(vault, pushable):  # noqa: F811
    rel = 'notes/say "hi".md'
    _commit_new(vault, rel)
    (vault / rel).unlink()
    res = cl.push([str(vault / rel)], "m")
    assert res["status"] == "ok"
    assert not res.get("dropped")
    status = _git(pushable, "log", "-1", "--name-status", "--format=")
    assert status.strip().startswith("D"), status
    assert _git(vault, "ls-files", "--", rel) == ""


def test_push_without_literal_pathspecs_would_wrongly_refuse_bracket_deletion(vault, pushable):  # noqa: F811
    """Regression guard for the --literal-pathspecs flag on g(): a tracked file whose OWN name contains
    pathspec-glob characters ('n[o]tes.md'), once deleted, must still be recognized by ls-files as tracked.
    Without --literal-pathspecs, `ls-files -- 'n[o]tes.md'` unions the literal match with whatever the
    bracket-class ALSO glob-matches (here the sibling 'notes.md'), so ls-files returns 2 lines instead of 1;
    tracked_as_one_file() then (correctly) refuses a 2-line result, but that means the legitimate deletion
    silently fails (status stage_failed, dropped) instead of committing. Verified by temporarily removing
    --literal-pathspecs from g() and confirming this exact test goes from 'ok' to 'stage_failed' (2026-09-28)."""
    bracket, sibling = "n[o]tes.md", "notes.md"
    _commit_new(vault, bracket, "bracket")
    _commit_new(vault, sibling, "sibling")
    (vault / bracket).unlink()
    res = cl.push([str(vault / bracket)], "m")
    assert res["status"] == "ok"
    # ls-files with a raw (non-literal) pathspec would ALSO glob-match the sibling here, so check the
    # literal filename against the full tracked-file list instead of using `bracket` as a pathspec.
    tracked = _git(vault, "ls-files").splitlines()
    assert bracket not in tracked
    assert sibling in _git(vault, "ls-files")
