# ~/.claude/tools/session/tests/test_ripple.py
"""/ripple hooks: watermark staleness for /preflight, un-rippled seam changes for /sync, Profile validation."""
import datetime as dt
import json
import subprocess

import close as cl
import open as op
import ripplemap as rm
from conftest import SAMPLE_HANDOFF, commit, sh

MAP = """# DATA_CONSUMERS.md

## Sweep watermark (last-swept commit per repo)

| Repo | Last-swept commit | Date | Swept by |
|---|---|---|---|
| alice/demo-proj | `{sha}` | {date} | alice |
| alice/other-repo (box `/srv/other`) | `abc1234` | 2026-10-20 | — |
| hermes/ (in-repo) | *never swept* | — | — |

## HTTP endpoints

| Producer | Seam | Consumers |
|---|---|---|
| api | `/x` | `deadbee` 2026-01-01 |
"""


def _sha(repo, rev="HEAD"):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", rev], capture_output=True, text=True, check=False,
                          encoding="utf-8").stdout.strip()


def _origin_here(repo):
    sh("git", "update-ref", "refs/remotes/origin/main", "HEAD", cwd=repo)
    sh("git", "branch", "--set-upstream-to=origin/main", cwd=repo)


def _write_map(repo, sha, date, commit_it=True):
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs/DATA_CONSUMERS.md").write_text(MAP.format(sha=sha, date=date), encoding="utf-8")
    if commit_it:
        sh("git", "add", "docs", cwd=repo)
        sh("git", "commit", "-qm", "map", cwd=repo)


def _handoff(vault, profile, updated="2026-09-27T20:49Z"):
    (vault / "handoffs").mkdir(exist_ok=True)
    text = SAMPLE_HANDOFF.replace('{"gh": "alice/demo-proj", "services": [{"unit": "demo", "scope": "user"}]}',
                                  json.dumps(profile)).replace("updated: 2026-09-27T20:49Z", f"updated: {updated}")
    p = vault / "handoffs/alice-demo-proj.md"
    p.write_text(text, encoding="utf-8")
    return p


# --- validate --------------------------------------------------------------------------------------

def test_validate_absent_and_good():
    assert rm.validate({}) is None
    assert rm.validate({"ripple": {"map": "docs/x.md", "branch": "main", "seam_paths": ["a/*"],
                                   "clones": {"o/r": "~/r"}, "partners": "memory/partners.md"}}) is None


def test_validate_reports_first_problem():
    assert rm.validate({"ripple": []}) == "ripple is not an object"
    assert rm.validate({"ripple": {"map": 3}}) == "ripple.map is not a string"
    assert rm.validate({"ripple": {"seam_paths": "a/*"}}) == "ripple.seam_paths is not a list of strings"
    assert rm.validate({"ripple": {"clones": {"o/r": 1}}}) == "ripple.clones is not an object of strings"


def test_validate_seam_label_must_name_a_clone():
    # a typo in "<clones key>:<glob>" used to be skipped silently, so that seam was never checked
    ok = {"clones": {"deepdesk": "~/dd"}, "seam_paths": ["deepdesk:src/*.py", "app/*.py"]}
    assert rm.validate({"ripple": ok}) is None
    bad = {"clones": {"deepdesk": "~/dd"}, "seam_paths": ["deepdsk:src/*.py"]}
    assert rm.validate({"ripple": bad}) == "ripple.seam_paths: 'deepdsk:' names no ripple.clones entry"


# --- watermark parsing ------------------------------------------------------------------------------

def test_parse_watermarks_reads_only_the_watermark_table():
    rows = rm.parse_watermarks(MAP.format(sha="1234567", date="2026-08-18"))
    assert [r["repo"] for r in rows] == ["alice/demo-proj", "alice/other-repo", "hermes/"]
    assert rows[0] == {"repo": "alice/demo-proj", "sha": "1234567", "date": "2026-08-18", "swept_by": "alice"}
    assert rows[1]["swept_by"] is None and rows[2]["sha"] is None and rows[2]["date"] is None


def test_parse_watermarks_without_section_is_none():
    assert rm.parse_watermarks("# map\n\n| a | b |\n") is None


# --- /preflight: watermark_block ---------------------------------------------------------------------

def test_no_map_is_silent(repo):
    assert rm.watermark_block(repo, {}) is None


def test_stale_watermark_counts_unswept_commits(repo):
    _write_map(repo, _sha(repo), "2026-08-18")
    commit(repo, "after 1")
    _origin_here(repo)
    b = rm.watermark_block(repo, {}, today=dt.date(2026, 11, 1))
    me = b["repos"][0]
    assert b["stale"] is True and b["oldest_days"] == 75 and b["never_swept"] == ["hermes/"]
    assert me["age_days"] == 75 and me["unswept"] == 2 and me["stale"] is True  # the map commit + "after 1"
    assert b["repos"][1]["unswept"] is None  # no local clone of alice/other-repo: unknown, never 0


