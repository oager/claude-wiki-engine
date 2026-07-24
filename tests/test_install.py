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


if __name__ == "__main__":
    unittest.main()
