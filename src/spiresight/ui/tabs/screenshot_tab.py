"""Tab that displays the latest screenshot(s) sent to the LLM."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.screenshot_store import ScreenshotBundle, ScreenshotStore


class ScreenshotTab(QWidget):
    def __init__(
        self,
        store: ScreenshotStore,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._locale = locale

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(6)

        # header row
        self._header = QHBoxLayout()
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color:#888; font-size:11px;")
        self._save_btn = QPushButton(locale.get("screenshot.save_as"))
        self._save_btn.clicked.connect(self._on_save)
        self._save_btn.setEnabled(False)
        self._header.addWidget(self._info_label)
        self._header.addStretch(1)
        self._header.addWidget(self._save_btn)
        outer.addLayout(self._header)

        # frames area — horizontal scroll
        self._frames_scroll = QScrollArea()
        self._frames_scroll.setWidgetResizable(True)
        self._frames_host = QWidget()
        self._frames_layout = QHBoxLayout(self._frames_host)
        self._frames_layout.setContentsMargins(0, 0, 0, 0)
        self._frames_layout.setSpacing(8)
        self._frames_scroll.setWidget(self._frames_host)
        outer.addWidget(self._frames_scroll, stretch=1)

        # empty state
        self._empty_label = QLabel(locale.get("screenshot.empty"))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color:#6e7a89;")
        outer.addWidget(self._empty_label, stretch=1)

        # Hide frames scroll by default; _refresh will show/hide as needed
        self._frames_scroll.setVisible(False)

        store.changed.connect(self._refresh)
        locale.changed.connect(self._retranslate)
        self._refresh()
        self.show()

    def _refresh(self) -> None:
        bundle = self._store.get()
        # clear existing frame widgets
        while self._frames_layout.count():
            item = self._frames_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        if bundle is None or not bundle.frames:
            self._info_label.setText("")
            self._save_btn.setEnabled(False)
            self._empty_label.setVisible(True)
            self._frames_scroll.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._frames_scroll.setVisible(True)
        self._save_btn.setEnabled(True)

        loc = self._locale
        dims = loc.get("screenshot.dims_format", w=bundle.width, h=bundle.height)
        ts = bundle.timestamp.strftime("%H:%M:%S")
        self._info_label.setText(f"{ts} · {dims} · {len(bundle.frames)} frame(s)")

        for i, png in enumerate(bundle.frames):
            pix = QPixmap()
            pix.loadFromData(png)
            # scale to fit-height ~360px max for readability
            if pix.height() > 360:
                pix = pix.scaledToHeight(360, Qt.TransformationMode.SmoothTransformation)
            container = QWidget()
            c_l = QVBoxLayout(container)
            c_l.setContentsMargins(0, 0, 0, 0)
            c_l.setSpacing(2)
            img = QLabel()
            img.setPixmap(pix)
            caption = QLabel(f"#{i + 1}")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setStyleSheet("color:#888; font-size:10px;")
            c_l.addWidget(img)
            c_l.addWidget(caption)
            self._frames_layout.addWidget(container)
        self._frames_layout.addStretch(1)

    def _on_save(self) -> None:
        bundle = self._store.get()
        if bundle is None or not bundle.frames:
            return
        ts = bundle.timestamp.strftime("%Y%m%d-%H%M%S")
        suggested = f"spiresight-{ts}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", suggested, "PNG (*.png)")
        if not path:
            return
        # If multi-frame, save the first frame; v2 could offer a chooser.
        with open(path, "wb") as f:
            f.write(bundle.frames[0])

    def _retranslate(self) -> None:
        loc = self._locale
        self._save_btn.setText(loc.get("screenshot.save_as"))
        self._empty_label.setText(loc.get("screenshot.empty"))
        self._refresh()
