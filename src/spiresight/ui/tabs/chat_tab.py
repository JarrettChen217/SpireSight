"""Thin wrapper around ConversationTranscript so it can live as a tab."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from spiresight.core.messages import Message
from spiresight.ui.widgets.conversation_transcript import ConversationTranscript


class ChatTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._transcript = ConversationTranscript()
        layout.addWidget(self._transcript)

    @property
    def output(self) -> ConversationTranscript:
        """Backward compatibility for tests referencing chat_tab.output."""
        return self._transcript

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
