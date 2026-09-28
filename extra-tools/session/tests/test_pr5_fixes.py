# PR #5 review fixes (2026-09-28). Each test fails on the pre-fix code.
import json
import os
import subprocess
from pathlib import Path

import close as cl
import inbox
import leakguard
import lib
import open as op
import pytest
import repohandoff as rh
from conftest import SAMPLE_HANDOFF, sh
from test_push import pushable  # noqa: F401  (fixture)
from test_repohandoff import PRIVATE


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8").stdout


@pytest.fixture
def symlinks(tmp_path):
    try:
        (tmp_path / "_probe").symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        pytest.skip("this OS/user cannot create symlinks")
    (tmp_path / "_probe").unlink()


# --- 1. push never commits ignored or secret-shaped files -----------------------------------------

def _assert_nothing_staged(vault, head):
    assert _git(vault, "diff", "--cached", "--name-only") == ""
    assert _git(vault, "rev-parse", "HEAD") == head
    assert not (vault / ".sync.lock").exists()


def test_push_refuses_listed_ignored_credentials(vault, pushable):  # noqa: F811
    (vault / ".gitignore").write_text(".credentials.json\n", encoding="utf-8")
    (vault / ".credentials.json").write_text('{"secret": "x"}', encoding="utf-8")
    (vault / "handoffs").mkdir()
    (vault / "handoffs/k.md").write_text("hand", encoding="utf-8")
    head = _git(vault, "rev-parse", "HEAD")
    res = cl.push([str(vault / "handoffs/k.md"), str(vault / ".credentials.json")], "m")
    assert res["status"] == "stage_failed" and ".credentials.json" in res["detail"]
    _assert_nothing_staged(vault, head)
    assert ".credentials.json" not in _git(pushable, "log", "--all", "--name-only", "--format=")


@pytest.mark.parametrize("rel", [".env", "cfg/.env.local", "keys/server.pem", "a.KEY", "id_rsa", "id_ed25519.pub"])
def test_push_refuses_secret_shaped_names_even_when_not_ignored(vault, pushable, rel):  # noqa: F811
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("secret", encoding="utf-8")
    head = _git(vault, "rev-parse", "HEAD")
    res = cl.push([str(p)], "m")
    assert res["status"] == "stage_failed" and rel in res["detail"]
    _assert_nothing_staged(vault, head)


def test_push_refuses_ignored_file_outside_project_memory(vault, pushable):  # noqa: F811
    (vault / ".gitignore").write_text("memory/raw/*\n", encoding="utf-8")
    raw = vault / "memory/raw/scratch.md"
    raw.parent.mkdir(parents=True)
    raw.write_text("scratch", encoding="utf-8")
    head = _git(vault, "rev-parse", "HEAD")
    res = cl.push([str(raw)], "m")
    assert res["status"] == "stage_failed" and "memory/raw/scratch.md" in res["detail"]
    _assert_nothing_staged(vault, head)


VAULT_IGNORE = "projects/**\n!projects/\n!projects/*/\n!projects/*/memory/\n!projects/*/memory/**\n"


def test_push_still_force_adds_new_project_memory_file(vault, pushable):  # noqa: F811
    (vault / ".gitignore").write_text(VAULT_IGNORE, encoding="utf-8")
    m = vault / "projects/-home-x-proj/memory/new-page.md"
    m.parent.mkdir(parents=True)
    m.write_text("lesson", encoding="utf-8")
    res = cl.push([str(m)], "m")
    assert res["status"] == "ok" and res["missing"] == []
    assert "projects/-home-x-proj/memory/new-page.md" in _git(vault, "ls-files")


def test_push_refuses_secret_even_under_project_memory(vault, pushable):  # noqa: F811
    (vault / ".gitignore").write_text(VAULT_IGNORE, encoding="utf-8")
    k = vault / "projects/p/memory/id_rsa"
    k.parent.mkdir(parents=True)
    k.write_text("key", encoding="utf-8")
    head = _git(vault, "rev-parse", "HEAD")
    assert cl.push([str(k)], "m")["status"] == "stage_failed"
    _assert_nothing_staged(vault, head)


# --- 2. a file inside a nested repository is reported, not silently skipped ------------------------

