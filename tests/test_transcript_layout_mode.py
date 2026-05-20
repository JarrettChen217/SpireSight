from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import pytest

from spiresight.core.messages import Message
from spiresight.ui.widgets.conversation_transcript import ConversationTranscript
from spiresight.ui.widgets.output_view import OutputView


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_compact_output_view_has_max_height(qtwidgets_app):
    out = OutputView()
    out.set_scroll_mode("compact", max_height=200)
    assert out.maximumHeight() == 200


def test_expanded_output_view_disables_inner_scroll(qtwidgets_app):
    out = OutputView()
    out.set_scroll_mode("expanded")
    assert out.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_expanded_grows_with_content(qtwidgets_app):
    long_md = "\n".join(f"paragraph {i} with some text" for i in range(40))

    compact = OutputView()
    compact.set_scroll_mode("compact", max_height=120)
    compact.resize(320, 120)
    compact.load_static(long_md)
    assert compact.maximumHeight() == 120

    expanded = OutputView()
    expanded.set_scroll_mode("expanded")
    expanded.resize(320, 50)
    expanded.show()
    QApplication.processEvents()
    expanded.load_static(long_md)
    QApplication.processEvents()
    doc_h = int(expanded.document().size().height())
    assert doc_h > 120
    assert expanded.height() >= doc_h


def test_transcript_mode_switch_updates_existing_outputs(qtwidgets_app):
    t = ConversationTranscript(transcript_mode="compact", assistant_max_height=180)
    t.render_turns((
        Message(role="user", text="q"),
        Message(role="assistant", text="a"),
    ))
    outputs = t.findChildren(OutputView)
    assert outputs
    assert outputs[0].maximumHeight() == 180

    t.set_transcript_mode("expanded")
    for out in outputs:
        assert out.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
