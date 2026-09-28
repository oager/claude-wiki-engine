"""Regression tests for install.py. Stdlib only -- run with:

    python -m unittest discover tests
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_installer():
    """Load install.py fresh. A new module object also gives each test a clean _SNAPSHOTTED set."""
    spec = importlib.util.spec_from_file_location("wiki_installer", REPO / "install.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MergeHookBackupTest(unittest.TestCase):
    """settings.json .wikibak must hold true pre-install state, not a mid-install checkpoint."""

    ORIGINAL = {"model": "opus", "permissions": {"allow": ["Bash"]}}

    def setUp(self):
        self.installer = load_installer()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.settings = self.tmp / "settings.json"
        self.settings.write_text(json.dumps(self.ORIGINAL, indent=2) + "\n", encoding="utf-8")

    def wire_two_hooks(self):
        """Mirrors a real run: install.py wires more than one hook per invocation."""
        self.installer.merge_hook(self.settings, "node /x/wiki-index.cjs", "PostToolUse", "Write|Edit")
        self.installer.merge_hook(self.settings, "node /x/wiki-sync-nudge.cjs", "Stop", "")

    def backup(self):
        return json.loads((self.tmp / "settings.json.wikibak").read_text(encoding="utf-8"))

    def live(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def test_backup_is_pre_install_state_after_wiring_two_hooks(self):
        # Regression: the second merge_hook used to overwrite .wikibak with settings that already
        # contained the first hook, so the backup could never restore the original.
        self.wire_two_hooks()
        self.assertEqual(self.backup(), self.ORIGINAL)

    def test_repeat_call_does_not_clobber_backup(self):
        self.wire_two_hooks()
        self.installer.merge_hook(self.settings, "node /x/wiki-index.cjs", "PostToolUse", "Write|Edit")
        self.assertEqual(self.backup(), self.ORIGINAL)

    def test_both_hooks_are_wired(self):
        self.wire_two_hooks()
        hooks = self.live()["hooks"]
        self.assertIn("PostToolUse", hooks)
        self.assertIn("Stop", hooks)

    def test_unrelated_settings_preserved(self):
        self.wire_two_hooks()
        live = self.live()
        self.assertEqual(live["model"], self.ORIGINAL["model"])
        self.assertEqual(live["permissions"], self.ORIGINAL["permissions"])


class SessionExtrasTest(unittest.TestCase):
    def setUp(self):
        self.inst = load_installer()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def cfg(self, **kw):
        base = {"dry_run": False, "config_base": self.tmp, "mode": "copy", "memory": self.tmp / "memory",
                "content_repo": None, "claude_md": True, "skills": [], "force_skills": False, "hooks": False,
                "extra_skills": ["preflight", "sync"], "no_pull": True, "yes": True}
        return {**base, **kw}

    def test_preflight_brings_tools_templates_user_file_and_block(self):
        self.inst.build_plan(self.cfg()).execute()
        self.assertTrue((self.tmp / "tools/session/open.py").is_file())
        self.assertTrue((self.tmp / "tools/session/.engine").is_file())
        self.assertTrue((self.tmp / "handoffs/_TEMPLATE.md").is_file())
        self.assertTrue((self.tmp / "handoffs/_USER.md").is_file())
        self.assertIn(self.inst.SESSION_START, (self.tmp / "CLAUDE.md").read_text(encoding="utf-8"))

    def test_existing_user_file_is_kept(self):
        (self.tmp / "handoffs").mkdir()
        (self.tmp / "handoffs/_USER.md").write_text("mine", encoding="utf-8")
        self.inst.build_plan(self.cfg()).execute()
        self.assertEqual((self.tmp / "handoffs/_USER.md").read_text(encoding="utf-8"), "mine")

    def test_foreign_tools_session_is_not_overwritten(self):
        (self.tmp / "tools/session").mkdir(parents=True)
        (self.tmp / "tools/session/open.py").write_text("mine", encoding="utf-8")
        self.inst.build_plan(self.cfg()).execute()
        self.assertEqual((self.tmp / "tools/session/open.py").read_text(encoding="utf-8"), "mine")

    def test_session_block_is_idempotent_and_keeps_wiki_block(self):
        cmd = self.tmp / "CLAUDE.md"
        cmd.write_text("<!-- wiki-engine:start -->\nw\n<!-- wiki-engine:end -->\n", encoding="utf-8")
        for _ in range(2):
            self.inst.inject_block(cmd, "s", self.inst.SESSION_START, self.inst.SESSION_END)
        t = cmd.read_text(encoding="utf-8")
        self.assertEqual(t.count(self.inst.SESSION_START), 1)
        self.assertIn("<!-- wiki-engine:start -->", t)

    def test_update_replaces_tagged_and_skips_untagged(self):
        s = self.tmp / "skills"
        (s / "preflight").mkdir(parents=True)
        (s / "sync").mkdir()
        (s / "preflight/SKILL.md").write_text("---\nname: preflight\nsource: claude-wiki-engine\n---\nold\n",
                                              encoding="utf-8")
        (s / "sync/SKILL.md").write_text("---\nname: sync\n---\nmine\n", encoding="utf-8")
        self.inst.do_update(self.cfg(extra_skills=[]))
        self.assertNotIn("\nold\n", (s / "preflight/SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("mine", (s / "sync/SKILL.md").read_text(encoding="utf-8"))
        # versioned backup lives under <config_base>/.wikibak/, never under skills/ (a
        # skills/<name>.wikibak/ dir with a SKILL.md could be loaded as a duplicate skill)
        baks = list((self.tmp / ".wikibak" / "skills").glob("preflight-*"))
        self.assertEqual(len(baks), 1)
        self.assertIn("old", (baks[0] / "SKILL.md").read_text(encoding="utf-8"))
        self.assertFalse(list(s.glob("*.wikibak*")))

    def test_update_backups_are_versioned_across_multiple_runs(self):
        self.inst.build_plan(self.cfg(extra_skills=["preflight"])).execute()
        skill_md = self.tmp / "skills/preflight/SKILL.md"
        skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nEDIT1\n", encoding="utf-8")
        self.inst.do_update(self.cfg(extra_skills=[]))
        skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nEDIT2\n", encoding="utf-8")
        self.inst.do_update(self.cfg(extra_skills=[]))
        baks = sorted((self.tmp / ".wikibak" / "skills").glob("preflight-*"))
        self.assertEqual(len(baks), 2)
        contents = [(b / "SKILL.md").read_text(encoding="utf-8") for b in baks]
        self.assertTrue(any("EDIT1" in c and "EDIT2" not in c for c in contents))
        self.assertTrue(any("EDIT2" in c for c in contents))
        self.assertFalse(list((self.tmp / "skills").glob("*.wikibak*")))

    def test_update_skips_symlinked_extra(self):
        s = self.tmp / "skills"
        s.mkdir(parents=True)
        target = self.inst.ENGINE / "extra-skills" / "preflight"
        link = s / "preflight"
        link.symlink_to(target, target_is_directory=True)
        self.inst.do_update(self.cfg(extra_skills=[]))  # must not crash (rmtree-on-symlink)
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), target.resolve())

    def test_update_skips_symlinked_core_skill(self):
        s = self.tmp / "skills"
        s.mkdir(parents=True)
        target = self.inst.ENGINE / "skills" / "wiki-ingest"
        link = s / "wiki-ingest"
        link.symlink_to(target, target_is_directory=True)
        self.inst.do_update(self.cfg(skills=["wiki-ingest"], extra_skills=[]))  # must not crash
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), target.resolve())

    def test_update_aborts_without_confirm_when_not_yes(self):
        s = self.tmp / "skills"
        (s / "preflight").mkdir(parents=True)
        (s / "preflight/SKILL.md").write_text("---\nsource: claude-wiki-engine\n---\nSENTINEL_UNCONFIRMED\n",
                                              encoding="utf-8")
        self.inst.confirm = lambda *a, **kw: False
        self.inst.do_update(self.cfg(extra_skills=[], yes=False))
        self.assertIn("SENTINEL_UNCONFIRMED", (s / "preflight/SKILL.md").read_text(encoding="utf-8"))

    def test_update_proceeds_when_confirmed(self):
        s = self.tmp / "skills"
        (s / "preflight").mkdir(parents=True)
        (s / "preflight/SKILL.md").write_text("---\nsource: claude-wiki-engine\n---\nSENTINEL_CONFIRMED\n",
                                              encoding="utf-8")
        self.inst.confirm = lambda *a, **kw: True
        self.inst.do_update(self.cfg(extra_skills=[], yes=False))
        self.assertNotIn("SENTINEL_CONFIRMED", (s / "preflight/SKILL.md").read_text(encoding="utf-8"))

    def test_update_with_claude_md_false_leaves_it_untouched(self):
        cmd = self.tmp / "CLAUDE.md"
        cmd.write_text("existing\n", encoding="utf-8")
        self.inst.do_update(self.cfg(claude_md=False, extra_skills=[]))
        self.assertEqual(cmd.read_text(encoding="utf-8"), "existing\n")

    def test_is_engine_skill_requires_frontmatter(self):
        d = self.tmp / "x"
        d.mkdir()
        (d / "SKILL.md").write_text("# my skill\nsee source: claude-wiki-engine\n", encoding="utf-8")
        self.assertFalse(self.inst.is_engine_skill(d))

    def test_legacy_untagged_engine_copies_are_recognized(self):
        # The 701848e installer copied preflight/sync without the source tag; their exact bytes identify them.
        for name in ("preflight", "sync"):
            data = (REPO / "tests" / "fixtures" / f"legacy-701848e-{name}-SKILL.md").read_bytes()
            self.assertIn(hashlib.sha256(data).hexdigest(), self.inst.LEGACY_ENGINE_SKILL_SHA256)
            d = self.tmp / name
            d.mkdir()
            (d / "SKILL.md").write_bytes(data)
            self.assertTrue(self.inst.is_engine_skill(d))
            (d / "SKILL.md").write_bytes(data + b"\nlocal edit\n")
            self.assertFalse(self.inst.is_engine_skill(d))

    def test_update_replaces_legacy_untagged_copy(self):
        d = self.tmp / "skills/sync"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_bytes((REPO / "tests/fixtures/legacy-701848e-sync-SKILL.md").read_bytes())
        self.inst.do_update(self.cfg(extra_skills=[]))
        self.assertIn(self.inst.ENGINE_TAG, (d / "SKILL.md").read_text(encoding="utf-8"))
        self.assertTrue((self.tmp / "tools/session/open.py").is_file())

    def test_non_default_config_base_warns_about_claude_vault(self):
        plan = self.inst.build_plan(self.cfg(dry_run=True))
        notes = [n for n in plan.notes if "CLAUDE_VAULT" in n]
        self.assertEqual(len(notes), 1)
        # CLAUDE_VAULT alone cannot fix it: the skills call ~/.claude/tools/session by that fixed path.
        self.assertNotIn("set CLAUDE_VAULT to", notes[0])
        for part in ("~/.claude/tools/session", str(self.tmp / "tools" / "session"), "skills/preflight",
                     "skills/sync", "vault only"):
            self.assertIn(part, notes[0])
        plan = self.inst.build_plan(self.cfg(dry_run=True, extra_skills=["karpathy-guidelines"]))
        self.assertFalse(any("CLAUDE_VAULT" in n for n in plan.notes))

    def test_default_config_base_does_not_warn(self):
        self.inst.home_claude = lambda: self.tmp  # this test's config_base plays ~/.claude
        plan = self.inst.build_plan(self.cfg(dry_run=True))
        self.assertFalse(any("CLAUDE_VAULT" in n for n in plan.notes))

    def test_crlf_claude_md_survives_repeated_injects(self):
        cmd = self.tmp / "CLAUDE.md"
        cmd.write_bytes(b"top\r\n<!-- wiki-engine:start -->\r\nw\r\n<!-- wiki-engine:end -->\r\nbottom\r\n")

        def run_sequence():
            self.inst.inject_block(cmd, "s\n", self.inst.SESSION_START, self.inst.SESSION_END)
            self.inst.inject_block(cmd, "s\n", self.inst.SESSION_START, self.inst.SESSION_END)
            self.inst.inject_block(cmd, "w2")

        run_sequence()
        raw = cmd.read_bytes()
        self.assertNotIn(b"\r\r", raw)
        self.assertGreater(raw.count(b"\r\n"), 0)
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))  # every LF is part of a CRLF pair
        self.assertEqual(raw.count(self.inst.SESSION_START.encode()), 1)
        self.assertEqual(raw.count(b"<!-- wiki-engine:start -->"), 1)

        run_sequence()
        self.assertEqual(cmd.read_bytes(), raw)


USER_SYNC = "---\nname: sync\ndescription: my own end-of-day ritual\n---\nmine\n"


class ReviewFixesTest(unittest.TestCase):
    """PR #5 review: session wiring vs a user's own sync/preflight, template backups, core-skill updates."""

    def setUp(self):
        self.inst = load_installer()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.skills = self.tmp / "skills"

    def cfg(self, **kw):
        base = {"dry_run": False, "config_base": self.tmp, "mode": "copy", "memory": self.tmp / "memory",
                "content_repo": None, "claude_md": True, "skills": [], "force_skills": False, "hooks": False,
                "extra_skills": ["preflight", "sync"], "no_pull": True, "yes": True}
        return {**base, **kw}

    def update(self, **kw) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.inst.do_update(self.cfg(extra_skills=[], **kw))
        return out.getvalue()

    def own_sync(self):
        (self.skills / "sync").mkdir(parents=True)
        (self.skills / "sync/SKILL.md").write_text(USER_SYNC, encoding="utf-8")

    def claude_md(self) -> str:
        p = self.tmp / "CLAUDE.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def assert_session_not_wired(self):
        self.assertFalse((self.tmp / "tools/session").exists())
        self.assertNotIn(self.inst.SESSION_START, self.claude_md())
        self.assertEqual((self.skills / "sync/SKILL.md").read_text(encoding="utf-8"), USER_SYNC)

    # --- fix 1: never wire the session system to the user's own /sync or /preflight ---

    def test_install_with_own_sync_does_not_wire_session(self):
        self.own_sync()
        env = {**os.environ, "CLAUDE_DIR": str(self.tmp), "HOME": str(self.tmp / "home"),
               "USERPROFILE": str(self.tmp / "home")}
        r = subprocess.run([sys.executable, str(REPO / "install.py"), "--extras", "preflight,sync", "-y",
                            "--no-hooks"], env=env, capture_output=True, text=True, encoding="utf-8",
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_session_not_wired()
        # the non-conflicting engine skill is held back too: /preflight without its tools cannot run
        self.assertFalse((self.skills / "preflight").exists())
        notes = [ln for ln in r.stdout.splitlines() if "session handoff" in ln and "skills/sync" in ln]
        self.assertEqual(len(notes), 1, r.stdout)
        self.assertIn("as a whole", notes[0])
        self.assertIn("--extras preflight,sync", notes[0])

    def test_update_with_own_sync_does_not_wire_session(self):
        self.own_sync()
        (self.skills / "preflight").mkdir()
        shutil.copy2(self.inst.ENGINE / "extra-skills/preflight/SKILL.md", self.skills / "preflight/SKILL.md")
        out = self.update()
        self.assert_session_not_wired()
        self.assertIn("session handoff", out)
        self.assertIn("skills/sync", out)

    def test_install_with_own_preflight_does_not_wire_session(self):
        (self.skills / "preflight").mkdir(parents=True)
        (self.skills / "preflight/SKILL.md").write_text("---\nname: preflight\n---\nmine\n", encoding="utf-8")
        plan = self.inst.build_plan(self.cfg())
        plan.execute()
        self.assertFalse((self.tmp / "tools/session").exists())
        self.assertFalse((self.skills / "sync").exists())
        self.assertNotIn(self.inst.SESSION_START, self.claude_md())
        self.assertTrue(any("skills/preflight" in n and "as a whole" in n for n in plan.notes))

    def test_requesting_only_preflight_next_to_own_sync_skips_both(self):
        self.own_sync()
        plan = self.inst.build_plan(self.cfg(extra_skills=["preflight"]))
        plan.execute()
        self.assertFalse((self.skills / "preflight").exists())
        self.assert_session_not_wired()
        self.assertEqual(sum("session handoff" in n for n in plan.notes), 1)

    def test_force_skills_does_not_override_an_unrequested_own_sync(self):
        self.own_sync()
        self.inst.build_plan(self.cfg(extra_skills=["preflight"], force_skills=True)).execute()
        self.assertFalse((self.skills / "preflight").exists())
        self.assert_session_not_wired()

    def stale_setup(self, crlf: bool) -> bytes:
        """An earlier (buggy) install: engine preflight + the session block next to the user's own sync."""
        self.own_sync()
        (self.skills / "preflight").mkdir()
        shutil.copy2(self.inst.ENGINE / "extra-skills/preflight/SKILL.md", self.skills / "preflight/SKILL.md")
        eol = b"\r\n" if crlf else b"\n"
        original = eol.join([b"# mine", b"<!-- wiki-engine:start -->", b"w", b"<!-- wiki-engine:end -->", b""])
        cmd = self.tmp / "CLAUDE.md"
        cmd.write_bytes(original)
        self.inst.inject_block(cmd, "## Session handoff\nuse /sync\n", self.inst.SESSION_START,
                               self.inst.SESSION_END)
        self.assertIn(self.inst.SESSION_START.encode(), cmd.read_bytes())
        return original

    def test_update_with_conflict_removes_stale_session_block(self):
        for crlf in (False, True):
            with self.subTest(crlf=crlf):
                shutil.rmtree(self.skills, ignore_errors=True)
                original = self.stale_setup(crlf)
                out = self.update()
                # expected = the pre-inject bytes plus the (unrelated) wiki-block refresh --update always does
                expected = self.tmp / "expected.md"
                expected.write_bytes(original)
                self.inst.inject_block(expected, (self.inst.ENGINE / "claude-md/ingestion-policy.md")
                                       .read_text(encoding="utf-8"))
                self.assertEqual((self.tmp / "CLAUDE.md").read_bytes(), expected.read_bytes())
                self.assertIn("Removing the engine's session-handoff block", out)
                self.assertFalse((self.tmp / "tools/session").exists())

    def test_update_with_no_claude_md_keeps_stale_block(self):
        self.stale_setup(crlf=False)
        before = (self.tmp / "CLAUDE.md").read_bytes()
        self.update(claude_md=False)
        self.assertEqual((self.tmp / "CLAUDE.md").read_bytes(), before)

    def test_update_without_conflict_keeps_session_block(self):
        self.inst.build_plan(self.cfg()).execute()
        self.update()
        self.assertEqual(self.claude_md().count(self.inst.SESSION_START), 1)

    def test_remove_block_is_noop_without_block(self):
        cmd = self.tmp / "CLAUDE.md"
        cmd.write_bytes(b"a\r\nb\r\n")
        self.inst.remove_block(cmd, self.inst.SESSION_START, self.inst.SESSION_END)
        self.assertEqual(cmd.read_bytes(), b"a\r\nb\r\n")

    def test_force_skills_replacing_own_sync_does_wire_session(self):
        self.own_sync()
        self.inst.build_plan(self.cfg(force_skills=True)).execute()
        self.assertTrue(self.inst.is_engine_skill(self.skills / "sync"))
        self.assertTrue((self.tmp / "tools/session/open.py").is_file())
        self.assertIn(self.inst.SESSION_START, self.claude_md())

    def test_preflight_alone_still_gets_its_tools(self):
        # an ABSENT sync is not a conflict: /preflight needs tools/session to run at all
        self.inst.build_plan(self.cfg(extra_skills=["preflight"])).execute()
        self.assertTrue((self.tmp / "tools/session/open.py").is_file())

    # --- fix 2: --update must not silently overwrite an edited handoff template ---

    def test_update_backs_up_edited_handoff_template(self):
        self.inst.build_plan(self.cfg()).execute()
        tmpl = self.tmp / "handoffs/_TEMPLATE.md"
        engine = (self.inst.ENGINE / "templates/handoffs/_TEMPLATE.md").read_bytes()
        tmpl.write_bytes(engine + b"\nMY EDIT\n")
        self.update()
        self.assertEqual(tmpl.read_bytes(), engine)
        baks = list((self.tmp / ".wikibak/handoffs").glob("_TEMPLATE.md-*"))
        self.assertEqual(len(baks), 1)
        self.assertIn(b"MY EDIT", baks[0].read_bytes())

    def test_update_with_unchanged_templates_makes_no_backup(self):
        self.inst.build_plan(self.cfg()).execute()
        self.update()
        self.assertFalse((self.tmp / ".wikibak/handoffs").exists())

    def test_user_file_is_never_touched_by_update(self):
        self.inst.build_plan(self.cfg()).execute()
        (self.tmp / "handoffs/_USER.md").write_text("mine", encoding="utf-8")
        self.update()
        self.assertEqual((self.tmp / "handoffs/_USER.md").read_text(encoding="utf-8"), "mine")

    # --- fix 3: --update replaces only engine-owned core skills, backing up edited ones ---

    def test_engine_core_skills_are_tagged(self):
        for name in self.inst.SKILL_SETS["core"]:
            self.assertTrue(self.inst.is_engine_skill(self.inst.ENGINE / "skills" / name), name)

    def test_update_skips_users_own_core_skill(self):
        d = self.skills / "wiki-ingest"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: wiki-ingest\n---\nmy own ingest\n", encoding="utf-8")
        out = self.update(skills=["wiki-ingest"])
        self.assertIn("my own ingest", (d / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("skip 'wiki-ingest'", out)
        self.assertFalse((self.tmp / ".wikibak/skills").exists())

    def test_update_backs_up_edited_engine_core_skill(self):
        self.inst.build_plan(self.cfg(skills=["doc-review"], extra_skills=[])).execute()
        md = self.skills / "doc-review/SKILL.md"
        md.write_text(md.read_text(encoding="utf-8") + "\nMY TWEAK\n", encoding="utf-8")
        self.update(skills=["doc-review"])
        self.assertNotIn("MY TWEAK", md.read_text(encoding="utf-8"))
        baks = list((self.tmp / ".wikibak/skills").glob("doc-review-*"))
        self.assertEqual(len(baks), 1)
        self.assertIn("MY TWEAK", (baks[0] / "SKILL.md").read_text(encoding="utf-8"))

    def test_update_of_unchanged_core_skill_makes_no_backup(self):
        self.inst.build_plan(self.cfg(skills=["doc-review"], extra_skills=[])).execute()
        self.update(skills=["doc-review"])
        self.assertFalse((self.tmp / ".wikibak/skills").exists())

    def test_update_replaces_legacy_untagged_core_copy(self):
        # The previous engine version shipped core skills without the tag: exact bytes identify them.
        for name in self.inst.SKILL_SETS["core"]:
            src = (self.inst.ENGINE / "skills" / name / "SKILL.md").read_bytes()
            legacy = src.replace(self.inst.ENGINE_TAG.encode() + b"\n", b"", 1)
            self.assertNotEqual(legacy, src)
            self.assertIn(hashlib.sha256(legacy).hexdigest(), self.inst.LEGACY_ENGINE_SKILL_SHA256)
            d = self.skills / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_bytes(legacy)
        self.update(skills=self.inst.SKILL_SETS["core"])
        for name in self.inst.SKILL_SETS["core"]:
            self.assertTrue(self.inst.is_engine_skill(self.skills / name))
            self.assertIn(self.inst.ENGINE_TAG, (self.skills / name / "SKILL.md").read_text(encoding="utf-8"))

    def test_update_installs_missing_core_skill(self):
        self.update(skills=["wiki-sync"])
        self.assertTrue(self.inst.is_engine_skill(self.skills / "wiki-sync"))


if __name__ == "__main__":
    unittest.main()