def test_push_file_in_nested_repo_is_stage_failed_and_unstages(vault, pushable):  # noqa: F811
    nested = vault / "memory"
    nested.mkdir()
    sh("git", "init", "-q", cwd=nested)
    (nested / "a.md").write_text("page", encoding="utf-8")
    (vault / "handoffs").mkdir()
    (vault / "handoffs/k.md").write_text("hand", encoding="utf-8")
    head = _git(vault, "rev-parse", "HEAD")
    res = cl.push([str(vault / "handoffs/k.md"), str(nested / "a.md")], "m")
    assert res["status"] == "stage_failed" and "memory/a.md" in res["detail"] and "nested" in res["detail"]
    _assert_nothing_staged(vault, head)


# --- 3. stale-lock break never removes another waiter's fresh lock --------------------------------

def test_stale_lock_race_keeps_the_other_waiters_fresh_lock(vault, pushable, monkeypatch):  # noqa: F811
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    lock = vault / ".sync.lock"
    lock.mkdir()
    os.utime(lock, (1, 1))  # stale
    real, raced = os.rename, []

    def racing(src, dst):
        if not raced and Path(src) == lock:
            # Between our stale judgement and our rename, another waiter broke the stale lock and took a fresh one.
            raced.append(1)
            os.rmdir(lock)
            os.mkdir(lock)
        return real(src, dst)

    monkeypatch.setattr(cl.os, "rename", racing)
    res = cl.push([str(vault / "f0.txt")], "x", retries=2)
    assert res["status"] == "locked"
    assert lock.is_dir() and lock.stat().st_mtime > 1  # the other waiter's fresh lock survived
    assert not list(vault.glob(".sync.lock.stale-*"))


def test_stale_lock_is_broken_without_leftovers(vault, pushable, monkeypatch):  # noqa: F811
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    lock = vault / ".sync.lock"
    lock.mkdir()
    os.utime(lock, (1, 1))
    assert cl.push([str(vault / "f0.txt")], "x", retries=2)["status"] == "nothing"
    assert not lock.exists() and not list(vault.glob(".sync.lock.stale-*"))


# --- 4. malformed Profile entries are `unknown`, never a crashed collector -------------------------

BAD_PROFILE = {"health": [{"URL": "http://x"}], "services": ["myunit"]}


def test_run_checks_bad_health_entry_is_unknown(fake, tmp_path):
    [c] = op.run_checks("workspace", tmp_path, {"health": [{"URL": "http://x"}]}, {})
    assert (c["kind"], c["status"]) == ("health", "unknown") and c["detail"].startswith("bad check:")


def test_run_checks_bad_service_entry_is_unknown(fake, tmp_path):
    [c] = op.run_checks("workspace", tmp_path, {"services": ["myunit"]}, {})
    assert (c["kind"], c["status"]) == ("service", "unknown") and c["detail"].startswith("bad check:")


def test_run_checks_section_not_a_list_is_unknown(fake, tmp_path):
    [c] = op.run_checks("workspace", tmp_path, {"ports": {"port": 1}}, {})
    assert c["status"] == "unknown" and "not a list" in c["detail"]


def test_run_checks_good_entries_survive_a_bad_neighbour(fake, tmp_path):
    fake.on(["curl"], 0, "fine")
    checks = op.run_checks("workspace", tmp_path, {"health": [{"URL": "x"}, {"url": "http://ok"}]}, {})
    assert [c["status"] for c in checks] == ["unknown", "ok"]


def test_deploy_drift_skips_bad_entries_with_reason(repo, fake):
    d = cl.deploy_drift(repo, {"services": ["myunit", {"deploys_from_repo": True}]}, {})
    assert [x["drift"] for x in d] == [None, None]
    assert all(x["detail"].startswith("bad check:") for x in d)


def _handoff(vault, profile):
    (vault / "handoffs").mkdir(exist_ok=True)
    (vault / "handoffs/alice-demo-proj.md").write_text(
        SAMPLE_HANDOFF.replace('{"gh": "alice/demo-proj", "services": [{"unit": "demo", "scope": "user"}]}',
                               json.dumps(profile)), encoding="utf-8")


