"""Config path resolution and the archive-folder picker."""

import json
import os
import sys

import pytest

from message_deleter import config


def _posix(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


def test_app_config_dir_linux(monkeypatch, tmp_path):
    _posix(monkeypatch, tmp_path)
    assert config.app_config_dir() == tmp_path / "message-deleter"


def test_app_config_dir_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    folder = config.app_config_dir()
    assert folder.name == "message-deleter"
    assert folder.parent.name == "Application Support"
    assert folder.parent.parent.name == "Library"


@pytest.mark.skipif(os.name != "nt", reason="pathlib cannot fake Windows paths on POSIX")
def test_app_config_dir_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config.app_config_dir() == tmp_path / "message-deleter"


def test_resolve_prefers_explicit_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DM_ARCHIVE_DIR", str(tmp_path / "env"))
    assert config.resolve_archive_dir(str(tmp_path / "explicit")) == tmp_path / "explicit"


def test_resolve_env_over_config(monkeypatch, tmp_path):
    _posix(monkeypatch, tmp_path)
    config_dir = tmp_path / "message-deleter"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"archive_dir": str(tmp_path / "file")}), encoding="utf-8")
    monkeypatch.setenv("DM_ARCHIVE_DIR", str(tmp_path / "env"))
    assert config.resolve_archive_dir() == tmp_path / "env"


def test_resolve_config_file_over_default(monkeypatch, tmp_path):
    _posix(monkeypatch, tmp_path)
    config_dir = tmp_path / "message-deleter"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"archive_dir": str(tmp_path / "file")}), encoding="utf-8")
    assert config.resolve_archive_dir() == tmp_path / "file"


def test_resolve_default(monkeypatch, tmp_path):
    _posix(monkeypatch, tmp_path)
    assert config.resolve_archive_dir() == tmp_path / "message-deleter" / "archives"


def test_configure_blank_keeps_current(monkeypatch, tmp_path):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert config.configure_archive_dir(tmp_path / "current") == tmp_path / "current"


def test_configure_persists_to_config_file(monkeypatch, tmp_path):
    _posix(monkeypatch, tmp_path)
    new_dir = tmp_path / "new"
    monkeypatch.setattr("builtins.input", lambda _: str(new_dir))
    assert config.configure_archive_dir(tmp_path / "old") == new_dir
    assert new_dir.is_dir()
    config_file = tmp_path / "message-deleter" / "config.json"
    assert json.loads(config_file.read_text(encoding="utf-8"))["archive_dir"] == str(new_dir)
    assert config.resolve_archive_dir() == new_dir