def test_fresh_watermark_is_not_stale(repo):
    _write_map(repo, _sha(repo), "2026-10-30")
    text = (repo / "docs/DATA_CONSUMERS.md").read_text(encoding="utf-8")
    (repo / "docs/DATA_CONSUMERS.md").write_text(text.replace("| hermes/ (in-repo) | *never swept* | — | — |\n", ""),
                                                 encoding="utf-8")
    sh("git", "commit", "-qam", "drop hermes row", cwd=repo)
    _origin_here(repo)
    b = rm.watermark_block(repo, {}, today=dt.date(2026, 11, 1))
    assert [r["stale"] for r in b["repos"]] == [False, False] and b["stale"] is False


def test_map_is_read_from_the_upstream_tip_not_the_local_file(repo):
    _write_map(repo, _sha(repo), "2026-08-18")
    _origin_here(repo)
    _write_map(repo, "fffffff", "2026-10-31", commit_it=False)  # a local edit the services do not run
    b = rm.watermark_block(repo, {}, today=dt.date(2026, 11, 1))
    assert b["source"] == "origin/main" and b["repos"][0]["date"] == "2026-08-18"


def test_map_without_upstream_falls_back_to_the_file(repo):
    _write_map(repo, _sha(repo), "2026-08-18")
    b = rm.watermark_block(repo, {}, today=dt.date(2026, 11, 1))
    assert b["source"] == "local file" and b["repos"][0]["unswept"] is None


def test_map_without_watermark_rows_is_stale(repo):
    (repo / "docs").mkdir()
    (repo / "docs/DATA_CONSUMERS.md").write_text("# map\n", encoding="utf-8")
    b = rm.watermark_block(repo, {})
    assert b["stale"] is True and b["reason"] == "no sweep watermark rows"


def test_profile_map_path_and_clone(repo, tmp_path):
    other = tmp_path / "other"
    sh("git", "clone", "-q", str(repo), str(other))
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes/map.md").write_text(MAP.format(sha=_sha(repo), date="2026-08-18"), encoding="utf-8")
    prof = {"ripple": {"map": str(tmp_path / "notes/map.md"), "clones": {"alice/other-repo": str(other)}}}
    b = rm.watermark_block(repo, prof, today=dt.date(2026, 11, 1))
    assert b["source"] == "local file"  # the map is not in a repo
    assert b["repos"][1]["unswept"] is None  # abc1234 is not a commit in that clone: unknown


def test_ripple_branch_applies_to_the_project_not_partner_clones(repo, tmp_path):
    other = tmp_path / "other"
    sh("git", "clone", "-q", str(repo), str(other))  # a partner clone tracking origin/main: no feature/x there
    _write_map(repo, _sha(repo), "2026-08-18", commit_it=False)
    path = repo / "docs/DATA_CONSUMERS.md"
    path.write_text(path.read_text(encoding="utf-8").replace("abc1234", _sha(other)), encoding="utf-8")
    sh("git", "add", "docs", cwd=repo)
    sh("git", "commit", "-qm", "map", cwd=repo)
    sh("git", "update-ref", "refs/remotes/origin/feature/x", "HEAD", cwd=repo)  # the services run feature/x
    prof = {"ripple": {"branch": "feature/x", "clones": {"alice/other-repo": str(other)}}}
    b = rm.watermark_block(repo, prof, today=dt.date(2026, 11, 1))
    assert b["repos"][0]["unswept"] == 1 and b["repos"][1]["unswept"] == 0  # was None before: a silent unknown
    assert "error" not in b["repos"][0] and "error" not in b["repos"][1]


def test_wrong_ripple_branch_is_an_error_not_a_silent_unknown(repo):
    _write_map(repo, _sha(repo), "2026-08-18")
    _origin_here(repo)
    b = rm.watermark_block(repo, {"ripple": {"branch": "nope"}}, today=dt.date(2026, 11, 1))
    assert b["repos"][0]["unswept"] is None and b["repos"][0]["error"] == "origin/nope not in clone"


def test_bad_profile_is_an_error_not_a_crash(repo):
    assert rm.watermark_block(repo, {"ripple": "x"}) == {"error": "ripple is not an object", "stale": False}


def test_preflight_collect_includes_ripple_only_with_a_map(repo, vault, fake):
    _handoff(vault, {})
    assert "ripple" not in op.collect(repo)
    _write_map(repo, _sha(repo), "2026-08-18")
    assert op.collect(repo)["ripple"]["stale"] is True


