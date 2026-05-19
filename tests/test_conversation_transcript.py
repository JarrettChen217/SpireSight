from PySide6.QtWidgets import QApplication

import pytest

from spiresight.core.messages import Message
from spiresight.ui.widgets.conversation_transcript import ConversationTranscript
from spiresight.ui.widgets.output_view import OutputView


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_render_turns_creates_separate_assistant_blocks(qtwidgets_app):
    t = ConversationTranscript()
    turns = (
        Message(role="user", text="hi"),
        Message(role="assistant", text="hello"),
        Message(role="user", text="again"),
        Message(role="assistant", text="sure"),
    )
    t.render_turns(turns)
    outputs = t.findChildren(OutputView)
    assert len(outputs) == 2
    assert outputs[0].current_markdown() == "hello"
    assert outputs[1].current_markdown() == "sure"


def test_streaming_two_turns_keeps_buffers_separate(qtwidgets_app):
    t = ConversationTranscript()
    t.append_user_message("q1")
    t.begin_assistant_turn()
    t.append_delta("a1")
    t.finalize()
    first = t.findChildren(OutputView)[0]

    t.append_user_message("q2")
    t.begin_assistant_turn()
    t.append_delta("a2")
    t.finalize()
    outputs = t.findChildren(OutputView)
    assert len(outputs) == 2
    assert first.current_markdown() == "a1"
    assert outputs[1].current_markdown() == "a2"
