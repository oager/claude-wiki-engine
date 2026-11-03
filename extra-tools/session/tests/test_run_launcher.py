# ~/.claude/tools/session/tests/test_run_launcher.py
"""run.sh picks the first working Python 3.11+ (python3, else python) and runs the tool exactly once."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
SH = shutil.which("sh")
pytestmark = pytest.mark.skipif(SH is None, reason="no sh on PATH")

TOOL = """import sys
from pathlib import Path
with open(Path(__file__).with_name("calls.log"), "a", encoding="utf-8") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(3)
"""


def fake(bin_dir, name, body):
    p = bin_dir / name
    p.write_bytes(f"#!/bin/sh\n{body}\n".encode())
    p.chmod(0o755)


def real_python(bin_dir, name):
    fake(bin_dir, name, f'exec "{Path(sys.executable).as_posix()}" "$@"')


def broken(bin_dir, name):  # like the Windows Store stub: prints to stderr, exits non-zero
    fake(bin_dir, name, 'echo "Python was not found" >&2; exit 49')


@pytest.fixture
def env(tmp_path):
    """run.sh copied next to a tool that logs its args and exits 3, plus an empty bin dir first on PATH."""
    tools, bin_dir = tmp_path / "tools", tmp_path / "bin"
    tools.mkdir()
    bin_dir.mkdir()
    shutil.copy2(TOOLS / "run.sh", tools / "run.sh")
    (tools / "tool.py").write_text(TOOL, encoding="utf-8")
    return tools, bin_dir


def run(tools, bin_dir, *args):
    e = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
    return subprocess.run([SH, (tools / "run.sh").as_posix(), *args], env=e, capture_output=True, text=True,
                          encoding="utf-8", timeout=30)


def calls(tools):
    log = tools / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_falls_back_to_python_when_python3_is_a_stub(env):
    tools, bin_dir = env
    broken(bin_dir, "python3")
    real_python(bin_dir, "python")
    r = run(tools, bin_dir, "tool.py", "push", "--files", "a b")
    assert r.returncode == 3, r.stderr
    assert calls(tools) == ["push --files a b"]


def test_prefers_python3_and_never_reruns_a_failing_tool(env):
    tools, bin_dir = env
    real_python(bin_dir, "python3")
    fake(bin_dir, "python", 'echo "python must not run" >&2; exit 1')
    r = run(tools, bin_dir, "tool.py", "x")
    assert r.returncode == 3  # the tool's own exit code, passed through
    assert calls(tools) == ["x"]  # once: a failing tool is not retried with the next interpreter
    assert "must not run" not in r.stderr


def test_too_old_python3_is_skipped(env):
    tools, bin_dir = env
    fake(bin_dir, "python3", 'case "$1" in -c) exit 1 ;; esac; echo "old python ran the tool" >&2; exit 1')
    real_python(bin_dir, "python")
    r = run(tools, bin_dir, "tool.py")
    assert r.returncode == 3 and calls(tools) == [""]
    assert "old python" not in r.stderr


def test_no_working_python_exits_127_with_a_message(env):
    tools, bin_dir = env
    broken(bin_dir, "python3")
    broken(bin_dir, "python")
    r = run(tools, bin_dir, "tool.py")
    assert r.returncode == 127
    assert "Python 3.11+" in r.stderr
    assert calls(tools) == []


def test_missing_tool_name_is_a_usage_error(env):
    tools, bin_dir = env
    real_python(bin_dir, "python3")
    r = run(tools, bin_dir)
    assert r.returncode == 2 and "usage" in r.stderr


def test_crlf_checkout_still_runs(env):
    # A vault cloned on Windows with core.autocrlf=true checks run.sh out with CRLF line endings.
    tools, bin_dir = env
    data = (tools / "run.sh").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    (tools / "run.sh").write_bytes(data)
    real_python(bin_dir, "python3")
    r = run(tools, bin_dir, "tool.py", "y")
    assert r.returncode == 3, r.stderr
    assert calls(tools) == ["y"]