# --- /sync: seams_block ------------------------------------------------------------------------------

def test_no_seam_paths_is_silent(repo):
    assert rm.seams_block(repo, {}, "2026-09-27T20:49Z", "alice-demo-proj") is None


def test_dirty_and_committed_seam_files_are_touched(repo, vault):
    (repo / "prompts").mkdir()
    (repo / "prompts/brief.txt").write_text("a", encoding="utf-8")
    sh("git", "add", "prompts", cwd=repo)
    sh("git", "commit", "-qm", "prompt", cwd=repo)
    (repo / "schema.sql").write_text("x", encoding="utf-8")  # untracked, dirty
    (repo / "README.md").write_text("x", encoding="utf-8")  # not a seam
    prof = {"ripple": {"seam_paths": ["prompts/*", "*.sql"]}}
    s = rm.seams_block(repo, prof, "2020-01-01T00:00Z", "alice-demo-proj")
    assert s == {"touched": ["prompts/brief.txt", "schema.sql"], "rippled": False, "ripple_at": None}


def test_modified_tracked_file_keeps_its_full_name(repo, vault):
    (repo / "f0.txt").write_text("changed", encoding="utf-8")  # the first porcelain line: " M f0.txt"
    s = rm.seams_block(repo, {"ripple": {"seam_paths": ["f0.txt"]}}, None, "alice-demo-proj")
    assert s["touched"] == ["f0.txt"]


def test_commits_before_the_last_sync_do_not_count(repo, vault):
    (repo / "prompts").mkdir()
    (repo / "prompts/brief.txt").write_text("a", encoding="utf-8")
    sh("git", "add", "prompts", cwd=repo)
    sh("git", "commit", "-qm", "prompt", cwd=repo)
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ")
    assert rm.seams_block(repo, {"ripple": {"seam_paths": ["prompts/*"]}}, future, "alice-demo-proj")["touched"] == []


def test_ripple_stamp_after_last_sync_marks_rippled(repo, vault):
    prof = {"ripple": {"seam_paths": ["*.sql"]}}
    rm.mark_rippled("alice-demo-proj", now=dt.datetime(2026, 9, 27, 18, 0, tzinfo=dt.UTC))
    assert rm.seams_block(repo, prof, "2026-09-27T20:49Z", "alice-demo-proj")["rippled"] is False  # before the sync
    rm.mark_rippled("alice-demo-proj", now=dt.datetime(2026, 9, 28, 9, 0, tzinfo=dt.UTC))
    s = rm.seams_block(repo, prof, "2026-09-27T20:49Z", "alice-demo-proj")
    assert s["rippled"] is True and s["ripple_at"] == "2026-09-28T09:00:00Z"


def test_clone_prefixed_seam_paths(repo, vault, tmp_path):
    other = tmp_path / "other"
    sh("git", "clone", "-q", str(repo), str(other))
    (other / "gather.py").write_text("x", encoding="utf-8")
    prof = {"ripple": {"clones": {"alice/other": str(other)},
                       "seam_paths": ["alice/other:gather*.py"]}}
    assert rm.seams_block(repo, prof, None, "alice-demo-proj")["touched"] == ["alice/other:gather.py"]
    prof["ripple"]["clones"]["alice/other"] = str(tmp_path / "not-cloned-here")  # a clone missing on this machine
    assert rm.seams_block(repo, prof, None, "alice-demo-proj")["touched"] == []


def test_sync_collect_and_cli(repo, vault, fake, capsys):
    _handoff(vault, {"ripple": {"seam_paths": ["*.sql"]}})
    (repo / "schema.sql").write_text("x", encoding="utf-8")
    assert cl.collect_close(repo)["seams"]["touched"] == ["schema.sql"]
    assert cl.main(["--cwd", str(repo), "ripple-done"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert cl.collect_close(repo)["seams"]["rippled"] is True


def test_sync_collect_without_ripple_key_has_null_seams(repo, vault, fake):
    _handoff(vault, {})
    assert cl.collect_close(repo)["seams"] is None


def test_check_profile_reports_ripple_error(vault):
    p = _handoff(vault, {"ripple": {"seam_paths": "x"}})
    assert cl.check_profile(p) == {"profile_error": None, "ripple_error": "ripple.seam_paths is not a list of strings"}
    p = _handoff(vault, {"ripple": {"seam_paths": ["*.sql"]}})
    assert cl.check_profile(p) == {"profile_error": None, "ripple_error": None}
    p = _handoff(vault, {})
    assert cl.check_profile(p) == {"profile_error": None}  # no ripple key: the one-field answer is unchanged
