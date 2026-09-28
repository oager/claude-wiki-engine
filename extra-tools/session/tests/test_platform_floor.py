import close as cl
import lib
import open as op
import pytest

NOBODY = {"names": [], "emails": [], "hosts": {}}


@pytest.fixture
def plain_vault(tmp_path, monkeypatch):
    v = tmp_path / "plainvault"
    v.mkdir()
    monkeypatch.setenv("CLAUDE_VAULT", str(v))
    return v


def test_plain_vault_collect(plain_vault, repo, fake):
    g = op.collect(repo)["global"]
    assert (g["vault"], g["pull"], g["stuck_merge"]) == ("local", "skipped", False)
    assert g["knowledge_changed"] == [] and g["skills_changed"] == []


def test_git_vault_reports_git(vault, repo, fake):
    assert op.collect(repo)["global"]["vault"] == "git"


def test_plain_vault_push_is_local(plain_vault):
    (plain_vault / "handoffs").mkdir()
    f = plain_vault / "handoffs/k.md"
    f.write_text("x", encoding="utf-8")
    assert cl.push([str(f)], "m") == {"status": "local"}


def test_close_creates_handoffs_dir(plain_vault, repo, fake):
    cl.collect_close(repo)
    assert (plain_vault / "handoffs").is_dir()


def test_service_check_without_systemctl(fake):
    fake.on(["systemctl"], 127, "", "No such file or directory")
    c = op.service_check({"unit": "demo"}, NOBODY, "profile")
    assert (c["status"], c["detail"]) == ("unknown", "systemctl unavailable")


def test_no_unit_guessing_without_systemctl(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(lib, "has_systemctl", lambda: False)
    checks = op.run_checks("web-app", tmp_path, {}, NOBODY)
    assert [c for c in checks if c["source"] == "guessed"] == []
