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
        # non-session extras: a tagged preflight next to an untagged sync is a session conflict (ReviewFixesTest)
        s = self.tmp / "skills"
        (s / "recap").mkdir(parents=True)
        (s / "ripple").mkdir()
        (s / "recap/SKILL.md").write_text("---\nname: recap\nsource: claude-wiki-engine\n---\nold\n",
                                          encoding="utf-8")
        (s / "ripple/SKILL.md").write_text("---\nname: ripple\n---\nmine\n", encoding="utf-8")
        self.inst.do_update(self.cfg(extra_skills=[]))
        self.assertNotIn("\nold\n", (s / "recap/SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("mine", (s / "ripple/SKILL.md").read_text(encoding="utf-8"))
        # versioned backup lives under <config_base>/.wikibak/, never under skills/ (a
        # skills/<name>.wikibak/ dir with a SKILL.md could be loaded as a duplicate skill)
        baks = list((self.tmp / ".wikibak" / "skills").glob("recap-*"))
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

    # --- round 2 ---

    def test_update_with_conflict_does_not_refresh_session_skills(self):
        # 701848e installed preflight without tools/session (its preflight did not need them) next to the
        # user's own sync. Refreshing it to today's preflight, which calls tools/session, would break it.
        self.own_sync()
        legacy = (REPO / "tests/fixtures/legacy-701848e-preflight-SKILL.md").read_bytes()
        (self.skills / "preflight").mkdir()
        (self.skills / "preflight/SKILL.md").write_bytes(legacy)
        out = self.update()
        self.assertEqual((self.skills / "preflight/SKILL.md").read_bytes(), legacy)
        self.assert_session_not_wired()
        self.assertFalse((self.tmp / ".wikibak/skills").exists())
        notes = [ln for ln in out.splitlines() if "session handoff" in ln]
        self.assertEqual(len(notes), 1, out)
        self.assertIn("preflight", notes[0])

    def test_update_without_conflict_still_refreshes_legacy_preflight(self):
        legacy = (REPO / "tests/fixtures/legacy-701848e-preflight-SKILL.md").read_bytes()
        (self.skills / "preflight").mkdir(parents=True)
        (self.skills / "preflight/SKILL.md").write_bytes(legacy)
        self.update()
        self.assertNotEqual((self.skills / "preflight/SKILL.md").read_bytes(), legacy)
        self.assertTrue((self.tmp / "tools/session/open.py").is_file())

    def misordered(self, crlf: bool = False) -> bytes:
        eol = "\r\n" if crlf else "\n"
        s, e = self.inst.SESSION_START, self.inst.SESSION_END
        return eol.join(["top", e, "middle", s, "bottom", ""]).encode()

    def assert_left_alone(self, fn, data: bytes):
        cmd = self.tmp / "CLAUDE.md"
        cmd.write_bytes(data)
        res = fn(cmd)  # must not raise
        self.assertEqual(cmd.read_bytes(), data)
        self.assertIsInstance(res, self.inst.Skipped)  # Plan.execute prints it instead of "[ok]"
        self.assertIn("left unchanged", res)

    def stray_start(self) -> bytes:
        # a prose mention / merge leftover of the start marker, user text, then the real block
        s, e = self.inst.SESSION_START, self.inst.SESSION_END
        return f"top\nsee {s} below\nUSER TEXT\n{s}\nold\n{e}\n".encode()

    def test_remove_block_leaves_extra_start_marker_alone(self):
        self.assert_left_alone(lambda c: self.inst.remove_block(c, self.inst.SESSION_START,
                                                                 self.inst.SESSION_END), self.stray_start())

    def test_inject_block_leaves_extra_start_marker_alone(self):
        self.assert_left_alone(lambda c: self.inst.inject_block(c, "new", self.inst.SESSION_START,
                                                                 self.inst.SESSION_END), self.stray_start())

    def test_inject_block_leaves_two_blocks_alone(self):
        s, e = self.inst.SESSION_START, self.inst.SESSION_END
        data = f"{s}\na\n{e}\nUSER TEXT\n{s}\nb\n{e}\n".encode()
        self.assert_left_alone(lambda c: self.inst.inject_block(c, "new", s, e), data)

    def test_broken_wiki_markers_plan_no_edit_step(self):
        cmd = self.tmp / "CLAUDE.md"
        cmd.write_text(f"x\n{self.inst.SENTINEL_END}\nmine\n{self.inst.SENTINEL_START}\n", encoding="utf-8")
        before = cmd.read_bytes()
        plan = self.inst.build_plan(self.cfg(extra_skills=[]))
        self.assertFalse(any("CLAUDE.md" in detail for _, detail, _ in plan.steps))
        self.assertTrue(any("left unchanged" in n and "CLAUDE.md" in n for n in plan.notes))
        out = self.update()
        self.assertNotIn("block refresh", out)
        self.assertIn("left unchanged", out)
        self.assertEqual(cmd.read_bytes(), before)

    def test_markers_broken_after_planning_print_warn_not_ok(self):
        cmd = self.tmp / "CLAUDE.md"
        cmd.write_text("x\n", encoding="utf-8")
        plan = self.inst.build_plan(self.cfg(extra_skills=[]))
        cmd.write_text(f"x\n{self.inst.SENTINEL_END}\n", encoding="utf-8")  # broken between plan and execute
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            plan.execute()
        self.assertIn("[warn]", out.getvalue())
        self.assertNotIn("[ok] edit CLAUDE.md", out.getvalue())

    def test_remove_block_leaves_misordered_markers_alone(self):
        for crlf in (False, True):
            self.assert_left_alone(lambda c: self.inst.remove_block(c, self.inst.SESSION_START,
                                                                     self.inst.SESSION_END),
                                   self.misordered(crlf))

    def test_inject_block_leaves_misordered_markers_alone(self):
        self.assert_left_alone(lambda c: self.inst.inject_block(c, "new", self.inst.SESSION_START,
                                                                 self.inst.SESSION_END), self.misordered())

    def test_inject_block_leaves_unpaired_start_alone(self):
        # appending a second block after an orphan start marker would, on the next inject, eat the text between
        data = f"a\n{self.inst.SESSION_START}\nkeep me\n".encode()
        self.assert_left_alone(lambda c: self.inst.inject_block(c, "new", self.inst.SESSION_START,
                                                                 self.inst.SESSION_END), data)

    def test_update_with_misordered_session_markers_does_not_crash(self):
        self.stale_setup(crlf=False)
        cmd = self.tmp / "CLAUDE.md"
        data = cmd.read_bytes().replace(self.inst.SESSION_START.encode(), b"@@S@@")
        data = data.replace(self.inst.SESSION_END.encode(), self.inst.SESSION_START.encode())
        data = data.replace(b"@@S@@", self.inst.SESSION_END.encode())
        cmd.write_bytes(data)
        self.update(claude_md=True)
        text = cmd.read_text(encoding="utf-8")
        self.assertIn("use /sync", text)  # nothing lost
        self.assertEqual(text.count(self.inst.SESSION_START), 1)

    def test_update_backs_up_tools_session_only_when_changed(self):
        self.inst.build_plan(self.cfg()).execute()
        tools = self.tmp / "tools/session"
        (tools / "__pycache__").mkdir(exist_ok=True)  # runtime bytecode is not a user change
        (tools / "__pycache__/lib.cpython-311.pyc").write_bytes(b"\0runtime")
        self.update()
        self.assertFalse((self.tmp / ".wikibak/tools").exists())
        (tools / "lib.py").write_text("# my local patch\n", encoding="utf-8")
        self.update()
        baks = list((self.tmp / ".wikibak/tools").glob("session-*"))
        self.assertEqual(len(baks), 1)
        self.assertIn("my local patch", (baks[0] / "lib.py").read_text(encoding="utf-8"))
        self.assertNotIn("my local patch", (tools / "lib.py").read_text(encoding="utf-8"))

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

    def test_all_engine_extras_are_tagged(self):
        for name in self.inst.EXTRA_SKILLS:
            self.assertTrue(self.inst.is_engine_skill(self.inst.ENGINE / "extra-skills" / name), name)

    def test_update_refreshes_untagged_committed_extra_versions(self):
        # An extra shipped untagged before this version and unchanged since: its latest untagged bytes = today's
        # minus the tag line. An extra edited after tagging (ripple, made generic) no longer derives that way; its
        # old untagged versions are still recognised by the hashes alone.
        others = []
        for name in sorted(set(self.inst.EXTRA_SKILLS) - self.inst.SESSION_EXTRAS):
            src = (self.inst.ENGINE / "extra-skills" / name / "SKILL.md").read_bytes()
            legacy = src.replace(self.inst.ENGINE_TAG.encode() + b"\n", b"", 1)
            self.assertNotEqual(legacy, src, name)
            if hashlib.sha256(legacy).hexdigest() not in self.inst.LEGACY_ENGINE_SKILL_SHA256:
                continue
            others.append(name)
            (self.skills / name).mkdir(parents=True)
            (self.skills / name / "SKILL.md").write_bytes(legacy)
        self.assertGreaterEqual(len(others), 5, others)  # an extra edited after tagging is the exception
        self.update()
        for name in others:
            self.assertEqual((self.skills / name / "SKILL.md").read_bytes(),
                             (self.inst.ENGINE / "extra-skills" / name / "SKILL.md").read_bytes(), name)
            self.assertEqual(len(list((self.tmp / ".wikibak/skills").glob(f"{name}-*"))), 1, name)

    # --- round 4 ---

    def blocks(self, shape: str) -> bytes:
        W = (self.inst.SENTINEL_START, self.inst.SENTINEL_END)
        S = (self.inst.SESSION_START, self.inst.SESSION_END)
        order = {"nested": [W[0], "w", S[0], "s", S[1], W[1]],
                 "interleaved": [W[0], "w", S[0], "s", W[1], S[1]]}[shape]
        return ("top\n" + "\n".join(order) + "\nbottom\n").encode()

    def test_nested_or_interleaved_blocks_are_left_alone(self):
        W = (self.inst.SENTINEL_START, self.inst.SENTINEL_END)
        S = (self.inst.SESSION_START, self.inst.SESSION_END)
        for shape in ("nested", "interleaved"):
            for start, end in (W, S):
                with self.subTest(shape=shape, block=start):
                    data = self.blocks(shape)
                    self.assert_left_alone(lambda c: self.inst.inject_block(c, "new", start, end), data)
                    self.assert_left_alone(lambda c: self.inst.remove_block(c, start, end), data)

    def test_install_over_nested_blocks_plans_no_edit(self):
        cmd = self.tmp / "CLAUDE.md"
        data = self.blocks("nested")
        cmd.write_bytes(data)
        plan = self.inst.build_plan(self.cfg())
        self.assertFalse(any("CLAUDE.md" in d for _, d, _ in plan.steps))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            plan.execute()
        self.assertNotIn("[ok] edit", out.getvalue())
        self.assertEqual(cmd.read_bytes(), data)

    def test_broken_marker_note_names_the_file_once(self):
        cmd = self.tmp / "CLAUDE.md"
        cmd.write_bytes(self.blocks("interleaved"))
        plan = self.inst.build_plan(self.cfg(extra_skills=[]))
        note = [n for n in plan.notes if "left unchanged" in n][0]
        self.assertEqual(note.count("CLAUDE.md"), 1, note)

    def test_symlinked_tools_session_is_skipped_not_crashed(self):
        real = self.tmp / "elsewhere"
        shutil.copytree(self.inst.ENGINE / "extra-tools/session", real)
        (self.tmp / "tools").mkdir()
        (self.tmp / "tools/session").symlink_to(real, target_is_directory=True)
        (self.skills / "preflight").mkdir(parents=True)
        shutil.copy2(self.inst.ENGINE / "extra-skills/preflight/SKILL.md", self.skills / "preflight/SKILL.md")
        out = self.update()  # must not raise
        self.assertIn("skip tools/session (symlinked", out)
        self.assertTrue((self.tmp / "tools/session").is_symlink())
        self.assertIn(self.inst.SESSION_START, self.claude_md())  # later steps still ran

    def test_symlinked_template_warning_says_symlink(self):
        self.inst.build_plan(self.cfg()).execute()
        tmpl = self.tmp / "handoffs/_TEMPLATE.md"
        mine = self.tmp / "my-template.md"
        mine.write_text("my own template\n", encoding="utf-8")
        tmpl.unlink()
        tmpl.symlink_to(mine)
        out = self.update()
        self.assertEqual(mine.read_text(encoding="utf-8"), "my own template\n")
        self.assertIn("is a symlink - left unchanged", out)
        self.assertNotIn("writable", out)

    def fake_legacy_recap(self) -> bytes:
        """A synthetic untagged 'older engine recap' whose hash this test registers as a known engine version
        (historical files are never copied into the tree as fixtures: they predate sanitisation)."""
        old = b"---\nname: recap\ndescription: an older engine recap\n---\n# Recap\nold generic text\n"
        self.inst.LEGACY_ENGINE_SKILL_SHA256 = self.inst.LEGACY_ENGINE_SKILL_SHA256 | {hashlib.sha256(old).hexdigest()}
        return old

    def test_update_refreshes_older_committed_recap(self):
        old = self.fake_legacy_recap()
        (self.skills / "recap").mkdir(parents=True)
        (self.skills / "recap/SKILL.md").write_bytes(old)
        self.update()
        self.assertEqual((self.skills / "recap/SKILL.md").read_bytes(),
                         (self.inst.ENGINE / "extra-skills/recap/SKILL.md").read_bytes())
        baks = list((self.tmp / ".wikibak/skills").glob("recap-*"))
        self.assertEqual(len(baks), 1)
        self.assertEqual((baks[0] / "SKILL.md").read_bytes(), old)

    def test_update_skips_user_edited_untagged_recap(self):
        old = self.fake_legacy_recap() + b"\nmy edit\n"
        (self.skills / "recap").mkdir(parents=True)
        (self.skills / "recap/SKILL.md").write_bytes(old)
        out = self.update()
        self.assertEqual((self.skills / "recap/SKILL.md").read_bytes(), old)
        self.assertIn("skip extra 'recap'", out)
        self.assertFalse((self.tmp / ".wikibak/skills").exists())

    def test_copy_tree_skips_runtime_caches_but_keeps_tests(self):
        src, dst = self.tmp / "src", self.tmp / "dst"
        for rel in ("a.py", "tests/test_a.py", "__pycache__/a.pyc", "tests/__pycache__/t.pyc",
                    ".pytest_cache/v/x"):
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text("x", encoding="utf-8")
        self.inst.copy_tree(src, dst)
        got = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
        self.assertEqual(got, ["a.py", "tests/test_a.py"])

    def test_tools_session_plan_line_says_backed_up(self):
        self.inst.build_plan(self.cfg()).execute()
        plan = self.inst.Plan(True)
        self.inst.session_plan(plan, self.tmp, update=True, claude_md=False)
        line = [d for _, d, _ in plan.steps if "extra-tools/session" in d][0]
        self.assertNotIn("backed up", line)
        (self.tmp / "tools/session/lib.py").write_text("# mine\n", encoding="utf-8")
        plan = self.inst.Plan(True)
        self.inst.session_plan(plan, self.tmp, update=True, claude_md=False)
        line = [d for _, d, _ in plan.steps if "extra-tools/session" in d][0]
        self.assertIn("backed up", line)

    def test_failed_backup_never_replaces_the_modified_copy(self):
        self.inst.build_plan(self.cfg(skills=["doc-review"])).execute()
        edits = {self.skills / "doc-review/SKILL.md": None, self.tmp / "handoffs/_TEMPLATE.md": None,
                 self.tmp / "tools/session/lib.py": None}
        for f in edits:
            f.write_bytes(f.read_bytes() + b"\nMY CHANGE\n")
            edits[f] = f.read_bytes()
        (self.tmp / ".wikibak").write_text("a file where the backup dir should be", encoding="utf-8")
        out = self.update(skills=["doc-review"])
        for f, data in edits.items():
            self.assertEqual(f.read_bytes(), data, f)
        self.assertEqual(out.count("backup failed"), 3, out)
        self.assertNotIn("[ok] copy skills/doc-review", out)

    def test_update_installs_missing_core_skill(self):
        self.update(skills=["wiki-sync"])
        self.assertTrue(self.inst.is_engine_skill(self.skills / "wiki-sync"))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SessionEndHookTest(unittest.TestCase):
    """hooks/session-end.cjs: a no-op without the session tools; else hands stdin to `close.py session end`."""

    def _config(self, with_tools):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        (base / "hooks").mkdir()
        shutil.copy2(REPO / "hooks" / "session-end.cjs", base / "hooks" / "session-end.cjs")
        if with_tools:
            tools = base / "tools" / "session"
            tools.mkdir(parents=True)
            (tools / "close.py").write_text(
                "import sys, pathlib\n"
                "pathlib.Path(__file__).with_name('called.txt').write_text("
                "' '.join(sys.argv[1:]) + '|' + sys.stdin.read(), encoding='utf-8')\n",
                encoding="utf-8")
        return base

    def _run(self, base, payload):
        return subprocess.run(["node", str(base / "hooks" / "session-end.cjs")], input=payload,
                              capture_output=True, text=True, timeout=30)

    def test_no_tools_is_a_silent_no_op(self):
        base = self._config(with_tools=False)
        r = self._run(base, '{"reason": "logout"}')
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_passes_hook_input_to_close_session_end(self):
        base = self._config(with_tools=True)
        r = self._run(base, '{"reason": "prompt_input_exit"}')
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        called = (base / "tools" / "session" / "called.txt").read_text(encoding="utf-8")
        self.assertEqual(called, 'session end|{"reason": "prompt_input_exit"}')

    def test_hook_is_registered_under_session_end(self):
        self.assertIn(("session-end.cjs", "SessionEnd", ""), load_installer().HOOKS)
