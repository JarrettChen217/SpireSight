import logging
from spiresight.logging_setup import configure_logging
from spiresight.config import paths


def test_configure_creates_rotating_file_handler(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIRESIGHT_CONFIG_DIR", str(tmp_path))
    paths.ensure_dirs()
    configure_logging()
    log = logging.getLogger("spiresight.test")
    log.info("hello")
    log_file = paths.log_dir() / "app.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text()
