from __future__ import annotations

from pathlib import Path
from exitzero.slicer import slice_log
from exitzero.models import Language

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_single_error_detected():
    contexts = slice_log(load("python_real_bug.txt"))
    assert len(contexts) == 1


def test_language_detected_as_python():
    contexts = slice_log(load("python_real_bug.txt"))
    assert contexts[0].language == Language.PYTHON


def test_file_and_line_extracted():
    contexts = slice_log(load("python_real_bug.txt"))
    ctx = contexts[0]
    assert ctx.file_path is not None
    assert "test_auth.py" in ctx.file_path
    assert ctx.line_number == 34


def test_multi_error_finds_all():
    contexts = slice_log(load("multi_error.txt"))
    assert len(contexts) >= 3


def test_all_errors_populated():
    contexts = slice_log(load("multi_error.txt"))
    for ctx in contexts:
        assert len(ctx.all_errors) >= 3


def test_node_language_detected():
    contexts = slice_log(load("node_error.txt"))
    assert len(contexts) >= 1
    assert contexts[0].language == Language.NODE


def test_empty_log_returns_nothing():
    contexts = slice_log(load("empty.txt"))
    assert contexts == []


def test_normalized_window_strips_noise():
    log = "2024-01-01T12:00:00Z pid=9999 Error: something failed at 0xDEADBEEF"
    contexts = slice_log(log)
    assert len(contexts) == 1
    assert "TIMESTAMP" in contexts[0].normalized_window
    assert "0xADDR" in contexts[0].normalized_window
