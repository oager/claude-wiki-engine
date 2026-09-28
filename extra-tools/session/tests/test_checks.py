# ~/.claude/tools/session/tests/test_checks.py
import json
import os

import lib
import open as op
import pytest


def test_detect_type(tmp_path):
    def t():
        return op.detect_type(tmp_path, {})["type"]
    assert t() == "workspace"
    (tmp_path / "templates/scaffold").mkdir(parents=True)
    (tmp_path / "templates/scaffold/server.js").write_text("", encoding="utf-8")
    assert t() == "web-app"
    (tmp_path / ".claude/memory").mkdir(parents=True)
    (tmp_path / ".claude/memory/status.json").write_text("{}", encoding="utf-8")
    assert t() == "trading-bot"
    assert op.detect_type(tmp_path, {"type": "static-site"}) == {
        "type": "static-site", "signals": ["handoff frontmatter"]}


def test_detect_static_site(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "wrangler.toml").write_text("", encoding="utf-8")
    assert op.detect_type(tmp_path, {})["type"] == "static-site"


@pytest.mark.parametrize("name,tok", [
    ("alpha_beta_bot_v2_daily", "alpha-beta"), ("gamma_bot", "gamma"), ("delta", "delta"),
    ("Sample Trading Bot", "sample-trading"), ("demo-hub", "demo-hub")])
def test_unit_token(tmp_path, name, tok):
    assert op.unit_token(tmp_path / name) == tok


UNITS = ("alpha-beta-bot.service loaded active running Task\n"
         "alpha-beta-watchdog.service loaded inactive dead Watch\n"
         "gamma-bot.service loaded active running K\n")


def test_guessed_services(fake, tmp_path):
    fake.on(["systemctl", "--user", "list-units"], 0, UNITS)
    fake.on(["systemctl", "list-units"], 0, "")
    fake.on(["systemctl", "--user", "is-active", "alpha-beta-bot"], 0, "active\n")
    fake.on(["systemctl", "--user", "is-active", "alpha-beta-watchdog"], 3, "inactive\n")
    root = tmp_path / "alpha_beta_bot_v2_daily"
    root.mkdir()
    checks = [c for c in op.run_checks("trading-bot", root, {}, {}) if c["kind"] == "service"]
    assert [(c["target"], c["source"], c["status"]) for c in checks] == [
        ("alpha-beta-bot", "guessed", "ok"), ("alpha-beta-watchdog", "guessed", "unknown")]
    assert "unverified" in checks[1]["detail"]


def test_guessed_no_match_is_unverified_not_down(fake, tmp_path):
    fake.on(["systemctl"], 0, "")
    root = tmp_path / "demo-hub"
    root.mkdir()
    [c] = [c for c in op.run_checks("web-app", root, {}, {}) if c["kind"] == "service"]
    assert c["status"] == "unknown" and "unverified" in c["detail"]


def test_no_guessing_for_workspace(fake, tmp_path):
    assert op.run_checks("workspace", tmp_path, {}, {}) == []


def test_profile_checks(fake, tmp_path):
    fake.on(["systemctl", "--user", "is-active", "webapp-dashboard"], 0, "active\n")
    fake.on(["systemctl", "--user", "is-active", "broken"], 3, "failed\n")
    fake.on(["curl"], 0, '{"ok":true,"boot":"x"}')
    fake.on(["ss"], 0, 'LISTEN 0 50 *:4002 *:* users:(("java",pid=1,fd=2))\n')
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/code_recs.md").write_text("- [OPEN] a\n- [DONE] b\n- [OPEN] c\n", encoding="utf-8")
    (tmp_path / "logs/bot.log").write_text("x", encoding="utf-8")
    os.utime(tmp_path / "logs/bot.log", (1, 1))
    (tmp_path / "state.json").write_text(json.dumps({"acct": {"equity": 123.45}}), encoding="utf-8")
    profile = {
        "services": [{"unit": "webapp-dashboard"}, {"unit": "broken"}],
        "health": [{"url": "http://localhost:8080/api/health", "expect": '"ok":true'}],
        "ports": [{"port": 4002, "owner": "java"}, {"port": 5999}],
        "queues": [{"name": "code recs", "file": "logs/code_recs.md", "count": r"\[OPEN\]"}],
        "logs": [{"path": "logs/bot.log", "max_age_h": 24}],
        "metrics": [{"name": "equity", "file": "state.json", "key": "acct.equity"},
                    {"name": "gone", "file": "nope.json", "key": "x"}]}
    checks = op.run_checks("web-app", tmp_path, profile, {})
    assert [(c["kind"], c["target"], c["status"]) for c in checks] == [
        ("service", "webapp-dashboard", "ok"), ("service", "broken", "fail"),
        ("health", "http://localhost:8080/api/health", "ok"),
        ("port", "4002", "ok"), ("port", "5999", "fail"),
        ("queue", "code recs", "ok"), ("log", "logs/bot.log", "warn"),
        ("metric", "equity", "ok"), ("metric", "gone", "unknown")]
    assert [c for c in checks if c["kind"] == "queue"][0]["count"] == 2
    assert [c for c in checks if c["target"] == "equity"][0]["detail"] == "123.45"


def test_remote_host_uses_ssh(fake, monkeypatch):
    monkeypatch.setattr(lib.socket, "gethostname", lambda: "HOST-B")
    fake.on(["ssh"], 0, "active\n")
    ids = {"hosts": {"hosta": {"aliases": ["hosta"], "ssh": "ubuntu"}}}
    [c] = op.run_checks("workspace", "/nonexistent",
                        {"services": [{"unit": "webapp-dashboard", "host": "hosta"}]}, ids)
    assert c["status"] == "ok"
    assert fake.calls[-1][:6] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "ubuntu"]
    assert fake.calls[-1][6] == "systemctl --user is-active webapp-dashboard"


def test_freshness_default_for_trading(fake, tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state/pos.json").write_text("{}", encoding="utf-8")
    os.utime(tmp_path / "state/pos.json", (1, 1))
    fake.on(["systemctl"], 0, "")
    [f] = [c for c in op.run_checks("trading-bot", tmp_path, {}, {}) if c["kind"] == "freshness"]
    assert (f["target"], f["status"]) == ("state/pos.json", "warn")
