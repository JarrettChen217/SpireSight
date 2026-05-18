from spiresight.core.conversation import ConversationStore
from spiresight.core.messages import Message


def test_store_starts_empty():
    store = ConversationStore()
    assert store.turns() == ()
    assert store.last_screenshot() is None


def test_append_and_turns():
    store = ConversationStore()
    m1 = Message(role="user", text="hello")
    m2 = Message(role="assistant", text="hi there")
    store.append(m1)
    store.append(m2)
    turns = store.turns()
    assert len(turns) == 2
    assert turns[0] is m1
    assert turns[1] is m2


def test_turns_is_immutable_snapshot():
    store = ConversationStore()
    store.append(Message(role="user", text="a"))
    snapshot = store.turns()
    store.append(Message(role="assistant", text="b"))
    assert len(snapshot) == 1
    assert len(store.turns()) == 2


def test_clear():
    store = ConversationStore()
    store.append(Message(role="user", text="x"))
    store.clear()
    assert store.turns() == ()


def test_last_screenshot_no_images():
    store = ConversationStore()
    store.append(Message(role="user", text="hi"))
    store.append(Message(role="assistant", text="hello"))
    assert store.last_screenshot() is None


def test_last_screenshot_returns_most_recent():
    store = ConversationStore()
    img1 = b"\x89PNG1"
    img2 = b"\x89PNG2"
    store.append(Message(role="user", text="first", image_png=img1))
    store.append(Message(role="assistant", text="ok"))
    store.append(Message(role="user", text="second", image_png=img2))
    assert store.last_screenshot() == img2


def test_last_screenshot_skips_assistant_images():
    store = ConversationStore()
    store.append(Message(role="user", text="q", image_png=b"\x89PNGu"))
    store.append(Message(role="assistant", text="a"))
    assert store.last_screenshot() == b"\x89PNGu"
