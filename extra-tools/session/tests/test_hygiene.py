"""Static guard: every text read/write names its encoding. Windows defaults to cp1252, and an unencoded
write_text of an em-dash broke 6 tests there (Task 16, 2026-09-28)."""
import ast
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = sorted(HERE.glob("*.py")) + sorted(HERE.parent.glob("*.py"))


def _unencoded(path):
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(n, ast.Call) or any(k.arg == "encoding" for k in n.keywords):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        text_mode = any(k.arg == "text" and getattr(k.value, "value", False) is True for k in n.keywords)
        if name in ("read_text", "write_text") or (name in ("run", "Popen", "check_output") and text_mode):
            yield f"{path.name}:{n.lineno}"


def test_every_text_io_call_names_its_encoding():
    assert [hit for p in FILES for hit in _unencoded(p)] == []