def test_both_collectors_survive_the_bad_profile(vault, repo, fake):
    _handoff(vault, BAD_PROFILE)
    res = op.collect(repo)
    assert "fatal" not in res
    assert {c["kind"]: c["status"] for c in res["checks"]} == {"service": "unknown", "health": "unknown"}
    res = cl.collect_close(repo)
    assert "fatal" not in res and res["drift"] == [{"unit": "?", "drift": None, "detail": "bad check: not an object"}]


# --- 5. Profile values never parse as command options ----------------------------------------------

def _no_exec(fake, marker, *tools):
    assert not marker.exists()
    assert not [c for c in fake.calls if c and c[0] in tools]


def test_ssh_proxycommand_host_is_refused(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(lib.socket, "gethostname", lambda: "HOST-B")
    marker = tmp_path / "pwned"
    host = f"-oProxyCommand=touch {marker}"
    [c] = op.run_checks("workspace", tmp_path, {"services": [{"unit": "demo", "host": host}]}, {})
    assert c["status"] == "unknown" and c["detail"].startswith("bad check:")
    _no_exec(fake, marker, "ssh")


def test_ssh_target_from_identity_is_refused(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(lib.socket, "gethostname", lambda: "HOST-B")
    marker = tmp_path / "pwned"
    ids = {"hosts": {"box": {"ssh": f"-oProxyCommand=touch {marker}"}}}
    [c] = op.run_checks("workspace", tmp_path, {"health": [{"url": "http://x", "host": "box"}]}, ids)
    assert c["status"] == "unknown" and c["detail"].startswith("bad check:")
    _no_exec(fake, marker, "ssh", "curl")


def test_option_shaped_unit_and_url_are_refused(fake, tmp_path):
    marker = tmp_path / "out"
    prof = {"services": [{"unit": "--host=evil"}], "health": [{"url": f"-o{marker}"}]}
    checks = op.run_checks("workspace", tmp_path, prof, {})
    assert [(c["status"], c["detail"][:10]) for c in checks] == [("unknown", "bad check:")] * 2
    _no_exec(fake, marker, "systemctl", "curl")
    [u] = op.user_checks({"checks": [{"kind": "service", "unit": "-H"}]}, {})
    assert u["status"] == "unknown"
    _no_exec(fake, marker, "systemctl")


def test_deploy_drift_option_shaped_unit_is_refused(repo, fake):
    [d] = cl.deploy_drift(repo, {"services": [{"unit": "-H", "deploys_from_repo": True}]}, {})
    assert d["drift"] is None and d["detail"].startswith("bad check:")
    assert not [c for c in fake.calls if c and c[0] == "systemctl"]


# --- 6. the repo handoff never writes through a symlink ---------------------------------------------

def test_repo_handoff_refuses_symlinked_claude_dir(tmp_path, symlinks):
    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / ".claude").symlink_to(outside, target_is_directory=True)
    res = rh.write(root, PRIVATE, "alice", ["bob@corp.example"])
    assert res["written"] is False and "symlink" in res["reason"]
    assert list(outside.iterdir()) == []


def test_repo_handoff_refuses_symlinked_file(tmp_path, symlinks):
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    victim = tmp_path / "bashrc"
    victim.write_text("original", encoding="utf-8")
    (root / rh.REL).symlink_to(victim)
    res = rh.write(root, PRIVATE, "alice", ["bob@corp.example"])
    assert res["written"] is False and "reason" in res
    assert victim.read_text(encoding="utf-8") == "original"


def test_repo_handoff_via_symlinked_root_is_fine_and_leaves_no_temp(tmp_path, symlinks):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert rh.write(link, PRIVATE, "alice", ["bob@corp.example"])["written"] is True
    assert [p.name for p in (real / ".claude").iterdir()] == ["HANDOFF.md"]


def test_repo_handoff_replaces_existing_file_atomically(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / rh.REL).write_text("old", encoding="utf-8")
    assert rh.write(tmp_path, PRIVATE, "alice", ["bob@corp.example"])["written"] is True
    assert "## Next up" in (tmp_path / rh.REL).read_text(encoding="utf-8")
    assert [p.name for p in (tmp_path / ".claude").iterdir()] == ["HANDOFF.md"]


# --- 7. leak guard: normalized, wrapped, home path --------------------------------------------------

@pytest.mark.parametrize("text", [
    "by Ce\u0301cile Roe",           # NFD
    "by Cé\u200bcile Roe",           # zero-width space inside the name
    "by \uff23\uff45\u0301cile Roe",  # fullwidth + NFD
    "by CÉCILE ROE",                 # case
])
def test_leakguard_normalizes(text):
    assert leakguard.find({"f": text}, ["Cécile Roe"]) == ["f:1: cécile roe"]


def test_leakguard_catches_a_name_wrapped_across_lines():
    assert leakguard.find({"f": "x\nsigned Cecile\n   Roe today\n"}, ["cecile roe"]) == ["f:2: cecile roe"]


def test_leakguard_home_path_is_always_a_needle(monkeypatch):
    monkeypatch.setattr(leakguard.Path, "home", staticmethod(lambda: Path("/home/zed-user")))
    hits = leakguard.find({"a": "cd /home/zed-user/proj", "b": r"C:\home\zed-user\x", "c": "zed-user alone"},
                          ["unrelated"])
    assert [h.split(":")[0] for h in hits] == ["a", "b"]


def test_leakguard_needles_have_no_home_so_empty_guard_still_refuses():
    assert leakguard.needles({}) == []


# --- 8. inbox-done moves notes only -----------------------------------------------------------------

def test_mark_done_refuses_non_notes_and_moves_the_rest(vault, capsys, symlinks):
    good = inbox.write_note("k", "s", "one", "b")
    d = good.parent
    done_note = d / "done" / "old.md"
    done_note.parent.mkdir()
    done_note.write_text("x", encoding="utf-8")
    txt = d / "notes.txt"
    txt.write_text("x", encoding="utf-8")
    link = d / "link.md"
    link.symlink_to(txt)
    bad = [str(d), str(done_note), str(txt), str(link), str(vault / "handoffs/other.md")]
    cl.main(["inbox-done", "--files", *bad, str(good)])
    res = json.loads(capsys.readouterr().out)
    assert res["refused"] == bad and res["moved"] == 1 and res["already_done"] == []
    assert d.is_dir() and done_note.is_file() and txt.is_file() and link.is_symlink()
    assert (d / "done" / good.name).is_file()


# --- 9. vault state checks work in a worktree vault (.git is a file) --------------------------------

@pytest.fixture
def wt_vault(tmp_path, monkeypatch):
    main = tmp_path / "main"
    main.mkdir()
    sh("git", "init", "-q", "-b", "main", cwd=main)
    sh("git", "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-q", "--allow-empty", "-m", "i",
       cwd=main)
    wt = tmp_path / "wt"
    sh("git", "worktree", "add", "-q", "-b", "wt", str(wt), cwd=main)
    monkeypatch.setenv("CLAUDE_VAULT", str(wt))
    return wt, main / ".git" / "worktrees" / "wt"


def test_worktree_vault_rebase_detected(wt_vault):
    wt, gitdir = wt_vault
    assert (wt / ".git").is_file() and lib.rebase_in_progress(wt) is False
    (gitdir / "rebase-merge").mkdir()
    assert lib.rebase_in_progress(wt) is True


def test_worktree_vault_merge_head_detected(wt_vault):
    wt, gitdir = wt_vault
    (gitdir / "MERGE_HEAD").write_text("0" * 40, encoding="utf-8")
    assert op.vault_state() == {"pull": "skipped", "stuck_merge": True}


def test_rebase_check_falls_back_when_git_fails(vault, fake):
    fake.on(["git", "-C", str(vault), "rev-parse"], 128, "", "fatal")
    (vault / ".git/rebase-apply").mkdir()
    assert lib.rebase_in_progress(vault) is True


# --- 10. check-profile ------------------------------------------------------------------------------

def test_check_profile_cli(tmp_path, capsys):
    good, bad = tmp_path / "good.md", tmp_path / "bad.md"
    good.write_text(SAMPLE_HANDOFF, encoding="utf-8")
    bad.write_text(SAMPLE_HANDOFF.replace('"services"', 'services'), encoding="utf-8")
    for path, ok in ((good, True), (bad, False), (tmp_path / "missing.md", False)):
        assert cl.main(["check-profile", str(path)]) == 0
        res = json.loads(capsys.readouterr().out)
        assert list(res) == ["profile_error"] and (res["profile_error"] is None) is ok
