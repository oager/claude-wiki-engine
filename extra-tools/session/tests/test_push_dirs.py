# P1 (security, 2026-09-28): push must refuse directories — a directory path (above all the vault root)
# would silently commit ignored files (.credentials.json, projects/**) and other sessions' half-writes.
import subprocess

import close as cl
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
