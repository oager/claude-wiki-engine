"""Regression tests for install.py. Stdlib only -- run with:

    python -m unittest discover tests
"""

import importlib.util
import json
import shutil
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
                "extra_skills": ["preflight", "sync"], "no_pull": True}
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
        self.assertTrue((s / "preflight.wikibak").exists())


if __name__ == "__main__":
    unittest.main()
