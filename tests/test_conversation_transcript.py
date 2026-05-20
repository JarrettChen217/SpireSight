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


_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000000500010d0a2db40000000049454e44"
    "ae426082"
)


def test_user_message_with_screenshot_shows_thumb(qtwidgets_app):
    from PySide6.QtWidgets import QLabel, QWidget

    t = ConversationTranscript()
    t.append_user_message("look at this", image_png=_PNG_1x1)
    bubble = t.findChild(QWidget, "bubble-user-msg")
    assert bubble is not None
    thumb_lbl = bubble.findChild(QLabel, "bubble-user-thumb")
    assert thumb_lbl is not None
    assert thumb_lbl.width() == 64 and thumb_lbl.height() == 36


def test_render_turns_includes_screenshot_thumb(qtwidgets_app):
    from PySide6.QtWidgets import QLabel, QWidget

    t = ConversationTranscript()
    turns = (
        Message(role="user", text="hi", image_png=_PNG_1x1),
        Message(role="assistant", text="ok"),
    )
    t.render_turns(turns)
    bubble = t.findChild(QWidget, "bubble-user-msg")
    assert bubble is not None
    assert bubble.findChild(QLabel, "bubble-user-thumb") is not None


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
