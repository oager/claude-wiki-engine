# Contributing

Feedback and fixes are welcome. You do not need write access to this repo for either.

## Ideas, questions, bug reports

Open an issue: <https://github.com/oager/claude-wiki-engine/issues>. Any GitHub account can do this.

A useful bug report says:
- your OS and Python version, and how you installed (`install.py` flags, copy or symlink mode, which extras)
- what you ran, what happened (the exact error line), and what you expected
- the engine version (`VERSION`, or `.wiki-engine-version` in your installed config)

Do not paste your own wiki pages, handoff files, `settings.json` secrets, or paths that name private
projects. A short description or a trimmed example is enough.

## Code changes (pull requests)

Outside contributors cannot push branches to this repo, so a pull request comes from your own fork.

1. **Fork** the repo on GitHub (or `gh repo fork oager/claude-wiki-engine --clone`).
2. **Sync the fork first** if you forked a while ago: click **Sync fork** on your fork's GitHub page,
   or run `gh repo sync <you>/claude-wiki-engine`. A branch cut from a stale `main` will conflict.
3. **Branch** from the fresh `main` and make your change.
4. **Push to your fork**, not to `oager/claude-wiki-engine` (pushing here returns a 403). Check with
   `git remote -v`: `origin` should be your fork.
5. **Open the PR** from `<you>:<branch>` into `oager:main`, on GitHub or with `gh pr create`.

If `git push` or `gh` fails with a permission error, check which account you are logged in as
(`gh auth status`; switch with `gh auth switch`).

### Before you open the PR

Run the same checks CI runs (Linux, macOS and Windows; Python 3.11 and 3.12), from the repo root:

```bash
pip install ruff pytest
ruff check .
python -m unittest discover tests
python -m pytest -p no:cacheprovider -q extra-tools/session/tests
python install.py --dry-run -y --into-repo "$(mktemp -d)" --extras preflight,sync
```

### What makes a PR easy to merge

- **One change per PR**, with a test that fails without it when it fixes a bug.
- **Engine only.** This repo holds the machinery (skills, tools, hooks, templates), never wiki content.
  No personal pages, names, hostnames or secrets; the session tools' leak-guard tests check for some of this.
- **Works on all three OSes.** Use `pathlib` and POSIX paths in generated hook commands; no shell-only tricks
  in Python.
- **Commit and PR titles** follow the existing style: `fix(session): ...`, `feat(install): ...`,
  `docs: ...`, `test(session): ...`.
- Say in the PR what you changed, why, and how you tested it.
