import publish


def _vault(tmp_path, planted=""):
    v = tmp_path / "vault"
    (v / "skills/preflight").mkdir(parents=True)
    (v / "skills/sync").mkdir(parents=True)
    (v / "skills/preflight/SKILL.md").write_text("---\nname: preflight\n---\nbody\n", encoding="utf-8")
    (v / "skills/sync/SKILL.md").write_text("---\nname: sync\n---\nbody\n", encoding="utf-8")
    t = v / "tools/session"
    (t / "tests").mkdir(parents=True)
    (t / "__pycache__").mkdir()
    (t / ".ruff_cache").mkdir()
    (t / "open.py").write_text(f"x = 1  {planted}\n", encoding="utf-8")
    (t / "tests/test_x.py").write_text("def test(): pass\n", encoding="utf-8")
    (t / "self_ids.json").write_text("{}", encoding="utf-8")
    (t / "__pycache__/open.cpython-312.pyc").write_bytes(b"\0")
    (t / ".ruff_cache/x.bin").write_bytes(b"\0\1\2")
    (t / "claude-md-block.md").write_text("## Session handoff\n", encoding="utf-8")
    (v / "handoffs").mkdir()
    (v / "handoffs/_TEMPLATE.md").write_text("# Handoff\n", encoding="utf-8")
    (v / "handoffs/_USER.template.md").write_text("# User handoff\n", encoding="utf-8")
    (v / "handoffs/_USER.md").write_text("secret-host\n", encoding="utf-8")
    return v


def _engine(tmp_path):
    e = tmp_path / "engine"
    (e / "extra-skills/preflight").mkdir(parents=True)
    (e / "extra-skills/preflight/OLD").write_text("old", encoding="utf-8")
    (e / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    return e


def test_publish_copies_tags_and_excludes(tmp_path):
    v, e = _vault(tmp_path), _engine(tmp_path)
    assert publish.publish(e, vault=v, needles=["secret-host"])["status"] == "ok"
    assert "source: claude-wiki-engine" in (e / "extra-skills/preflight/SKILL.md").read_text(encoding="utf-8")
    assert not (e / "extra-skills/preflight/OLD").exists()
    assert (e / "extra-tools/session/open.py").is_file() and (e / "extra-tools/session/tests/test_x.py").is_file()
    assert not (e / "extra-tools/session/self_ids.json").exists()
    assert not (e / "extra-tools/session/__pycache__").exists()
    assert not (e / "extra-tools/session/.ruff_cache").exists()
    assert (e / "extra-tools/session/.engine").read_text(encoding="utf-8").strip() == "9.9.9"
    assert (e / "claude-md/session-handoff.md").is_file()
    assert (e / "templates/handoffs/_USER.template.md").is_file()
    assert not (e / "templates/handoffs/_USER.md").exists()


def test_publish_refuses_a_leak_and_touches_nothing(tmp_path):
    v, e = _vault(tmp_path, planted="# ssh secret-host"), _engine(tmp_path)
    res = publish.publish(e, vault=v, needles=["secret-host"])
    assert res["status"] == "refused" and res["hits"] == ["extra-tools/session/open.py:1: secret-host"]
    assert (e / "extra-skills/preflight/OLD").exists()


def test_publish_refuses_without_needles(tmp_path):
    v, e = _vault(tmp_path), _engine(tmp_path)
    res = publish.publish(e, vault=v, needles=[])
    assert res["status"] == "refused" and "identity" in res["reason"]


def test_dry_run_writes_nothing(tmp_path):
    v, e = _vault(tmp_path), _engine(tmp_path)
    res = publish.publish(e, vault=v, needles=["secret-host"], dry_run=True)
    assert res["status"] == "dry-run" and "extra-tools/session/open.py" in res["files"]
    assert (e / "extra-skills/preflight/OLD").exists()


def test_caller_needles_are_lowercased_and_stripped(tmp_path):
    v, e = _vault(tmp_path, planted="# ssh secret-host"), _engine(tmp_path)
    res = publish.publish(e, vault=v, needles=[" Secret-Host "])
    assert res["status"] == "refused" and res["hits"] == ["extra-tools/session/open.py:1: secret-host"]


def test_refuses_when_profile_has_only_publish_deny(tmp_path, monkeypatch):
    v, e = _vault(tmp_path), _engine(tmp_path)
    monkeypatch.setattr(publish.lib, "user_file",
                         lambda: {"profile": {"publish_deny": ["acct-42"]}})
    res = publish.publish(e, vault=v)
    assert res["status"] == "refused" and "identity" in res["reason"]
