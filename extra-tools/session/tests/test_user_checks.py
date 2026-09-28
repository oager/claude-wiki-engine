import json
import sys

import open as op

NOBODY = {"names": [], "emails": [], "hosts": {}}
CHARTS = {"kind": "command", "name": "charts", "cmd": [sys.executable, "<vault>/skills/q/check.py", "--json"],
          "fields": {"count": "queued", "oldest_h": "oldest_hours", "label": "oldest_channel"}, "loud_after_h": 24}


def _script(vault, payload, rc=1):
    s = vault / "skills/q/check.py"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.write_text(f"import json,sys\nprint(json.dumps({payload!r}))\nsys.exit({rc})\n", encoding="utf-8")


def test_command_check_loud(vault):
    _script(vault, {"queued": 15, "oldest_hours": 97.3, "oldest_channel": "chan-a"})
    [c] = op.user_checks({"checks": [CHARTS]}, NOBODY)
    assert (c["source"], c["target"], c["loud"], c["count"], c["status"]) == ("user", "charts", True, 15, "warn")
    assert "chan-a" in c["detail"]


def test_command_check_young_queue_is_quiet(vault):
    _script(vault, {"queued": 2, "oldest_hours": 3.0})
    [c] = op.user_checks({"checks": [CHARTS]}, NOBODY)
    assert (c["loud"], c["status"]) == (False, "ok")


def test_command_check_empty(vault):
    _script(vault, {"queued": 0}, rc=0)
    [c] = op.user_checks({"checks": [CHARTS]}, NOBODY)
    assert (c["loud"], c["status"], c["count"]) == (False, "ok", 0)


def test_command_check_timeout_is_unknown(vault, fake):
    fake.on([sys.executable], 124, "", "timeout after 8s")
    [c] = op.user_checks({"checks": [CHARTS]}, NOBODY)
    assert (c["status"], c["loud"]) == ("unknown", False)


def test_command_check_not_json_is_unknown(vault, fake):
    fake.on([sys.executable], 0, "hello")
    [c] = op.user_checks({"checks": [CHARTS]}, NOBODY)
    assert c["status"] == "unknown" and "not JSON" in c["detail"]


def test_queue_user_check_loud_over(vault):
    (vault / "state").mkdir()
    (vault / "state/bf.json").write_text(json.dumps({"pending": [{"status": "pending"}, {"status": "opened"}]}),
                                         encoding="utf-8")
    q = {"kind": "queue", "name": "bf", "file": "<vault>/state/bf.json", "count": r'"status":\s*"pending"'}
    [c] = op.user_checks({"checks": [q]}, NOBODY)
    assert (c["source"], c["count"], c["loud"]) == ("user", 1, True)
    [c] = op.user_checks({"checks": [{**q, "loud_over": 1}]}, NOBODY)
    assert c["loud"] is False


def test_unknown_kind(vault):
    [c] = op.user_checks({"checks": [{"kind": "telepathy", "name": "x"}]}, NOBODY)
    assert (c["status"], c["source"], c["loud"]) == ("unknown", "user", False)


def test_collect_has_user_block_and_no_fleet(vault, repo, fake):
    g = op.collect(repo)["global"]
    assert "fleet" not in g and g["user_checks"] == [] and g["user"]["exists"] is False
