# ~/.claude/tools/session/tests/test_trim.py
import datetime as dt

import close as cl

DOC = """---
key: k
---
## Next up
1. x

## Last session
- **2026-09-27** — new entry
  continued line
- **2026-09-10** — old entry
- **2026-08-01/02** — older entry

## Standing notes
- keep me
"""


def test_trim_moves_old_entries(tmp_path):
    p = tmp_path / "k.md"
    p.write_text(DOC, encoding="utf-8")
    r = cl.trim(p, today=dt.date(2026, 9, 27))
    assert r["moved"] == 2 and r["over_100kb"] is False
    live = p.read_text(encoding="utf-8")
    arc = (tmp_path / "k.archive.md").read_text(encoding="utf-8")
    assert "new entry\n  continued line" in live and "keep me" in live
    assert "old entry" not in live and "older entry" not in live
    assert "old entry" in arc and "older entry" in arc and "archive: true" in arc


def test_trim_prepends_to_existing_archive(tmp_path):
    p = tmp_path / "k.md"
    p.write_text(DOC, encoding="utf-8")
    cl.trim(p, today=dt.date(2026, 9, 27))
    p.write_text(p.read_text(encoding="utf-8").replace("- **2026-09-27**", "- **2026-09-12** — mid entry\n- **2026-09-27**"), encoding="utf-8")
    r = cl.trim(p, today=dt.date(2026, 10, 1))
    assert r["moved"] == 1
    arc = (tmp_path / "k.archive.md").read_text(encoding="utf-8")
    assert arc.index("mid entry") < arc.index("old entry")
    assert arc.count("## Last session (archived)") == 1


def test_trim_nothing_old(tmp_path):
    p = tmp_path / "k.md"
    p.write_text(DOC, encoding="utf-8")
    assert cl.trim(p, today=dt.date(2026, 8, 1))["moved"] == 0
    assert not (tmp_path / "k.archive.md").exists()
    assert p.read_text(encoding="utf-8") == DOC


def test_trim_no_section(tmp_path):
    p = tmp_path / "k.md"
    p.write_text("## Next up\n1. x\n", encoding="utf-8")
    assert cl.trim(p)["moved"] == 0
