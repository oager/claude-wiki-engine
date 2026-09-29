import json

import lib

FENCE = "`" * 3


def _user(vault, profile, extra=""):
    (vault / "handoffs").mkdir(exist_ok=True)
    p = vault / "handoffs/_USER.md"
    p.write_text(f"---\nkey: _user\ntype: user\n---\n# User handoff\n\n## Conventions\n- one\n\n"
                 f"## Profile\n{FENCE}json\n{profile}\n{FENCE}\n{extra}", encoding="utf-8")
    return p


def test_user_file_missing(vault, monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "HERE", tmp_path)  # no legacy self_ids.json either
    u = lib.user_file()
    assert (u["exists"], u["profile"], u["profile_error"], u["over_max"]) == (False, {}, None, False)
    assert lib.load_self_ids() == {"names": [], "emails": [], "hosts": {}}


def test_identity_from_user_file(vault, monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "HERE", tmp_path)
    _user(vault, json.dumps({"identity": {"names": ["alice"], "emails": ["a@example.com"], "hosts": {}}}))
    assert lib.load_self_ids() == {"names": ["alice"], "emails": ["a@example.com"], "hosts": {}}


def test_broken_profile_falls_back_to_legacy_file(vault, monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "HERE", tmp_path)
    (tmp_path / "self_ids.json").write_text(json.dumps({"names": ["legacy"], "emails": [], "hosts": {}}),
                                            encoding="utf-8")
    _user(vault, "{not json")
    assert lib.user_file()["profile_error"].startswith("Profile json invalid")
    assert lib.load_self_ids()["names"] == ["legacy"]


def test_partial_identity_gets_defaults(vault, monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "HERE", tmp_path)
    _user(vault, json.dumps({"identity": {"names": ["alice"]}}))
    ids = lib.load_self_ids()
    assert ids["emails"] == [] and ids["hosts"] == {}


def test_over_max(vault):
    _user(vault, json.dumps({"max_kb": 1}), extra="x" * 2000)
    u = lib.user_file()
    assert u["over_max"] is True and u["size_kb"] > 1


def test_max_kb_default_is_8(vault):
    _user(vault, json.dumps({}), extra="x" * 5000)
    assert lib.user_file()["over_max"] is False


def test_expand(vault):
    assert lib.expand("<vault>/state/q.json") == str(vault) + "/state/q.json"
    assert not lib.expand("~/x").startswith("~")
