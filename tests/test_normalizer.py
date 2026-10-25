from __future__ import annotations

from exitzero.normalizer import normalize


def test_strips_hex_address():
    assert "0xADDR" in normalize("crash at 0xDEADBEEF")


def test_strips_iso_timestamp():
    assert "TIMESTAMP" in normalize("2024-01-01T12:00:00Z something failed")


def test_strips_time():
    assert "TIME" in normalize("12:34:56.789 server started")


def test_strips_pid():
    assert "PID" in normalize("pid=12345 process exited")


def test_strips_large_number():
    assert "NUM" in normalize("port 54321 already in use")


def test_preserves_short_numbers():
    result = normalize("line 34 in test_auth.py")
    assert "34" in result


def test_empty_string():
    assert normalize("") == ""
