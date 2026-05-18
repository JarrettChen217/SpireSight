"""Collapsible log row widgets for the Logs tab.

LogRow renders a single inference request with header (always visible) and
body (system / messages / params / response) hidden by default. TextRow is
the non-collapsible sibling used for plain log lines and cost rows.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from spiresight.core.usage import LogStatus, RequestLog
from spiresight.prompts.ui_locale import UILocale


_MONOSPACE_QSS = "font-family: ui-monospace, Menlo, monospace; font-size: 11px;"
_TRUNCATE_LIMIT = 2000


def _make_section(title: str) -> tuple[QLabel, QPlainTextEdit]:
    label = QLabel(title)
    label.setStyleSheet("font-weight: 600; padding-top: 4px;")
    edit = QPlainTextEdit()
    edit.setReadOnly(True)
    edit.setStyleSheet(_MONOSPACE_QSS)
    edit.setMaximumBlockCount(_TRUNCATE_LIMIT)
    return label, edit


def _format_header(record: RequestLog) -> str:
    ts = record.timestamp.astimezone().strftime("%H:%M:%S")
    return f"[{ts}] [{record.status}] {record.provider}/{record.model} · {record.correlation_id}"


def _loc(locale: UILocale | None, key: str, fallback: str) -> str:
    if locale is None:
        return fallback
    try:
        return locale.get(key)
    except KeyError:
        return fallback


class LogRow(QFrame):
    def __init__(
        self,
        record: RequestLog,
        parent: QWidget | None = None,
        locale: UILocale | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LogRow")
        self.setProperty("status", record.status)
        self._record = record

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)

        self._header = QWidget()
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(2, 2, 2, 2)
        self._chevron = QLabel("▶")
        self._summary = QLabel(_format_header(record))
        self._summary.setObjectName("LogRowSummary")
        self._summary.setStyleSheet(_MONOSPACE_QSS)
        header_layout.addWidget(self._chevron)
        header_layout.addWidget(self._summary, stretch=1)
        self._copy_btn = QToolButton()
        self._copy_btn.setText(_loc(locale, "logs.copy_row", "Copy"))
        self._copy_btn.clicked.connect(self._on_copy)
        header_layout.addWidget(self._copy_btn)
        outer.addWidget(self._header)

        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(20, 2, 2, 6)
        body_layout.setSpacing(2)

        sys_title = _loc(locale, "logs.section.system", "System prompt")
        self._sys_label, self._sys_edit = _make_section(sys_title)
        self._sys_edit.setPlainText(record.system)
        body_layout.addWidget(self._sys_label)
        body_layout.addWidget(self._sys_edit)

        msgs_title = _loc(locale, "logs.section.messages", "Messages")
        self._msgs_label = QLabel(f"{msgs_title} ({len(record.messages)})")
        self._msgs_label.setStyleSheet("font-weight: 600; padding-top: 4px;")
        body_layout.addWidget(self._msgs_label)
        msg_text_parts: list[str] = []
        for m in record.messages:
            msg_text_parts.append(f"[{m.role}] {m.text}")
            if m.image_summary:
                msg_text_parts.append(f"  [image: {m.image_summary}]")
        self._msgs_edit = QPlainTextEdit("\n".join(msg_text_parts))
        self._msgs_edit.setReadOnly(True)
        self._msgs_edit.setStyleSheet(_MONOSPACE_QSS)
        self._msgs_edit.setMaximumBlockCount(_TRUNCATE_LIMIT)
        body_layout.addWidget(self._msgs_edit)

        params_title = _loc(locale, "logs.section.params", "Params")
        self._params_label, self._params_edit = _make_section(params_title)
        self._params_edit.setPlainText(
            "\n".join(f"{k}: {v!r}" for k, v in record.params.items())
        )
        body_layout.addWidget(self._params_label)
        body_layout.addWidget(self._params_edit)

        resp_title = _loc(locale, "logs.section.response", "Response")
        self._resp_label, self._response = _make_section(resp_title)
        streaming_text = _loc(locale, "logs.streaming_placeholder", "[streaming…]")
        self._response.setPlainText(streaming_text)
        body_layout.addWidget(self._resp_label)
        body_layout.addWidget(self._response)

        outer.addWidget(self._body)
        self._body.setVisible(False)

        self._header.mousePressEvent = self._on_header_click  # type: ignore[method-assign]

    @property
    def correlation_id(self) -> str:
        return self._record.correlation_id

    def toggle(self) -> None:
        self._body.setVisible(not self._body.isVisible())
        self._chevron.setText("▼" if self._body.isVisible() else "▶")

    def _on_header_click(self, event: QMouseEvent) -> None:
        self.toggle()

    def set_response(self, text: str, status: LogStatus, error: str | None) -> None:
        self._record.status = status
        self._record.response = text
        self._record.error = error
        self.setProperty("status", status)
        self.style().unpolish(self)
        self.style().polish(self)
        self._summary.setText(_format_header(self._record))

        if status == "ok":
            body = text
        elif status == "cancelled":
            body = text if text else "(no output)"
        else:  # error, timeout
            parts = [text] if text else []
            if error:
                parts.append(f"[error] {error}")
            body = "\n".join(parts) if parts else "(no output)"
        self._response.setPlainText(body)

    def to_plain_text(self) -> str:
        lines: list[str] = [self._summary.text(), ""]
        lines.append("System prompt")
        lines.append(self._sys_edit.toPlainText())
        lines.append("")
        lines.append(self._msgs_label.text())
        lines.append(self._msgs_edit.toPlainText())
        lines.append("")
        lines.append("Params")
        lines.append(self._params_edit.toPlainText())
        lines.append("")
        lines.append("Response")
        lines.append(self._response.toPlainText())
        return "\n".join(lines)

    def _on_copy(self) -> None:
        QGuiApplication.clipboard().setText(self.to_plain_text())


class TextRow(QFrame):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TextRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self._label = QLabel(text)
        self._label.setStyleSheet(_MONOSPACE_QSS)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._label, stretch=1)

    def to_plain_text(self) -> str:
        return self._label.text()
