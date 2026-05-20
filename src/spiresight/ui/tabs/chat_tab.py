"""Thin wrapper around ConversationTranscript so it can live as a tab."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from spiresight.core.messages import Message
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.conversation_transcript import ConversationTranscript
from spiresight.ui.widgets.output_view import TranscriptScrollMode


class ChatTab(QWidget):
    clear_requested = Signal()

    def __init__(
        self,
        locale: UILocale,
        *,
        transcript_mode: TranscriptScrollMode = "compact",
        assistant_max_height: int = 200,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locale = locale

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 0)
        toolbar.addStretch(1)
        self._clear_btn = QPushButton()
        self._clear_btn.setObjectName("chat-clear")
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        toolbar.addWidget(self._clear_btn)
        layout.addLayout(toolbar)

        self._transcript = ConversationTranscript(
            transcript_mode=transcript_mode,
            assistant_max_height=assistant_max_height,
        )
        layout.addWidget(self._transcript, stretch=1)

        locale.changed.connect(self._retranslate)
        self._retranslate()

    @property
    def output(self) -> ConversationTranscript:
        """Backward compatibility for tests referencing chat_tab.output."""
        return self._transcript

    def set_transcript_mode(
        self,
        mode: TranscriptScrollMode,
        *,
        assistant_max_height: int | None = None,
    ) -> None:
        self._transcript.set_transcript_mode(
            mode, assistant_max_height=assistant_max_height
        )

    def reset(self) -> None:
        self._transcript.reset()

    def append_delta(self, text: str) -> None:
        self._transcript.append_delta(text)

    def finalize(self) -> None:
        self._transcript.finalize()

    def load_static(self, markdown: str) -> None:
        self._transcript.load_static(markdown)

    def append_user_message(self, text: str) -> None:
        self._transcript.append_user_message(text)

    def begin_assistant_turn(self) -> None:
        self._transcript.begin_assistant_turn()

    def render_turns(self, turns: tuple[Message, ...]) -> None:
        self._transcript.render_turns(turns)

    def current_markdown(self) -> str:
        return self._transcript.current_markdown()

    def _retranslate(self) -> None:
        self._clear_btn.setText(self._locale.get("chat.clear_context"))
