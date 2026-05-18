from datetime import datetime, timezone

from spiresight.core.usage import LoggedMessage, RequestLog
from spiresight.ui.tabs.logs_tab import LogsTab
from spiresight.prompts.ui_locale import UILocale


def _record(cid: str = "aaaaaaaa") -> RequestLog:
    return RequestLog(
        correlation_id=cid,
        timestamp=datetime.now(tz=timezone.utc),
        provider="openai",
        model="gpt-4o",
        system="SYS",
        messages=[LoggedMessage(role="user", text="hi", image_summary=None)],
        params={"json_mode": False, "has_images": False},
    )


def _make_tab(qtbot, tmp_path) -> LogsTab:
    en_dir = tmp_path / "en"
    en_dir.mkdir()
    (en_dir / "ui_strings.yaml").write_text(
        "logs:\n  copy_all: Copy all\n  clear: Clear\n",
        encoding="utf-8",
    )
    locale = UILocale(tmp_path, "en")
    tab = LogsTab(locale)
    qtbot.addWidget(tab)
    return tab


def test_log_request_inserts_row(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab.log_request(_record("aaaaaaaa"))
    assert "aaaaaaaa" in tab._rows
    assert tab._row_count() == 1


def test_log_request_then_update_response(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab.log_request(_record("aaaaaaaa"))
    tab.update_response("aaaaaaaa", "the answer", "ok", None)
    row = tab._rows["aaaaaaaa"]
    assert "ok" in row._summary.text()
    assert "the answer" in row._response.toPlainText()


def test_update_response_for_missing_id_is_noop(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    # should not raise:
    tab.update_response("zzzzzzzz", "x", "ok", None)


def test_ring_buffer_evicts_oldest(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    for i in range(205):
        tab.log_request(_record(f"id{i:05d}"))
    assert tab._row_count() == 200
    assert "id00000" not in tab._rows
    assert "id00204" in tab._rows
