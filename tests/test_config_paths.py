# tests/test_config_paths.py
from pathlib import Path
from spiresight.config import paths


def test_config_dir_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIRESIGHT_CONFIG_DIR", str(tmp_path))
    assert paths.config_dir() == tmp_path
    assert paths.config_file() == tmp_path / "config.json"


def test_config_dir_macos(monkeypatch):
    monkeypatch.delenv("SPIRESIGHT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "_platform", lambda: "darwin")
    monkeypatch.setenv("HOME", "/Users/test")
    assert paths.config_dir() == Path("/Users/test/Library/Application Support/SpireSight")


def test_config_dir_windows(monkeypatch):
    monkeypatch.delenv("SPIRESIGHT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "_platform", lambda: "win32")
    monkeypatch.setenv("APPDATA", "C:/Users/test/AppData/Roaming")
    assert paths.config_dir() == Path("C:/Users/test/AppData/Roaming/SpireSight")


def test_config_dir_linux(monkeypatch):
    monkeypatch.delenv("SPIRESIGHT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "_platform", lambda: "linux")
    monkeypatch.setenv("HOME", "/home/test")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert paths.config_dir() == Path("/home/test/.config/SpireSight")


def test_log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIRESIGHT_CONFIG_DIR", str(tmp_path))
    assert paths.log_dir() == tmp_path / "logs"


def test_card_knowledge_dir_defaults_to_repo_data(monkeypatch):
    monkeypatch.delenv("SPIRESIGHT_CARD_KNOWLEDGE_DIR", raising=False)
    assert paths.card_knowledge_dir() == paths.repo_root() / "data" / "sts2_cards"


def test_card_knowledge_dir_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIRESIGHT_CARD_KNOWLEDGE_DIR", str(tmp_path))
    assert paths.card_knowledge_dir() == tmp_path


def test_card_knowledge_dir_uses_pyinstaller_bundle(monkeypatch, tmp_path):
    monkeypatch.delenv("SPIRESIGHT_CARD_KNOWLEDGE_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.card_knowledge_dir() == tmp_path / "data" / "sts2_cards"
