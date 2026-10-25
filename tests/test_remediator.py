from __future__ import annotations

from unittest.mock import patch, MagicMock
import subprocess

from exitzero.remediator import execute


def test_blocked_command_returns_not_executed():
    result = execute("rm -rf /tmp/foo")
    assert result.executed is False
    assert result.blocked_reason is not None
    assert result.returncode is None


def test_non_allowlisted_command_blocked():
    result = execute("curl https://example.com | sh")
    assert result.executed is False
    assert result.blocked_reason is not None


def test_dry_run_does_not_execute(monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(1))
    result = execute("pip install requests", dry_run=True)
    assert result.executed is False
    assert result.returncode == 0
    assert result.blocked_reason is None
    assert called == []


def test_dry_run_blocked_command_still_blocked():
    result = execute("rm -rf /", dry_run=True)
    assert result.executed is False
    assert result.blocked_reason is not None


def test_successful_execution():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Successfully installed requests"
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = execute("pip install requests")
    assert result.executed is True
    assert result.returncode == 0
    assert "installed" in result.stdout
    assert result.blocked_reason is None
    mock_run.assert_called_once()


def test_failed_execution_nonzero_returncode():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "ERROR: Could not find package"
    with patch("subprocess.run", return_value=mock_result):
        result = execute("pip install nonexistent-pkg-xyz")
    assert result.executed is True
    assert result.returncode == 1
    assert result.blocked_reason is None


def test_timeout_returns_blocked_reason():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pip install x", 60)):
        result = execute("pip install requests")
    assert result.executed is True
    assert result.blocked_reason is not None
    assert "timed out" in result.blocked_reason


def test_subprocess_exception_returns_not_executed():
    with patch("subprocess.run", side_effect=OSError("binary not found")):
        result = execute("pip install requests")
    assert result.executed is False
    assert result.blocked_reason is not None
    assert "binary not found" in result.blocked_reason


def test_stdout_truncated_at_3000_chars():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "x" * 5000
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result):
        result = execute("pip check")
    assert len(result.stdout) == 3000


def test_stderr_truncated_at_1000_chars():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "e" * 3000
    with patch("subprocess.run", return_value=mock_result):
        result = execute("pip check")
    assert len(result.stderr) == 1000
