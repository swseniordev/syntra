from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.setup_smtp_password import save_password


def test_smtp_password_is_written_outside_repo_without_overwrite(tmp_path: Path):
    target = tmp_path / "private" / "smtp_password"
    with patch("scripts.setup_smtp_password.restrict_to_current_user") as restrict:
        save_password(target, "test-only-password")
        assert target.read_text(encoding="utf-8") == "test-only-password"
        assert restrict.call_count == 2
        with pytest.raises(FileExistsError):
            save_password(target, "another-test-only-password")
        assert target.read_text(encoding="utf-8") == "test-only-password"


def test_smtp_password_rejects_empty_and_newline(tmp_path: Path):
    target = tmp_path / "private" / "smtp_password"
    for secret in ("", "abc\ndef", "abc\rdef"):
        with pytest.raises(ValueError):
            save_password(target, secret)
    assert not target.exists()


def test_smtp_password_removes_new_file_if_acl_fails(tmp_path: Path):
    target = tmp_path / "private" / "smtp_password"
    with patch("scripts.setup_smtp_password.restrict_to_current_user", side_effect=[None, RuntimeError("ACL")]):
        with pytest.raises(RuntimeError):
            save_password(target, "test-only-password")
    assert not target.exists()
