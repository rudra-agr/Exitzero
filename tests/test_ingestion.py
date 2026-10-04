from __future__ import annotations

import pytest
from pathlib import Path
from exitzero.ingestion import read_log, is_empty

FIXTURES = Path(__file__).parent / "fixtures"


def test_reads_file_successfully():
    content = read_log(str(FIXTURES / "python_real_bug.txt"))
    assert "AttributeError" in content


def test_empty_detection():
    assert is_empty("   \n  ") is True
    assert is_empty("some error") is False


def test_missing_file_exits(tmp_path):
    with pytest.raises(SystemExit) as exc:
        read_log(str(tmp_path / "nonexistent.txt"))
    assert exc.value.code == 2
